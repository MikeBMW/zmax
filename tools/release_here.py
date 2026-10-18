#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""release_here.py —— 老倪口径: **先放回去 → 松开夹爪 → 再抬升**

现场口径(2026-10-18 收工前):
  · 腕相机俯仰使 tool1 +x 朝上 ⇒ 模块比 TCP 高约 110mm。
  · 老倪认可的"光模块回位"状态 = TCP (646.6, 205.6, 109.5) / ABC (143.2,-85.58,37.74) 这一位姿
    (place_back 退到这里的画面他说"好，成功回位"), 此时模块正落在槽里, 只是爪还夹着(174)。
  · 所以顺序必须是: 先降到这个位姿 → 张爪 → 确认真张开(>700) → 再抬升离开。
    先抬升会把模块带离槽位(他刚就骂了"你又抬升了")。

用法: release_here.py [速度]   (默认 20mm/s)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import grasp_opt as G                                          # noqa: E402
from place_back import GRASP_ABC, PULL_TCP, cur, step_move      # noqa: E402
from place_back_finish import gripper_pos                       # noqa: E402

RAISE = np.array([PULL_TCP[0], PULL_TCP[1], PULL_TCP[2] + 80.0])   # 松爪后往上抬 80mm 离开


def main():
    speed = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    xyz, abc = cur()
    print("起点 TCP %s ABC %s · 夹爪 %s" % (np.round(xyz, 1), np.round(abc, 1), gripper_pos()))

    # ① 先放回去: 降到老倪认可的位姿(只降不升)
    if np.linalg.norm(xyz - PULL_TCP) > 2.0:
        if not step_move(PULL_TCP, GRASP_ABC, speed, 35.0, 4.0, 2.0, "降到槽位(只降)"):
            print("没降到槽位 ⇒ 不张爪")
            return 2
    time.sleep(1.5)

    # ② 张爪
    print("张爪: {'skill':'L2.grip_open'}")
    r = G.send({"skill": "L2.grip_open", "speed": 20.0}, wait=45)
    print("  回执:", json.dumps(r, ensure_ascii=False)[:220])
    time.sleep(2.5)
    gp = gripper_pos()
    print("  夹爪真值:", gp, "(合住 174 / 张开应 >700)")
    if gp is None or gp < 500:
        print("⚠ 没真张开 ⇒ 先不抬升, 请人看")
        return 3

    # ③ 松开之后才抬升离开
    if not step_move(RAISE, GRASP_ABC, speed, 35.0, 4.0, 2.0, "抬升离开"):
        print("抬升没到位 ⇒ 人来看")
        return 4
    print("完成: 模块在槽里 · 夹爪 %s · 机械臂 %s" % (gripper_pos(), np.round(cur()[0], 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
