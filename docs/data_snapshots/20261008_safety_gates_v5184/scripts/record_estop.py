#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""① 事故台账插行 ②碰撞点入库(先看代码是重写还是追加, 重写则另存 append-only 台账) ③回读核验"""
import json
import os
import re
import shutil
import time

REPO = "/home/ubuntu/zmax"
IDX = os.path.join(REPO, "docs/INCIDENT-INDEX.md")
LEDGER = os.path.expanduser("~/zmax/zmax_data/collision_points.json")
ESTOP = os.path.expanduser("~/zmax/zmax_data/estop_events.jsonl")
DOC = "INCIDENT-20261008-gsmap-space7-movej-rise-estop.md"

REC = {
    "ts": "2026-10-08 10:23:00",
    "code": 0,
    "joint": None,
    "torque": None,
    "limit": None,
    "content": ("人为急停(防过高, near-miss · 非撞击): 建图第2轮去 space7, MoveL 被 50102 奇异点拒 ⇒ "
                "MoveJ 自愈接管(关节插值)⇒ 臂途中意外升高/摆动, 老倪现场按急停. 报警流水无 30400/13036 碰撞力矩告警"),
    "kind": "operator_estop_near_miss",
    "pose": {"tcp": [0.5907, 0.2421, 0.3176], "quat": [0.7656, 0.077, 0.616, 0.1685]},
    "pose_note": "急停后静止位姿(on/idle/automatic, 4s 0 位移)",
    "target": {"skill": "L2.goto_space7", "pos": [0.5899, 0.2498, 0.3241]},
    "residual_mm": [0.86, -7.66, -6.51],
    "evidence": "l2_daemon_stdout.log 10:22:09 / 10:23:34 / 10:24:09 · gs_map/status.json · gs_map/run.log",
    "doc": "docs/" + DOC,
}

# ① 台账插行(插在 "## 待补充" 之前 = 表体末)
row = ("| 2026-10-08(2) | [建图第2轮去 space7：MoveL 被拒→**MoveJ 自愈关节摆升**，老倪急停](%s) | "
       "MoveL 走直线被 50102 拒后，**自愈改走 MoveJ（关节插值）⇒ 末端路径不再受目标 Δz=+86mm 约束**，"
       "臂途中意外升高/摆动（代理: `MoveJ · rc=6 · 残差 [0.86,-7.66,-6.51]mm`，执行器 120s 超时中止）。"
       "**无碰撞力矩告警（30400/13036 都没有）⇒ 是人为急停制止，不是撞上**；臂停 (0.5907,0.2421,0.3176) | "
       "①**MoveJ 自愈默认关闸**：只在\"目标 z ≤ 当前 z+30mm 且姿态差 ≤5°\"（下降/纯平移）允许，且带\"关节插值中途 z 上限\"闸；"
       "**升高类一律不许自愈**，被拒就停+问人 ②建图/回点等自主跑点**一律带自愈关** ③急停后回安全区只用**纯 -Z 分步下降**"
       "（≤20mm/步、慢速、关自愈、每步核真值）④待补 space7 及该 XY 的实测净空 |\n") % DOC
s = open(IDX, encoding="utf-8").read()
if "gsmap-space7-movej-rise-estop" in s:
    print("  ① 台账已有此行, 跳过")
else:
    assert "## 待补充" in s, "台账结构不符合预期, 停手"
    open(IDX, "w", encoding="utf-8").write(s.replace("## 待补充", row + "\n## 待补充", 1))
    print("  ① 台账已插行 ✓")

# ② 碰撞点入库: 先看代码怎么写的
src = open(os.path.join(REPO, "tools/cam_live_stream.py"), encoding="utf-8").read()
i = src.find("COLLISION_LEDGER")
seg = src[i:i + 1400]
mode = "重写" if re.search(r"json\.dump\(\s*\w+\s*,\s*\w*open\(\s*COLLISION_LEDGER", seg) or "'w'" in seg.split("json.dump")[0][-200:] else "未知/追加"
print("  ② 该文件的写入方式线索: %s" % mode)
print("     %s" % " · ".join(l.strip()[:88] for l in seg.splitlines()[1:9] if l.strip()))

led = json.load(open(LEDGER, encoding="utf-8"))
if any((it or {}).get("kind") == "operator_estop_near_miss" and "10:23" in str((it or {}).get("ts")) for it in led):
    print("  ② 碰撞库已有本次条目, 跳过")
else:
    shutil.copy2(LEDGER, LEDGER + ".bak_" + time.strftime("%Y%m%d_%H%M%S"))
    led.append(REC)
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  ② 碰撞库已追加本次条目 (共 %d 条) ✓" % len(led))

# ③ append-only 独立台账(防被程序重写覆盖)
with open(ESTOP, "a", encoding="utf-8") as f:
    f.write(json.dumps(REC, ensure_ascii=False) + "\n")
print("  ③ append-only 台账: %s (共 %d 行)" % (ESTOP, sum(1 for _ in open(ESTOP, encoding="utf-8"))))

# ④ 回读核验
led2 = json.load(open(LEDGER, encoding="utf-8"))
hit = [it for it in led2 if (it or {}).get("kind") == "operator_estop_near_miss"]
print("  ④ 回读碰撞库: 共 %d 条, 本次条目 %d 条" % (len(led2), len(hit)))
s2 = open(IDX, encoding="utf-8").read()
print("  ④ 回读台账: 行在文件里 = %s" % ("✅" if "gsmap-space7-movej-rise-estop" in s2 else "❌"))
