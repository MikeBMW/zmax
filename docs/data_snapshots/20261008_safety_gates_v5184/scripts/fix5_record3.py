#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""① 余量 40→5(横移高度 = max(当前,目标)+5mm) ②重注册 ③dry 复算验证
   ④碰撞点/急停入库(碰撞库 + INCIDENT-INDEX 插行 + append-only)  全程零运动"""
import ast
import json
import os
import re
import subprocess
import sys
import urllib.request

REPO = "/home/ubuntu/zmax"
F = os.path.join(REPO, "tools/register_space_skills.py")
IDX = os.path.join(REPO, "docs/INCIDENT-INDEX.md")
LEDGER = os.path.expanduser("~/zmax/zmax_data/collision_points.json")
ESTOP = os.path.expanduser("~/zmax/zmax_data/estop_events.jsonl")
DOC = "INCIDENT-20261008-goto3stage-lift40-estop.md"

# ── ① 余量 40 → 5 ──
s = open(F, encoding="utf-8").read()
m = re.search(r"LIFT_MARGIN_MM = 40\.0.*?\n.*?\n", s)
assert m, "找不到 LIFT_MARGIN_MM 定义"
s = s[:m.start()] + (
    'LIFT_MARGIN_MM = 5.0    # 2026-10-08 第三次事故更正: 40mm 余量在「目标只高一点点」时就是无谓上升\n'
    '                        # (实测 +106.5mm 里 40mm 多余) ⇒ 压到 5mm。横移高度 = max(当前z, 目标点z)+5mm\n') + s[m.end():]
s = s.replace('"stage": 1, "rel": True, "dz_mm": 0.0,', '"stage": 1, "rel": True, "dz_mm": 5.0,', 1)
ast.parse(s)
open(F, "w", encoding="utf-8").write(s)
print("  ① 余量 40→5mm + 阶段1 dz 0→5 (公式 max(cur+5, point+5)) ✓")

# ── ② 重注册 ──
r = subprocess.run(["python3", os.path.join(REPO, "tools/register_space_skills.py")],
                   cwd=REPO, capture_output=True, text=True)
print("  ② " + " / ".join(r.stdout.strip().splitlines()[-2:]))

# ── ③ dry 复算 ──
sys.path.insert(0, os.path.join(REPO, "tools/rokae"))
import l2_transport_sdk as T  # noqa: E402


def post(path, body, t=120):
    req = urllib.request.Request("http://127.0.0.1:8793" + path, method="POST",
                                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


p = T.read_pose()
print("  ③ 臂现在 %s (天花板 %.4f)" % ([round(v, 4) for v in p["pos"]], T.taught_z_ceiling()))
for sk in ("L2.goto_space7", "L2.goto_space4"):
    resp = post("/ctl/move", {"action": "move", "dry": True, "arm": 0, "skill": sk, "by": "静静:余量5mm复核"})
    lines = resp.get("lines") or []
    m2 = re.search(r"受理: DRY-RUN\(未下发\) (\d+) 阶段: (.*)", "\n".join(lines))
    print("     %-16s %s" % (sk, (m2.group(2)[:160] if m2 else "❌ " + str(lines[-1])[:150])))
    for l in lines:
        if "自适应抬升" in str(l):
            print("        %s" % str(l)[:150])

# ── ④ 记录 ──
REC = {
    "ts": "2026-10-08 10:43:44",
    "code": 0, "joint": None, "torque": None, "limit": None,
    "content": ("人为急停(near-miss · 非撞击): 点「去空间7」后执行器阶段1 竖直抬升 +106.5mm"
                "(目标点只高 66mm, 其中 40mm 是我把横移余量写成 +40mm 造成的无谓上升) ⇒ "
                "老倪现场按急停并手动降回安全区. 无 30400/13036 碰撞力矩告警"),
    "kind": "operator_estop_near_miss",
    "pose": {"tcp": [0.5907, 0.1802, 0.1854], "quat": None},
    "pose_note": "急停+老倪手动降回后的静止位姿(on/idle/automatic, 6s 0.0mm)",
    "target": {"skill": "L2.goto_space7", "stage": "1/3 竖直抬到该点z+40mm", "pos": [0.5907, 0.2421, 0.3641]},
    "dispatch_id": "l2_27424390",
    "residual_mm": [-0.01, -61.98, -178.65],
    "evidence": "l2_daemon_stdout.log 10:43:44 / 10:45:14 · 真值连采 · 老倪口述",
    "doc": "docs/" + DOC,
}
row = ("| 2026-10-08(3) | [回点三段配方阶段1「竖直抬升 106.5mm」，老倪急停](%s) | "
       "三段配方的**横移高度余量写成 +40mm**，而 space7 只比当时高 66mm ⇒ 阶段1 变成 +106.5mm"
       "（其中 40mm 纯多余），现场看到「臂原地往上窜」按下急停（代理回执 `rc=-2 · 残差 [-0.01,-61.98,-178.65]mm`）。"
       "**无碰撞力矩告警 ⇒ 人为急停(near-miss)**；臂终位 (0.5907,0.1802,0.1854) | "
       "①**余量压到最小**：横移高度 = `max(当前z, 目标点z)+5mm`（LIFT_MARGIN 40→5）"
       "②老倪今天对「可见的自动上升」已敏感三次 ⇒ **自动流程里任何明显抬升都必须事先讲清「为什么抬、抬多少」** "
       "③抬升必要性由「目标点是否更高」决定，不是固定加码 |\n") % DOC

s2 = open(IDX, encoding="utf-8").read()
if "goto3stage-lift40-estop" not in s2:
    assert "## 待补充" in s2, "台账结构不符"
    open(IDX, "w", encoding="utf-8").write(s2.replace("## 待补充", row + "\n## 待补充", 1))
    print("  ④ 台账已插行 ✓")
led = json.load(open(LEDGER, encoding="utf-8"))
if not any("106.5mm" in str((it or {}).get("content")) for it in led):
    led.append(REC)
    json.dump(led, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  ④ 碰撞库已追加(共 %d 条) ✓" % len(led))
with open(ESTOP, "a", encoding="utf-8") as f:
    f.write(json.dumps(REC, ensure_ascii=False) + "\n")
print("  ④ append-only: 共 %d 行" % sum(1 for _ in open(ESTOP, encoding="utf-8")))
print("  ④ 回读: 台账含行=%s · 人为急停条目=%d 条"
      % ("✅" if "goto3stage-lift40-estop" in open(IDX, encoding="utf-8").read() else "❌",
         sum(1 for it in json.load(open(LEDGER, encoding="utf-8")) if (it or {}).get("kind") == "operator_estop_near_miss")))
print("  臂位姿(应没变) = %s" % [round(v, 4) for v in T.read_pose()["pos"]])
