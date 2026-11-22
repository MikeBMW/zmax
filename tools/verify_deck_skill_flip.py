#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_deck_skill_flip.py — 按真源重算《自动翻转技能 SK13》PPT 里的每个数, 再断言页面写的就是它。

真源: skills/atomic_skills.py:class SK13Flip + data/…/canvas/state_space_obs.json
判据: 每个数字现算 → 格式化 → 去 PPT 文本里找; 版面越界/文字重叠必须为 0。任一条不匹配 ⇒ exit 1。
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, "/home/ubuntu/zmax/src")
from pptx import Presentation                                                   # noqa: E402

from lerobot.policies.left_right.state_space.skills.atomic_skills import SK13Flip as F   # noqa: E402

DECK = "/home/ubuntu/zmax/zmax_data/reports/自动翻转技能_SK13_功能说明_v1.pptx"
CANVAS = "/home/ubuntu/zmax/data/database/zmax/sources/canvas/state_space_obs.json"

prs = Presentation(DECK)
parts = []
for s in prs.slides:
    for sh in s.shapes:
        if sh.has_text_frame:
            parts.append(sh.text_frame.text)
        if sh.has_table:
            for row in sh.table.rows:
                for c in row.cells:
                    parts.append(c.text)
ALL = "\n".join(parts).replace("\u2212", "-").replace("\uff0b", "+")
ALL_N = re.sub(r"\s+", "", ALL)

P = F.params
dr = float(F.DR_DEG_STEP)
flip = float(P["flip_deg"])
n_rot = int(round(flip / dr))
clear = float(P["clearance_h"]) * 1000.0
tol = float(P["yaw_tol_deg"])
plan = F.plan_flip([648.79, 407.03, 108.58], (1.0, 0.0, 0.0, 0.0), clear_mm=clear)
n_steps = len(plan)

cv = json.load(open(CANVAS, encoding="utf-8"))
links = [l for l in cv["links"] if l.get("f") == "sssk13" or l.get("t") == "sssk13"]
node = next(n for n in cv["nodes"] if n["id"] == "sssk13")

checks = []


def chk(name, cond, detail=""):
    checks.append((name, bool(cond), detail))


chk("翻转角 %.0f°" % flip, "%.0f°" % flip in ALL)
chk("每拍 ≤%.0f°" % dr, "%.0f°" % dr in ALL)
chk("旋转拍数 %d" % n_rot, str(n_rot) in ALL)
chk("净空 %.0fmm" % clear, ("%.0fmm" % clear) in ALL_N)
chk("序列步数 %d" % n_steps, str(n_steps) in ALL)
chk("容差 ±%.0f°" % tol, ("%.0f°" % tol) in ALL)
chk("平移上限 %.2f m/s" % F.V_CAP, ("%.2f" % F.V_CAP) in ALL)
chk("角速度 %.1f rad/s" % F.W_CAP, ("%.1f" % F.W_CAP) in ALL)
chk("a_max = F/m", ("%.4f" % (5.0 / 1.35)) in ALL)
chk("节点 id %s" % node["id"], node["id"] in ALL)
chk("节点位置 (%d, %d)" % (node["x"], node["y"]), ("(%d, %d)" % (node["x"], node["y"])) in ALL)
chk("连线 %d 条" % len(links), ("%d 条连线" % len(links)) in ALL or ("%d 条" % len(links)) in ALL)
chk("每条连线端点在页面上", all(("%s.%s" % (l["f"], l.get("f_port"))) in ALL for l in links))

# 序列自洽
rot = [s for s in plan if s["kind"] == "rotate"]
chk("序列: 抬升+%d+回落" % n_rot, plans_ok := (len(rot) == n_rot and plan[0]["kind"] == "lift" and plan[-1]["kind"] == "descend"))
chk("旋转期间高度不变", all(abs(s["pos"][2] - plan[0]["pos"][2]) < 1e-6 for s in rot))
chk("每拍角度 ≤ 上限", all(s["dr_max_deg"] <= dr + 1e-9 for s in rot), max(s["dr_max_deg"] for s in rot))
chk("累计 = %.0f°" % flip, abs(rot[-1]["deg_done"] - flip) < 1e-9)

# 判据三档
c1 = F.needs_flip(0.0, 180.0)[0]
c2 = F.needs_flip(0.0, 0.0)[0]
c3 = F.needs_flip(0.0, 95.0)[0]
chk("判据: 相反翻/一致不翻/偏95不翻", c1 is True and c2 is False and c3 is False)
chk("页面写了三档判定", "交 L3 重选技能" in ALL and "直接放料" in ALL)

# 版面
W, H = prs.slide_width, prs.slide_height
bad = 0
for s in prs.slides:
    for sh in s.shapes:
        if not (sh.width and sh.height):
            continue
        if sh.left < 0 or sh.top < 0 or sh.left + sh.width > W + 1000 or sh.top + sh.height > H + 1000:
            bad += 1
chk("无越界形状", bad == 0, "bad=%d" % bad)


def R(sh):
    return (sh.left / 914400, sh.top / 914400, (sh.left + sh.width) / 914400, (sh.top + sh.height) / 914400)


def inter(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


ov = 0
for s in prs.slides:
    sh2 = [sh for sh in s.shapes if sh.width and sh.height]
    for i in range(len(sh2)):
        for j in range(i + 1, len(sh2)):
            A, B = sh2[i], sh2[j]
            ta = A.text_frame.text.strip() if A.has_text_frame else ""
            tb = B.text_frame.text.strip() if B.has_text_frame else ""
            if (ta and not tb) or (tb and not ta) or (not ta and not tb):
                continue
            if inter(R(A), R(B)) > 0.02:
                ov += 1
                print("  重叠 p?  [%s] × [%s]" % (ta[:18], tb[:18]))
chk("文字无重叠", ov == 0, "overlaps=%d" % ov)
chk("页数 12", len(prs.slides) == 12, str(len(prs.slides)))

npass = sum(1 for _, ok, _ in checks if ok)
for name, ok, det in checks:
    print(("✓ " if ok else "× ") + name + (("  [" + str(det) + "]") if det else ""))
print("\n%d/%d PASS" % (npass, len(checks)))
sys.exit(0 if npass == len(checks) else 1)
