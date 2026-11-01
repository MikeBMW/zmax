#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""母版前 5 页 (三视图/尺寸页) 的定点修字/改框 —— 这几页没有生成脚本, 母版即真源。

老倪 2026-11-02: 解决方案册要「数据来源可核」; 第 3 页写「AR 场景几何渲染」是口径不清
(图是 URDF STL 网格 + 工位常量渲的, 不是 AR 页面截的), 改为「URDF 几何渲染」;
顺手把两处实测溢出的框放大/缩字号 (check_deck_fit 报的 2 处 + 1 处)。

用法: gui-venv311/bin/python tools/fix_base_pages_v550c.py
     (幂等: 已是新文案/新尺寸则跳过)
"""
from pptx import Presentation
from pptx.util import Inches, Pt

DECK = '/home/ubuntu/zmax_data/deliveries/母版/机器人整机内容源_5.50.C.pptx'
OLD_LINE = 'AR 场景几何渲染'
NEW_LINE = 'URDF 几何渲染'

pr = Presentation(DECK)
changed = []

# --- 第 1 页: 标题块文案 + 框高/下移, 避免 32pt 5 行压到下面的尺寸块 ---
s1 = pr.slides[0]
for sh in s1.shapes:
    if not sh.has_text_frame:
        continue
    for p in sh.text_frame.paragraphs:
        for r in p.runs:
            if r.text.strip() == OLD_LINE:
                r.text = r.text.replace(OLD_LINE, NEW_LINE)
                changed.append('p1 文案 %s → %s' % (OLD_LINE, NEW_LINE))
    if sh.top is not None and abs(sh.top / 914400 - 1.90) < 0.02 and abs(sh.height / 914400 - 2.50) < 0.02:
        sh.height = Inches(2.62)
        changed.append('p1 标题块 h 2.50 → 2.62')
    if sh.width is not None and abs(sh.width / 914400 - 3.15) < 0.02 and sh.height / 914400 < 1.7:
        # 3.15in 宽放不下 15pt 的 6 行 → 先用满下方空白 (h 1.72), 不动字号
        if abs(sh.top / 914400 - 4.55) < 0.02:
            sh.top = Inches(4.72)
            changed.append('p1 尺寸块 t 4.55 → 4.72')
        if sh.height / 914400 < 1.7:
            sh.height = Inches(1.72)
            changed.append('p1 尺寸块 h → 1.72 (15pt 6 行放得下)')

# --- 第 2 页: 正面/侧面两行标注 14pt 放不下 → 12.5pt ---
s2 = pr.slides[1]
for sh in s2.shapes:
    if not sh.has_text_frame or abs(sh.top / 914400 - 5.55) > 0.02:
        continue
    for p in sh.text_frame.paragraphs:
        for r in p.runs:
            if r.font.size and r.font.size.pt == 14.0:
                r.font.size = Pt(12.5)
                changed.append('p2 标注字号 14 → 12.5: %s…' % r.text[:12])

if changed:
    pr.save(DECK)
for c in dict.fromkeys(changed):
    print('✓', c)
print('母版页数 %d · 改动 %d 处' % (len(pr.slides._sldIdLst), len(dict.fromkeys(changed))))
