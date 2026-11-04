#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""💪 力通道回填 — 用引擎自己的接触力方程, 从已录状态反算每步真实接触力

背景 (实测):
  引擎每步都算接触力 (src/lerobot/engine/sim.py:411-425):
    未夹持: force_z = K·max(0.012-(x_z-peg_z), 0.5·D)
    已夹持: force_z = K·max(0, D-d_hole_h)
    force_norm = clip(force_z/(K·D), 0, 1)
  但 perception.fuse_sensors 明确写 "force_6d 不直接进 obs" ⇒ 43D obs = visual39 + tactile4,
  recorder 存下来的只有 visual39 ⇒ **训练数据里力全是 0** (实测 obs[13:18] max|·|=0.0)。

本工具: 只用已录 obs (x/grip/peg/hole) + 引擎常量, 逐帧反算 force_norm 与 contact,
        产出独立 h5 (force(N,5) = [f_norm, contact, gripper, 0, 0]), 供 V6 力支路使用。
        口径与引擎 sim.py 完全一致 (常量直接 import, 不抄写)。

用法:
  PY=/home/ubuntu/zmax/external/INTACT-JEPA/.venv/bin/python
  $PY tools/backfill_force_v6.py --h5 <原h5> --out <cache>/datasets/force_v6.h5
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, f"{ROOT}/src")

# 引擎真常量 (唯一来源: sim.py), 不在这里抄数值
from lerobot.engine.sim import (  # noqa: E402
    D_CONTACT, HOLE_MOUTH, K_CONTACT, PEG_HEAD_OFF,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--h5", default="/home/ubuntu/zmax/zmax_data/stable-wm-cache/datasets/optical_insert_v6_disturb.h5")
    ap.add_argument("--out", default="/home/ubuntu/zmax/zmax_data/stable-wm-cache/datasets/force_v6.h5")
    a = ap.parse_args()

    import h5py
    src = h5py.File(a.h5, "r")
    obs = np.asarray(src["observation"][:], np.float32)
    off = np.asarray(src["ep_offset"][:], np.int64)
    ln = np.asarray(src["ep_len"][:], np.int64)
    N = len(obs)

    force = np.zeros((N, 5), np.float32)
    n_contact = 0
    n_grasped_steps = 0
    for e in range(len(off)):
        o0, L = int(off[e]), int(ln[e])
        grasped = False
        for t in range(L):
            i = o0 + t
            x, grip, peg = obs[i, 0:3], float(obs[i, 3]), obs[i, 7:10]
            # 夹持锁存 (sim.py:542 — 抓取阶段 gripper>0.5 后永久随末端)
            if (not grasped) and grip > 0.5:
                grasped = True
            if grasped:
                n_grasped_steps += 1
            peg_head = peg + PEG_HEAD_OFF
            d_xy_peg = float(np.linalg.norm(x[:2] - peg[:2]))
            d_hole_h = float(np.linalg.norm(peg_head[:2] - HOLE_MOUTH[:2]))
            contact = (d_xy_peg < 0.03 and (x[2] - peg[2]) < 0.012) if not grasped else (d_hole_h < D_CONTACT)
            fz = 0.0
            if contact:
                if not grasped:
                    gap_z = max(0.0, 0.012 - (x[2] - peg[2]))
                    fz = K_CONTACT * max(gap_z, 0.5 * D_CONTACT)
                else:
                    fz = K_CONTACT * max(0.0, D_CONTACT - d_hole_h)
                n_contact += 1
            f_norm = float(np.clip(fz / (K_CONTACT * D_CONTACT), 0.0, 1.0))
            force[i] = (f_norm, float(contact), grip, 0.0, 0.0)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with h5py.File(a.out, "w") as dst:
        dst.create_dataset("force", data=force)
        dst.create_dataset("ep_offset", data=off)
        dst.create_dataset("ep_len", data=ln)
        dst.attrs["src"] = os.path.abspath(a.h5)
        dst.attrs["formula"] = "sim.py:411-425 contact force (K_CONTACT/D_CONTACT/HOLE_MOUTH/PEG_HEAD_OFF imported)"
        dst.attrs["cols"] = "f_norm,contact,gripper,0,0"

    print(f"力通道回填 → {a.out}")
    print(f"  行数 {N} | 接触帧 {n_contact} ({n_contact / N * 100:.1f}%) | 夹持帧 {n_grasped_steps}")
    print(f"  f_norm: mean {force[:, 0].mean():.4f} max {force[:, 0].max():.3f} 非零帧 {(force[:, 0] > 0).sum()}")
    print(f"  contact 帧 {int(force[:, 1].sum())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
