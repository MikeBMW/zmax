#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_skill_flip.py — SK13Flip(自动翻转) 自检: 注册、判据、包络、姿态数学。

不碰机器人、不下发；全是可复现的判定。
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from lerobot.policies.left_right.state_space.skills import atomic_skills as A   # noqa: E402
from lerobot.policies.left_right.state_space import physics_constraints as PC  # noqa: E402

ok = 0
bad = []


def chk(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print("✓ " + name + (("  [" + str(detail) + "]") if detail else ""))
    else:
        bad.append(name)
        print("× " + name + (("  [" + str(detail) + "]") if detail else ""))


F = A.SK13Flip

# 1 注册
chk("SK13 在按需技能表", F in A.SKILLS_ONDEMAND)
chk("SK13 在 SKILL_BY_CODE", A.SKILL_BY_CODE.get("SK13") is F)
chk("stage「翻转」可查到", A.SKILL_BY_STAGE.get("翻转") is F)
chk("没污染 8 段主链", [c.code for c in A.SKILLS] == ["SK01", "SK02", "SK03", "SK04", "SK05", "SK06", "SK07", "SK08"],
    [c.code for c in A.SKILLS])
chk("没污染 13 段全链", "SK13" not in [c.code for c in A.SKILLS_FULL], len(A.SKILLS_FULL))

# 2 物理真源取到「翻转」
lim = PC.limits_for("翻转")
chk("真源段名可解析 (非 unknown)", lim.get("unknown_stage") == 0, lim.get("calib_src_kind"))
chk("v_cap 取真源 0.05", abs(float(lim["v"]) - 0.05) < 1e-9, lim["v"])
chk("a_max = F/m = 3.7037", abs(float(lim["a_max"]) - 5.0 / 1.35) < 1e-4, round(float(lim["a_max"]), 6))
chk("s_step = v·dt = 0.005", abs(float(lim["s_step"]) - 0.005) < 1e-9, lim["s_step"])

# 3 自动调用判据
c1, d1, w1 = F.needs_flip(0.0, 180.0)
c2, d2, w2 = F.needs_flip(0.0, 10.0)
c3, d3, w3 = F.needs_flip(0.0, 95.0)
chk("朝向相反 ⇒ 要翻", c1 is True and abs(abs(d1) - 180.0) < 1e-9, w1)
chk("朝向一致 ⇒ 不翻", c2 is False, w2)
chk("偏 95° ⇒ 不硬翻 (交 L3 重选)", c3 is False, w3)
c4, d4, _ = F.needs_flip(90.0, 275.0)
chk("yaw 环绕算对 (90→275 = 185°≈相反)", c4 is True, round(d4, 1))

# 4 auto_call 带计划
res = F.auto_call(0.0, 180.0, pos_mm=[648.79, 407.03, 108.58], quat_wxyz=(1.0, 0.0, 0.0, 0.0))
chk("auto_call 命中返回计划", res.get("call") is True and res.get("n_steps", 0) > 10, res.get("n_steps"))
res2 = F.auto_call(0.0, 5.0, pos_mm=[0, 0, 100])
chk("auto_call 未命中如实说不做", res2.get("call") is False and "直接放料" in res2.get("why", ""), res2.get("why"))

# 5 包络: 先抬净空、分段 ≤5°、累计正好 180°、末步回落
plan = F.plan_flip([648.79, 407.03, 108.58], (1.0, 0.0, 0.0, 0.0), clear_mm=30.0)
kinds = [s["kind"] for s in plan]
rot = [s for s in plan if s["kind"] == "rotate"]
chk("第一步是抬升", kinds[0] == "lift", kinds[:3])
chk("抬升量 = 30mm", abs(plan[0]["pos"][2] - (108.58 + 30.0)) < 1e-6, plan[0]["pos"])
chk("每拍角度 ≤5°", all(s["dr_max_deg"] <= 5.0 + 1e-9 for s in rot), max(s["dr_max_deg"] for s in rot))
chk("累计角度 = 180°", abs(rot[-1]["deg_done"] - 180.0) < 1e-9, rot[-1]["deg_done"])
chk("旋转拍数 = 36", len(rot) == 36, len(rot))
chk("旋转期间不降高度", all(abs(s["pos"][2] - (108.58 + 30.0)) < 1e-6 for s in rot))
chk("末步回落原位", plan[-1]["kind"] == "descend" and abs(plan[-1]["pos"][2] - 108.58) < 1e-6, plan[-1]["pos"])

# 6 姿态数学: 绕 Z 转 180° 后 X 轴应反向
q180 = F.rotate_quat((1.0, 0.0, 0.0, 0.0), 180.0)
ang = F.angle_between((1.0, 0, 0, 0), q180)
chk("绕 Z 180° 的旋转角 = 180°", abs(ang - 180.0) < 1e-6, round(ang, 4))
chk("末姿态与计划末步一致", abs(F.angle_between(tuple(plan[-1]["quat"]), q180)) < 1e-3)

# 7 平移限幅仍在 (base clamp)
r = F().clamp([1.0, 0.0, 0.0, 1.0])
chk("平移被削到 ≤0.10 m/s", abs(float(r["u"][0])) <= 0.10 + 1e-9, "why=%s u=%s" % (r.get("why"), r["u"]))
chk("夹爪原样下发", float(r["u"][3]) == 1.0)

print("\n%d/%d PASS" % (ok, ok + len(bad)))
sys.exit(0 if not bad else 1)
