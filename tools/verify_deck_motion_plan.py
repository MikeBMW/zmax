#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_deck_motion_plan.py — 按真源重算《动作规划节点 · 功能描述》里的每个数, 再断言页面上写的就是它。

判据: 所有轨迹数从 action_trail_slot3.json 现算, 所有槽位/姿态从 cell_points.json 与轨迹头现算,
再把算出来的**格式化值**去 PPT 文本里找; 任一条不匹配 ⇒ 退出码 1。
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter

from pptx import Presentation

DECK = "/home/ubuntu/zmax/zmax_data/reports/动作规划节点_功能描述_v2.pptx"
TRAIL = "/home/ubuntu/zmax/zmax_data/ss_live/action_trail_slot3.json"
POINTS = "/home/ubuntu/zmax/config/points/cell_points.json"

ev = json.load(open(TRAIL, encoding="utf-8"))
tp = ev["target_pose"]
steps = ev["steps"]
taught = [s["pos"] for s in json.load(open(POINTS, encoding="utf-8"))["slots"] if s["name"] == "槽3"][0]

prs = Presentation(DECK)
text = []
for s in prs.slides:
    for sh in s.shapes:
        if sh.has_text_frame:
            text.append(sh.text_frame.text)
        if sh.has_table:
            for row in sh.table.rows:
                for c in row.cells:
                    text.append(c.text)
ALL = "\n".join(text).replace("\u2212", "-").replace("\uff0b", "+")

checks = []


def chk(name, cond, detail=""):
    checks.append((name, bool(cond), detail))


n = len(steps)
cnt = Counter(s["phase"] for s in steps)
tot = round(sum(math.dist(steps[i - 1]["pos"], steps[i]["pos"]) for i in range(1, n)), 1)
ds = [(steps[i]["phase"], round(math.dist(steps[i - 1]["pos"], steps[i]["pos"]), 2)) for i in range(1, n)]
max_step = max(v for _, v in ds)
desc = [v for k, v in ds if k == "descend"]

chk("拍数 %d" % n, ("%d 拍" % n) in ALL, str(dict(cnt)))
chk("总长 %.1fmm" % tot, ("%.1fmm" % tot) in ALL)
chk("单拍最大 %.2fmm" % max_step, ("%.2fmm" % max_step) in ALL)
chk("下降段单拍 %s" % " / ".join("%.2f" % v for v in desc),
    (" / ".join("%.2f" % v for v in desc)) in ALL, str(desc))
chk("单步上限 25mm 未被突破", max_step <= 25.0 + 1e-6, "max=%.2f" % max_step)
chk("下降段 ≤20mm", all(v <= 20.0 + 1e-6 for v in desc), str(desc))
chk("分段计数 %s" % dict(cnt),
    all(("%s %d" % (k, cnt[k])) in ALL for k in ("approach", "descend", "grip", "lift") if cnt[k]))

hover = round(tp["pre_pos_mm"][2] - tp["grasp_mm"][2], 2)
chk("预抓点高出 %.0fmm" % hover, hover == 40.0 and "40mm" in ALL)
d = [round(tp["grasp_mm"][i] - taught[i], 1) for i in range(3)]
want = "(%.1f, %.1f, +%.1f)" % (d[0], d[1], d[2])
chk("先验与示教差 %s" % want, want in ALL, str(d))
pos_s = "%.1f, %.1f, %.1f" % tuple(tp["pos_mm"])
chk("引导 pos %s" % pos_s, pos_s in ALL)
chk("valid=false 如实标注", "valid=false" in ALL)
chk("事故 Δ69.25mm + 落点", "69.25" in ALL and "533.55" in ALL and "327.12" in ALL)
chk("常量 25mm / 20mm / 2.0s", "25mm" in ALL and "20mm" in ALL and "2.0s" in ALL)
chk("工作空间数值", "0.15~1.05" in ALL and "0.95" in ALL)

W, H = prs.slide_width, prs.slide_height
bad = 0
for s in prs.slides:
    for sh in s.shapes:
        if not (sh.width and sh.height):
            continue
        if sh.left < 0 or sh.top < 0 or sh.left + sh.width > W + 1000 or sh.top + sh.height > H + 1000:
            bad += 1
chk("无越界形状", bad == 0, "bad=%d" % bad)
chk("页数 12", len(prs.slides) == 12, str(len(prs.slides)))


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
chk("文字无重叠", ov == 0, "overlaps=%d" % ov)

npass = sum(1 for _, ok, _ in checks if ok)
for name, ok, det in checks:
    print(("✓ " if ok else "× ") + name + (("  [" + det + "]") if det else ""))
print("\n%d/%d PASS" % (npass, len(checks)))
sys.exit(0 if npass == len(checks) else 1)
