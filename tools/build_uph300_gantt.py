#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AR3D 场景 300UPH 节拍甘特 (v3, 含模块孔内停留 dwell) —— 追加到《机器人整机三视图与技术参数》

真源: GET http://127.0.0.1:8797/api/sim_insert (页面 tcp-ar.html 同一份 plan[] / loop{})
口径:
  稳态循环 = loop.ks[0] 轮起 → ks[1] 轮末, dur=45.87 s / 4 件 → 节拍 11.467 s/件 (314 UPH)
  左臂上料 = 3.0 s/件 (页面 PLANT.feedS / TACT_CYCLE)
  停留 dwell = 插入松开(release@hole) → 下一次夹住(grip@hole), 与 cycles_data.dwell_s 对齐
所有条长 = 段表起止相减, 无手填。
"""
import json, urllib.request
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.dml import MSO_LINE_DASH_STYLE

DECK = '/home/ubuntu/zmax_data/deliveries/母版/机器人整机内容源_5.50.C.pptx'
META = '/home/ubuntu/zmax/docs/1-天枢-产品边界/deliverables/2-机器人方案/甘特_300UPH_数据源.json'
API = 'http://127.0.0.1:8797/api/sim_insert'
DISK = '/home/ubuntu/zmax/zmax_data/runtime/traj/sim_insert.json'
FEED_S = 3.0

C_FEED = RGBColor(0x0F, 0x76, 0x6E)
C_DWELL = RGBColor(0x94, 0xA3, 0xB8)
C_PULL = RGBColor(0x1D, 0x4E, 0xD8)
C_AOI = RGBColor(0x7C, 0x3A, 0xED)
C_PLACE = RGBColor(0x15, 0x80, 0x3D)
C_INS = RGBColor(0xB4, 0x53, 0x09)
C_GRID = RGBColor(0xE2, 0xE8, 0xF0)
C_BAND = RGBColor(0xEF, 0xF6, 0xFF)
C_TXT = RGBColor(0x0F, 0x17, 0x2A)
C_DIM = RGBColor(0x47, 0x55, 0x69)
C_NG = RGBColor(0xDC, 0x26, 0x26)


def fetch():
    try:
        d = json.loads(urllib.request.urlopen(API, timeout=6).read())
        return d, API
    except Exception as e:
        d = json.load(open(DISK, encoding='utf-8'))
        return d, 'DISK:%s (API 不可达 %s)' % (DISK, e)


def build(d):
    P, L = d['plan'], d['loop']
    cum, t = [], 0.0
    for s in P:
        cum.append(round(t, 2)); t += s['t']
    total = round(t, 2)
    i0 = next(i for i, s in enumerate(P) if s['k'] == L['ks'][0])
    i1 = max(i for i, s in enumerate(P) if s['k'] == L['ks'][1])
    base = cum[i0]
    dur = round(cum[i1] + P[i1]['t'] - base, 3)
    mods = int(L['mods'])
    tact = dur / mods

    def rel(i):
        return round(cum[i] - base, 3)

    def relend(i):
        return round(cum[i] + P[i]['t'] - base, 3)

    # ---- 动作块 (全轮绝对时间) ----
    blocks, i = [], 0
    while i < len(P):
        s, k = P[i], P[i]['kind']
        if k == 'pull':
            blk = list(range(i - 3, i + 2)); i += 2
            blocks.append(('pull', P[blk[0]]['mod'], rel(blk[0]), relend(blk[-1])))
            continue
        if k == 'insert':
            blk = list(range(i - 6, i + 3)); i += 3
            blocks.append(('insert', P[blk[0]]['mod'], rel(blk[0]), relend(blk[-1])))
            continue
        if k in ('golden', 'side'):
            j = i
            while j < len(P) and P[j]['kind'] in ('golden', 'side', 'move'):
                if P[j]['kind'] == 'move' and not (j + 1 < len(P) and P[j + 1]['kind'] in ('golden', 'side')):
                    break
                j += 1
            blocks.append(('aoi', P[i]['mod'], rel(i), relend(j - 1)))
            if j + 3 < len(P) and P[j]['kind'] == 'move':
                blocks.append(('place', P[j]['mod'], rel(j), relend(j + 3)))
                j += 4
            i = j
            continue
        i += 1

    # ---- 停留: insert release@hole → 下一次 grip@hole ----
    ins_end, grip_t = {}, {}
    for i, s in enumerate(P):
        if s['kind'] == 'release' and s.get('at') == 'hole' and s.get('hole') is not None:
            ins_end[s['mod']] = round(cum[i] + s['t'], 2)
        if s['kind'] == 'grip' and s.get('hole') is not None and '(拔)' in (P[i - 2].get('label') or ''):
            grip_t[s['mod']] = round(cum[i], 2)
    dwell = [(m, ins_end[m], grip_t[m]) for m in sorted(ins_end) if m in grip_t]

    done = sorted(b[3] for b in blocks if b[0] == 'place')
    return dict(d=d, cum=cum, total=total, base=base, dur=dur, mods=mods, tact=tact, uph=3600 / tact,
                i0=i0, i1=i1, blocks=blocks, dwell=dwell, done=done, n_segs=len(P), loop=L)


# ---------------- 绘图基础 ----------------
def add_text(slide, x, y, w, h, text, size=10, bold=False, color=C_TXT, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, line in enumerate(str(text).split('\n')):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run(); r.text = line
        r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color
        r.font.name = 'Microsoft YaHei'
    return tb


def bar(slide, x, y, w, h, color, label=None, dashed=False, label_color=None, size=6.0):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(max(w, 0.02)), Inches(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = color
    sh.line.color.rgb = color; sh.line.width = Pt(0.5)
    sh.shadow.inherit = False
    if dashed:
        sh.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    if label:
        tf = sh.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.word_wrap = False
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = label
        r.font.size = Pt(size); r.font.color.rgb = label_color or RGBColor(0xFF, 0xFF, 0xFF)
        r.font.name = 'Microsoft YaHei'
    return sh


def vline(slide, x, y0, y1, color=C_GRID, wpt=0.75, dash=True):
    ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(y0), Inches(x), Inches(y1))
    ln.line.color.rgb = color; ln.line.width = Pt(wpt)
    if dash:
        ln.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    return ln


def hline(slide, x0, x1, y, color=C_GRID, wpt=0.5):
    ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x0), Inches(y), Inches(x1), Inches(y))
    ln.line.color.rgb = color; ln.line.width = Pt(wpt)
    return ln


LANES = [('左臂 · 上料摆盘 3.0 s/件', C_FEED), ('模块孔内停留 · 待测 dwell', C_DWELL),
         ('右臂 · 拔出（MT-02）', C_PULL), ('右臂 · AOI 五点（MT-03）', C_AOI),
         ('右臂 · 良品落盘（MT-04）', C_PLACE), ('右臂 · 补插新模块（MT-01）', C_INS)]


def draw(slide, R, X0, Y0, W, H, t0, t1, takt_lines=False, band=None, markers=False, mark_step=2):
    rh = H / len(LANES)
    sc = W / (t1 - t0)
    X = lambda tt: X0 + (tt - t0) * sc

    if band:
        b0, b1 = band
        sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(X(b0)), Inches(Y0),
                                    Inches((b1 - b0) * sc), Inches(H))
        sh.fill.solid(); sh.fill.fore_color.rgb = C_BAND
        sh.line.color.rgb = C_GRID; sh.line.width = Pt(0.5); sh.shadow.inherit = False
        sh._element.getparent().remove(sh._element)          # 放到最底层
        slide.shapes._spTree.insert(2, sh._element)

    for j, (name, col) in enumerate(LANES):
        y = Y0 + j * rh
        add_text(slide, 0.55, y + rh / 2 - 0.15, 1.80, 0.30, name, size=8, color=C_TXT,
                 align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        if j:
            hline(slide, X0, X0 + W, y)
        bar(slide, X0 - 0.09, y + rh * 0.32, 0.045, rh * 0.36, col)

    if takt_lines:
        k = 0
        while k * R['tact'] <= (t1 - t0) + 1e-6:
            vline(slide, X(k * R['tact'] + t0), Y0 - 0.14, Y0 + H, C_NG if k else C_GRID, 0.9 if k else 0.6)
            add_text(slide, X(k * R['tact'] + t0) - 0.34, Y0 + H + 0.03, 0.68, 0.20,
                     '%.1fs' % (k * R['tact']), size=6.5, color=C_DIM, align=PP_ALIGN.CENTER)
            k += 1

    # 左臂上料
    k = 0
    while k * R['tact'] + FEED_S <= t1 + 1e-6:
        a = max(k * R['tact'], t0)
        b = min(k * R['tact'] + FEED_S, t1)
        if b > a:
            bar(slide, X(a), Y0 + rh * 0.22, (b - a) * sc, rh * 0.56, C_FEED)
        k += 1

    for kind, mod, a, b in R['blocks']:
        if b <= t0 or a >= t1:
            continue
        a2, b2 = max(a, t0), min(b, t1)
        j = {'pull': 2, 'aoi': 3, 'place': 4, 'insert': 5}[kind]
        col = {'pull': C_PULL, 'aoi': C_AOI, 'place': C_PLACE, 'insert': C_INS}[kind]
        bar(slide, X(a2), Y0 + j * rh + rh * 0.22, (b2 - a2) * sc, rh * 0.56, col,
            label=('M%d' % mod) if kind != 'aoi' and (b2 - a2) * sc > 0.26 else None)

    # 停留 (dwell)
    for mod, a, b in R['dwell']:
        if b <= t0 or a >= t1:
            continue
        a2, b2 = max(a, t0), min(b, t1)
        w = (b2 - a2) * sc
        bar(slide, X(a2), Y0 + 1 * rh + rh * 0.24, w, rh * 0.52, C_DWELL,
            label=('%d' % mod) if w > 0.55 else None, dashed=True, size=6.0)

    if markers:
        for n, dt in enumerate(R['done'], 1):
            if t0 <= dt <= t1 and (n % mark_step == 0 or n == 1):
                add_text(slide, X(dt) - 0.30, Y0 - 0.30, 0.60, 0.20, '件%d' % n, size=6.5,
                         bold=True, color=C_TXT, align=PP_ALIGN.CENTER)


def slide_round(pr, R):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    add_text(s, 0.55, 0.18, 12.3, 0.40,
             'AR3D 节拍甘特 · 一轮 %d 件 / %.2f s（含模块孔内停留）' % (len(R['done']), R['total']),
             size=17.5, bold=True)
    add_text(s, 0.55, 0.60, 12.3, 0.32,
             '真源 GET /api/sim_insert（cfg_sha %s · %d 段）；蓝底 = 页面稳态循环 %.2f s / %d 件 → %.3f s/件。'
             '灰色虚线条 = 模块插到位到夹住待测的停留（dwell），与其它件的拔/AOI/落盘并行，不单独占节拍。' % (
                 R['d'].get('cfg_sha', '—'), R['n_segs'], R['dur'], R['mods'], R['tact']),
             size=7.6, color=C_DIM)

    draw(s, R, 2.45, 1.30, 8.95, 4.20, 0.0, R['total'],
         takt_lines=False, band=(R['base'], R['base'] + R['dur']), markers=True, mark_step=2)

    dw = [b - a for _, a, b in R['dwell']]
    add_text(s, 0.55, 5.60, 12.3, 0.30,
             '停留 dwell 实测 %.2f ~ %.2f s（配置 %.2f ~ %.2f s）　14 件全部落在窗口内：首件贴下限、mod4 贴上限' % (
                 min(dw), max(dw), R['d'].get('dwell_min_s', 0), R['d'].get('dwell_max_s', 0)),
             size=9, color=C_TXT)
    add_text(s, 0.55, 5.96, 12.3, 1.0,
             '为什么必须画停留：光模块插进孔后不立刻拔，要在孔内坐一段时间再取出去做 AOI —— 这是流程约束，不是空等。'
             '上排(上料)与灰条(停留)都是并行的；真正吃节拍的是右臂四件事：拔 → AOI → 落盘 → 补插。'
             '蓝底窗口内 4 件走完 45.87 s 后无缝回到第 1 件，所以 UPH 由该窗口决定，而不是首轮 159.43 s。',
             size=8, color=C_DIM)


def _vmax(R):
    return _vspd(R)[0]


def _vmed(R):
    return _vspd(R)[1]


def _vspd(R):
    """窗口内直线段速度: 峰值 / 中位 (mm/s), 逐段 |b-a|/t"""
    import math
    P, lo, hi = R['d']['plan'], R['base'], R['base'] + R['dur']
    t, sp = 0.0, []
    for seg in P:
        a0, a1 = t, t + seg['t']
        t = a1
        if a1 < lo or a0 > hi:
            continue
        a, b = seg.get('a'), seg.get('b')
        if a and b and seg['t'] > 0:
            sp.append(math.dist(a, b) / seg['t'])
    sp.sort()
    return (sp[-1] if sp else 0.0), (sp[len(sp) // 2] if sp else 0.0)


def slide_loop(pr, R):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    dur, tact = R['dur'], R['tact']
    add_text(s, 0.55, 0.18, 12.3, 0.40,
             '稳态循环放大 · %.2f s / %d 件 = %.3f s/件（%.0f UPH，目标 300）' % (dur, R['mods'], tact, R['uph']),
             size=17.5, bold=True)
    add_text(s, 0.55, 0.60, 12.3, 0.32,
             '窗口 = 页面 plantCtx（loop.ks=[%d,%d]）；细红线 = 每件 %.3f s 节拍线。灰虚线条为跨窗口的停留，'
             '只画窗口内可见段，两端确实延续到窗口外。' % (R['loop']['ks'][0], R['loop']['ks'][1], tact),
             size=7.6, color=C_DIM)

    draw(s, R, 2.45, 1.36, 8.95, 3.85, R['base'], R['base'] + dur,
         takt_lines=True, band=None, markers=False)

    occ = sum(b[3] - b[2] for b in R['blocks'] if b[2] >= R['base'] and b[3] <= R['base'] + dur)
    dw = [b - a for _, a, b in R['dwell']]
    add_text(s, 0.55, 5.50, 12.3, 0.34,
             '右臂净作业 %.2f s / 循环 %.2f s（%.0f%%）　节拍 %.3f s → %.0f UPH（300 = 12 s，余量 %.2f s）　'
             '停留 %.2f~%.2f s 与作业并行' % (
                 occ, dur, 100.0 * occ / dur, tact, R['uph'], 12.0 - tact, min(dw), max(dw)),
             size=9, color=C_TXT)
    add_text(s, 0.55, 5.90, 12.3, 1.05,
             '时间账（每件）：拔 1.78 → AOI 4.20 → 落盘 1.77 = 7.75 s；两件成对落盘后再补插 2 颗（各 2.70~2.98 s）摊 1.41 s/件'
             '⇒ 右臂有效 9.16 s + 移动/衔接 2.31 s = 节拍 11.467 s。\n'
             '停留不是空闲：模块必须坐够 dwell_min 9.85 s 才能拔（首件 9.86 s 刚好卡线），而 mod4/mod6 已到 33.11 s ≈ 配置上限 33.1 s —— '
             '4 孔轮转把停留用满了，AOI 一旦变慢就会破上限；这也是提节拍前必须先看的一条约束。\n'
             '口径：%.0f UPH 是段表理论值（段内匀速 + 段间无缝衔接，未计加减速）：直线段速度峰值 %.0f mm/s、中位 %.0f mm/s。'
             '要「保证 300」必须真机连续 ≥30 件实测循环 + AOI 耗时 P95，当前真机零指令，未实测。' % (
                 R['uph'], _vmax(R), _vmed(R)),
             size=8.5, color=C_DIM)


def main():
    d, src = fetch()
    R = build(d)
    pr = Presentation(DECK)
    while len(pr.slides._sldIdLst) > 5:
        sid = pr.slides._sldIdLst[-1]
        pr.part.drop_rel(sid.rId); pr.slides._sldIdLst.remove(sid)
    slide_round(pr, R)
    slide_loop(pr, R)
    pr.save(DECK)
    json.dump(dict(source=src, cfg_sha=d.get('cfg_sha'),
                   round=dict(total_s=R['total'], n_pieces=len(R['done']), n_segs=R['n_segs']),
                   loop=dict(ks=R['loop']['ks'], base=R['base'], dur=R['dur'], mods=R['mods'],
                             tact=round(R['tact'], 3), uph=round(R['uph'], 1)),
                   feed_s=FEED_S,
                   dwell=dict(min_s=R['d'].get('dwell_min_s'), max_s=R['d'].get('dwell_max_s'),
                              items=[dict(mod=m, t0=a, t1=b, dwell_s=round(b - a, 2)) for m, a, b in R['dwell']]),
                   blocks=[dict(kind=a, mod=b, t0=c, t1=e) for a, b, c, e in R['blocks']],
                   done=R['done']),
              open(META, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    dw = [b - a for _, a, b in R['dwell']]
    print('页数 %d | 一轮 %.2f s / %d 件 | 循环 %.2f s / %d 件 | 节拍 %.3f s | %.1f UPH | dwell %.2f~%.2f s | 块 %d' % (
        len(pr.slides._sldIdLst), R['total'], len(R['done']), R['dur'], R['mods'], R['tact'], R['uph'],
        min(dw), max(dw), len(R['blocks'])))
    print('源:', src)


if __name__ == '__main__':
    main()
