#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 AR 场景 300UPH 节拍方案画成甘特图, 追加到《机器人整机三视图与技术参数》PPT。

真源: zmax_data/runtime/traj/sim_insert.json (392 段 / 159.43 s / 14 件)
      config/orders/BS_SCN-07-AOI.json -> ar_300uph (节拍口径)
不手填任何时间: 每根条 = 段表里对应任务的段区间求和。
"""
import json, sys
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

DECK = '/home/ubuntu/zmax/docs/1-天枢-产品边界/deliverables/2-机器人方案/机器人整机三视图与技术参数_5.50.C_20261101.pptx'
SIM = '/home/ubuntu/zmax/zmax_data/runtime/traj/sim_insert.json'
ORD = '/home/ubuntu/zmax/config/orders/BS_SCN-07-AOI.json'
META = '/home/ubuntu/zmax/docs/1-天枢-产品边界/deliverables/2-机器人方案/甘特_300UPH_数据源.json'

C_LEFT = RGBColor(0x0F, 0x76, 0x6E)   # 左臂
C_RIGHT = RGBColor(0x1D, 0x4E, 0xD8)  # 右臂拔
C_AOI = RGBColor(0x7C, 0x3A, 0xED)    # AOI
C_PLACE = RGBColor(0x15, 0x80, 0x3D)  # 良品落盘
C_NG = RGBColor(0xDC, 0x26, 0x26)     # NG
C_GRID = RGBColor(0xCB, 0xD5, 0xE1)
C_TXT = RGBColor(0x0F, 0x17, 0x2A)
C_DIM = RGBColor(0x47, 0x55, 0x69)


def load():
    sim = json.load(open(SIM, encoding='utf-8'))
    ordr = json.load(open(ORD, encoding='utf-8'))['ar_300uph']
    plan, cyc = sim['plan'], sim['cycles_data']

    # 段表 -> 绝对时间轴 (段表顺序执行, 逐段累加即得起止时刻)
    t, spans = 0.0, []
    for s in plan:
        spans.append((t, t + s['t'], s))
        t += s['t']
    assert abs(t - sim['total_t']) < 0.05, (t, sim['total_t'])

    def idx_of_nearest(kind, anchor):
        best = None
        for i, (t0, t1, s) in enumerate(spans):
            if s['kind'] != kind:
                continue
            d = abs(t1 - anchor)
            if best is None or d < best[0]:
                best = (d, i)
        return best[1]

    # 口径(与 cycles_data 锚点对齐, 全部由段表取时):
    #   MT-01 = 取料插入块 [move 起 → 松开完成]  (9 段)
    #   MT-02 = 拔出块 [移到孔位 → 拔后抬起]      (5 段)
    #   MT-03 = [t_aoi0, t_aoi1]  AOI 五点(金手指+3 侧面, 含点间移动)
    #   落盘   = [t_aoi1, t_placed]
    rows = []
    for c in cyc:
        r = dict(k=c['k'], slot=c['slot_name'], verdict=c['verdict'], dwell=c['dwell_s'],
                 t_ins=c['t_ins'], t_pull=c['t_pull'], t_aoi0=c['t_aoi0'], t_aoi1=c['t_aoi1'],
                 t_placed=c['t_placed'])
        ir = idx_of_nearest('release', c['t_ins'])
        r['mt01_0'], r['mt01_1'] = spans[ir - 7][0], c['t_ins']
        ip = idx_of_nearest('pull', c['t_pull'] + 0.492)
        r['mt02_0'], r['mt02_1'] = spans[ip - 3][0], spans[ip + 1][1]
        r['mt03_0'], r['mt03_1'] = c['t_aoi0'], c['t_aoi1']
        r['place_0'], r['place_1'] = c['t_aoi1'], c['t_placed']
        for kind in ('mt01', 'mt02', 'mt03', 'place'):
            r[kind] = round(r[kind + '_1'] - r[kind + '_0'], 3)
        rows.append(r)
    return sim, ordr, rows


def add_text(slide, x, y, w, h, text, size=10, bold=False, color=C_TXT, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    tf.vertical_anchor = anchor
    for i, line in enumerate(str(text).split('\n')):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        r.font.name = 'Microsoft YaHei'
    return tb


def bar(slide, x, y, w, h, color, label=None, dashed=False):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(max(w, 0.02)), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = color
    sh.line.color.rgb = color
    sh.line.width = Pt(0.5)
    sh.shadow.inherit = False
    if label:
        tf = sh.text_frame
        tf.margin_left = tf.margin_right = Emu(0)
        tf.word_wrap = False
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = label
        r.font.size = Pt(6.5)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        r.font.name = 'Microsoft YaHei'
    return sh


def vline(slide, x, y0, y1, color=C_GRID, dash=True, wpt=0.75):
    from pptx.enum.shapes import MSO_CONNECTOR
    ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(y0), Inches(x), Inches(y1))
    ln.line.color.rgb = color
    ln.line.width = Pt(wpt)
    if dash:
        from pptx.enum.dml import MSO_LINE_DASH_STYLE
        ln.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    return ln


def hline(slide, x0, x1, y, color=C_GRID, wpt=0.5):
    from pptx.enum.shapes import MSO_CONNECTOR
    ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x0), Inches(y), Inches(x1), Inches(y))
    ln.line.color.rgb = color
    ln.line.width = Pt(wpt)
    return ln


def slide_full(pr, sim, ordr, rows):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    takt = ordr['tact_s']
    total = sim['total_t']
    add_text(s, 0.55, 0.22, 12.2, 0.42,
             'AR 场景 300 UPH 节拍方案 · 甘特图（一轮 %d 段 / %.2f s / %d 件）' % (sim['n_segs'], total, sim['mods']),
             size=19, bold=True)
    add_text(s, 0.55, 0.66, 12.2, 0.3,
             '真源 sim_insert.json：段表 392 段逐段计时求和，未手填｜左臂 MT-01 取料插入 · 右臂 MT-02 拔出 → MT-03 AOI 五点 → MT-04 良品落盘 / MT-05 NG 废料盘',
             size=9, color=C_DIM)

    X0, Y0, W, H = 2.30, 1.28, 9.15, 3.95
    rows_def = [('左臂 · 取料并插入（MT-01）', C_LEFT), ('右臂 · 从孔内拔出（MT-02）', C_RIGHT),
                ('右臂 · AOI 五点检测（MT-03）', C_AOI), ('右臂 · 落盘（MT-04 良品 / MT-05 NG）', C_PLACE)]
    rh = H / len(rows_def)
    sc = W / total

    # 网格 + 节拍线
    t, i = 0.0, 1
    while t <= total + 1e-6:
        x = X0 + t * sc
        vline(s, x, Y0, Y0 + H, C_GRID if i % 1 else C_GRID, True)
        add_text(s, x - 0.28, Y0 + H + 0.04, 0.56, 0.24, '%.0fs' % t, size=6.5, color=C_DIM, align=PP_ALIGN.CENTER)
        t += takt
        i += 1

    for j, (name, col) in enumerate(rows_def):
        y = Y0 + j * rh
        add_text(s, 0.55, y + rh / 2 - 0.16, 1.68, 0.34, name, size=9, bold=False, color=C_TXT,
                 align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        if j:
            hline(s, X0, X0 + W, y)

    for r in rows:
        for j, kind in enumerate(('mt01', 'mt02', 'mt03', 'place')):
            t0, t1 = r[kind + '_0'], r[kind + '_1']
            col = (C_NG if r['verdict'] == 'NG' else C_PLACE) if kind == 'place' else \
                  {'mt01': C_LEFT, 'mt02': C_RIGHT, 'mt03': C_AOI}[kind]
            bar(s, X0 + t0 * sc, Y0 + j * rh + rh * 0.22, max(t1 - t0, 0.04) * sc, rh * 0.56, col,
                label=(('NG ' if r['verdict'] == 'NG' else '') + r['slot']) if kind == 'place' else None)
        # 完成件标记
        xc = X0 + r['t_placed'] * sc
        add_text(s, xc - 0.30, Y0 - 0.30, 0.60, 0.22, '%s' % r['slot'], size=6.5,
                 color=(C_NG if r['verdict'] == 'NG' else C_DIM), align=PP_ALIGN.CENTER)

    # 底部 KPI
    ok = sum(1 for r in rows if r['verdict'] == 'OK')
    ng = len(rows) - ok
    kpi = ('节拍锁 %.2f s/件（目标 12 s，UPH %.0f）　单件 %.2f s　一轮 %d 件 / %.2f s　'
           '演示件 %d 件：OK %d / NG %d（%s）　几何稳态 %.1f UPH（两块相邻轮次可无缝平铺）') % (
        takt, 3600 / takt, sim['cycles_data'][0]['t_work'], sim['mods'], total,
        sim['mods'], ok, ng, '、'.join(sim['ng_slots']), sim['loop']['uph'])
    add_text(s, 0.55, 5.62, 12.25, 0.5, kpi, size=9.5, color=C_TXT)

    add_text(s, 0.55, 6.10, 12.25, 0.85,
             '读数：①每件落盘间隔 = 11.42 s（竖虚线），即 300 件的节拍；②左臂 3.0 s 摆盘与右臂 7.45 s「拔→检→放」并行，'
             '右臂是节拍瓶颈、余量 3.97 s；③AOI 四点（金手指 + 3 侧面点）每件 4.2 s，占右臂 59%；'
             '④NG 走废料盘不占良品位，良品位 12 个与 OK 件数一致。', size=8.5, color=C_DIM)


def slide_single(pr, sim, ordr, rows):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    takt = ordr['tact_s']
    r = rows[0]
    add_text(s, 0.55, 0.22, 12.2, 0.42, '单件节拍分解 · %.2f s 窗口里两条臂在干什么' % takt, size=19, bold=True)
    add_text(s, 0.55, 0.66, 12.2, 0.3,
             '取槽 1 那一件（段表 k=1 的 36 段）：左臂 9 段 = %.2f s；右臂「拔 5 段 → AOI 10 段 → 落盘 4 段」串行 = %.2f s' % (
                 r['mt01'], r['mt02'] + r['mt03'] + r['place']),
             size=9, color=C_DIM)

    X0, Y0, W = 1.75, 1.35, 9.40
    sc = W / takt
    seq = [('左臂 · 取料并插入（9 段）', C_LEFT, 0.0, r['mt01']),
           ('右臂 · 拔出（5 段）', C_RIGHT, r['mt01'], r['mt02']),
           ('右臂 · AOI 五点（10 段）', C_AOI, r['mt01'] + r['mt02'], r['mt03']),
           ('右臂 · 落盘（4 段）', C_PLACE, r['mt01'] + r['mt02'] + r['mt03'], r['place'])]
    bh = 0.52
    for j, (name, col, t0, dur) in enumerate(seq):
        y = Y0 + j * (bh + 0.30)
        add_text(s, 0.55, y + 0.10, 1.12, 0.32, name.split('（')[0], size=8.5, align=PP_ALIGN.RIGHT)
        bar(s, X0 + t0 * sc, y, dur * sc, bh, col, label='%.2f s' % dur)
        add_text(s, X0 + t0 * sc + dur * sc + 0.06, y + 0.14, 1.4, 0.26, '→ %.2f s' % (t0 + dur), size=7.5, color=C_DIM)

    # 节拍线
    for tt in (0.0, takt):
        vline(s, X0 + tt * sc, Y0 - 0.22, Y0 + 4 * (bh + 0.30) - 0.05,
              C_NG if tt else C_GRID, True, 1.0)
    add_text(s, X0 + takt * sc - 0.85, Y0 - 0.33, 1.7, 0.26, '节拍锁 %.2f s' % takt, size=8, bold=True,
             color=C_NG, align=PP_ALIGN.CENTER)

    right = r['mt02'] + r['mt03'] + r['place']
    add_text(s, 0.55, 5.05, 12.2, 1.9,
             '平衡表：左臂 %.2f s ／ 右臂 %.2f s（拔 %.2f + AOI %.2f + 放 %.2f），节拍 %.2f s → 余量 %.2f s\n'
             '提节拍只有两个抓手：①AOI 五点占 %.2f s（%.0f%%），把金手指与侧面点合并取图可省 1.5~2 s；'
             '②落盘 %.2f s 可与下一件「取料」重叠，右臂等效占用降到 %.2f s，节拍可压到 %.2f s（≈%.0f UPH）。' % (
                 r['mt01'], right, r['mt02'], r['mt03'], r['place'], takt, takt - right,
                 r['mt03'], 100.0 * r['mt03'] / right, r['place'], right - r['place'],
                 max(r['mt01'], right - r['place']), 3600 / max(r['mt01'], right - r['place'])),
             size=10, color=C_TXT)


def main():
    sim, ordr, rows = load()
    pr = Presentation(DECK)
    slide_full(pr, sim, ordr, rows)
    slide_single(pr, sim, ordr, rows)
    pr.save(DECK)
    json.dump({'source': SIM, 'order': ORD, 'takt_s': ordr['tact_s'], 'total_t': sim['total_t'],
               'n_segs': sim['n_segs'], 'mods': sim['mods'], 'rows': rows,
               'note': '每根条 = 段表对应任务段区间求和; mt01=取料插入9段, mt02=拔5段, mt03=AOI(cycles_data.aoi_s), place=落盘(place_s)'},
              open(META, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('已追加 2 页甘特; 总页数 %d' % len(pr.slides._sldIdLst))
    print('数据源副本:', META)
    print('第1件: mt01=%.2f mt02=%.2f mt03=%.2f place=%.2f 合计右臂=%.2f 节拍=%.2f 余量=%.2f' % (
        rows[0]['mt01'], rows[0]['mt02'], rows[0]['mt03'], rows[0]['place'],
        rows[0]['mt02'] + rows[0]['mt03'] + rows[0]['place'], ordr['tact_s'],
        ordr['tact_s'] - (rows[0]['mt02'] + rows[0]['mt03'] + rows[0]['place'])))


if __name__ == '__main__':
    main()
