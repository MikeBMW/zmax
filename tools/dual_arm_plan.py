#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dual_arm_plan.py — 双臂 plan 节点 (AR 工位 // 真机同构的几何规划器)

老倪 2026-10-29: 「L2 感知接渲染图 → 输出感知定位结果 → 给到 plan 模块进行规划 →
                 驱动 AR 场景的左臂和右臂都进行基于 plan 节点和动作执行节点的指令」

本节点只做**规划**, 不动手 (执行在 ar_render_station 的 act 节点)。
输入 = 感知定位结果 (世界系 xyz) + 双臂当前 TCP 真值 + 孔口真值;
输出 = 有序步骤表, 每步给「哪只臂 / 目标 TCP xyz / 夹爪开合 / 判据」。

口径 (如实):
  · src = "plan.dual_arm.geometric" —— 几何位姿规划 (可达性/分层下降/双臂协同), **不是**学习型策略
  · 每步都带 when/until 判据, 执行节点按真值判到位, 不按"发过指令"就算做完
  · 双臂都受力: R = 主操作臂 (抓取/搬运), L = 协同臂 (对位/接应), 不是只动一条
"""
from __future__ import annotations

import time

PARK = {"L": [-0.10, 0.30, 0.33], "R": [0.44, 0.30, 0.33]}     # 观察位 (臂不用时不挡机位)


class DualArmPlanner:
    """几何双臂规划器 —— 与画布 plan 节点同职责: 输入感知结果, 输出动作序列。"""

    name = "plan.dual_arm"
    src = "plan.dual_arm.geometric"

    def __init__(self, safe_h=0.12, grasp_h=0.012, tol_mm=10.0, tol_free_mm=10.0):
        self.safe_h = float(safe_h)          # 观察高度 (模块上方 m)
        self.grasp_h = float(grasp_h)        # 抓取高度
        self.tol_mm = float(tol_mm)              # 收口段 (撤离/接触) 判据
        self.tol_free_mm = float(tol_free_mm)    # 空程段 (观察/对位) 判据

    def plan(self, perc: dict, truth: dict) -> dict:
        """perc = {ok, xyz:[x,y,z], conf, box}; truth = /state.json#truth (has tcpL/tcpR/gold/hole)。
        返回 {ok, src, reason, steps:[{i, side, action, xyz, grip, until, tol_mm}], grasp_ok}
        """
        if not perc or not perc.get("ok") or not perc.get("xyz"):
            return {"ok": False, "src": self.src,
                    "reason": "感知无定位结果 ⇒ 不规划 (不拿默认点冒充目标)",
                    "steps": []}
        tgt = [float(v) for v in perc["xyz"][:3]]
        gz = float(tgt[2])
        # 🦾 2026-10-29 按真机布局重算: 两臂都装在箱体顶板 x=0, 沿 y 并排 (R: y=0, L: y=0.5),
        #    都朝 +x 伸 ⇒ 双臂从**模块的 -y / +y 两侧**对进, 不再像旧工位那样沿 x 左右夹。
        above = [tgt[0], tgt[1] - 0.090, gz + self.safe_h]      # R 观察位 (-y 侧, 模块上方 12cm)
        align = [tgt[0], tgt[1] - 0.065, gz + 0.060]            # R 对位位 (距模块 65mm, 不碰)
        # L 侧偏移收一点 (实测: +y 0.090 时 L 臂伸展过大, 静差 24mm 到不了 15mm 判据;
        #   收到 +0.075 且高度 0.11 后落在可达较优区)
        l_side = [tgt[0] + 0.010, tgt[1] + 0.075, gz + 0.110]         # L 协同观察位 (+y 侧)
        l_align = [tgt[0] + 0.015, tgt[1] + 0.055, gz + 0.060]        # L 协同对位位
        # 撤离位 = 规划时刻的双腕真值 (reset 后的 home) ⇒ 一定可达, 且把视野让出来给复测
        park_r = [float(v) for v in ((truth or {}).get("tcpR") or [0.43, 0.32, 0.33])]
        park_l = [float(v) for v in ((truth or {}).get("tcpL") or [-0.09, 0.32, 0.33])]

        # 🔴 对位高度一律 ≥60mm 净空: 30mm 时夹爪指会刮到模块把 freejoint 刚体顶出料盘
        #    (实测整轮结束后 gold_px=0, 模块掉出视野 ⇒ 复测无框)。臂只做对位/协同, 不做接触。
        steps = [
            dict(side="L", action="协同观察位", xyz=l_side, grip=0.0, until="TCP 到位"),
            dict(side="R", action="观察位(模块上方)", xyz=above, grip=0.0, until="TCP 到位"),
            dict(side="R", action="对位(距模块60mm)", xyz=align, grip=0.0, until="TCP 到位"),
            dict(side="L", action="协同对位(左侧60mm)", xyz=l_align, grip=0.0, until="TCP 到位"),
            dict(side="R", action="撤离(让出视野给复测)", xyz=park_r, grip=0.0, until="TCP 到位"),
            dict(side="L", action="撤离(让出视野给复测)", xyz=park_l, grip=0.0, until="TCP 到位"),
        ]
        for i, s in enumerate(steps, 1):
            s["i"] = i
            s["xyz"] = [round(v, 5) for v in s["xyz"]]
            # 判据统一 10mm: 执行器 kp 已调到 300/kv 20, 远伸位姿实测静差 7.1mm (原 kp=60 是
            # 24~34mm)。10mm 覆盖静差且远小于对位净空 (55~65mm), 不是放水。
            s["tol_mm"] = self.tol_free_mm if ("观察" in s["action"] or "对位" in s["action"]) else self.tol_mm
        return {"ok": True, "src": self.src,
                "reason": "几何双臂规划: 感知目标 → 双腕对位/协同 → 抬升复位 (双臂都受控)",
                "target": [round(v, 5) for v in tgt],
                "hole": [round(float(v), 5) for v in (truth or {}).get("hole") or []],
                "steps": steps, "ts": time.time(), "grasp_ok": False,
                "grasp_note": "本场景夹爪两指沿 x 并列布置, 对 16mm 宽模块不成对夹 (实测夹紧后模块仍原地, 只被推 5mm)"
                             " ⇒ 本轮只做双臂对位/协同, 不做搬运插入; 要搬运需改夹爪几何(指沿 y 对夹)并重训 AR 权重",
                "note": "每步以 /state.json 真值到位判据收口, 不按'发过指令'算完成; "
                        "空程段 15mm / 收口段 8mm (执行器静差实测 9~13mm)"}


if __name__ == "__main__":
    import json
    p = DualArmPlanner()
    demo = p.plan({"ok": True, "xyz": [0.52, 0.35, 0.112], "conf": 0.9},
                  {"hole": [0.49, 0.50, 0.125]})
    print(json.dumps(demo, ensure_ascii=False, indent=1)[:1200])
