#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_action_mapping.py — 量 metaworld 的「动作 → 真实位移/速度」映射口径。

回答“引擎/前馈的速度到底怎么进 MuJoCo、标定准不准”。只读探针: 不写任何仓库状态, 不动真机。

用法 (仓库根目录):
    MUJOCO_GL=egl ./gui-venv311/bin/python scripts/probe_action_mapping.py
    MUJOCO_GL=egl ./gui-venv311/bin/python scripts/probe_action_mapping.py --acts 0.24 0.5 1.0 --seed 104
    MUJOCO_GL=egl ./gui-venv311/bin/python scripts/probe_action_mapping.py --k-act 0.5 --dz-only

输出四项事实:
  ① action_scale / frame_skip / timestep ⇒ 每个 env.step 的真物理时长 (常被默认当成 20ms 或 0.1s)
  ② mocap 目标每步位移 是否 == act×action_scale (校验换算通不通)
  ③ 稳态末端实测位移 ÷ 真 dt = 真实速度, 与指令 (act×K_ACT m/s) 的倍率
  ④ 关节 qvel 每步变化 (非零 = 动力学在跑, 我们从不写它)
"""
from __future__ import annotations

import argparse
import os

import numpy as np


def build_env(env_name: str, seed: int, camera: str = "corner2"):
    """与引擎同口径建 env (metaworld MT1 → train_classes[env_name] → set_task)。"""
    os.environ.setdefault("MUJOCO_GL", "egl")
    import metaworld
    mt = metaworld.MT1(env_name, seed=int(seed))
    env = mt.train_classes[env_name](render_mode="rgb_array", camera_name=camera)
    env.set_task(mt.train_tasks[0])
    try:
        env.max_path_length = 3000
    except Exception:                                                     # noqa: BLE001
        pass
    return env


def probe(env, act: float, axis: int = 2, warm: int = 20, meas: int = 20, k_act: float = 0.5) -> dict:
    """让末端沿 axis 方向走 act, 跳过 servo 爬升后量稳态位移。"""
    env.reset()
    a = np.zeros(4)
    a[axis] = float(act)
    mocap_step, ee_step, qvel_step = [], [], []
    for i in range(warm + meas):
        mp0 = np.array(env.data.mocap_pos[0], float)
        qv0 = np.array(env.data.qvel[:7], float)
        H0 = np.array(env.get_endeff_pos(), float)
        env.step(a)
        dm = np.linalg.norm(np.array(env.data.mocap_pos[0], float) - mp0)
        dq = np.linalg.norm(env.data.qvel[:7] - qv0)
        dH = np.linalg.norm(np.array(env.get_endeff_pos(), float) - H0)
        if i >= warm:
            mocap_step.append(dm)
            ee_step.append(dH)
            qvel_step.append(dq)
    dt_phys = float(env.frame_skip) * float(env.model.opt.timestep)
    d = float(np.mean(ee_step))
    return {
        "act": float(act),
        "cmd_mps": float(act) * float(k_act),
        "mocap_mm": float(np.mean(mocap_step)) * 1e3,
        "theory_mocap_mm": abs(float(act)) * float(env.action_scale) * 1e3,
        "ee_mm": d * 1e3,
        "real_mps": d / dt_phys if dt_phys > 0 else float("nan"),
        "d_qvel": float(np.mean(qvel_step)),
        "dt_phys": dt_phys,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="peg-insert-side-v3")
    ap.add_argument("--seed", type=int, default=104)
    ap.add_argument("--acts", type=float, nargs="+", default=[0.24, 0.5, 1.0])
    ap.add_argument("--axis", type=int, default=2, help="0/1/2 = x/y/z")
    ap.add_argument("--k-act", type=float, default=0.5, help="引擎 u(m/s) → act 的标定常数")
    ap.add_argument("--dz-only", action="store_true", help="只打一行结论, 便于脚本消费")
    args = ap.parse_args()

    env = build_env(args.env, args.seed)
    dt_phys = float(env.frame_skip) * float(env.model.opt.timestep)
    if not args.dz_only:
        print("=" * 78)
        print("metaworld 动作→物理 映射探针 · env=%s seed=%d" % (args.env, args.seed))
        print("=" * 78)
        print("action_scale = %s m · frame_skip = %s · timestep = %s s"
              % (env.action_scale, env.frame_skip, env.model.opt.timestep))
        print("每个 env.step 的真物理时长 = %d × %.4f = %.4f s   (K_ACT=%.3f 隐含 dt=%.4f s)"
              % (env.frame_skip, env.model.opt.timestep, dt_phys, args.k_act,
                 float(env.action_scale) / max(args.k_act, 1e-9)))
        print("nmocap = %s · eq(含 mocap weld) = %s · action_dim = %s"
              % (env.model.nmocap, env.model.neq, env.action_space.shape))
        print("-" * 78)
        print("  act   指令(m/s)  mocap/步   理论mocap   末端稳态/步   真实速度   对指令   Δqvel")
    for act in args.acts:
        r = probe(env, act, axis=args.axis, k_act=args.k_act)
        ratio = (r["real_mps"] / r["cmd_mps"]) if r["cmd_mps"] else float("nan")
        if args.dz_only:
            print("act=%.2f cmd=%.3f m/s real=%.4f m/s ratio=%.2fx ee=%.2fmm/step dt_phys=%.4fs"
                  % (r["act"], r["cmd_mps"], r["real_mps"], ratio, r["ee_mm"], r["dt_phys"]))
        else:
            print("  %.2f  %7.3f  %7.3fmm  %7.3fmm  %8.3fmm  %7.3f m/s  %5.2fx  %.4f"
                  % (r["act"], r["cmd_mps"], r["mocap_mm"], r["theory_mocap_mm"],
                     r["ee_mm"], r["real_mps"], ratio, r["d_qvel"]))
    if not args.dz_only:
        print("-" * 78)
        print("判读: ① mocap/步 == 理论 ⇒ action_scale 与换算通 ② 真实速度/指令 ≈1 ⇒ 口径对齐;")
        print("      ≠1 ⇒ K_ACT 与 frame_skip×timestep 不自洽 (按 action_scale/dt 重算 K_ACT 或调 frame_skip)")
        print("      ③ Δqvel≠0 ⇒ 关节速度由 MuJoCo 动力学给出, 外部没有写 qvel")
        print("      ④ 拿 data.mocap_pos 的变化当速度会偏高——目标总是精确到位, 末端才受伺服/饱和限制")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
