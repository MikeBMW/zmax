#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""put_back_now.py —— 把模块送回抓取点 → 松爪 → 再抬升(老倪收工前最后一条)

几何依据(实测数据, 不是猜):
  · 抓取序列 grasp_ref.json: TCP 从 (646.6,205.6,110.5) 沿 tool1 +x 直进 110mm 到 (653.3,210.7,220.2), **在此处合爪**。
  · 夹爪手指就在 TCP 上 ⇒ **模块的位置 = 合爪时的 TCP** = (653.3, 210.7, 220.2)。
  · 所以"送回去" = 把 TCP 升回这个点(这也是模块原本的高度 z≈220); 之前那次退到 z=109.5
    等于把模块**往下拖了 110mm 出槽**, 这就是老倪说"你还是没回去"的原因。
顺序(老倪口径): 先送回 → 张爪(确认真张开) → 最后抬升离开。
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import grasp_opt as G                                            # noqa: E402
from place_back import GRASP_ABC, GRASP_TCP, cur, step_move       # noqa: E402
from place_back_finish import gripper_pos                         # noqa: E402

LEAVE = np.array([GRASP_TCP[0], GRASP_TCP[1], GRASP_TCP[2] + 80.0])


def main():
    speed = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
    xyz, abc = cur()
    print("起点 TCP %s ABC %s · 夹爪 %s" % (np.round(xyz, 1), np.round(abc, 1), gripper_pos()))
    print("送回点 TCP %s (合爪时的 TCP = 模块原位)" % GRASP_TCP)

    # ① 送回(升回抓取点)
    if not step_move(GRASP_TCP, GRASP_ABC, speed, 35.0, 4.0, 2.0, "送回槽位"):
        print("没送到位 ⇒ 不张爪")
        return 2
    time.sleep(2.0)
    print("  到位后 TCP %s ABC %s" % (np.round(cur()[0], 1), np.round(cur()[1], 1)))

    # ② 张爪
    print("张爪: {'skill':'L2.grip_open'}")
    r = G.send({"skill": "L2.grip_open", "speed": 20.0}, wait=60)
    print("  回执:", json.dumps(r, ensure_ascii=False)[:220])
    time.sleep(3.0)
    gp = gripper_pos()
    print("  夹爪真值:", gp, "(合住 174 / 张开 >700)")
    if gp is None or gp < 500:
        print("⚠ 没真张开 ⇒ 不抬升, 请人看")
        return 3

    # ③ 松开后抬升离开(往上, 不再往下拖)
    if not step_move(LEAVE, GRASP_ABC, speed, 35.0, 4.0, 2.0, "抬升离开"):
        print("抬升没到位 ⇒ 人来看")
        return 4
    print("完成: 模块留在原位 · 夹爪 %s · 臂 %s" % (gripper_pos(), np.round(cur()[0], 1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
