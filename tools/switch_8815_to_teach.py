#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""switch_8815_to_teach.py — 让 8815 看板改为跟随**当前正在回放的示教轨迹**。

背景: 页面原来固定读 demo 集(现场演示那一遍), 而机械臂现在跑的是"示教关节轨迹",
两条路线不同 ⇒ 投影距离 >60mm, 前端按设计不跟随(看起来就是"状态没跟着动")。

做法(不动服务端代码, 直接换 demo 集的文件, 原文件备份为 *_orig):
  real_traj_joints_demo.json  ← real_traj_absj.json (448 帧, 带 p/rpy)
  traj_phase_demo.json        ← 由同一条轨迹算 s/s_mm/p
  phase_states_demo.json      ← 沿用已学出的段表(按帧比例映射到新索引)
"""
from __future__ import annotations

import json
import math
import os
import shutil

SDK = "/home/ubuntu/zmax/zmax_data/rokae_sdk"
BK = os.path.join(SDK, "_backup_8815")
os.makedirs(BK, exist_ok=True)


def backup(name):
    src = os.path.join(SDK, name)
    if os.path.exists(src):
        dst = os.path.join(BK, name)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)


for n in ("real_traj_joints_demo.json", "traj_phase_demo.json", "phase_states_demo.json"):
    backup(n)

src = json.load(open(os.path.join(SDK, "real_traj_absj.json")))["frames"]
P = [f["p"] for f in src]
n = len(P)

# 轨迹(带 p/rpy)
traj = {"summary": {"n": n}, "frames": [{"i": i, "p": f["p"], "rpy": f["rpy"]} for i, f in enumerate(src)]}
json.dump(traj, open(os.path.join(SDK, "real_traj_joints_demo.json"), "w"))

# 相位
acc = [0.0]
for i in range(n - 1):
    acc.append(acc[-1] + math.dist(P[i], P[i + 1]))
tot = acc[-1] or 1.0
phase = {"summary": {"len_mm": round(tot, 1)},
         "frames": [{"s": round(a / tot, 6), "s_mm": round(a, 1), "p": P[i]} for i, a in enumerate(acc)]}
json.dump(phase, open(os.path.join(SDK, "traj_phase_demo.json"), "w"))

# 段表: 把已学的段(基于 1247 帧原始日志) 按比例映射到 448 帧
learned = sorted([f for f in os.listdir(SDK) if f.startswith("learned_")])
if learned:
    lf = os.path.join(SDK, learned[-1])
else:
    import glob
    lf = sorted(glob.glob("/home/ubuntu/zmax/zmax_data/teach/learned_*.json"))[-1]
st = json.load(open(lf))["states"]
n_old = max(s["i1"] for s in st) + 1
out = [{"i0": int(round(s["i0"] / n_old * (n - 1))), "i1": int(round(s["i1"] / n_old * (n - 1))),
        "name": s["name"]} for s in st]
json.dump({"states": out}, open(os.path.join(SDK, "phase_states_demo.json"), "w"), ensure_ascii=False, indent=1)
print("8815 已切到示教轨迹: %d 帧 · %.0fmm · 段 %d 条" % (n, tot, len(out)))
print("备份目录:", BK)
