#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCP 速度探针: URDF FK + 雅可比 × 桥 jointVel, 并与位置差分对账。

跑一条命令就能回答三件事 (无需 pinocchio, 只用 numpy + stdlib):
  1) 链对不对  —— FK(q).tool0 vs 桥 flangeInBase, FK(q).tool1 vs 桥 endInRef (实测 ≤1.8 / ≤2.9mm)
  2) 速度能不能用 —— J(q)·q̇  vs 0.5s 位置最小二乘 (实测差 5~10%)
  3) jointVel 此刻是否可信 —— 桥会整帧报 0 (缓存帧) ⇒ 报 0 时退回位置差分, 不许当真实静止

用法:
    ./gui-venv311/bin/python scripts/tcp_velocity_probe.py            # 单次快照
    ./gui-venv311/bin/python scripts/tcp_velocity_probe.py --watch 5  # 5 秒连续采样 (运动中跑)
数据源: http://127.0.0.1:39071/status 的 status.endInRef / jointPos / jointVel / flangeInBase
注意: 只读, 不下发任何动作。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.request
import xml.etree.ElementTree as ET

import numpy as np

ROOT = os.path.expanduser("~/zmax")
URDF = os.path.join(ROOT, "data/database/zmax/sources/config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf")
BRIDGE = "http://127.0.0.1:39071/status"


def rpy2R(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def T(xyz, rpy) -> np.ndarray:
    M = np.eye(4)
    M[:3, :3] = rpy2R(*rpy)
    M[:3, 3] = xyz
    return M


def axis_rot(axis, q: float) -> np.ndarray:
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    M = np.eye(4)
    M[:3, :3] = np.eye(3) + math.sin(q) * K + (1 - math.cos(q)) * (K @ K)
    return M


def chain():
    """按 URDF 文件顺序取出关节链 (本臂是 base→link1..6→tool0→tool1 的串联)。"""
    root = ET.parse(URDF).getroot()
    out = []
    for j in root.findall("joint"):
        o = j.find("origin")
        xyz = [float(v) for v in (o.get("xyz") or "0 0 0").split()] if o is not None else [0, 0, 0]
        rpy = [float(v) for v in (o.get("rpy") or "0 0 0").split()] if o is not None else [0, 0, 0]
        a = j.find("axis")
        ax = [float(v) for v in (a.get("xyz") or "0 0 1").split()] if a is not None else [0, 0, 1]
        out.append({"type": j.get("type"), "child": j.find("child").get("link"),
                    "xyz": xyz, "rpy": rpy, "axis": ax})
    return out


_CHAIN = None


def fk(q):
    """返回 (T_tool0, T_tool1), 均在基座系; q 单位 rad。"""
    global _CHAIN
    if _CHAIN is None:
        _CHAIN = chain()
    M = np.eye(4)
    T0 = T1 = None
    ki = 0
    for j in _CHAIN:
        M = M @ T(j["xyz"], j["rpy"])
        if j["type"] == "revolute":
            if ki < len(q):
                M = M @ axis_rot(j["axis"], float(q[ki]))
            ki += 1
        if j["child"].endswith("link6") or j["child"] == "tool0":
            T0 = M.copy()
        if j["child"] == "tool1":
            T1 = M.copy()
    return T0, T1


def jac(q, frame: str = "tool1", eps: float = 1e-5) -> np.ndarray:
    """3×6 平移雅可比 (中心差分形态的 FK 差分), frame=tool1|tool0。"""
    base = fk(q)[1 if frame == "tool1" else 0]
    J = np.zeros((3, 6))
    for i in range(6):
        qq = list(q)
        qq[i] += eps
        p = fk(qq)[1 if frame == "tool1" else 0]
        J[:, i] = (p[:3, 3] - base[:3, 3]) / eps
    return J


def bridge() -> dict:
    return json.loads(urllib.request.urlopen(BRIDGE, timeout=3).read())["status"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=float, default=0.0, help="连续采样秒数 (运动中对账用)")
    a = ap.parse_args()

    st = bridge()
    q = np.array(st["jointPos"], float)
    qd = np.array(st.get("jointVel") or [0] * 6, float)
    T0, T1 = fk(q)
    print("链校验 (差 >5mm 说明 URDF/零点不对):")
    print("  FK tool0 − flangeInBase :", np.round((T0[:3, 3] - np.array(st["flangeInBase"][:3])) * 1000, 2).tolist(), "mm")
    print("  FK tool1 − endInRef     :", np.round((T1[:3, 3] - np.array(st["endInRef"][:3])) * 1000, 2).tolist(), "mm")

    J = jac(q)
    vj = J @ qd
    print("jointVel:", np.round(qd, 5).tolist(), "| J·q̇ (mm/s):", np.round(vj * 1000, 2).tolist())
    if not np.any(np.abs(qd) > 1e-9):
        print("  ⚠ jointVel 整帧为 0 (桥缓存帧或真静止) ⇒ 相图必须退回位置差分, 不许直接记 0")

    if a.watch <= 0:
        return 0
    print("\n连续采样 %.1fs 对账 (J·q̇ vs 0.5s 位置最小二乘):" % a.watch)
    buf = []
    t0 = time.time()
    while time.time() - t0 < a.watch:
        st = bridge()
        ts, pos = float(st.get("ts") or time.time()), np.array(st["endInRef"][:3], float)
        buf.append((ts, pos))
        if len(buf) >= 3:
            arr = np.array([b[1] for b in buf[-6:]])
            tt = np.array([b[0] for b in buf[-6:]])
            vd = np.linalg.lstsq(np.vstack([tt - tt[-1], np.ones(len(tt))]).T, arr, rcond=None)[0][0]
            vj = jac(np.array(st["jointPos"], float)) @ np.array(st.get("jointVel") or [0] * 6, float)
            print("  v_z  J·q̇ %+7.2f | 差分 %+7.2f mm/s   |v| %5.1f mm/s"
                  % (vj[2] * 1000, vd[2] * 1000, float(np.linalg.norm(vd)) * 1000), flush=True)
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
