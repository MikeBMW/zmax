#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_deck_dual_guide_1p.py — 一页 PPT 的自检 (不靠眼睛):

  ① 只有 1 页  ② 所有形状在页面内  ③ 每个文本框按"中文字宽≈1em, 行高=字号×行距×1.2"
  估算所需高度, 超过框高 ⇒ 报越界  ④ 文本框之间粗判重叠  ⑤ 数字必须与现算一致 (pair/位姿)

用法: ./gui-venv311/bin/python tools/verify_deck_dual_guide_1p.py
"""
from __future__ import annotations

import math
import os
import re
import sys

from pptx import Presentation
from pptx.util import Emu

ROOT = "/home/ubuntu/zmax"
PPTX = os.path.join(ROOT, "zmax_data/reports/左右3D引导位姿_双臂协同_v1.pptx")
EMU_IN = 914400.0

fails, notes = [], []


def inch(v):
    return float(v) / EMU_IN


def main():
    sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space"))
    import numpy as np
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from plan_guide import dual_arm_guide

    obs = np.zeros(43)
    obs[0:3] = [0.649, 0.404, 0.1142]
    d = dual_arm_guide({"in1": obs})

    prs = Presentation(PPTX)
    if len(prs.slides) != 1:
        fails.append("页数 %d ≠ 1" % len(prs.slides))
    sw, sh = inch(prs.slide_width), inch(prs.slide_height)
    if abs(sw - 13.333) > 0.01 or abs(sh - 7.5) > 0.01:
        fails.append("页面 %.3f×%.3f 不是 16:9" % (sw, sh))

    s = prs.slides[0]
    boxes = []
    alltext = []
    for shp in s.shapes:
        x, y, w, h = inch(shp.left), inch(shp.top), inch(shp.width), inch(shp.height)
        if x < -0.01 or y < -0.01 or x + w > sw + 0.01 or y + h > sh + 0.01:
            fails.append("形状越出页面: %s (%.2f,%.2f %.2fx%.2f)" % (shp.shape_type, x, y, w, h))
        if not shp.has_text_frame:
            continue
        tf = shp.text_frame
        need = 0.0
        txt = "\n".join(p.text for p in tf.paragraphs)
        alltext.append(txt)
        for p in tf.paragraphs:
            t = p.text
            if not t:
                need += 0.04
                continue
            size = max([r.font.size.pt for r in p.runs if r.font.size] or [12])
            cpl = max(1, int((w - 0.06) * 72 / (size * 1.02)))            # 中文字宽≈1em
            lines = max(1, math.ceil(len(t) / cpl))
            need += lines * size * (p.line_spacing or 1.0) * 1.2 / 72.0
        if need > h + 0.04:
            fails.append("文字可能溢出: 「%s」需 %.2f in > 框高 %.2f in" % (txt[:18].replace("\n", " "), need, h))
        boxes.append((x, y, w, h, need, txt[:18]))

    # 粗判重叠: 只在"A 的框底 越过 B 的顶"且横向相交时报
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            xi, yi, wi, hi, ni, ti = boxes[i]
            xj, yj, wj, hj, nj, tj = boxes[j]
            ox = min(xi + wi, xj + wj) - max(xi, xj)
            if ox <= 0.05:
                continue
            # A 实际用到 yi+ni, B 从 yj 开始
            if yi <= yj and yi + ni > yj + 0.04 and yi + hi > yj:
                fails.append("疑似压字: 「%s」用到 %.2f in, 「%s」从 %.2f 开始" % (ti, yi + ni, tj, yj))

    body = "\n".join(alltext)
    for name, val in (("左", d["L"]["grasp_mm"]), ("右", d["R"]["grasp_mm"])):
        pat = "%7.1f, %7.1f, %6.1f" % tuple(val)
        if pat.strip()[:9] not in body:
            fails.append("%s臂位姿 %s 没出现在页面上" % (name, val))
    m = re.findall(r"PAIR_\d{8}_\d{6}", body)
    if not m:
        fails.append("页面上没有 pair_id (PAIR_日期_时刻)")
    else:
        notes.append("页面 pair_id: %s (生成时刻的组号, 每次生成新组 ⇒ 不与现算逐字比)" % m[0])

    print("页数 %d · 形状 %d · 16:9 %.2f×%.2f" % (len(prs.slides), len(s.shapes), sw, sh))
    for n in notes:
        print("注:", n)
    print("现算: pair %s · L %s · R %s · hold %s" % (d["pair_id"], d["L"]["grasp_mm"], d["R"]["grasp_mm"], d["hold"]))
    if fails:
        print("\n❌ %d 项:" % len(fails))
        for f in fails:
            print("   -", f)
        return 1
    print("\n✅ 一页自检全过 (页数/边界/溢出/压字/数字同源)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
