#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_wire_skill_physics.py — 画布: 原子技能 → ⚖物理约束闸 → 🧪状态校正器(小偏差) / 📡融合定位(大偏差) → 🧮流形引擎。

老倪 2026-10-15: 「所有 L2 层的原子动作, 都要有物理质量变化率的约束 … 确保进入原子技能的 action 能够符合物理定律 …
如果不能执行, 可以发出偏差 error, 这个 error 可以反馈给状态校正节点, 修正误差; 如果误差太大, 则可以通过融合定位节点,
将大偏差先直接反馈给流形引擎节点, 从而改变顶层结构, 修复补偿偏差。」

连线 (节点位置不动, 只加端口/连线; 幂等可重跑):
  ① sssk1..8 各加出端口 out2「⚖ 物理不可行偏差 error」 → **新节点** ssphys「⚖ 物理约束 · 惯性/质量率闸」in1..in8
     (新节点的真身 = src/.../physics_constraints.py::InertiaLimiter.limit — 每个技能进执行前先过物理)
  ② ssphys:out1「可行动作」 → sslimit:in2「安全执行边界」(物理可行后仍要过安全限幅)
  ③ ssphys:out2「偏差 error (小)」 → ssinnov:in4「状态校正器 · 修正误差」
  ④ ssphys:out3「大偏差 (‖e‖>50mm/s)」 → sssensor:in6「融合定位建图 · 定位核对」
  ⑤ 融合定位建图 → 流形引擎 这条边**本来就有** (sssensor:out2 → ss_mani_eng:in1, 43D 状态);
     GUI 对同 (源,靶) 只画一条 ⇒ 大偏差核对结果由这条既有边一并交上去, 标签已写实 (不再另加重复边)。

⚠️ 为什么不用 "ssinnov→sssensor" / "sssensor→ss_mani_eng" 的重复边: 台架 GUI 的 add_link 对**完全重复的 (源,靶)** 去重
   (simulink_module.add_link: 同 f/t 直接 return), 加了也不渲染 ⇒ 渲染项数与连线数对不上 (判据会红)。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
CANVAS = os.path.realpath(os.path.join(REPO, "flows", "state_space_obs.json"))
d = json.load(open(CANVAS, encoding="utf-8"))
N = {n["id"]: n for n in d["nodes"]}
SKILLS = ["sssk%d" % i for i in range(1, 9)]

# ── 0) 清掉上一版留下的重复边/多余端口 (GUI 不渲染它们, 留着只会让"连线数 vs 渲染数"对不上) ──
before = len(d["links"])
d["links"] = [l for l in d["links"] if not (
    (l["f"] == "sssensor" and l["t"] == "ss_mani_eng" and l.get("f_port") == "out3") or
    (l["f"] == "ssinnov" and l["t"] == "sssensor" and l.get("f_port") == "out3") or
    (str(l["f"]).startswith("sssk") and l["t"] == "ssinnov" and l.get("f_port") == "out2"))]
print("清掉重复/不渲染的边 %d 条" % (before - len(d["links"])))
for sid in ("sssensor", "ssinnov"):
    _o = [x for x in (N[sid].get("outputs") or []) if x != "out3"]
    N[sid]["outputs"] = _o
N["ss_mani_eng"]["inputs"] = [x for x in (N["ss_mani_eng"].get("inputs") or []) if x != "in7"]
N["ssinnov"]["inputs"] = [x for x in (N["ssinnov"].get("inputs") or []) if x != "in4"]

# ── 1) 技能出端口 out2 (物理偏差) ──
for sid in SKILLS:
    n = N[sid]
    n.setdefault("outputs", [])
    if "out2" not in n["outputs"]:
        n["outputs"].append("out2")

# ── 2) 新节点: ⚖ 物理约束闸 (真身 physics_constraints.InertiaLimiter) ──
from lerobot.policies.left_right.state_space.physics_constraints import InertiaLimiter  # noqa: E402
_audit = InertiaLimiter().audit()
if "ssphys" not in N:
    d["nodes"].append({
        "id": "ssphys", "type": "model", "icon": "⚖", "color": "#f0a030",
        "name": "⚖ 物理约束 · 惯性/质量率闸 (SK01-08)",
        "x": 8310, "y": 5620, "w": 300, "h": 130, "actions": [],
        "inputs": ["in1", "in2", "in3", "in4", "in5", "in6", "in7", "in8"],
        "outputs": ["out1", "out2", "out3"],
        "params": {"state_space": True, "physics_gate": True,
                   "desc": "[基础·分段小模型] 原子技能物理闸: 进技能的 action 先过 ①速度 ②加速度 ③加加速度 "
                           "④动量/质量变化率 ⑤位移 五条约束 (每技能自带 m/F/v/a/s/jerk/dm·dt⁻¹, "
                           "数值+物理上下限唯一依据 config/calib/zmax_skill_physics.json) ⇒ 削出偏差 error; "
                           "小偏差 → 状态校正器, 大偏差 → 融合定位 → 流形引擎顶层补偿",
                   "source": "src/lerobot/policies/left_right/state_space/physics_constraints.py"
                             "::InertiaLimiter.limit",
                   "skills": {r["技能"]: {"m_kg": r["m_kg"], "F_max_N": r["F_max_N"], "v_cap_mps": r["v_cap_mps"],
                                          "a_max_mps2": r["a_max_mps2"], "jerk_max_mps3": r["jerk_max_mps3"],
                                          "dmdt_max_kg_s": r["dmdt_max_kg_s"],
                                          "s_step_m": r.get("s_step_m"), "s_max_m": r.get("s_max_m"),
                                          "标定唯一依据": r.get("标定唯一依据"), "唯一依据": r["唯一依据"]}
                              for r in _audit},
                   "big_err_mps": 0.05}})
    N = {n["id"]: n for n in d["nodes"]}
else:
    N["ssphys"]["params"]["desc"] = ("[基础·分段小模型] 原子技能物理闸: 进技能的 action 先过 ①速度 ②加速度 ③加加速度 "
                                     "④动量/质量变化率 ⑤位移 五条约束 (每技能自带 m/F/v/a/s/jerk/dm·dt⁻¹, "
                                     "数值+物理上下限唯一依据 config/calib/zmax_skill_physics.json) ⇒ 削出偏差 error; "
                                     "小偏差 → 状态校正器, 大偏差 → 融合定位 → 流形引擎顶层补偿")
    N["ssphys"]["params"]["skills"] = {r["技能"]: {"m_kg": r["m_kg"], "F_max_N": r["F_max_N"],
                                                   "v_cap_mps": r["v_cap_mps"], "a_max_mps2": r["a_max_mps2"],
                                                   "jerk_max_mps3": r["jerk_max_mps3"],
                                                   "dmdt_max_kg_s": r["dmdt_max_kg_s"],
                                                   "s_step_m": r.get("s_step_m"), "s_max_m": r.get("s_max_m"),
                                                   "标定唯一依据": r.get("标定唯一依据"), "唯一依据": r["唯一依据"]}
                                       for r in _audit}

# ── 3) 连线 ──
for sid in ("ssphys", "sslimit"):
    pass
n = N["sslimit"]
n.setdefault("inputs", [])
if "in2" not in n["inputs"]:
    n["inputs"].append("in2")
have = {(l["f"], l["t"], l.get("f_port"), l.get("t_port")) for l in d["links"]}
add = []
for i, sid in enumerate(SKILLS):
    key = (sid, "ssphys", "out2", "in%d" % (i + 1))
    if key not in have:
        add.append({"id": "lk_phys_g%d" % (i + 1), "f": sid, "t": "ssphys",
                    "f_port": "out2", "t_port": "in%d" % (i + 1),
                    "label": "⚖ 技能动作 → 物理约束 (惯性/质量变化率)"})
        have.add(key)
for spec in ({"id": "lk_phys_ok", "f": "ssphys", "t": "sslimit", "f_port": "out1", "t_port": "in2",
              "label": "⚖ 物理可行动作 → 安全执行边界 (再限幅)"},
             {"id": "lk_phys_small", "f": "ssphys", "t": "ssinnov", "f_port": "out2", "t_port": "in4",
              "label": "⚖ 偏差 error (小) → 🧪 状态校正器 · 修正误差"},
             {"id": "lk_phys_big", "f": "ssphys", "t": "sssensor", "f_port": "out3", "t_port": "in6",
              "label": "⚖ 大偏差 (‖e‖>50mm/s) → 📡 融合定位建图 · 定位核对"}):
    key = (spec["f"], spec["t"], spec["f_port"], spec["t_port"])
    if key not in have:
        add.append(spec)
        have.add(key)

# ── 4) 既有 融合定位→流形引擎 那条边的标签写实 (大偏差核对结果由它一并上交) ──
for l in d["links"]:
    if l["f"] == "sssensor" and l["t"] == "ss_mani_eng" and l.get("f_port") == "out2":
        l["label"] = ("43D 状态 (融合定位建图) → x∈R^N · 含核对后大偏差 ⇒ 流形引擎顶层结构补偿 "
                      "(改目标点/结构; 见 ss_engine_loop._top_compensate)")

print("新增连线 %d 条:" % len(add))
for a in add:
    print("   %-10s %-5s → %-10s %-5s | %s" % (a["f"], a["f_port"], a["t"], a["t_port"], a["label"]))
print("新节点: ssphys ⚖ 物理约束闸 (%d 个技能的物理上限已写进 params.skills)" % len(_audit))
if "--apply" not in sys.argv:
    print("(干跑; 加 --apply 落盘)")
    sys.exit(0)
d["links"].extend(add)
ts = time.strftime("%Y%m%d_%H%M%S")
bak = os.path.join(REPO, "flows", "_archive", "state_space_obs_before_skill_phys_%s.json" % ts)
shutil.copy2(CANVAS, bak)
from lerobot.engineering import flows as F                                    # noqa: E402
F.save_canvas(d)
d2 = json.load(open(CANVAS, encoding="utf-8"))
dup = {}
for l in d2["links"]:
    dup[(l["f"], l["t"])] = dup.get((l["f"], l["t"]), 0) + 1
_nd = sum(1 for k, v in dup.items() if v > 1)
print("已写盘 (备份 %s)\n回读: 节点 %d · 连线 %d · 重复(源,靶)对 %d (GUI 只画一条 ⇒ 渲染数 = %d)"
      % (bak, len(d2["nodes"]), len(d2["links"]), _nd, len(d2["links"]) - _nd))
