#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""层节点页 (L5 / L4 / L3 / L2) —— 名称/子层/数量一律以画布为唯一真源, 逐字照抄。

老倪 2026-11-01: 「PPT 增加 L3 L4 L5 层的功能」

真源:
  节点/名称/子层带   data/database/zmax/sources/canvas/state_space_obs.json
                    L5=ssbg5(14) · L4=row_mem_l4+ssbg7(16) · L3=row_mem_l3+ssbg_vlm(4) · L2=七带(31)
  功能/实现/PURE     src/lerobot/middleware/nodes/<mod>.py 的 PARAMS['desc'] / SOURCE / PURE

页序 (母版重置到 7 页后追加):
  L5 全景 + L5 功能表 (2 页)
  L4 全景 + L4 功能表 (2 页)
  L3 全景+功能表合一 (1 页, 只有 4 个节点)
  L2 全景 + 2 张功能表 (3 页, 与既有版式一致)

用法: ./gui-venv311/bin/python tools/build_layer_nodes.py
"""
import json
import os
import re

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = '/home/ubuntu/zmax'
ROOT_DATA = '/home/ubuntu/zmax_data'
DECK = ROOT_DATA + '/deliveries/母版/机器人整机内容源_5.50.C.pptx'
CANVAS = ROOT + '/data/database/zmax/sources/canvas/state_space_obs.json'
NODEDIR = ROOT + '/src/lerobot/middleware/nodes'

LAYERS = [
    ('L5', ['ssbg5'],
     'L5 大模型层 · 任务/编排/记忆中枢（回路外慢决策）',
     'L5 不参与 10Hz 控制回路：出任务意图、场景理解、技能序列与经验记忆；'
     '每拍都可读，慢决策异步刷新。'),
    ('L4', ['row_mem_l4', 'ssbg7'],
     'L4 专家自主功能 · 标定与流形世界模型',
     'L4 负责世界模型预测、安全导航与标定参数（M/流形/INTACT）；'
     '输出作为 L3 的条件与 L2 的可行域约束。'),
    ('L3', ['row_mem_l3', 'ssbg_vlm'],
     'L3 高级自动功能 · VLM 编码 + Flow-Matching',
     'L3 把视觉编码成 token（VLM），再由 Flow-Matching 动作头解码成动作序列；'
     'LoRA 微调接在其后，冻结原权重只调 ΔW。'),
    ('L2', ['row_mem_l2', 'ssbg0', 'ssbg1', 'ssbg2', 'ssbg3', 'ssbg_skill', 'ssbg4'],
     'L2 基础辅助功能（分段感知 → 融合 → 控制 → 决策 → 技能 → 执行）',
     'L2 是执行层：43D 统一状态 → 测地线规划引导 → 工艺动作 → 限幅/调制 → 运动规划 → 执行器。'),
]

BAND_COL = {
    'ssbg5': (0x6D, 0x28, 0xD9),
    'row_mem_l4': (0xB4, 0x53, 0x09), 'ssbg7': (0xC2, 0x41, 0x0C),
    'row_mem_l3': (0x03, 0x69, 0xA1), 'ssbg_vlm': (0x1D, 0x4E, 0xD8),
    'row_mem_l2': (0x6D, 0x28, 0xD9), 'ssbg0': (0x0E, 0x74, 0x90), 'ssbg1': (0x1D, 0x4E, 0xD8),
    'ssbg2': (0x7C, 0x3A, 0xED), 'ssbg3': (0xC2, 0x41, 0x0C), 'ssbg_skill': (0x15, 0x80, 0x3D),
    'ssbg4': (0x0F, 0x76, 0x6E),
}
C_TXT, C_DIM, C_LINE = RGBColor(0x0F, 0x17, 0x2A), RGBColor(0x47, 0x55, 0x69), RGBColor(0xE2, 0xE8, 0xF0)
AR_WRITERS = {'n_moveit', 'ssact'}

DESC_FALLBACK = {
    'ss_mem_l2': '小脑·标杆回放：吃 ss_mem_share + n_skill_dict，回放固化标杆并出 ss_mem_field',
    'n_moveit': '原子技能意图 + 安全限制 → 段表 PlanSegments；只规划永不动作',
    'n_exec': 'L2 收口：读 l2_daemon 真值状态与最近事件做授权/闸/到位判定，不造数不下发',
    'ss_mem_l5': 'L5 记忆中枢：总装三层协同（L2/L3/L4 势场 → 意图 −∇Φ）',
}


def add_text(slide, x, y, w, h, text, size=10, bold=False, color=C_TXT, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, spacing=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, line in enumerate(str(text).split('\n')):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing:
            p.line_spacing = spacing
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        r.font.name = 'Microsoft YaHei'
    return tb


def box(slide, x, y, w, h, fill, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    sh.line.color.rgb = line or fill
    sh.line.width = Pt(0.6)
    sh.shadow.inherit = False
    return sh


def load_nodes(band_ids):
    N = json.load(open(CANVAS, encoding='utf-8'))['nodes']
    bands = {n['id']: n for n in N if n['type'] == 'row_bg'}
    idx = open(NODEDIR + '/_index.py', encoding='utf-8').read()
    out = []
    for bid in band_ids:
        b = bands[bid]
        inner = sorted([n for n in N if n['type'] != 'row_bg' and b['y'] <= n['y'] < b['y'] + b['h']],
                       key=lambda z: (z['y'], z['x']))
        for n in inner:
            m = re.search(r'["\']%s["\']\s*:\s*["\']([^"\']+)' % re.escape(n['id']), idx)
            mod = m.group(1).split('.')[-1] if m else ''
            f = '%s/%s.py' % (NODEDIR, mod)
            desc = src = ''
            pure = '-'
            if os.path.exists(f):
                t = open(f, encoding='utf-8').read()
                d = re.search(r"'desc'\s*:\s*'([^']*)'", t)
                desc = d.group(1) if d else DESC_FALLBACK.get(n['id'], '')
                s = re.search(r'^SOURCE\s*=\s*[\'"]([^\'"]+)', t, re.M)
                src = s.group(1) if s else ''
                p = re.search(r'^PURE\s*=\s*(\S+)', t, re.M)
                pure = 'True' if p and p.group(1).startswith('True') else 'False'
            out.append(dict(id=n['id'], name=n['name'], band=bid, band_name=b['name'],
                            desc=desc or DESC_FALLBACK.get(n['id'], ''),
                            src=src or (mod + '.py'), pure=pure))
    return out, bands


_HUMAN = (("层间链接 links", "层间连线"), ("真源", "来源文件"), ("口径", "计算方式"), ("UPH", "件/小时"),
          ("PURE", "内部算法"), ("in1", "输入1"), ("in2", "输入2"), ("in3", "输入3"),
          ("out1", "输出1"), ("out2", "输出2"), ("out3", "输出3"))


def human(t):
    """把节点自述里的内部说法换成人话(只在显示层替换, 不改节点代码与画布)。"""
    for a, b in _HUMAN:
        t = (t or "").replace(a, b)
    return t


def short(desc, n=54):
    d = re.sub(r'^\[[^\]]*\]\s*', '', desc or '').strip()
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


def lay_panorama(pr, layer, title, note, nodes, bands, band_ids, top_only=False, height=None):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    add_text(s, 0.50, 0.18, 12.4, 0.34,
             '%s 层功能全景 · %d 个节点，名称与画布一致' % (layer, len(nodes)), size=16, bold=True)
    add_text(s, 0.50, 0.54, 12.4, 0.42, note, size=8.0, color=C_DIM, spacing=1.15)
    y = 0.98
    CW, GAP, CH, PER = 1.746, 0.05, 0.40, 7
    for bid in band_ids:
        bn = bands[bid]['name']
        inner = [n for n in nodes if n['band'] == bid]
        col = RGBColor(*BAND_COL.get(bid, (0x47, 0x55, 0x69)))
        box(s, 0.50, y, 12.33, 0.19, RGBColor(*[min(255, c + 210) for c in BAND_COL.get(bid, (0x47, 0x55, 0x69))]),
            col, MSO_SHAPE.RECTANGLE)
        add_text(s, 0.56, y + 0.012, 12.2, 0.17, '%s（%d 个）' % (bn, len(inner)), size=7.4, bold=True, color=col)
        y += 0.21
        rows = [inner[i:i + PER] for i in range(0, len(inner), PER)]
        for j, row in enumerate(rows):
            for k, n in enumerate(row):
                cx = 0.50 + k * (CW + GAP)
                cy = y + j * (CH + 0.05)
                box(s, cx, cy, CW, CH, RGBColor(0xFA, 0xFB, 0xFD), col)
                add_text(s, cx + 0.05, cy + 0.02, CW - 0.10, CH - 0.04, n['name'], size=6.2,
                         color=C_TXT, anchor=MSO_ANCHOR.MIDDLE, spacing=0.95)
                if n['id'] in AR_WRITERS:
                    box(s, cx + CW - 0.34, cy + 0.02, 0.30, 0.14, RGBColor(0x16, 0xA3, 0x4A),
                        RGBColor(0x16, 0xA3, 0x4A))
                    add_text(s, cx + CW - 0.33, cy + 0.035, 0.28, 0.11, 'AR', size=5.6, bold=True,
                             color=RGBColor(0xFF, 0xFF, 0xFF), align=PP_ALIGN.CENTER)
        y += len(rows) * (CH + 0.05) + 0.03
    add_text(s, 0.50, min(y + 0.01, 6.95), 12.4, 0.26,
             '合计 %d 个 · 与画布 state_space_obs.json 逐字一致，可用 tools/verify_solution_deck.py 自动比对。' % len(nodes),
             size=7.6, color=C_DIM)
    return s, y


def lay_table(pr, layer, chunk, part, total_parts, y0=0.82):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    add_text(s, 0.42, 0.16, 12.5, 0.32,
             '%s 层功能说明表（%d/%d）· 逐节点' % (layer, part, total_parts), size=15, bold=True)
    add_text(s, 0.42, 0.50, 12.5, 0.22,
             '每一行是一个功能节点：名称照画布原样，说明取该节点代码里写的第一句功能描述，'
             '最后一列给出它的计算代码位置，以及内部算法在当前这一拍是否真的参与运算。',
             size=7.4, color=C_DIM)
    cols = [('所属功能带', 1.75), ('节点名称', 3.20), ('节点代号', 1.16),
            ('这个节点负责什么（取自代码里的功能说明）', 4.40), ('计算代码 / 内部算法', 1.55)]
    gx, gy, rowh = 0.42, y0, 0.315 if len(chunk) > 10 else 0.40
    x = gx
    for name, w in cols:
        box(s, x, gy, w, 0.24, RGBColor(0x0B, 0x1B, 0x2B), shape=MSO_SHAPE.RECTANGLE)
        add_text(s, x + 0.05, gy + 0.04, w - 0.08, 0.17, name, size=7.0, bold=True,
                 color=RGBColor(0xFF, 0xFF, 0xFF))
        x += w
    y = gy + 0.24
    for i, n in enumerate(chunk):
        x = gx
        fill = RGBColor(0xF7, 0xF9, 0xFC) if i % 2 == 0 else RGBColor(0xFF, 0xFF, 0xFF)
        vals = [n['band_name'].replace('L2 基础辅助功能 · ', '').replace('L2 记忆 · ', '记忆 · ')
                        .replace('L3 高级自动功能 · ', '').replace('L3 记忆 · ', '记忆 · ')
                        .replace('L4 专家自主功能 · ', '').replace('L4 记忆 · ', '记忆 · ')
                        .replace('🧠 大模型层 · ', ''),
                n['name'], n['id'], human(short(n['desc'])),
                '%s ／ %s' % (os.path.basename(n['src']),
                              '内部算法参与运算' if n['pure'] == 'True' else '本拍仅转发数据')]
        for j, (cname, w) in enumerate(cols):
            box(s, x, y, w, rowh, fill, C_LINE, MSO_SHAPE.RECTANGLE)
            col = C_TXT
            if j == 0:
                col = RGBColor(*BAND_COL.get(n['band'], (0x47, 0x55, 0x69)))
            if j == 4:
                col = RGBColor(0x15, 0x80, 0x3D) if n['pure'] == 'True' else C_DIM
            add_text(s, x + 0.045, y + 0.02, w - 0.09, rowh - 0.03, vals[j],
                     size=6.5, bold=(j == 1), color=col, anchor=MSO_ANCHOR.MIDDLE, spacing=0.95)
            x += w
        y += rowh
    return s


def main():
    pr = Presentation(DECK)
    reset_deck(pr, keep=7)
    total = {}
    for layer, band_ids, title, note in LAYERS:
        nodes, bands = load_nodes(band_ids)
        total[layer] = len(nodes)
        if layer == 'L3':                     # 只有 4 个节点: 全景 + 表放一页
            s, yend = lay_panorama(pr, layer, title, note, nodes, bands, band_ids)
            # 同一页下半部分放功能表
            cols = [('节点名称', 3.30), ('节点代号', 1.10), ('这个节点负责什么（取自代码里的功能说明）', 6.20),
                    ('计算代码 / 内部算法', 1.46)]
            gy = max(yend + 0.12, 3.2)
            x = 0.50
            for name, w in cols:
                box(s, x, gy, w, 0.24, RGBColor(0x0B, 0x1B, 0x2B), shape=MSO_SHAPE.RECTANGLE)
                add_text(s, x + 0.05, gy + 0.04, w - 0.08, 0.17, name, size=7.0, bold=True,
                         color=RGBColor(0xFF, 0xFF, 0xFF))
                x += w
            y = gy + 0.24
            for i, n in enumerate(nodes):
                x = 0.50
                fill = RGBColor(0xF7, 0xF9, 0xFC) if i % 2 == 0 else RGBColor(0xFF, 0xFF, 0xFF)
                vals = [n['name'], n['id'], human(short(n['desc'], 78)),
                        '%s ／ %s' % (os.path.basename(n['src']),
                                      '内部算法参与运算' if n['pure'] == 'True' else '本拍仅转发数据')]
                for j, (cname, w) in enumerate(cols):
                    box(s, x, y, w, 0.34, fill, C_LINE, MSO_SHAPE.RECTANGLE)
                    add_text(s, x + 0.05, y + 0.02, w - 0.09, 0.30, vals[j], size=6.8, bold=(j == 0),
                             color=(RGBColor(0x15, 0x80, 0x3D) if (j == 3 and n['pure'] == 'True') else C_TXT),
                             anchor=MSO_ANCHOR.MIDDLE, spacing=0.95)
                    x += w
                y += 0.34
            continue
        if layer == 'L2':                     # L2: 两页连线图 (内部 + 层外) 代替原全景页, 后面接功能表
            import l2_wiring
            _c = l2_wiring.counts()
            s1 = pr.slides.add_slide(pr.slide_layouts[6])       # 标题先写, 保证大纲/首框就是标题
            add_text(s1, 0.50, 0.13, 12.4, 0.32,
                     '基础层内部连线 · %d 个功能节点之间共 %d 条连线，另有 %d 个上层节点接入（%d 条连线）'
                     % (_c['l2_nodes'], _c['l2_edges'], _c['l3_nodes'], _c['l3_edges']),
                     size=15, bold=True)
            add_text(s1, 0.50, 0.50, 12.4, 0.40,
                     '读法：左→右 = 数据流方向（记忆 → 感知 → 融合 → 小模型 → 决策 → 技能 → 执行）；每带标题括号里 = 该带节点数 · 发出连线数。'
                     '顶部 L3 只放与 L2 真有连线的 3 个节点（VLM 编码器 / 长程规划记忆 / Flow-Matching 动作头）——'
                     'L3 的 VLM 编码收 L2 感知的 token（青虚线），动作头与前馈/规划接通（橙实线）。',
                     size=7.2, color=C_DIM, spacing=1.1)
            i1 = l2_wiring.draw_core_page(s1)
            s2 = pr.slides.add_slide(pr.slide_layouts[6])
            add_text(s2, 0.50, 0.13, 12.4, 0.32,
                     'L2 ↔ 层外节点连线 · %d 个节点 / %d 条连线（L5 / L4 / 数据源 / 可视化 / 层外）'
                     % (_c['ext_nodes'], _c['ext_edges']), size=15, bold=True)
            add_text(s2, 0.50, 0.50, 12.4, 0.30,
                     '只画与 L2 真有连线的层外节点，一条不漏；右侧 L2 节点按被连条数排序；箭头 = 数据流向。'
                     '参数级细节见后续功能表。', size=7.2, color=C_DIM)
            i2 = l2_wiring.draw_ext_page(s2)
            print('L2 连线页: 内部 %d 条 / L3 %d 条 / 层外 %d 节点 %d 条' % (
                i1['l2_edges'], i1['l3_edges'], i2['ext_nodes'], i2['ext_edges']))
        else:
            lay_panorama(pr, layer, title, note, nodes, bands, band_ids)
        if len(nodes) > 20:
            half = (len(nodes) + 1) // 2
            lay_table(pr, layer, nodes[:half], 1, 2)
            lay_table(pr, layer, nodes[half:], 2, 2)
        else:
            lay_table(pr, layer, nodes, 1, 1)
    pr.save(DECK)
    print('层节点页已写入母版 %d 页 · %s' % (len(pr.slides._sldIdLst),
                                     ' · '.join('%s %d 个' % (k, v) for k, v in total.items())))


if __name__ == '__main__':
    main()
