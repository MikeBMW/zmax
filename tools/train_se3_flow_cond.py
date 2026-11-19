#!/usr/bin/env python3
"""五流形条件 flow-matching 训练 (intel Arc XPU)。

任务: 给定当前状态 x0 与条件 c(五流形 20 维), 用 flow matching 学"下一步往哪走",
      推理时对速度场做测地线积分, 端点就是预测的下一状态。

数据: 真机 215 帧 (layers_215.json / real_traj_joints.json), 214 个真实转移 + 跳步(bigdt)增广。
判据: **同口径** 5 折(按时间块)对照 —— 模型 / persist(保持不动) / 线性外推 / 零基线,
      每折同一批样本、同一套误差函数 (A mm · B/C/D 度 · E 相位% · TQ %)。

诚实边界: 数据只有一条 215 点轨迹, 这是"接法+判据"验证, 不是策略上线。进默认档要真数据规模 + 有提升。

用法:
  python3 train_se3_flow_cond.py --epochs 2000 --folds 5            # XPU
  python3 train_se3_flow_cond.py --epochs 200 --device cpu --subset  # 冒烟
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np
import torch
import torch.nn as nn

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src", "lerobot", "manifold"))
import se3_flow_cond as FC                                               # noqa: E402
from se3_flow_cond import q_normalize  # noqa: E402

TWO_PI = 2.0 * math.pi


def _tq(s: dict):
    """TQ 缺省安全取值 (ndarray 不能用 `or` 判断真假)。"""
    tq = s.get("TQ")
    return np.zeros(6) if tq is None else np.asarray(tq, float)


# ── 状态字典 ↔ 张量 ────────────────────────────────────────────────────────────
def state_vec(s: dict) -> np.ndarray:
    """五流形状态 → 20 维平面向量 (S¹ 用 cos/sin, 与条件编码同口径)。"""
    q = np.asarray(q_normalize(s["C"]), float)
    if q[3] < 0:
        q = -q
    return np.concatenate([np.asarray(s["A"], float) / 1000.0, np.asarray(s["B"], float), q,
                           [math.cos(s["D"]), math.sin(s["D"])],
                           [math.cos(TWO_PI * s["E"]), math.sin(TWO_PI * s["E"])],
                           np.asarray(_tq(s), float) / 100.0]).astype(np.float32)


def vec_state(v: np.ndarray) -> dict:
    v = np.asarray(v, float)
    return {"A": v[0:3] * 1000.0, "B": v[3:6] / (np.linalg.norm(v[3:6]) or 1.0),
            "C": np.asarray(q_normalize(v[6:10]), float),
            "D": math.atan2(v[11], v[10]) % TWO_PI, "E": (math.atan2(v[13], v[12]) % TWO_PI) / TWO_PI,
            "TQ": v[14:20] * 100.0}


def tangent(s0: dict, s1: dict) -> np.ndarray:
    """x0→x1 的**流形切向量** (17 维): A3 · B3(⊥n) · C3(rotvec) · D1 · E1 · TQ6。"""
    t = np.zeros(17)
    t[0:3] = (np.asarray(s1["A"], float) - np.asarray(s0["A"], float)) / 1000.0
    n0 = np.asarray(s0["B"], float) / (np.linalg.norm(s0["B"]) or 1.0)
    n1 = np.asarray(s1["B"], float) / (np.linalg.norm(s1["B"]) or 1.0)
    d = math.acos(float(np.clip(np.dot(n0, n1), -1, 1)))
    u = n1 - np.dot(n0, n1) * n0
    un = np.linalg.norm(u)
    t[3:6] = (d * u / un) if un > 1e-12 else np.zeros(3)
    q0 = q_normalize(s0["C"]); q1 = q_normalize(s1["C"])
    dot = float(np.clip(abs(np.dot(q0, q1)), -1, 1))
    if dot > 1 - 1e-12:
        t[6:9] = np.zeros(3)
    else:
        if np.dot(q0, q1) < 0:
            q1 = tuple(-c for c in q1)
        ang = 2 * math.acos(float(np.clip(np.dot(q0, q1), -1, 1)))
        # 相对旋转 r = q0* ⊗ q1 的 rotvec
        ax, ay, az, aw = q0
        bx, by, bz, bw = q1
        rx = aw * bx - ax * bw - ay * bz + az * by
        ry = aw * by + ax * bz - ay * bw - az * bx
        rz = aw * bz - ax * by + ay * bx - az * bw
        rw = aw * bw + ax * bx + ay * by + az * bz
        sn = math.sqrt(max(1e-16, 1 - rw * rw))
        t[6:9] = (np.array([rx, ry, rz]) / sn * ang) if sn > 1e-9 else np.zeros(3)
    t[9] = (s1["D"] - s0["D"] + math.pi) % TWO_PI - math.pi
    t[10] = ((s1["E"] - s0["E"] + 0.5) % 1.0) - 0.5
    t[11:17] = (np.asarray(_tq(s1), float) -
                np.asarray(_tq(s0), float)) / 100.0
    return t.astype(np.float32)


def exp_map(s0: dict, t: np.ndarray) -> dict:
    t = np.asarray(t, float)
    L = math.sqrt(max(1e-16, 1 - 0.0))
    p = np.asarray(s0["A"], float) + t[0:3] * 1000.0
    n0 = np.asarray(s0["B"], float) / (np.linalg.norm(s0["B"]) or 1.0)
    th = float(np.linalg.norm(t[3:6]))
    if th > 1e-12:
        v = t[3:6] / th
        v = v - np.dot(v, n0) * n0
        vn = np.linalg.norm(v)
        n1 = math.cos(th) * n0 + math.sin(th) * (v / vn if vn > 1e-12 else 0)
    else:
        n1 = n0
    q0 = q_normalize(s0["C"])
    ang = float(np.linalg.norm(t[6:9]))
    if ang > 1e-12:
        ax = t[6:9] / ang
        dq = (ax[0] * math.sin(ang / 2), ax[1] * math.sin(ang / 2), ax[2] * math.sin(ang / 2),
              math.cos(ang / 2))
        x1, y1, z1, w1 = q0
        x2, y2, z2, w2 = dq
        q1 = (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
              w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)
    else:
        q1 = q0
    return {"A": p, "B": n1 / (np.linalg.norm(n1) or 1.0), "C": np.asarray(q_normalize(q1), float),
            "D": (s0["D"] + t[9]) % TWO_PI, "E": (s0["E"] + t[10]) % 1.0,
            "TQ": np.asarray(_tq(s0), float) + t[11:17] * 100.0}


# ── 速度场 ────────────────────────────────────────────────────────────────────
class VNet(nn.Module):
    def __init__(self, in_dim: int = 20 + 1 + 20, hidden: int = 192, out_dim: int = 17) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, hidden), nn.SiLU(),
            nn.Linear(hidden, hidden), nn.SiLU(),
            nn.Linear(hidden, hidden // 2), nn.SiLU(),
            nn.Linear(hidden // 2, out_dim))

    def forward(self, xt, tt, c):
        return self.net(torch.cat([xt, tt, c], dim=-1))


def metrics(pred: dict, true: dict) -> dict:
    """同口径误差 (只用几何差, 不做归一化粉饰)。"""
    dp = float(np.linalg.norm(np.asarray(pred["A"], float) - np.asarray(true["A"], float)))
    n1 = np.asarray(pred["B"], float); n2 = np.asarray(true["B"], float)
    db = math.degrees(math.acos(float(np.clip(np.dot(n1 / (np.linalg.norm(n1) or 1), n2 / (np.linalg.norm(n2) or 1)), -1, 1))))
    qa = np.asarray(q_normalize(pred["C"]), float); qb = np.asarray(q_normalize(true["C"]), float)
    dq = math.degrees(2 * math.acos(float(np.clip(abs(np.dot(qa, qb)), -1, 1))))
    dd = abs((pred["D"] - true["D"] + math.pi) % TWO_PI - math.pi)
    de = abs(((pred["E"] - true["E"] + 0.5) % 1.0) - 0.5) * 100.0
    return {"A_mm": dp, "B_deg": db, "C_deg": dq, "D_deg": math.degrees(dd), "E_pct": de}


def load_frames(path: str):
    fr = json.load(open(path))["frames"]
    out = []
    for f in fr:
        q = f["q"]
        from se3_hopf import hopf  # 包内 hopf: q → (n, φ)
        n, phi = hopf(q_normalize(q))
        out.append({"A": np.asarray(f["p"], float) * 1000.0, "B": np.asarray(n, float),
                    "C": np.asarray(q_normalize(q), float), "D": float(phi) % TWO_PI, "E": 0.0,
                    "TQ": np.zeros(6)})
    return out, fr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "..", "tools", "web", "real_traj_joints.json"))
    ap.add_argument("--layers", default=os.path.join(HERE, "..", "zmax_data", "se3_layers", "layers_215.json"))
    ap.add_argument("--epochs", type=int, default=2000)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--hidden", type=int, default=192)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "zmax_data", "se3_flow_cond"))
    ap.add_argument("--subset", action="store_true")
    a = ap.parse_args()

    dev = a.device
    if dev == "auto":
        dev = "xpu" if getattr(torch, "xpu", None) is not None and torch.xpu.is_available() else (
            "cuda" if torch.cuda.is_available() else "cpu")
    print("[env] torch %s · dev=%s (%s)" % (torch.__version__, dev,
          torch.xpu.get_device_name(0) if dev == "xpu" else torch.cuda.get_device_name(0) if dev == "cuda" else "cpu"),
          flush=True)

    F = FC.SE3FlowCond()
    frames, fr_raw = load_frames(a.data)
    n = len(frames)
    print("[data] %d 帧" % n, flush=True)
    # 相位 s 与 TQ 从引擎五层数据补齐 (若有)
    if os.path.exists(a.layers):
        lay = json.load(open(a.layers))
        rows = lay if isinstance(lay, list) else (lay.get("frames") or [])
        if len(rows) == n:
            for i, r in enumerate(rows):
                frames[i]["E"] = float(r["E_s"])                  # 相位 (0~1)
                frames[i]["D"] = math.radians(float(r["D_phi_deg"])) % TWO_PI
            print("[data] 已并入五层相位/D 滚转 (%s)" % a.layers, flush=True)

    # 样本: (x0, x1, cond) —— 含跳步增广 (k=1,2,3)
    S = []
    for k in (1, 2, 3):
        for i in range(n - k):
            S.append((i, i + k))
    if a.subset:
        S = S[: max(64, len(S) // 10)]
    print("[data] 转移样本 %d (跳步 1/2/3 增广)" % len(S), flush=True)

    # TQ: 用相邻帧关节差分补 (layers_215.json 的 TQ 只有元数据, 没有逐帧 dq)
    js = [np.asarray(f["j"], float) for f in fr_raw]
    ts = [float(f["t"]) for f in fr_raw]
    for i in range(len(frames)):
        k = min(i + 1, len(frames) - 1)
        dt = max(1e-3, ts[k] - ts[i]) if k != i else 1e-3
        frames[i]["TQ"] = np.degrees(js[k] - js[i]) / dt
    conds = [F.encode(fr["A"], fr["B"], fr["C"], fr["D"], fr["E"], fr["TQ"]) for fr in frames]
    X0 = torch.tensor(np.stack([state_vec(frames[i]) for i, _ in S]))
    X1 = torch.tensor(np.stack([state_vec(frames[j]) for _, j in S]))
    TAN = torch.tensor(np.stack([tangent(frames[i], frames[j]) for i, j in S]))
    COND = torch.tensor(np.stack([conds[i] for i, _ in S]))
    idx_all = np.array([i for i, _ in S])

    # 5 折: 按时间块切 (禁止随机切, 否则相邻帧泄漏)
    order = np.argsort(idx_all)
    folds = np.array_split(order, a.folds)
    res = {"dev": dev, "frames": n, "samples": int(len(S)), "epochs": a.epochs,
           "hidden": a.hidden, "folds": a.folds, "per_fold": [], "baselines": {}}

    def run_fold(k_fold: int, te_idx: np.ndarray) -> dict:
        te = torch.tensor(te_idx, dtype=torch.long)
        mask = torch.ones(len(S), dtype=torch.bool); mask[te] = False
        tr = torch.nonzero(mask).squeeze(1)
        net = VNet(hidden=a.hidden).to(dev)
        opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
        sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=a.epochs)
        x0d, x1d, tand, cd = X0[tr].to(dev), X1[tr].to(dev), TAN[tr].to(dev), COND[tr].to(dev)
        B = min(256, len(tr))
        t0 = time.time(); last = None
        for ep in range(1, a.epochs + 1):
            perm = torch.randperm(len(tr), device=dev)[:B]
            tt = torch.rand(B, 1, device=dev)
            # 测地线路径上的中间点 (欧氏近似用于网络输入, 目标仍是切向量)
            xt = (1 - tt) * x0d[perm] + tt * x1d[perm]
            v = net(xt, tt, cd[perm])
            loss = ((v - tand[perm]) ** 2).mean()
            opt.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            opt.step(); sch.step()
            last = float(loss.detach())
            if ep % max(1, a.epochs // 5) == 0 or ep == 1:
                print("  fold%d ep %d/%d loss %.5f (%.1fs)" % (k_fold, ep, a.epochs, last, time.time() - t0), flush=True)
        net.eval()
        # 推理: 从 x0 起沿**流形**积分速度场 (20 步欧拉 + 逐层指数映射)
        cte = COND[te].to(dev)
        cur = [vec_state(X0[te][r].numpy()) for r in range(len(te))]
        with torch.no_grad():
            for step in range(20):
                xt = torch.tensor(np.stack([state_vec(s) for s in cur]), dtype=torch.float32, device=dev)
                tt = torch.full((len(cur), 1), step / 20.0, device=dev)
                v = net(xt, tt, cte).cpu().numpy()
                cur = [exp_map(cur[r], v[r] / 20.0) for r in range(len(cur))]
        pred = np.stack([state_vec(s) for s in cur])
        errs = {"model": [], "persist": [], "zero": [], "linear": []}
        for r, te_i in enumerate(te_idx):
            i, j = S[int(te_i)]
            true = frames[j]
            pm = metrics(vec_state(pred[r]), true)
            pp = metrics(frames[i], true)                                    # persist: 不动
            pz = metrics(exp_map(frames[i], np.zeros(17)), true)             # 零速度参考
            # 线性外推: 用 i-1→i 的切向量外推 (没有前一点就退化为 persist)
            if i >= 1:
                tprev = tangent(frames[i - 1], frames[i])
                pl = metrics(exp_map(frames[i], tprev * (S[int(te_i)][1] - i)), true)
            else:
                pl = pp
            for k, v in (("model", pm), ("persist", pp), ("zero", pz), ("linear", pl)):
                errs[k].append(v)
        return {"fold": k_fold, "n_test": int(len(te_idx)),
                "errs": {k: {m: float(np.median([e[m] for e in vs])) for m in vs[0]} for k, vs in errs.items()},
                "secs": round(time.time() - t0, 1)}

    for f in range(a.folds):
        r = run_fold(f, folds[f])
        res["per_fold"].append(r)
        print("[fold %d] model A %.2fmm B %.2f° C %.2f° | persist A %.2fmm | lin A %.2fmm"
              % (f + 1, r["errs"]["model"]["A_mm"], r["errs"]["model"]["B_deg"], r["errs"]["model"]["C_deg"],
                 r["errs"]["persist"]["A_mm"], r["errs"]["linear"]["A_mm"]), flush=True)

    for k in ("model", "persist", "zero", "linear"):
        res["baselines"][k] = {m: float(np.median([f["errs"][k][m] for f in res["per_fold"]]))
                               for m in res["per_fold"][0]["errs"][k]}
    m = res["baselines"]["model"]; p = res["baselines"]["persist"]
    res["verdict"] = ("模型优于 persist" if (m["A_mm"] < p["A_mm"] and m["B_deg"] < p["B_deg"] and m["C_deg"] < p["C_deg"])
                      else "模型不优于 persist ⇒ 只可留影子, 不进默认档")
    os.makedirs(a.out, exist_ok=True)
    p_out = os.path.join(a.out, "train_%s.json" % time.strftime("%m%d_%H%M"))
    json.dump(res, open(p_out, "w"), ensure_ascii=False, indent=1)
    print("[baselines 中位]", json.dumps(res["baselines"], ensure_ascii=False), flush=True)
    print("[verdict]", res["verdict"], flush=True)
    print("[out]", p_out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
