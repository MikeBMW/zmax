#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_l4_cond_l2.py — 训「L4 条件 → L2 真实 action」, 并做同口径消融。

为什么不是训 DiT 里那张 l4_cond_proj:
  那条路要 image + state + action 的真实数据集。现场唯一的真机 lerobot 数据集
  (zmax_live_215ep1_128, 4 episodes / 9171 帧) 的 images/ 目录是**空的**(0 个文件),
  没有图像就没法跑策略前向 ⇒ 那条路当前物理上做不了, 硬训出来的只是随机投影。
  能做且能证明的: 在真值上直接学 cond → action, 并做「有 cond / 无 cond / 线性 / 不动」四路对照。

数据: zmax_data/rokae_sdk/real_traj_joints_v2q.json (239 点真值回放, 238 个转移)
  cond_i  = SE3Engine 同源 build_cond (15 维: ξ̂6 + manifold6 + intent3), 目标=下一拍真值
  action_i= [Δx,Δy,Δz (mm), Δrx,Δry,Δrz (deg), grip]
判据: 按时间 8:2 切, 报 RMSE(mm)。有提升(≥5%)才写 models/l4_cond_l2.pt, 否则如实写影子。
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.manifold import se3_engine as SE  # noqa: E402

DATA = os.path.join(ROOT, "zmax_data/rokae_sdk/real_traj_joints_v2q.json")
OUT = os.path.join(ROOT, "models/l4_cond_l2.pt")
MARGIN = 0.05


def T_from(p, q):
    from lerobot.manifold.se3_engine import T_from_rot_t, quat_to_R
    return T_from_rot_t(quat_to_R(np.asarray(q, float)), np.asarray(p, float))


def build():
    fr = json.load(open(DATA))["frames"]
    X, Y, C = [], [], []
    for a, b in zip(fr, fr[1:]):
        Ta, Tb = T_from(a["p"], a["q"]), T_from(b["p"], b["q"])
        xi = SE.se3_log(np.linalg.inv(Tb) @ Ta)          # 体坐标: log(T_goal⁻¹ T) 的口径取负号方向
        xi = -xi                                          # 取“朝目标走”的方向
        cond = SE.build_cond(SE.normalize_twist(xi), np.zeros(6), np.zeros(3))
        act = [ (b["p"][0]-a["p"][0])*1000, (b["p"][1]-a["p"][1])*1000, (b["p"][2]-a["p"][2])*1000,
                *[math.degrees(b["rpy"][k]-a["rpy"][k]) for k in range(3)], 1.0 ]
        X.append(cond); Y.append(act); C.append(xi)
    return np.asarray(X, np.float32), np.asarray(Y, np.float32)


def main():
    import torch
    import torch.nn as nn
    X, Y = build()
    n = len(X)
    cut = int(n * 0.8)
    dev = "cpu"
    xt, yt = torch.tensor(X[:cut]), torch.tensor(Y[:cut])
    xv, yv = torch.tensor(X[cut:]), torch.tensor(Y[cut:])
    print("[data] %d 转移 (train %d / val %d) · cond %d 维 · action %d 维"
          % (n, cut, n - cut, X.shape[1], Y.shape[1]))

    def mk(din):
        return nn.Sequential(nn.Linear(din, 128), nn.SiLU(), nn.Linear(128, 128), nn.SiLU(),
                             nn.Linear(128, 7)).to(dev)

    def rmse(model, x, y):
        with torch.no_grad():
            return float(torch.sqrt(((model(x) - y) ** 2).mean()))

    res = {}
    # ① 保持不动 (全零动作)
    res["persist"] = float(torch.sqrt((yv ** 2).mean()))
    # ② 线性外推 (沿用上一个动作)
    res["linear"] = float(torch.sqrt((yv - yt[-1:].expand_as(yv)) ** 2).mean())
    # ③ 无 cond 消融
    m0 = mk(0); opt = torch.optim.Adam(m0.parameters(), 1e-3)
    for ep in range(400):
        opt.zero_grad(); loss = ((m0(torch.zeros(len(xt), 0)) - yt) ** 2).mean(); loss.backward(); opt.step()
    res["no_cond"] = rmse(m0, torch.zeros(len(xv), 0), yv)
    # ④ 有 cond
    m1 = mk(X.shape[1]); opt = torch.optim.Adam(m1.parameters(), 1e-3)
    for ep in range(400):
        opt.zero_grad(); loss = ((m1(xt) - yt) ** 2).mean(); loss.backward(); opt.step()
    res["with_cond"] = rmse(m1, xv, yv)

    gain = (res["no_cond"] - res["with_cond"]) / max(res["no_cond"], 1e-9) * 100
    print("[rmse mm] " + " · ".join("%s %.2f" % (k, v) for k, v in res.items()))
    print("[cond 增益] 相对无 cond %+.2f%% ; 相对 persist %+.2f%%"
          % (gain, (res["persist"] - res["with_cond"]) / res["persist"] * 100))
    ok = gain >= MARGIN * 100
    if ok:
        torch.save({"state_dict": m1.state_dict(), "dim": int(X.shape[1]),
                    "note": "L4 cond(15) → L2 action(7), 真值训练", "rmse": res}, OUT)
        print("[adopt] 写 %s" % OUT)
    else:
        print("[shadow] cond 增益不足 %.1f%% ⇒ 不写默认权重, 只报数" % (MARGIN * 100))
    os.makedirs(os.path.join(ROOT, "zmax_data/se3_evolve"), exist_ok=True)
    json.dump({"n": n, "rmse": res, "gain_pct": round(gain, 2), "adopted": bool(ok),
               "data": DATA}, open(os.path.join(ROOT, "zmax_data/se3_evolve/l4_cond_l2_report.json"), "w"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
