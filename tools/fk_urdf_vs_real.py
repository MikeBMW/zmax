#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线统计: 用一整天的 50Hz 真值 tap (jpos + tcp) 批量核对 URDF 口径。

📚 2026-10-18 老倪: 「先别动真机，想想用 moveit 怎么精确控制机器人，先给出完整方案」
   MoveIt 要"精确控制"，第一块地基是模型口径。这里**只读** tcp_direct_*.jsonl，不动臂:
     · FK(tool1) 位置误差 分布 (均值/中位/95%/最大)
     · 姿态误差 (度)
     · 误差向量在 base 系里是否恒定 (恒定=常值偏置; 随位形变=零位/标定问题)

用法: ./gui-venv311/bin/python tools/fk_urdf_vs_real.py [--every 200]
"""
import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fk_check_tool_frame import fk, URDF      # noqa: E402  (同一个 FK 实现, 不复制)

TAP = "zmax_data/rokae_sdk/tcp_out/tcp_direct_20261018.jsonl"


def quat_angle_deg(q1, q2):
    a = np.asarray(q1, float)
    b = np.asarray(q2, float)
    a /= np.linalg.norm(a)
    b /= np.linalg.norm(b)
    d = abs(float(np.dot(a, b)))
    return math.degrees(2 * math.acos(min(1.0, d)))


def quat_of(T):
    R = T[:3, :3]
    w = math.sqrt(max(0.0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    if w < 1e-8:
        return [0, 0, 0, 1]
    x = (R[2, 1] - R[1, 2]) / (4 * w)
    y = (R[0, 2] - R[2, 0]) / (4 * w)
    z = (R[1, 0] - R[0, 1]) / (4 * w)
    return [x, y, z, w]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=200)
    ap.add_argument("--tap", default=TAP)
    a = ap.parse_args()

    if not os.path.exists(a.tap):
        print("找不到真值 tap: %s" % a.tap)
        return 2

    pos_err, ang_err, vecs = [], [], []
    n = 0
    with open(a.tap, "r", encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f):
            if i % a.every:
                continue
            try:
                d = json.loads(line)
                q = d.get("joint") or d.get("jpos") or []
                tcp = d.get("tcp") or [d.get("x"), d.get("y"), d.get("z")]
                quat = d.get("tcp_quat") or [d.get("qx"), d.get("qy"), d.get("qz"), d.get("qw")]
                if len(q) < 6 or any(v is None for v in tcp) or any(v is None for v in quat):
                    continue
                T = fk(URDF, "tool1", [float(v) for v in q[:6]])
                p = T[:3, 3]
                e = p - np.asarray([float(v) for v in tcp], float)
                pos_err.append(np.linalg.norm(e) * 1000.0)
                ang_err.append(quat_angle_deg(quat_of(T), [float(v) for v in quat]))
                vecs.append(e * 1000.0)
                n += 1
            except Exception:                                            # noqa: BLE001
                continue

    if not pos_err:
        print("没有可用样本")
        return 2
    pe = np.asarray(pos_err)
    ae = np.asarray(ang_err)
    V = np.asarray(vecs)
    print("样本数: %d (每 %d 行取 1)" % (n, a.every))
    print("位置误差 mm : 均值 %.2f · 中位 %.2f · 95%% %.2f · 最大 %.2f" %
          (pe.mean(), np.median(pe), np.percentile(pe, 95), pe.max()))
    print("姿态误差 deg: 均值 %.2f · 95%% %.2f · 最大 %.2f" % (ae.mean(), np.percentile(ae, 95), ae.max()))
    print("误差向量 base 系 (mm): 均值 (%+.1f, %+.1f, %+.1f) · std (%.1f, %.1f, %.1f)" %
          (V[:, 0].mean(), V[:, 1].mean(), V[:, 2].mean(), V[:, 0].std(), V[:, 1].std(), V[:, 2].std()))
    const = np.linalg.norm(V.mean(axis=0))
    resid = pe.mean()
    print("常值偏置 %.1f mm / 抖动 %.1f mm  ⇒ %s" %
          (const, resid, "以常值偏置为主(改 tool1 偏移即可)" if const > 2 * V.std(axis=0).mean()
           else "随位形变化(需关节零位/连杆标定)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
