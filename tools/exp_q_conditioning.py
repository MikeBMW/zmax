#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exp_q_conditioning.py — 「用四元数做条件调制」值不值: 实测对比 (不是拍脑袋)

问题: 统一状态空间的四元数该不该进流形引擎?
做法: 不塞进 43D 编码器 (会污染按 43 维标定的潜空间), 而是当**条件**喂下一步预测器:
      ẑ(t+1) = f(z_t, rotvec(q_t))   vs   基线 f(z_t)
      q_t = 统一状态空间 L2 几何误差群点 (encode_obs43), z_t = 引擎潜表示 (同一帧 project)
判据: 留出集 (后段帧) 的 1 步潜预测 RMSE, 条件版 vs 无条件版; 以及 p 空间角误差。
数据: 状态空间工程轨迹 357 帧 (与 ▶运行 同一份 ss_traj_last.json)。
"""
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "src"),
          os.path.join(REPO, "src", "lerobot", "policies", "left_right", "state_space")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pose_caliper as pc                                          # noqa: E402
from lerobot.manifold.manifold_engine import ManifoldEngine        # noqa: E402
from lerobot.policies.left_right.state_space.su2 import encode_obs43  # noqa: E402

TRAJ = os.path.join(REPO, "data", "database", "zmax", "sources", "canvas", "ss_traj_last.json")
CKPT = os.path.join(REPO, "models", "manifold_engine.npz")
STATE_DIM, LATENT = 43, 16


def collect():
    traj = json.load(open(TRAJ, encoding="utf-8"))
    O = np.asarray(traj["obs"], float)[:, :STATE_DIM]
    eng = ManifoldEngine(manifold_type="su2", latent_dim=LATENT, state_dim=STATE_DIM,
                         action_dim=4, manifold_M=3.643, inertia=False, su2_tangent=True)
    loaded = False
    try:
        loaded = bool(eng.load(CKPT))
    except Exception:                                               # noqa: BLE001
        loaded = False
    Z, Q, P = [], [], []
    for i in range(len(O)):
        r = eng.project(O[i])
        Z.append(np.asarray(r["z"], float).ravel()[:LATENT])
        P.append(np.asarray(r["p"], float).ravel())
        q = encode_obs43(O[i])
        Q.append(np.asarray(pc.rotvec_from_q(np.array([q.w, q.x, q.y, q.z])), float))
    return np.asarray(Z), np.asarray(Q), np.asarray(P), loaded


def main() -> int:
    Z, Q, P, loaded = collect()
    print("帧 %d · z %s · q(rotvec) %s · 标定 loaded=%s" % (len(Z), Z.shape, Q.shape, loaded))
    n = len(Z)
    cut = int(n * 0.7)                                  # 前 70% 训练, 后 30% 留出 (时序切分, 不随机)
    # 标准化 (只用训练段统计)
    mz, sz_ = Z[:cut].mean(0), Z[:cut].std(0) + 1e-9
    mq, sq_ = Q[:cut].mean(0), Q[:cut].std(0) + 1e-9
    Zn = (Z - mz) / sz_
    Qn = (Q - mq) / sq_
    X0 = Zn[:-1].copy()                                 # 基线输入: z_t
    X1 = np.hstack([Zn[:-1], Qn[:-1]])                  # 条件输入: z_t + rotvec(q_t)
    Y = Zn[1:]                                          # 目标: z_{t+1}
    tr, va = slice(0, cut - 1), slice(cut - 1, None)

    import torch
    import torch.nn as nn
    torch.manual_seed(0)

    def fit(din, seed=0):
        torch.manual_seed(seed)
        net = nn.Sequential(nn.Linear(din, 32), nn.ReLU(), nn.Linear(32, 32), nn.ReLU(),
                            nn.Linear(32, LATENT))
        opt = torch.optim.Adam(net.parameters(), lr=3e-3, weight_decay=1e-4)
        xa = torch.tensor((X1 if din > LATENT else X0)[tr], dtype=torch.float32)
        ya = torch.tensor(Y[tr], dtype=torch.float32)
        for _ in range(600):
            opt.zero_grad()
            loss = ((net(xa) - ya) ** 2).mean()
            loss.backward()
            opt.step()
        return net

    def rmse(net, X, sel):
        with torch.no_grad():
            pred = net(torch.tensor(X[sel], dtype=torch.float32)).numpy()
        return float(np.sqrt(((pred - Y[sel]) ** 2).mean()))

    base = fit(LATENT)
    cond = fit(LATENT + 3)
    zoh = float(np.sqrt(((X0[va] - Y[va]) ** 2).mean()))            # 零阶保持基线
    rb, rc = rmse(base, X0, va), rmse(cond, X1, va)
    # 反标准化后的绝对误差尺度 (z 单位)
    scale = float(sz_.mean())
    rep = {
        "frames": int(n), "train": int(cut - 1), "holdout": int(n - cut),
        "rmse_zoh_normalized": round(zoh, 5),
        "rmse_base_z_only_normalized": round(rb, 5),
        "rmse_cond_z_plus_q_normalized": round(rc, 5),
        "cond_vs_base": round(rc / max(rb, 1e-12), 4),
        "cond_vs_zoh": round(rc / max(zoh, 1e-12), 4),
        "holdout_z_scale_mean": round(scale, 5),
        "note": "小样本 (留出 %d 段): 只证信号有无, 不当泛化精度" % int(n - cut),
    }
    os.makedirs(os.path.join(REPO, "reports"), exist_ok=True)
    with open(os.path.join(REPO, "reports", "q_conditioning.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    print("报告: %s" % os.path.join(REPO, "reports", "q_conditioning.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
