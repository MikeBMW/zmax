#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 连线页 —— 把画布 links 逐条画出来。

老倪 2026-11-02: 「PPT 增加 L2 层的连线, 以及与 L3 层的连线节点; 主要是 L2 层,
但也要有跟 L2 层有连接关系的所有节点」。

真源: data/database/zmax/sources/canvas/state_space_obs.json
      nodes(名称逐字) + links(f/t/label 逐条) —— 连线不新增、不改向、不省略。

页①  L2 内部数据流: 31 个 L2 节点 / 65 条 L2↔L2 连线, 顶部 L3 的 3 个节点 + 5 条 L3↔L2 连线。
页②  L2 ↔ 层外节点二部图: 左 29 个与 L2 有连线的层外节点(按层分组), 右 22 个被连到的 L2 节点,
      55 条连线逐条画。

线先画、框后画 ⇒ 线压在框下, 长线穿框不挡字 (与画布 GUI 同一观感)。
"""
import json

from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

ROOT = '/home/ubuntu/zmax'
CANVAS = ROOT + '/data/database/zmax/sources/canvas/state_space_obs.json'

L2_BANDS = ['row_mem_l2', 'ssbg0', 'ssbg1', 'ssbg2', 'ssbg3', 'ssbg_skill', 'ssbg4']
L3_BANDS = ['row_mem_l3', 'ssbg_vlm']
SKILL_ORDER = ['sslimit'] + ['sssk%d' % i for i in range(1, 9)] + ['ssphys', 'n_moveit', 'n_exec']

BAND_COL = {
    'row_mem_l2': (0x6D, 0x28, 0xD9), 'ssbg0': (0x0E, 0x74, 0x90), 'ssbg1': (0x1D, 0x4E, 0xD8),
    'ssbg2': (0x7C, 0x3A, 0xED), 'ssbg3': (0xC2, 0x41, 0x0C), 'ssbg_skill': (0x15, 0x80, 0x3D),
    'ssbg4': (0x0F, 0x76, 0x6E),
}
LAYER_STYLE = {
    'ssbg_vlm': ((0xC2, 0x41, 0x0C), 'L3 · VLM + Flow-Matching'),
    'row_mem_l3': ((0xC2, 0x41, 0x0C), 'L3 · 长程规划记忆'),
    'ssbg5': ((0x6D, 0x28, 0xD9), 'L5 · 大模型层'),
    'ssbg7': ((0xB4, 0x53, 0x09), 'L4 · 标定与流形世界模型'),
    'row_mem_l4': ((0xB4, 0x53, 0x09), 'L4 · 筹划记忆'),
    'ssbg_data': ((0x0F, 0x76, 0x6E), '数据源 / 硬件'),
    'ssbg9': ((0x15, 0x80, 0x3D), '可视化 · 观察器'),
    'ssbg8': ((0x47, 0x55, 0x69), '验证层'),
    'none': ((0x47, 0x55, 0x69), '层外 / 硬件'),
}
C_WIRE = RGBColor(0x7C, 0x87, 0x98)
C_L3 = RGBColor(0xC2, 0x41, 0x0C)
C_UP = RGBColor(0x0E, 0x74, 0x90)
C_TXT = RGBColor(0x0F, 0x17, 0x2A)
C_DIM = RGBColor(0x47, 0x55, 0x69)


# ------------------------------------------------------------------ 真源
def load_canvas():
    d = json.load(open(CANVAS, encoding='utf-8'))
    N = {n['id']: n for n in d['nodes']}
    bands = {n['id']: n for n in d['nodes'] if n['type'] == 'row_bg'}

    def inner(bid):
        b = bands[bid]
        return sorted([n for n in d['nodes'] if n['type'] != 'row_bg'
                       and b['y'] <= n['y'] < b['y'] + b['h']], key=lambda z: (z['y'], z['x']))

    l2 = {n['id'] for bid in L2_BANDS for n in inner(bid)}
    l3 = {n['id'] for bid in L3_BANDS for n in inner(bid)}

    def layer_of(nid):
        n = N[nid]
        for bid, b in bands.items():
            if b['y'] <= n['y'] < b['y'] + b['h']:
                return bid
        return 'none'

    return dict(N=N, bands=bands, inner=inner, l2=l2, l3=l3, layer_of=layer_of, links=d['links'])


_C = load_canvas()


# ------------------------------------------------------------------ 图元
def add_text(slide, x, y, w, h, text, size=7.0, bold=False, color=C_TXT, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.MIDDLE, spacing=0.95):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, line in enumerate(str(text).split('\n')):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        r.font.name = 'Microsoft YaHei'
    return tb


def box(slide, x, y, w, h, fill, line, shape=MSO_SHAPE.ROUNDED_RECTANGLE, lw=0.6):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    sh.line.color.rgb = line
    sh.line.width = Pt(lw)
    sh.shadow.inherit = False
    return sh


def seg(slide, x1, y1, x2, y2, col, w=0.6, arrow=False, dash=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = col
    c.line.width = Pt(w)
    if dash:
        c.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    if arrow:
        ln = c.line._get_or_add_ln()
        el = ln.makeelement(qn('a:tailEnd'), {'type': 'triangle', 'w': 'sm', 'len': 'sm'})
        ln.append(el)
    return c


class Cell:
    def __init__(self, nid, name, row, x, y, w, h):
        self.id, self.name, self.row = nid, name, row
        self.x, self.y, self.w, self.h = x, y, w, h

    cx = property(lambda s: s.x + s.w / 2)
    cy = property(lambda s: s.y + s.h / 2)
    right = property(lambda s: s.x + s.w)
    bottom = property(lambda s: s.y + s.h)


class Router:
    """a→b 三折线: 出 a 竖直 → 行间沟横走 → 进 b。行间沟按 lane 错开, 避免整段重合。"""

    def __init__(self, gutters):
        self.gutters = gutters
        self.used = {}

    def lane(self, key, y0):
        n = self.used.get(key, 0)
        self.used[key] = n + 1
        return y0 + 0.022 + (n % 3) * 0.030

    def wire(self, slide, a, b, col=C_WIRE, w=0.6, dash=False):
        if a.row == b.row and b.x >= a.right - 1e-6:      # 同一行且目标在右: 直连
            seg(slide, a.right, a.cy, b.x, b.cy, col, w, arrow=True, dash=dash)
            return 1
        down = b.row > a.row
        gi = min(max(a.row + (1 if down else 0), 0), len(self.gutters) - 1)
        ly = self.lane(('r' if a.row == b.row else ('d' if down else 'u'), a.row), self.gutters[gi])
        y0 = a.bottom if (down or a.row == b.row) else a.y
        y1 = b.y if (down or a.row == b.row) else b.bottom
        seg(slide, a.cx, y0, a.cx, ly, col, w, dash=dash)
        seg(slide, a.cx, ly, b.cx, ly, col, w, dash=dash)
        seg(slide, b.cx, ly, b.cx, y1, col, w, arrow=True, dash=dash)
        return 3


# ------------------------------------------------------------------ 版面 (页①)
def l2_layout(top=1.30, cell_h=0.38, gutter=0.13, x0=0.50, W=12.33, per=7):
    cw = (W - (per - 1) * 0.05) / per
    cells, bands_layout, gutters = {}, [], []
    y, row_i = top, 0
    for bid in L2_BANDS:
        y_strip = y
        y += 0.17
        ids = [n['id'] for n in _C['inner'](bid)]
        if bid == 'ssbg_skill':
            ids = [i for i in SKILL_ORDER if i in ids] + [i for i in ids if i not in SKILL_ORDER]
        for k0 in range(0, len(ids), per):
            for k, nid in enumerate(ids[k0:k0 + per]):
                cells[nid] = Cell(nid, _C['N'][nid]['name'], row_i, x0 + k * (cw + 0.05), y, cw, cell_h)
            y += cell_h + gutter
            gutters.append(y - gutter)
            row_i += 1
        bands_layout.append((bid, y_strip, ids))
    return cells, bands_layout, gutters


# ------------------------------------------------------------------ 页①: L2 内部 + L3
def draw_core_page(slide, note=''):
    cells, bands_layout, gutters = l2_layout()
    l2_edges = [k for k in _C['links'] if k['f'] in _C['l2'] and k['t'] in _C['l2']]
    band_of = {nid: bid for bid, _, ids in bands_layout for nid in ids}

    # L3 条带: 只放与 L2 有连线的 3 个节点
    l3_ids = ['ssvlm', 'ss_mem_l3', 'ssdec']
    l3_cells, l3_y, l3_h, l3_w = {}, 0.94, 0.26, 2.30
    add_text(slide, 0.50, l3_y, 1.05, l3_h, 'L3 层（%d）' % len(l3_ids), size=7.4, bold=True,
             color=C_L3)
    for i, nid in enumerate(l3_ids):
        l3_cells[nid] = Cell(nid, _C['N'][nid]['name'], -1, 1.58 + i * (l3_w + 0.12), l3_y, l3_w, l3_h)

    cross = [k for k in _C['links']
             if (k['f'] in _C['l3'] and k['t'] in _C['l2']) or (k['f'] in _C['l2'] and k['t'] in _C['l3'])]

    # 线先画
    R = Router(gutters)
    nseg = sum(R.wire(slide, cells[k['f']], cells[k['t']]) for k in l2_edges
               if k['f'] in cells and k['t'] in cells)
    up = Router([1.24, 1.24] + gutters)
    n_cross = 0
    for k in cross:
        a = l3_cells.get(k['f']) or cells.get(k['f'])
        b = cells.get(k['t']) or l3_cells.get(k['t'])
        if not a or not b:
            continue
        n_cross += 1
        if a.row == -1:                                  # L3 → L2 (橙实线)
            ly = up.lane(('down', 'l3'), 1.22)
            seg(slide, a.cx, a.bottom, a.cx, ly, C_L3, 1.0)
            seg(slide, a.cx, ly, b.cx, ly, C_L3, 1.0)
            seg(slide, b.cx, ly, b.cx, b.y, C_L3, 1.0, arrow=True)
        else:                                            # L2 → L3 (青虚线)
            ly = up.lane(('up', 'l3'), 1.22)
            seg(slide, a.cx, a.y, a.cx, ly, C_UP, 0.9, dash=True)
            seg(slide, a.cx, ly, b.cx, ly, C_UP, 0.9, dash=True)
            seg(slide, b.cx, ly, b.cx, b.bottom, C_UP, 0.9, arrow=True, dash=True)
        nseg += 3

    # 框后画
    for c in l3_cells.values():
        box(slide, c.x, c.y, c.w, c.h, RGBColor(0xFF, 0xF7, 0xED), C_L3, lw=1.0)
        add_text(slide, c.x + 0.05, c.y, c.w - 0.10, c.h, c.name, size=6.4, color=RGBColor(0x7C, 0x2D, 0x12))
    for bid, y_strip, ids in bands_layout:
        tri = BAND_COL[bid]
        col = RGBColor(*tri)
        box(slide, 0.50, y_strip, 12.33, 0.16, RGBColor(*[min(255, v + 210) for v in tri]), col,
            MSO_SHAPE.RECTANGLE)
        add_text(slide, 0.56, y_strip, 12.2, 0.16,
                 '%s（%d 个节点 · %d 条连线）' % (_C['bands'][bid]['name'], len(ids),
                                                sum(1 for k in l2_edges
                                                    if band_of.get(k['f']) == bid)),
                 size=7.0, bold=True, color=col)
    for nid, c in cells.items():
        col = RGBColor(*BAND_COL[band_of[nid]])
        box(slide, c.x, c.y, c.w, c.h, RGBColor(0xFA, 0xFB, 0xFD), col)
        add_text(slide, c.x + 0.05, c.y, c.w - 0.10, c.h, c.name, size=5.8, color=C_TXT)

    add_text(slide, 0.50, 6.88, 12.4, 0.22,
             '合计 %d 个节点 · 基础层内部 %d 条连线 · 层间 %d 条（橙实线为上层到基础层，青虚线为反向）；'
             '连线逐条取自画布，走行间空隙、压在框下不挡字，名称照画布原样。%s' % (len(cells), len(l2_edges), n_cross, note),
             size=6.8, color=C_DIM)
    return dict(l2_nodes=len(cells), l2_edges=len(l2_edges), l3_nodes=len(l3_cells),
                l3_edges=n_cross, segs=nseg)


# ------------------------------------------------------------------ 页②: L2 ↔ 层外
def draw_ext_page(slide, note=''):
    l2 = _C['l2']
    ext_edges = [k for k in _C['links'] if (k['f'] in l2) != (k['t'] in l2)]
    on_core = {'ssvlm', 'ss_mem_l3', 'ssdec'}            # 页① 已画
    ext_of = lambda k: k['f'] if k['f'] not in l2 else k['t']
    edges = [k for k in ext_edges if ext_of(k) not in on_core]
    ext_ids = sorted({ext_of(k) for k in edges})
    tgt_ids = sorted({(k['t'] if k['t'] in l2 else k['f']) for k in edges},
                     key=lambda i: -sum(1 for k in edges if (k['t'] if k['t'] in l2 else k['f']) == i))

    groups = {}
    for i in ext_ids:
        groups.setdefault(_C['layer_of'](i), []).append(i)
    order = ['ssbg5', 'ssbg7', 'row_mem_l4', 'ssbg_data', 'ssbg9', 'ssbg8', 'none']
    gorder = [g for g in order if g in groups] + [g for g in groups if g not in order]

    lx, lw, rx, rw = 0.50, 2.62, 10.14, 2.70
    y = 1.00
    lcells = {}
    for g in gorder:
        col, label = LAYER_STYLE.get(g, ((0x47, 0x55, 0x69), g))
        add_text(slide, lx, y, lw, 0.15, '%s（%d）' % (label, len(groups[g])), size=6.4, bold=True,
                 color=RGBColor(*col))
        y += 0.16
        for nid in groups[g]:
            lcells[nid] = Cell(nid, _C['N'][nid]['name'], 0, lx, y, lw, 0.135)
            y += 0.145
        y += 0.045
    add_text(slide, lx, y + 0.01, 3.2, 0.16, '↑ 层外节点（按层分组）→ 右侧 L2 节点', size=6.2, color=C_DIM)

    y = 1.00
    rcells = {}
    for nid in tgt_ids:
        rcells[nid] = Cell(nid, _C['N'][nid]['name'], 0, rx, y, rw, 0.21)
        y += 0.235
    add_text(slide, rx, 0.84, rw, 0.15, 'L2 被连到的节点（%d 个）' % len(tgt_ids), size=6.6,
             bold=True, color=C_DIM)

    # 线先画 (直线, 跨列扇形)
    for k in edges:
        inbound = k['t'] in l2
        a = lcells[k['f']] if inbound else rcells[k['f']]
        b = rcells[k['t']] if inbound else lcells[k['t']]
        layer = _C['layer_of'](k['f'] if inbound else k['t'])
        col = RGBColor(*LAYER_STYLE.get(layer, ((0x47, 0x55, 0x69), ''))[0])
        seg(slide, a.right, a.cy, b.x, b.cy, col, 0.6, arrow=True)

    for nid, c in lcells.items():
        col = RGBColor(*LAYER_STYLE.get(_C['layer_of'](nid), ((0x47, 0x55, 0x69), ''))[0])
        box(slide, c.x, c.y, c.w, c.h, RGBColor(0xF7, 0xF9, 0xFC), col)
        add_text(slide, c.x + 0.05, c.y, c.w - 0.10, c.h, c.name, size=5.4, color=C_TXT)
    for nid, c in rcells.items():
        bid = [b for b in L2_BANDS if nid in {x['id'] for x in _C['inner'](b)}][0]
        box(slide, c.x, c.y, c.w, c.h, RGBColor(0xFF, 0xFF, 0xFF), RGBColor(*BAND_COL[bid]), lw=0.8)
        add_text(slide, c.x + 0.05, c.y, c.w - 0.10, c.h, c.name, size=5.6, color=C_TXT)

    add_text(slide, 0.50, 6.88, 12.4, 0.22,
             '与 L2 有连线的层外节点 %d 个 / 连线 %d 条，一条不落；颜色按层（紫 L5 · 棕 L4 · 绿 可视化 · '
             '青绿 数据源/硬件 · 灰 层外）；L3 的 3 个节点与 5 条线见页①。%s' % (len(lcells), len(edges), note),
             size=6.8, color=C_DIM)
    return dict(ext_nodes=len(lcells), ext_edges=len(edges), targets=len(tgt_ids))

# ------------------------------------------------------------------ 计数 (建页/自检同源)
def counts():
    l2, l3 = _C['l2'], _C['l3']
    on_core = {'ssvlm', 'ss_mem_l3', 'ssdec'}          # 页① 已画的 L3 节点
    ext_of = lambda k: k['f'] if k['f'] not in l2 else k['t']
    l2e = [k for k in _C['links'] if k['f'] in l2 and k['t'] in l2]
    cross = [k for k in _C['links']
             if (k['f'] in l3 and k['t'] in l2) or (k['f'] in l2 and k['t'] in l3)]
    ext = [k for k in _C['links']
           if (k['f'] in l2) != (k['t'] in l2) and ext_of(k) not in on_core]
    return dict(l2_nodes=len(l2), l3_nodes=len(on_core), l2_edges=len(l2e), l3_edges=len(cross),
                ext_nodes=len({ext_of(k) for k in ext}), ext_edges=len(ext))
