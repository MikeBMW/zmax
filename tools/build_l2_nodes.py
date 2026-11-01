#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 层节点三页(全景图 + 功能表 1/2、2/2) —— 名称/子层/数量一律以画布为唯一真源, 逐字照抄, 不改写不缩写。

真源:
  节点集合/名称/子层带   data/database/zmax/sources/canvas/state_space_obs.json  （L2 七条 row_bg 带, 逐带取带内节点）
  功能/实现/PURE        src/lerobot/middleware/nodes/<mod>.py 的 PARAMS['desc'] / SOURCE / PURE
  不带 desc 的 3 个节点 取各自实现文件头原文(见 DESC_FALLBACK, 已标注来源)

用法: ./gui-venv311/bin/python tools/build_l2_nodes.py
母版: ~/zmax_data/deliveries/母版/机器人整机内容源_5.50.C.pptx  (重置到 7 页后追加本 3 页)
"""
import json, re, os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

ROOT = '/home/ubuntu/zmax'
ROOT_DATA = '/home/ubuntu/zmax_data'
DECK = ROOT_DATA + '/deliveries/母版/机器人整机内容源_5.50.C.pptx'
CANVAS = ROOT + '/data/database/zmax/sources/canvas/state_space_obs.json'
NODEDIR = ROOT + '/src/lerobot/middleware/nodes'

L2_BANDS = ['row_mem_l2', 'ssbg0', 'ssbg1', 'ssbg2', 'ssbg3', 'ssbg_skill', 'ssbg4']
BAND_COL = {'row_mem_l2': (0x6D, 0x28, 0xD9), 'ssbg0': (0x0E, 0x74, 0x90), 'ssbg1': (0x1D, 0x4E, 0xD8),
            'ssbg2': (0x7C, 0x3A, 0xED), 'ssbg3': (0xC2, 0x41, 0x0C), 'ssbg_skill': (0x15, 0x80, 0x3D),
            'ssbg4': (0x0F, 0x76, 0x6E)}
C_TXT, C_DIM, C_LINE = RGBColor(0x0F, 0x17, 0x2A), RGBColor(0x47, 0x55, 0x69), RGBColor(0xE2, 0xE8, 0xF0)

AR_WRITERS = {'n_moveit', 'ssact'}   # 唯二调 ar_bridge 写 ar_cmd_chain.json 的节点(读自源码调用点)

DESC_FALLBACK = {
    'ss_mem_l2': '小脑·标杆回放：吃 ss_mem_share + n_skill_dict，回放固化标杆并出 ss_mem_field（n_muscle.py 文件头原文）',
    'n_moveit': '原子技能意图 + 安全限制 → 段表 PlanSegments；只规划永不动作（plan_impl.py 文件头原文）',
    'n_exec': 'L2 收口：读 l2_daemon 真值状态与最近事件做授权/闸/到位判定，不造数不下发（n_l2.py 文件头原文）',
}


def add_text(slide, x, y, w, h, text, size=10, bold=False, color=C_TXT, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, spacing=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, line in enumerate(str(text).split('\n')):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing:
            p.line_spacing = spacing
        r = p.add_run(); r.text = line
        r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color; r.font.name = 'Microsoft YaHei'
    return tb


def box(slide, x, y, w, h, fill, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    sh.line.color.rgb = line or fill; sh.line.width = Pt(0.6)
    sh.shadow.inherit = False
    return sh


def load_nodes():
    """严格从画布取 L2 七带的节点: 名称逐字照抄, 不做任何改写"""
    N = json.load(open(CANVAS, encoding='utf-8'))['nodes']
    bands = {n['id']: n for n in N if n['type'] == 'row_bg'}
    idx = open(NODEDIR + '/_index.py', encoding='utf-8').read()
    out = []
    for bid in L2_BANDS:
        b = bands[bid]
        inner = sorted([n for n in N if n['type'] != 'row_bg' and b['y'] <= n['y'] < b['y'] + b['h']],
                       key=lambda z: (z['y'], z['x']))
        for n in inner:
            m = re.search(r'["\']%s["\']\s*:\s*["\']([^"\']+)' % re.escape(n['id']), idx)
            mod = m.group(1).split('.')[-1] if m else ''
            f = '%s/%s.py' % (NODEDIR, mod)
            desc = src = ''; pure = '-'
            if os.path.exists(f):
                t = open(f, encoding='utf-8').read()
                d = re.search(r"'desc'\s*:\s*'([^']*)'", t)
                desc = d.group(1) if d else DESC_FALLBACK.get(n['id'], '')
                s = re.search(r'^SOURCE\s*=\s*[\'"]([^\'"]+)', t, re.M)
                src = s.group(1) if s else ''
                p = re.search(r'^PURE\s*=\s*(\S+)', t, re.M)
                pure = 'True' if p and p.group(1).startswith('True') else 'False'
            if not desc:
                desc = DESC_FALLBACK.get(n['id'], '')
            out.append(dict(id=n['id'], name=n['name'], band=bid, band_name=b['name'], desc=desc,
                            src=src or (mod + '.py'), pure=pure, y=n['y']))
    return out, bands


def short(desc, n=54):
    d = re.sub(r'^\[[^\]]*\]\s*', '', desc).strip()
    for sep in ('；', ';', '。', '，'):
        i = d.find(sep)
        if 0 < i <= n:
            return d[:i]
    return d[:n] + ('…' if len(d) > n else '')


def reset_deck(pr, keep=7):
    lst = pr.slides._sldIdLst
    while len(lst) > keep:
        rId = lst[-1].rId
        pr.part.drop_rel(rId)
        lst.remove(lst[-1])


def slide_panorama(pr, nodes, bands):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    add_text(s, 0.50, 0.18, 12.4, 0.38, 'L2 层全景 · 画布七条带 %d 个节点（名称逐字照抄画布，未改写）' % len(nodes),
             size=17, bold=True)
    add_text(s, 0.50, 0.58, 12.4, 0.38,
             '读法：每一带 = 画布 state_space_obs.json 的一条 row_bg 带，带内卡片 = 画布节点（含 emoji 原名）；'
             '🌍 物理世界 是环境实体节点，画布把它与执行器同放在执行层带，本页照画布保留。功能/实现见后两页。\n'
             '🟩AR 角标 = 真正每拍写 ss_live/ar_cmd_chain.json 驱动 AR 虚拟臂的节点，只有 2 个（n_moveit 写 plan 分区、ssact 写 exec 分区，'
             '由源码 ar_bridge 调用点核出）；其余 29 个节点画布上有、也在跑，但不写 AR 文件，AR 画面里看不到它们。',
             size=8.2, color=C_DIM, spacing=1.2)

    y = 1.02
    CW, GAP, CH, PER = 1.746, 0.05, 0.42, 7
    for bid in L2_BANDS:
        bn = bands[bid]['name']
        inner = [n for n in nodes if n['band'] == bid]
        col = RGBColor(*BAND_COL[bid])
        # 带名: 整行标题(逐字照抄画布带名)
        box(s, 0.50, y, 12.33, 0.19, RGBColor(*[min(255, c + 210) for c in BAND_COL[bid]]),
            RGBColor(*BAND_COL[bid]), MSO_SHAPE.RECTANGLE)
        add_text(s, 0.56, y + 0.012, 12.2, 0.17, '%s（%d 个）' % (bn, len(inner)), size=7.6, bold=True, color=col)
        y += 0.22
        rows = [inner[i:i + PER] for i in range(0, len(inner), PER)]
        for j, row in enumerate(rows):
            for k, n in enumerate(row):
                cx = 0.50 + k * (CW + GAP)
                cy = y + j * (CH + 0.05)
                box(s, cx, cy, CW, CH, RGBColor(0xFA, 0xFB, 0xFD), RGBColor(*BAND_COL[bid]))
                add_text(s, cx + 0.05, cy + 0.02, CW - 0.10, CH - 0.04, n['name'], size=6.2,
                         color=C_TXT, anchor=MSO_ANCHOR.MIDDLE, spacing=0.95)
                if n['id'] in AR_WRITERS:
                    box(s, cx + CW - 0.34, cy + 0.03, 0.30, 0.15, RGBColor(0x16, 0xA3, 0x4A),
                        RGBColor(0x16, 0xA3, 0x4A), MSO_SHAPE.ROUNDED_RECTANGLE)
                    add_text(s, cx + CW - 0.33, cy + 0.045, 0.28, 0.11, 'AR', size=5.6, bold=True,
                             color=RGBColor(0xFF, 0xFF, 0xFF), align=PP_ALIGN.CENTER)
        y += len(rows) * (CH + 0.05) + 0.04
    add_text(s, 0.50, min(y + 0.02, 6.95), 12.4, 0.30,
             '合计 %d 个（逻辑节点 %d + 环境实体 1）；名称与画布逐字一致，可用 tools/verify_solution_deck.py 自动比对。'
             % (len(nodes), len(nodes) - 1), size=8, color=C_DIM)


def slide_table(pr, chunk, part, total_parts):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    add_text(s, 0.42, 0.16, 12.5, 0.34, 'L2 节点功能表（%d/%d）· %d 个节点逐条' % (part, total_parts, len(chunk)),
             size=15, bold=True)
    add_text(s, 0.42, 0.52, 12.5, 0.24,
             '节点名 = 画布原名逐字；功能 = 节点实现 PARAMS["desc"] 首句；实现 = SOURCE 文件 + PURE 是否真算。',
             size=7.6, color=C_DIM)
    cols = [('画布带', 1.55), ('节点（画布原名）', 3.15), ('节点 ID', 1.18), ('功能（节点实现原文首句）', 4.40),
            ('实现文件 / PURE', 1.60)]
    gx, gy, rowh = 0.42, 0.82, 0.335
    x = gx
    for name, w in cols:
        box(s, x, gy, w, 0.26, RGBColor(0x0B, 0x1B, 0x2B), shape=MSO_SHAPE.RECTANGLE)
        add_text(s, x + 0.05, gy + 0.045, w - 0.08, 0.18, name, size=7.2, bold=True,
                 color=RGBColor(0xFF, 0xFF, 0xFF))
        x += w
    y = gy + 0.26
    for i, n in enumerate(chunk):
        x = gx
        fill = RGBColor(0xF7, 0xF9, 0xFC) if i % 2 == 0 else RGBColor(0xFF, 0xFF, 0xFF)
        vals = [n['band_name'].replace('🔧 ', '').replace('L2 基础辅助功能 · ', '').replace('L2 记忆 · ', '记忆 · '),
                n['name'], n['id'], short(n['desc']), '%s / %s' % (os.path.basename(n['src']), n['pure'])]
        for j, (cname, w) in enumerate(cols):
            box(s, x, y, w, rowh, fill, C_LINE, MSO_SHAPE.RECTANGLE)
            col = C_TXT
            bold = (j == 1)
            if j == 0:
                col = RGBColor(*BAND_COL[n['band']])
            if j == 4:
                col = RGBColor(0x15, 0x80, 0x3D) if n['pure'] == 'True' else C_DIM
            add_text(s, x + 0.045, y + 0.02, w - 0.09, rowh - 0.03, vals[j],
                     size=6.6 if j != 3 else 6.5, bold=bold, color=col, anchor=MSO_ANCHOR.MIDDLE, spacing=0.95)
            x += w
        y += rowh


def main():
    nodes, bands = load_nodes()
    pr = Presentation(DECK)
    reset_deck(pr, keep=7)
    slide_panorama(pr, nodes, bands)
    half = (len(nodes) + 1) // 2
    slide_table(pr, nodes[:half], 1, 2)
    slide_table(pr, nodes[half:], 2, 2)
    pr.save(DECK)
    print('L2 节点 %d 个（画布逐字）→ 母版 %d 页' % (len(nodes), len(pr.slides._sldIdLst)))
    for b in L2_BANDS:
        print('  %-44s %d' % (bands[b]['name'], len([n for n in nodes if n['band'] == b])))
    print('  PURE=True %d / 总 %d' % (len([n for n in nodes if n['pure'] == 'True']), len(nodes)))
    print('  n_exec 名称 =', [n['name'] for n in nodes if n['id'] == 'n_exec'])
    out = ROOT + '/docs/1-天枢-产品边界/deliverables/2-机器人方案/L2节点清单_数据源.json'
    json.dump(nodes, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('清单 →', out)


if __name__ == '__main__':
    main()
