#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_deck_multi_machine.py — 《多机动作协同》自检 (不靠眼睛)

① 页数/比例  ② 形状越界  ③ 文本按中文字宽估算是否溢出框高  ④ 同页文本框压字粗判
⑤ 页面数字必须与现算一致 (α_s / 力残差 / 主机能量 / 计划-实测-缺口 / 层份额)
用法: PYTHONPATH=src ./gui-venv311/bin/python tools/verify_deck_multi_machine.py
"""
from __future__ import annotations

import math
import os
import sys

from pptx import Presentation

ROOT = "/home/ubuntu/zmax"
PPTX = os.path.join(ROOT, "zmax_data/reports/多机动作协同_功能说明_v1.pptx")
EMU_IN = 914400.0
fails, notes = [], []


def inch(v):
    return float(v) / EMU_IN


def main():
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import numpy as np
    from lerobot.manifold.multi_machine_energy import machine_energy, assist_share, dual_layer_forces
    from lerobot.manifold.state_space_energy import StateSpaceHamiltonian
    from lerobot.manifold.se3_gravity_provider import _rpy_to_T
    from lerobot.manifold.se3_impedance import pose_error

    ham = StateSpaceHamiltonian()
    g = _rpy_to_T([0.649, 0.404, 0.114, 2.961, -1.490, 0.205, 0.0])
    gd = g.copy()
    gd[:3, 3] = g[:3, 3] + g[:3, 2] * 0.005
    M = machine_energy(g, gd, np.array([0, 0, 0.05, 0, 0, 0]), ham)
    a = assist_share(240.0, 319.0, 120.0)
    _, xi_e = pose_error(g, gd)
    dl = dual_layer_forces(ham, {"M": a["alpha_master"], "S": a["alpha_slave"]}, xi_e)

    prs = Presentation(PPTX)
    if len(prs.slides) != 8:
        fails.append("页数 %d ≠ 8" % len(prs.slides))
    sw, sh = inch(prs.slide_width), inch(prs.slide_height)

    body = []
    for si, s in enumerate(prs.slides, 1):
        bx = []
        for shp in s.shapes:
            x, y, w, h = inch(shp.left), inch(shp.top), inch(shp.width), inch(shp.height)
            if x < -0.01 or y < -0.01 or x + w > sw + 0.01 or y + h > sh + 0.01:
                fails.append("p%d 形状越界 (%.2f,%.2f %.2fx%.2f)" % (si, x, y, w, h))
            if not shp.has_text_frame:
                continue
            tf = shp.text_frame
            t_all = "\n".join(p.text for p in tf.paragraphs)
            body.append(t_all)
            need = 0.0
            for p in tf.paragraphs:
                t = p.text
                if not t:
                    need += 0.04
                    continue
                size = max([r.font.size.pt for r in p.runs if r.font.size] or [12])
                cpl = max(1, int((w - 0.06) * 72 / (size * 1.02)))
                lines = max(1, math.ceil(len(t) / cpl))
                need += lines * size * (p.line_spacing or 1.0) * 1.2 / 72.0
            if need > h + 0.04:
                fails.append("p%d 文字可能溢出 「%s」需 %.2f>框高 %.2f"
                             % (si, t_all[:16].replace("\n", " "), need, h))
            bx.append((x, y, w, h, need, t_all[:14]))
        for i in range(len(bx)):
            for j in range(i + 1, len(bx)):
                xi, yi, wi, hi, ni, ti = bx[i]
                xj, yj, wj, hj, nj, tj = bx[j]
                if min(xi + wi, xj + wj) - max(xi, xj) <= 0.05:
                    continue
                if yi <= yj and yi + ni > yj + 0.05 and yi + hi > yj + 0.02:
                    fails.append("p%d 疑似压字 「%s」用到 %.2f, 「%s」从 %.2f" % (si, ti, yi + ni, tj, yj))

    txt = "\n".join(body)
    must = {
        "α_s": "%.4f" % a["alpha_slave"],
        "力残差": "%.1e" % dl["resid_sumF"],
        "主机能量 H": "%.6f" % M["H"],
        "缺口": "%.0f" % a["gap"],
        "饱和 shortfall": "%.0f" % assist_share(240.0, 319.0, 40.0)["shortfall"],
    }
    for k, v in must.items():
        if v not in txt:
            fails.append("页面缺 %s=%s" % (k, v))
        else:
            notes.append("%s=%s ✓" % (k, v))
    if "saturated=true" not in txt:
        fails.append("页面没有 saturated=true 的如实记账")

    print("页数 %d · 16:9 %.2f×%.2f · 文本框 %d" % (len(prs.slides), sw, sh, len(body)))
    for n in notes:
        print("  ", n)
    if fails:
        print("\n❌ %d 项:" % len(fails))
        for f in fails:
            print("   -", f)
        return 1
    print("\n✅ 全过 (页数/边界/溢出/压字/数字同源)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
