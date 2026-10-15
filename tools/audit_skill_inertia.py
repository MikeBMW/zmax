#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_skill_inertia.py — ⚖ 整体盘查: 每个 L2 原子技能是否带物理惯性/质量变化率约束。

老倪 2026-10-15: 「每个 L2 层的原子技能, 都有肌肉记忆 … 每个技能, 都清楚的知道自己动作的惯性, 例如 接近动作的
速度与加速度的关系, 位置与速度的导数关系等; 所有 L2 层的原子动作, 都要有物理质量变化率的约束, 你来整体盘查
所有原子技能, 是否用这样的惯性约束 …」

输出 (可复制进报告):
  ① 技能级盘查表: m / F_max / v_cap / a_max=F/m / jerk_max / dm·dt⁻¹ + 四条约束 + 物理量真源
  ② 画布口径一致性: 画布 ⚖物理约束闸 节点 params.skills 与代码真源逐字段一致 (防"界面上写一套、代码跑另一套")
  ③ 现场闸门统计: skill_error.json 的削因计数 + 每技能最近请求/可行/偏差/大偏差
  ④ 判定: 9 个技能全部带 4 条约束 ⇒ 通过; 缺任何一条 ⇒ 红。
"""
from __future__ import annotations

import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
from lerobot.policies.left_right.state_space.physics_constraints import InertiaLimiter, PHYS   # noqa: E402

lim = InertiaLimiter()
rows = lim.audit()
print("=" * 118)
print("⚖ 原子技能物理惯性 / 质量变化率 盘查表 (真源 src/lerobot/policies/left_right/state_space/physics_constraints.py)")
print("=" * 118)
print("%-4s %-8s %-8s %-9s %-11s %-12s %-11s %s"
      % ("技能", "m/kg", "Fmax/N", "v_cap/(m/s)", "a_max/(m/s²)", "jerk/(m/s³)", "dm/dt/(kg/s)", "约束"))
ok = True
for r in rows:
    _four = r["约束"].count("①") == 1 and r["约束"].count("②") == 1 and r["约束"].count("③") == 1 and r["约束"].count("④") == 1
    ok = ok and _four and r["m_kg"] > 0 and r["F_max_N"] > 0 and r["a_max_mps2"] > 0 and r["jerk_max_mps3"] > 0
    print("%-4s %-8.2f %-8.1f %-9.3f %-11.2f %-12.1f %-11.2f %s%s"
          % (r["技能"], r["m_kg"], r["F_max_N"], r["v_cap_mps"], r["a_max_mps2"], r["jerk_max_mps3"],
             r["dmdt_max_kg_s"], r["约束"], "" if _four else "  ❌ 缺约束"))
print("\n物理量真源 (逐个技能可复核):")
for r in rows:
    print("   %-3s %s" % (r["技能"], r["真源"]))

# ② 画布口径一致
print("\n" + "-" * 118)
print("② 画布口径一致性 (⚖物理约束闸 节点 params.skills vs 代码真源)")
try:
    d = json.load(open(os.path.realpath(os.path.join(REPO, "flows", "state_space_obs.json")), encoding="utf-8"))
    node = next((n for n in d["nodes"] if n["id"] == "ssphys"), None)
    assert node, "画布上没有 ssphys 节点 (跑 tools/canvas_wire_skill_physics.py --apply)"
    sk = node["params"]["skills"]
    bad = []
    for r in rows:
        c = sk.get(r["技能"])
        if not c:
            bad.append("%s 缺" % r["技能"])
            continue
        for k, v in (("m_kg", r["m_kg"]), ("F_max_N", r["F_max_N"]), ("v_cap_mps", r["v_cap_mps"]),
                     ("a_max_mps2", r["a_max_mps2"]), ("jerk_max_mps3", r["jerk_max_mps3"]),
                     ("dmdt_max_kg_s", r["dmdt_max_kg_s"])):
            if abs(float(c.get(k, -1)) - float(v)) > 1e-6:
                bad.append("%s.%s 画布 %s ≠ 代码 %s" % (r["技能"], k, c.get(k), v))
    print("   节点 %s · 技能 %d 个 · 差异 %d %s" % (node["name"], len(sk), len(bad), bad[:3] if bad else ""))
    ok = ok and not bad
except Exception as e:                                                                # noqa: BLE001
    print("   ❌ 读画布失败: %s" % e)
    ok = False

# ③ 现场闸门统计
print("\n" + "-" * 118)
print("③ 现场闸门统计 (真源 zmax_data/ss_live/skill_error.json, 由 zmax-ss-skill-dispatch 每拍写)")
try:
    p = os.path.join(REPO, "zmax_data", "ss_live", "skill_error.json")
    e = json.load(open(p, encoding="utf-8"))
    age = time.time() - float(e.get("ts") or 0)
    st = e.get("stats") or {}
    print("   帧龄 %.2fs · 累计过闸 %d 次 · 削因计数 %s · 大偏差阈值 %.3f m/s"
          % (age, st.get("n") or 0, st.get("n_cut") or {}, st.get("big_err") or 0))
    print("   最近每技能: 请求 → 可行 · 偏差 · 削因 · 大偏差")
    for k in e.get("req") or {}:
        q = e["req"][k]
        u = (e.get("u") or {}).get(k) or []
        print("     %-3s 请求[%s] → 可行[%s] · 偏差 %.4f m/s · %s · big=%d"
              % (k, ",".join("%.3f" % x for x in q[:3]), ",".join("%.3f" % x for x in u[:3]),
                 float((e.get("err_norm") or {}).get(k) or 0), (e.get("why") or {}).get(k),
                 int((e.get("big") or {}).get(k) or 0)))
    ok = ok and age < 5.0
except Exception as ex:                                                               # noqa: BLE001
    print("   ❌ 读现场闸门统计失败: %s" % ex)
    ok = False

print("\n" + "=" * 118)
print("盘查结论: %s" % ("✅ 9 个 L2 原子技能**全部**带 ①速度 ②加速度 ③加加速度 ④动量/质量变化率 四条物理约束, "
                    "且画布口径与代码真源一致" if ok else "❌ 有技能缺约束或口径不一致"))
print("=" * 118)
sys.exit(0 if ok else 1)
