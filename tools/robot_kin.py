#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""robot_kin.py — 用 truth 机器人描述做正/逆解(XMS5-R800)。

真源: zmax_data/full_system_20260922/config/robot/zmax_robot_spec.json
     joints[i] = {axis, origin_xyz, origin_rpy, limit}

为什么需要它: 回放"照搬示教轨迹"时, 笛卡尔 MoveL/MoveJ 都会在手腕奇异区停住
(实测 694.5,192.1,208.0 / pitch −88.5°)。绕开的办法是**关节空间 MoveAbsJ**,
而控制器不提供 IK, 所以在这里自己算。

用法:
  python tools/robot_kin.py selftest            # 用当前关节位姿自检 FK 与控制器 TCP 的偏差
  python tools/robot_kin.py ik  <traj.json> <out.json>   # 逐点 IK(以前一点为种子)
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "zmax_data/full_system_20260922/config/robot/zmax_robot_spec.json")


def rot(axis, q):
    axis = np.asarray(axis, float)
    axis = axis / (np.linalg.norm(axis) or 1.0)
    x, y, z = axis
    c, s = math.cos(q), math.sin(q)
    C = 1 - c
    return np.array([[x*x*C + c, x*y*C - z*s, x*z*C + y*s],
                     [y*x*C + z*s, y*y*C + c, y*z*C - x*s],
                     [z*x*C - y*s, z*y*C + x*s, z*z*C + c]])


def rpy_mat(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy*cp, cy*sp*sr - sy*cr, cy*sp*cr + sy*sr],
                     [sy*cp, sy*sp*sr + cy*cr, sy*sp*cr - cy*sr],
                     [-sp, cp*sr, cp*cr]])


def load_chain(spec_path=SPEC):
    d = json.load(open(spec_path))
    js = []
    for j in d["joints"]:
        if j.get("type") not in (None, "revolute"):
            continue
        lm = j.get("limit") or {}
        js.append({"axis": j["axis"], "xyz": j["origin_xyz"], "rpy": j["origin_rpy"],
                   "lim": (lm.get("lower", -6.2832), lm.get("upper", 6.2832))})
    return js


def fk(js, q):
    T = np.eye(4)
    for j, qi in zip(js, q):
        A = np.eye(4)
        A[:3, :3] = rpy_mat(*j["rpy"])
        A[:3, 3] = j["xyz"]
        B = np.eye(4)
        B[:3, :3] = rot(j["axis"], qi)
        T = T @ A @ B
    return T


def mat_to_rpy(R):
    p = math.atan2(-R[2, 0], math.hypot(R[0, 0], R[1, 0]))
    return [math.atan2(R[2, 1], R[2, 2]), p, math.atan2(R[1, 0], R[0, 0])]


def ik(js, p_mm, rpy, seed):
    """数值 IK(信任种子, 输出与种子同解支)。p_mm 毫米; 返回 (q, err_mm, err_deg)。"""
    from scipy.optimize import least_squares
    target = np.asarray(p_mm, float) / 1000.0
    Rt = rpy_mat(*rpy)

    def res(q):
        T = fk(js, q)
        e1 = (T[:3, 3] - target)
        dR = T[:3, :3].T @ Rt
        ang = math.acos(max(-1.0, min(1.0, (np.trace(dR) - 1) / 2)))
        ax = np.array([dR[2, 1] - dR[1, 2], dR[0, 2] - dR[2, 0], dR[1, 0] - dR[0, 1]])
        n = np.linalg.norm(ax)
        e2 = (ax / n * ang) if n > 1e-9 else np.zeros(3)
        return np.concatenate([e1 * 1000.0, e2 * 500.0])   # mm 与 rad 混合加权

    lo = [j["lim"][0] for j in js]
    hi = [j["lim"][1] for j in js]
    r = least_squares(res, np.asarray(seed, float), bounds=(lo, hi),
                      xtol=1e-10, ftol=1e-10, max_nfev=400)
    T = fk(js, r.x)
    err_mm = float(np.linalg.norm((T[:3, 3] - target) * 1000.0))
    dR = T[:3, :3].T @ Rt
    err_deg = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(dR) - 1) / 2))))
    return list(r.x), err_mm, err_deg


def _selftest():
    jp = json.load(open(os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/joints.json"))) if os.path.exists(
        os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/joints.json")) else None
    if not jp:
        print("没有 joints.json, 先跑 tools/rokae/_probe_joints.py 落一份")
        return 1
    js = load_chain()
    q = jp["q"]
    T = fk(js, q)
    print("FK  flange  %.1f,%.1f,%.1f mm  rpy %.3f,%.3f,%.3f"
          % (*(T[:3, 3] * 1000.0), *mat_to_rpy(T[:3, :3])))
    print("控制器 TCP %.1f,%.1f,%.1f mm  rpy %s"
          % (*jp["tcp_mm"], [round(v, 3) for v in jp.get("rpy") or []]))
    print("差 %.1f mm" % float(np.linalg.norm(T[:3, 3] * 1000.0 - np.asarray(jp["tcp_mm"]))))
    return 0


def _ik_traj(src, dst):
    js = load_chain()
    fr = json.load(open(src))["frames"]
    q = list(fr[0].get("q") or [0.0] * 6)
    out, worst = [], (0.0, 0.0)
    for f in fr:
        p = f["p"]
        rpy = f["rpy"]
        seed = q
        q, e_mm, e_deg = ik(js, p, rpy, seed)
        worst = (max(worst[0], e_mm), max(worst[1], e_deg))
        out.append({"p": p, "rpy": rpy, "q": [round(v, 6) for v in q]})
    json.dump({"frames": out, "worst": {"mm": round(worst[0], 3), "deg": round(worst[1], 3)}},
              open(dst, "w"))
    print("IK %d 点 · 最差 %.2fmm / %.2f° → %s" % (len(out), worst[0], worst[1], dst))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "selftest":
        raise SystemExit(_selftest())
    if len(sys.argv) >= 4 and sys.argv[1] == "ik":
        raise SystemExit(_ik_traj(sys.argv[2], sys.argv[3]))
    print(__doc__)
