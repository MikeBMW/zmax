#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线标定: 拟合 URDF tool1 (夹爪尖) 到真机 TCP 的**常值偏置** (平移 + 旋转)。

📚 2026-10-18 老倪: 「先别动真机，想想用 moveit 怎么精确控制机器人，先给出完整方案」
   方案 V1 的第一步: 口径统一。实测 FK(tool1) vs 真机 TCP 残差 3.05mm / 3.66°,
   且误差向量在 base 系近似恒定 ⇒ 是"模型里夹爪尖位置/姿态没对准"的常值偏置, 可以拟合出来。

模型 (都在工具系里表达):
    p_real = p_fk + R_fk · t_off
    R_real = R_fk · R_off
只读 50Hz 真值 tap, 不动臂、不写任何配置; 输出 t_off(mm) / rpy_off(deg) 与拟合前后残差。

用法: ./gui-venv311/bin/python tools/fit_tcp_offset.py [--every 60] [--tap 路径]
"""
import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fk_check_tool_frame import fk, URDF, rpy2m            # noqa: E402

TAP_DEFAULT = "zmax_data/rokae_sdk/tcp_out/tcp_direct_20261018.jsonl"
TIP = "tool1"


def quat2R(q):
    x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], float)


def R2rpy(R):
    sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    if sy > 1e-9:
        return math.degrees(math.atan2(R[2, 1], R[2, 2])), math.degrees(math.atan2(-R[2, 0], sy)), \
            math.degrees(math.atan2(R[1, 0], R[0, 0]))
    return math.degrees(math.atan2(-R[1, 2], R[1, 1])), math.degrees(math.atan2(-R[2, 0], sy)), 0.0


def angle_deg(Ra, Rb):
    c = (np.trace(Ra.T @ Rb) - 1.0) / 2.0
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def load(tap, every):
    ps, qs, prs, qrs = [], [], [], []
    with open(tap, encoding="utf-8") as f:
        for i, ln in enumerate(f):
            if i % every:
                continue
            try:
                d = json.loads(ln)
            except Exception:                                            # noqa: BLE001
                continue
            # 真值 tap 实际字段: joint[12] + x/y/z + qx/qy/qz/qw (见 tcp_direct_*.jsonl 首行)
            q = d.get("joint") or d.get("jpos")
            p = d.get("tcp") or d.get("pos") or ([d.get("x"), d.get("y"), d.get("z")]
                                                 if d.get("x") is not None else None)
            qr = d.get("quat") or ([d.get("qx"), d.get("qy"), d.get("qz"), d.get("qw")]
                                   if d.get("qx") is not None else None)
            if not (q and p and qr and len(q) >= 6 and len(p) >= 3):
                continue
            ps.append([float(v) for v in q[:6]])
            prs.append(np.array([float(v) for v in p[:3]], float))
            qrs.append(quat2R(qr[:4]))
    return np.array(ps), prs, qrs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tap", default=TAP_DEFAULT)
    ap.add_argument("--every", type=int, default=60)
    a = ap.parse_args()
    if not os.path.isfile(a.tap):
        print("❌ 没有真值 tap: %s" % a.tap)
        return 1
    joints, preal, Rreal = load(a.tap, max(1, a.every))
    if len(joints) < 20:
        print("❌ 样本太少: %d" % len(joints))
        return 1

    Fk, Rfk = [], []
    for q in joints:
        T = fk(URDF, TIP, q)
        Fk.append(T[:3, 3])
        Rfk.append(T[:3, :3])
    Fk = np.array(Fk)
    preal = np.array(preal)

    e0 = preal - Fk
    n0 = np.linalg.norm(e0, axis=1)
    a0 = [angle_deg(Rfk[i], Rreal[i]) for i in range(len(Rfk))]

    # ① 平移: p_real - p_fk = R_fk · t   (最小二乘, 每个样本 3 行)
    A = np.vstack([R for R in Rfk])
    b = e0.reshape(-1)
    t_off, *_ = np.linalg.lstsq(A, b, rcond=None)

    # ② 旋转: 用平移修正后的点求平均 R_off = mean(R_fk^T · R_real) → 投到 SO(3)
    M = np.zeros((3, 3))
    for i in range(len(Rfk)):
        M += Rfk[i].T @ Rreal[i]
    U, _, Vt = np.linalg.svd(M)
    R_off = U @ Vt
    if np.linalg.det(R_off) < 0:
        U[:, -1] *= -1
        R_off = U @ Vt

    # 拟合后残差
    p_adj = np.array([Fk[i] + Rfk[i] @ t_off for i in range(len(Fk))])
    e1 = preal - p_adj
    n1 = np.linalg.norm(e1, axis=1)
    a1 = [angle_deg(Rfk[i] @ R_off, Rreal[i]) for i in range(len(Rfk))]
    rpy = R2rpy(R_off)

    print("样本: %d (每 %d 帧抽 1) · tip=%s" % (len(joints), a.every, TIP))
    print("拟合前: 位置 均值 %.2fmm · 95%% %.2fmm · 最大 %.2fmm | 姿态 均值 %.2f° 最大 %.2f°"
          % (n0.mean(), np.percentile(n0, 95), n0.max(), np.mean(a0), np.max(a0)))
    print("拟合后: 位置 均值 %.2fmm · 95%% %.2fmm · 最大 %.2fmm | 姿态 均值 %.2f° 最大 %.2f°"
          % (n1.mean(), np.percentile(n1, 95), n1.max(), np.mean(a1), np.max(a1)))
    print("常值偏置 (工具系): t_off = [%.2f, %.2f, %.2f] mm" % tuple(t_off * 1000.0))
    print("常值偏置 (工具系): rpy_off = [%.3f, %.3f, %.3f] deg" % rpy)

    out = {"tip": TIP, "n": int(len(joints)), "every": a.every,
           "before": {"mean_mm": float(n0.mean()), "p95_mm": float(np.percentile(n0, 95)),
                      "max_mm": float(n0.max()), "rot_mean_deg": float(np.mean(a0)), "rot_max_deg": float(np.max(a0))},
           "after": {"mean_mm": float(n1.mean()), "p95_mm": float(np.percentile(n1, 95)),
                     "max_mm": float(n1.max()), "rot_mean_deg": float(np.mean(a1)), "rot_max_deg": float(np.max(a1))},
           "t_off_mm": [float(x * 1000.0) for x in t_off], "rpy_off_deg": [float(x) for x in rpy]}
    fp = "zmax_data/runtime/moveit_plan/tcp_offset_fit.json"
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("落盘: %s" % fp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
