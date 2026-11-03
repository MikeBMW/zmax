#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_p_cond_proj.py — 训练 action_head 的条件投影 (L4 条件 → 动作)

背景: `p_cond_proj`/`l4_cond_proj` 是零初始化 residual 投影, 权重为 0 时对动作
      影响严格为零 (已实测 max|Δ|=0)。本脚本冻结主干, 只训这一层, 用真数据
      (lerobot 数据集: image + state + action) 让它学到"L4 条件如何修正动作"。

判据 (留出集, 按 episode 切):
  ① 基线 p_cond=0 的 RMSE
  ② 训练后 p_cond=真值 的 RMSE  —— 必须下降
  ③ 置零对照 (训好的权重 + p_cond=0) —— 必须回到基线 (证明增益来自条件)

用法:
  ./gui-venv311/bin/python tools/train_p_cond_proj.py --smoke      # 8 帧链路自检
  ./gui-venv311/bin/python tools/train_p_cond_proj.py --epochs 3
"""
import argparse
import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

DS_DEFAULT = os.path.join(ROOT, "data/datasets/sim_TASK-01-FW")
CK_DEFAULT = "outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model"


# ── 数据 ────────────────────────────────────────────────────────────────
def load_ds(ds, limit=None):
    import pyarrow.parquet as pq
    fs = sorted(glob.glob(os.path.join(ds, "data/**/*.parquet"), recursive=True))
    if not fs:
        raise FileNotFoundError("无 parquet: %s" % ds)
    cols = {k: [] for k in ("observation.state", "action", "episode_index", "frame_index")}
    for f in fs:
        t = pq.read_table(f)
        for k in cols:
            if k in t.column_names:
                cols[k].append(np.asarray(t[k].to_pylist()))
    for k in cols:
        cols[k] = np.concatenate(cols[k]) if cols[k] else None
    st, ac = cols["observation.state"], cols["action"]
    n = len(st) if limit is None else min(int(limit), len(st))
    return {"state": st[:n].astype(np.float32), "action": ac[:n].astype(np.float32),
            "ep": cols["episode_index"][:n], "fi": cols["frame_index"][:n],
            "video": _video_path(ds)}


def _video_path(ds):
    c = sorted(glob.glob(os.path.join(ds, "videos/observation.image/**/*.mp4"), recursive=True))
    return c[0] if c else None


class VideoFrames:
    """按 frame_index 顺序读 mp4 (整段解码到内存, 7252×128²×3 ≈ 356MB 可控)。"""

    def __init__(self, path):
        import cv2
        self.frames = []
        cap = cv2.VideoCapture(path)
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            self.frames.append(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
        cap.release()
        if not self.frames:
            raise RuntimeError("视频解不出帧: %s" % path)

    def __len__(self):
        return len(self.frames)

    def get(self, i):
        return self.frames[int(i) % len(self.frames)]


# ── 条件: L4 流形点 p (四元数) → 3 维 rotvec ────────────────────────────
def build_pcond(states, log=print):
    """用流形引擎逐帧算 p (四元数), 取 rotvec 前 3 维当 L4 条件。

    state 39 维 → 补齐到引擎要的 43 维 (缺的 4 维填 0 并在 meta 里标)。
    """
    from lerobot.manifold.manifold_engine import ManifoldEngine
    eng = ManifoldEngine()
    out = np.zeros((len(states), 3), dtype=np.float32)
    for i, s in enumerate(states):
        x = np.zeros(43, dtype=np.float32)
        x[:min(39, len(s))] = s[:39]
        try:
            rec = eng.step(x, 0.1)
            p = np.asarray(rec.get("p") or [1, 0, 0, 0], dtype=np.float64).ravel()[:4]
            n = np.linalg.norm(p) or 1.0
            p = p / n
            w, v = float(p[0]), p[1:4]
            ang = 2.0 * np.arctan2(np.linalg.norm(v), abs(w))
            ax = v / (np.linalg.norm(v) or 1.0)
            out[i] = (ax * ang)[:3]
        except Exception:                                              # noqa: BLE001
            pass
        if (i + 1) % 500 == 0:
            log("  p_cond %d/%d" % (i + 1, len(states)))
    return out


# ── 模型 ────────────────────────────────────────────────────────────────
def load_policy(root, ck, dev):
    import torch
    from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
    from lerobot.policies.factory import make_pre_post_processors
    if not os.path.isabs(ck):
        ck = os.path.join(root, ck)
    pol = SmolVLALewPolicy.from_pretrained(ck).to(dev).eval()
    pre, post = make_pre_post_processors(getattr(pol, "config", None), ck)
    return pol, pre, post


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", default=DS_DEFAULT)
    ap.add_argument("--ckpt", default=CK_DEFAULT)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--accum", type=int, default=4, help="梯度累积 (显存紧时等效放大 batch)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--smoke", action="store_true", help="8 帧跑通链路, 不训练")
    ap.add_argument("--out", default="models/p_cond_proj.pt")
    a = ap.parse_args()

    import torch
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print("设备:", dev, "| torch", torch.__version__)

    d = load_ds(a.ds, a.limit or (8 if a.smoke else None))
    print("数据: %d 帧 | state %s | action %s | video %s"
          % (len(d["state"]), d["state"].shape, d["action"].shape, os.path.basename(d["video"] or "-")))

    pol, pre, post = load_policy(ROOT, a.ckpt, dev)
    try:                                     # 预处理器里的 device_processor 跟随 config.device
        pol.config.device = dev
        from lerobot.policies.factory import make_pre_post_processors
        pre, post = make_pre_post_processors(pol.config, os.path.join(ROOT, a.ckpt))
    except Exception as _e:                                            # noqa: BLE001
        print("⚠️ 重建预处理器失败(沿用原):", str(_e)[:80])
    head = None
    for path in ("action_model", "model.action_model", "model.action_head", "action_head"):
        obj = pol
        ok = True
        for part in path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                ok = False
                break
        if ok and hasattr(obj, "ensure_p_cond"):
            head = obj
            print("action_head = pol.%s" % path)
            break
    if not hasattr(head, "ensure_p_cond"):
        print("❌ 找不到 action_head.ensure_p_cond")
        return 1
    head.ensure_p_cond(dim=3)
    proj = head.p_cond_proj
    print("p_cond_proj:", tuple(proj.weight.shape), "| 初始 max|w| = %.3e" % float(proj.weight.abs().max()))

    # 解除两处 @torch.no_grad(): chunk 级 + action_head.predict_action (DiT 采样)
    for _owner, _name in ((pol, "predict_action_chunk"), (head, "predict_action")):
        _raw = getattr(getattr(_owner, _name, None), "__wrapped__", None)
        if _raw is not None:
            setattr(_owner, _name, _raw.__get__(_owner, type(_owner)))
            print("已解除 no_grad: %s.%s" % (type(_owner).__name__, _name))
        else:
            print("⚠️ %s.%s 无 __wrapped__" % (type(_owner).__name__, _name))

    # 冻结除 proj 外全部
    for p_ in pol.parameters():
        p_.requires_grad_(False)
    proj.weight.requires_grad_(True)

    vf = VideoFrames(d["video"]) if d["video"] else None
    print("视频帧:", len(vf) if vf else 0)

    pcond = build_pcond(d["state"])

    def _act(batch, pc):
        """直接出动作 chunk (绕过 predict_action 的队列缓存), 取首拍 4 维。"""
        with torch.enable_grad():
            y = pol.predict_action_chunk(batch, p_cond=pc)
        if isinstance(y, dict):
            y = y.get("action") if "action" in y else list(y.values())[0]
        return y

    def make_batch(sel, pc_np, zero_cond=False):
        imgs = np.stack([vf.get(i) for i in sel]) if vf else None
        batch = {"observation.state": torch.from_numpy(d["state"][sel]).to(dev)}
        if imgs is not None:
            batch["observation.image"] = torch.from_numpy(imgs).permute(0, 3, 1, 2).float().to(dev) / 255.0
        batch = pre(batch)
        # task 必须在 pre 之后补: 预处理器会把它清成空 list, 导致 instructions[0] 越界
        batch["task"] = ["insert the optical module into the slot"] * len(sel)
        if os.environ.get("TPC_DEBUG") == "1":
            print("  [dbg] " + " ".join("%s=%s" % (k, tuple(v.shape) if hasattr(v, "shape") else type(v).__name__)
                                        for k, v in batch.items()))
        pc = torch.zeros((len(sel), 3), device=dev) if zero_cond else torch.from_numpy(pc_np[sel]).to(dev)
        return batch, pc

    idx = np.arange(len(d["state"]))
    if a.smoke:
        b, pc = make_batch(idx, pcond)
        with torch.no_grad():
            y = _act(b, pc)
        print("smoke 输出:", tuple(y.shape) if hasattr(y, "shape") else type(y))
        return 0

    # 按 episode 切 train/val
    eps = np.unique(d["ep"])
    if len(eps) >= 5:
        cut = max(1, int(len(eps) * 0.8))
        tr = idx[np.isin(d["ep"], eps[:cut])]
        va = idx[np.isin(d["ep"], eps[cut:])]
    else:                                   # 帧数少时按时间顺序 8:2 切 (避免只有 2 个 episode)
        cut = int(len(idx) * 0.8)
        tr, va = idx[:cut], idx[cut:]
    print("train %d / val %d (%d episodes)" % (len(tr), len(va), len(eps)))

    opt = torch.optim.Adam([proj.weight], lr=a.lr)
    tgt_all = torch.from_numpy(d["action"]).to(dev)

    def rmse(sel, zero_cond=False):
        tot, cnt = 0.0, 0
        with torch.no_grad():
            for b0 in range(0, len(sel), a.batch):
                b = sel[b0:b0 + a.batch]
                batch, pc = make_batch(b, pcond, zero_cond=zero_cond)
                y = _act(batch, pc)
                y = y.reshape(len(b), -1)[:, :4]
                tot += float(((y - tgt_all[b]) ** 2).sum()); cnt += len(b) * 4
        return (tot / max(cnt, 1)) ** 0.5

    base = rmse(va, zero_cond=True)
    print("基线 (p_cond=0) val RMSE = %.6f" % base)

    for ep in range(a.epochs):
        np.random.shuffle(tr)
        run = 0.0
        for b0 in range(0, len(tr), a.batch):
            b = tr[b0:b0 + a.batch]
            batch, pc = make_batch(b, pcond)
            y = _act(batch, pc).reshape(len(b), -1)[:, :4]
            loss = ((y - tgt_all[b]) ** 2).mean() / max(1, a.accum)
            loss.backward()
            if (b0 // a.batch + 1) % max(1, a.accum) == 0:
                opt.step(); opt.zero_grad()
            run += float(loss) * max(1, a.accum)
        v1 = rmse(va, zero_cond=False)
        v0 = rmse(va, zero_cond=True)
        print("epoch %d | train MSE %.6f | val RMSE(cond) %.6f | val RMSE(zero) %.6f | 增益 %+.2f%%"
              % (ep + 1, run / max(1, len(tr) // a.batch), v1, v0, (v1 - base) / base * 100))

    torch.save({"p_cond_proj": proj.weight.detach().cpu(), "dim": 3}, os.path.join(ROOT, a.out))
    print("✅ 已保存", a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
