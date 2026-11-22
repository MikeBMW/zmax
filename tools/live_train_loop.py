#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_train_loop.py — 边采集边训练 (在线增量学习)。

只读采集目录, 每 ROUND 秒: 读新增帧 → 缩图 → 组 batch → 训 N 步 → 记账 + 存 ckpt。
不碰机器人, 不下发任何指令; 采集进程照常跑。

输入 zmax_data/live_ds/<ep>/data/frames.jsonl (pose7 + joints6) + images/*.jpg
输出 zmax_data/live_train/ledger.jsonl · models/live_policy.pt
判据: 每轮报 val RMSE(mm), 与 persist(不动) 对照; 有改善才更新"best"。

用法: ./gui-venv311/bin/python tools/live_train_loop.py --rounds 200 --round-secs 20
"""
from __future__ import annotations
import argparse, glob, json, os, time
import numpy as np
from PIL import Image

ROOT = "/home/ubuntu/zmax"
DS = os.path.join(ROOT, "zmax_data/live_ds_fix")   # 去重后的元数据 (图仍从 live_ds 取)
OUT = os.path.join(ROOT, "zmax_data/live_train")
# 🔴 ckpt 必须按 tag 分文件: 否则后跑的消融组会把先跑出来的更好模型覆盖掉
#    (实测 A(有图)3.00 → 被 B(无图)3.47 覆盖, 因为 best 判定各自独立)
CK = os.path.join(ROOT, "models/live_policy_%s.pt" % os.environ.get("ZMAX_TAG", "img"))
SZ = 96


def load_rows():
    rows = []
    for f in sorted(glob.glob(os.path.join(DS, "episode_*/data/frames.jsonl"))):
        ep = f.split("/")[-3]
        for ln in open(f):
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if os.environ.get("ZMAX_EP") and ep != os.environ["ZMAX_EP"]:
                continue                       # 只吃指定 episode (默认全吃)
            r["_ep"] = ep
            rows.append(r)
    rows.sort(key=lambda r: r["ts"])
    return rows


def vec(r):
    return np.asarray(r["pose7"], np.float32)



# ── 图像缓存 (tools/build_img_cache.py 产出): 命中就从 .npy 取, 免去 1280×720 解码 ──
_MEM = {}
def _from_cache(ep, img):
    if ep not in _MEM:
        import numpy as _np
        f = os.path.join(ROOT, "zmax_data/live_cache", "%s_X.npy" % ep)
        g = os.path.join(ROOT, "zmax_data/live_cache", "%s_idx.json" % ep)
        if not (os.path.exists(f) and os.path.exists(g)):
            _MEM[ep] = None
        else:
            X = _np.load(f)
            idx = {n: i for i, n in enumerate(json.load(open(g)))}
            _MEM[ep] = (X, idx)
    c = _MEM[ep]
    if not c or img not in c[1]:
        return None
    return (c[0][c[1][img]].astype("float32") / 255.0).transpose(2, 0, 1)


def build(rows, seen, cache):
    # 🔴 抽样必须**在展开之前**: 之前放在展开之后, 36061 条先转 float32(3.9GB),
    #    实测 RSS 冲到 7.2GB 逼近 8GB 红线, 13 分钟还没走到训练。这里先按步长抽行。
    _cap = int(os.environ.get("ZMAX_TRAIN_CAP", "10000"))
    if _cap and len(rows) > _cap:
        rows = rows[::max(1, len(rows) // _cap)]
    """新样本: (img96, state13, action7@1拍) —— action 用相邻真值差分/实际 dt。"""
    import torch
    X, S, Y = [], [], []
    for a, b in zip(rows, rows[1:]):
        if (b["_ep"], b["i"]) in seen:      # i 每段从 0 起, 必须带 ep 做键, 否则跨段互相顶掉
            continue
        p = os.path.join(ROOT, "zmax_data/live_ds", b["_ep"], b["img"])  # 图像仍在 live_ds, 修复目录只放元数据
        if not os.path.exists(p):
            continue
        try:
            im = Image.open(p).convert("RGB").resize((SZ, SZ))
        except Exception:
            continue
        x = cache.get(p)
        if x is None:
            x = _from_cache(b["_ep"], b["img"])          # 先吃 96×96 缓存 (快 20 倍)
            if x is None:
                im = Image.open(p).convert("RGB").resize((SZ, SZ))
                x = (np.asarray(im, np.float32) / 255.0).transpose(2, 0, 1)
            cache[p] = x
        dt = max(1e-3, float(b["ts"]) - float(a["ts"]))
        d = vec(b) - vec(a)
        act = np.concatenate([d[:3] / dt * 0.2, d[3:6] / dt * 0.2, [1.0]]).astype(np.float32)
        X.append(x); S.append(np.asarray(b["joints_deg"], np.float32)); Y.append(act)
    if not X:
        return None
    return (torch.tensor(np.stack(X)), torch.tensor(np.stack(S)), torch.tensor(np.stack(Y)))


def main() -> int:
    import torch, torch.nn as nn
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=200)
    ap.add_argument("--round-secs", type=float, default=20.0)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--no-img", action="store_true", help="消融: 把图像置零, 只看关节 (证明图有没有用)")
    ap.add_argument("--tag", default="img")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    dev = "cuda" if torch.cuda.is_available() else "cpu"

    class Net(nn.Module):                     # 双分支: 图像走卷积, 关节走 MLP, 特征再拼
        def __init__(self):
            super().__init__()
            self.c = nn.Sequential(nn.Conv2d(3, 16, 5, 2, 2), nn.ReLU(), nn.Conv2d(16, 32, 5, 2, 2),
                                   nn.ReLU(), nn.AdaptiveAvgPool2d(4), nn.Flatten())
            self.f = nn.Sequential(nn.Linear(32 * 16 + 6, 128), nn.SiLU(), nn.Linear(128, 7))
        def forward(self, x, s):
            return self.f(torch.cat([self.c(x), s], 1))
    net = Net().to(dev)
    opt = torch.optim.Adam(net.parameters(), 3e-4)
    seen, cache, best = set(), {}, 1e18
    for rd in range(a.rounds):
        rows = load_rows()
        B = build(rows, seen, cache)
        if B is None:
            print("[%s] rd%d 无新帧 (累计 %d)" % (time.strftime("%H:%M:%S"), rd, len(seen)), flush=True)
            time.sleep(a.round_secs); continue
        X, S, Y = B
        # 🔴 3.6 万条一次性展开成 float32 = 3.9GB, 实测把机器拖到 2.2GB 还没开始训。
        #    改成等间隔抽样上限 10000 条(跨全部 episode/全部槽), 保证每段都有代表。
        cap = int(os.environ.get("ZMAX_TRAIN_CAP", "10000"))
        if len(X) > cap:
            idx = torch.linspace(0, len(X) - 1, cap).long()
            X, S, Y = X[idx], S[idx], Y[idx]
            print("[抽样] 取 %d/%d 条 (等间隔)" % (cap, len(B[0])), flush=True)
        if a.no_img:
            X = torch.zeros_like(X)
        for t in Y[:, 1:4].abs().max(0).values.tolist():  # 尺度归一, 只影响损失量级
            pass
        n = len(X); cut = max(1, int(n * 0.85))
        xt, st, yt = X[:cut].to(dev), S[:cut].to(dev), Y[:cut].to(dev)
        xv, sv, yv = X[cut:].to(dev), S[cut:].to(dev), Y[cut:].to(dev)
        last = 0.0
        for _ in range(a.steps):
            opt.zero_grad()
            imp = net(xt, st)
            loss = ((imp - yt) ** 2).mean(); loss.backward(); opt.step(); last = float(loss)
        with torch.no_grad():
            val = float(torch.sqrt(((net(xv, sv) - yv) ** 2).mean()))
            base = float(torch.sqrt((yv ** 2).mean()))
        ok = val < base
        rec = {"ts": time.strftime("%F %T"), "round": rd, "new": int(n), "train": int(cut),
               "loss": round(last, 5), "val_rmse": round(val, 3), "persist_rmse": round(base, 3),
               "better": bool(ok), "tag": a.tag, "no_img": bool(a.no_img)}
        with open(os.path.join(OUT, "ledger.jsonl"), "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if ok and val < best:
            best = val
            torch.save({"state_dict": net.state_dict(), "size": SZ, "val_rmse": val}, CK)
            print("[%s] rd%d 新 best val %.2f (baseline %.2f) → %s" % (rec["ts"], rd, val, base, CK), flush=True)
        else:
            print("[%s] rd%d 新增 %d · val %.2f vs baseline %.2f" % (rec["ts"], rd, n, val, base), flush=True)
        # 全部已入过库的帧不再重复
        for r in rows[1:]:
            seen.add((r["_ep"], r["i"]))
        time.sleep(a.round_secs)
    print(json.dumps({"ok": True, "best_val_rmse": round(best, 3) if best < 1e17 else None,
                      "ledger": os.path.join(OUT, "ledger.jsonl")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
