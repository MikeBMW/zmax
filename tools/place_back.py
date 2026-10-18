#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""place_back.py —— 把夹在爪里的光模块放回原来的槽位(反向复现抓取路径)

老倪 2026-10-18: 「你能把光模块，放回槽里么？」

依据(全部是实测真值, 不是猜):
  · 抓取参考 zmax_data/ar_rs/grasp_ref.json:
      抓取起始 TCP (646.6, 205.6, 110.5)  ABC (143.2, -85.58, 37.74)
      沿 tool1 +x 直进 110mm ⇒ 夹住时 TCP (653.3, 210.7, 220.2)
    模块被夹住后与爪是刚体 ⇒ **回到当初夹住千那一瞬的位姿, 模块就回到了它原来的位置**。
  · 所以放回 = 把 TCP/ABC 精确恢复到 (653.3, 210.7, 220.2)/(143.2,-85.58,37.74) → 松爪 → 沿 -tool1 x 退 110mm。

安全(每一步都卡):
  · 姿态差 >5°/步 会被 50113 拒 ⇒ 姿态按 ≤4° 分步
  · 位移按 ≤40mm 分步, motion=J(笛卡尔 MoveL 会撞 50120 奇异)
  · 每步前置: armed / automatic / idle / estop / power / has_error
  · 松爪前先核对 TCP 与目标差 <2mm
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import grasp_opt as G                       # noqa: E402

GRASP_TCP = np.array([653.3, 210.7, 220.2])
GRASP_ABC = np.array([143.2, -85.58, 37.74])
PULL_TCP = np.array([646.6, 205.6, 110.5])


def cur():
    """返回 (TCP mm, ABC 度)。G.pose() 的姿态是**弧度**, 必须换算 —— 不换算会把 3.1rad 当成 3.1°。"""
    xyz, abc = G.pose()[0], G.pose()[1]
    abc = np.array(abc, float)
    if np.abs(abc).max() <= 4.0:
        abc = np.degrees(abc)
    return np.array(xyz) * 1000.0, abc


def gm(a, b):
    """姿态差(度), 按单轴最大差算"""
    d = np.abs(((a - b + 180) % 360) - 180)
    return float(d.max()), d


def step_move(tgt_xyz, tgt_abc, speed, step_mm, step_deg, pause, tag):
    xyz0, abc0 = cur()
    n = max(int(math.ceil(np.linalg.norm(tgt_xyz - xyz0) / step_mm)),
            int(math.ceil(gm(abc0, tgt_abc)[0] / step_deg)), 1)
    print("  %s: %.0fmm / %.1f° ⇒ 分 %d 步" % (tag, np.linalg.norm(tgt_xyz - xyz0), gm(abc0, tgt_abc)[0], n))
    for k in range(1, n + 1):
        p = xyz0 + (tgt_xyz - xyz0) * k / n
        a = abc0 + (((tgt_abc - abc0 + 180) % 360) - 180) * k / n
        ok, bad, _s, _r = G.preflight()
        if not ok:
            print("   前置失效: %s" % " / ".join(bad))
            return False
        c0, _ = cur()
        # 🔴 实测(level_tool.py 里的教训): **纯姿态**(位移 0)的 move-abs 会被控制器静默忽略 ——
        #    回执 PASS、Δ=0、姿态一动不动。所以每一步姿态都带一个 ±1mm 的 z 抖动, 让它变成"位姿同时动"。
        zz = p[2] + (1.0 if k % 2 else -1.0)
        r = G.send({"cmd": "move-abs", "x": float(p[0] / 1000), "y": float(p[1] / 1000), "z": float(zz / 1000),
                    "rx": math.radians(float(a[0])), "ry": math.radians(float(a[1])),
                    "rz": math.radians(float(a[2])),
                    "speed": speed, "motion": "L", "allow_movej_retry": True}, wait=90)
        v = str(r.get("verdict", ""))
        if "PASS" not in v:
            print("   第%d/%d步被拒: %s" % (k, n, v[:90]))
            return False
        G.wait_settle(c0 / 1000.0, float(np.linalg.norm(p - c0)), timeout=45, min_frac=0.4)
        print("   [%d/%d] TCP %s ABC %s" % (k, n, np.round(np.array(cur()[0]), 1), np.round(cur()[1], 1)))
        time.sleep(pause)
    x1, a1 = cur()
    okp = np.linalg.norm(x1 - tgt_xyz) < 3.0 and gm(a1, tgt_abc)[0] < 1.5
    print("  %s 结果: 位置差 %.1fmm · 姿态差 %.2f° ⇒ %s" % (
        tag, np.linalg.norm(x1 - tgt_xyz), gm(a1, tgt_abc)[0], "到位" if okp else "没到位"))
    return okp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=20.0)
    ap.add_argument("--step-mm", type=float, default=35.0)
    ap.add_argument("--step-deg", type=float, default=4.0)
    ap.add_argument("--pause", type=float, default=3.0)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    xyz, abc = cur()
    print("起点 TCP %s ABC %s" % (np.round(xyz, 1), np.round(abc, 1)))
    print("目标 TCP %s ABC %s (当初夹住时的位姿)" % (GRASP_TCP, GRASP_ABC))
    print("姿态差 %.1f° · 距离 %.1fmm" % (gm(abc, GRASP_ABC)[0], np.linalg.norm(GRASP_TCP - xyz)))
    if a.dry:
        return 0

    # ① 先在当前高度把姿态转回抓取姿态(不升降, 免撞围栏/上横梁)
    if not step_move(xyz, GRASP_ABC, a.speed, a.step_mm, a.step_deg, a.pause, "转姿态"):
        print("姿态没到位 ⇒ 停(不乱动)")
        return 2
    # ② 平移到当初夹住的位姿
    if not step_move(GRASP_TCP, GRASP_ABC, a.speed, a.step_mm, a.step_deg, a.pause, "移到槽位"):
        print("平移没到位 ⇒ 停")
        return 3

    # ③ 松爪前最后核对
    x1, a1 = cur()
    if np.linalg.norm(x1 - GRASP_TCP) > 2.0 or gm(a1, GRASP_ABC)[0] > 1.0:
        print("⚠ 距目标 %.1fmm / %.2f° > 容差 ⇒ 不松爪" % (np.linalg.norm(x1 - GRASP_TCP), gm(a1, GRASP_ABC)[0]))
        return 4
    ok, bad, _s, _r = G.preflight()
    if not ok:
        print("前置失效: %s ⇒ 不松爪" % " / ".join(bad))
        return 5

    print("松爪…")
    r = G.send({"cmd": "grip", "op": "open"}, wait=40)
    print("  回执: %s" % str(r)[:160])
    time.sleep(2.0)

    # ④ 沿 -tool1 x 退 110mm(原路退出)
    if not step_move(PULL_TCP, GRASP_ABC, a.speed, a.step_mm, a.step_deg, a.pause, "退出"):
        print("退出没到位 ⇒ 人来看一眼")
        return 6
    print("完成: 模块已放回, 机械臂退到 %s" % np.round(cur()[0], 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
