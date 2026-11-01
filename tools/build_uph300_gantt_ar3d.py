#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AR3D 场景 300UPH 节拍甘特图 (追加到《机器人整机三视图与技术参数》PPT)

真源: AR3D 页面自己吃的接口 GET http://127.0.0.1:8797/api/sim_insert
      (页面 tcp-ar.html inspPrepare/plantCtx 用同一份: plan[] 逐段 t + loop{ks,dur,mods})
口径与页面一致:
  稳态循环 = 第 ks[0] 轮起 到 ks[1] 轮末  (页面 plantCtx: dur = cum[i1]+t[i1]-base)
  节拍     = dur / mods ; UPH = 3600 / 节拍
  左臂上料 = 3.0 s/件 (tcp-ar.html: PLANT.feedS = 3.0, TACT_CYCLE = 3.0)
每根条 = 段表里对应动作块的起止时刻, 无手填。
"""
import json, urllib.request
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR

DECK = '/home/ubuntu/zmax/docs/1-天枢-产品边界/deliverables/2-机器人方案/机器人整机三视图与技术参数_5.50.C_20261101.pptx'
META = '/home/ubuntu/zmax/docs/1-天枢-产品边界/deliverables/2-机器人方案/甘特_300UPH_数据源.json'
API = 'http://127.0.0.1:8797/api/sim_insert'
DISK = '/home/ubuntu/zmax/zmax_data/runtime/traj/sim_insert.json'
FEED_S = 3.0

C_L = RGBColor(0x0F, 0x76, 0x6E)
C_PULL = RGBColor(0x1D, 0x4E, 0xD8)
C_AOI = RGBColor(0x7C, 0x3A, 0xED)
C_PLACE = RGBColor(0x15, 0x80, 0x3D)
C_INS = RGBColor(0xB4, 0x53, 0x09)
C_GRID = RGBColor(0xCB, 0xD5, 0xE1)
C_TXT = RGBColor(0x0F, 0x17, 0x2A)
C_DIM = RGBColor(0x47, 0x55, 0x69)
C_NG = RGBColor(0xDC, 0x26, 0x26)


def fetch():
    try:
        d = json.loads(urllib.request.urlopen(API, timeout=6).read())
        return d, API, d.get('cfg_sha', '')
    except Exception as e:
        d = json.load(open(DISK, encoding='utf-8'))
        return d, 'DISK:%s (API 不可达: %s)' % (DISK, e), d.get('cfg_sha', '')


def build(d):
    P, L = d['plan'], d['loop']
    cum, t = [], 0.0
    for s in P:
        cum.append(round(t, 2)); t += s['t']
    i0 = next(i for i, s in enumerate(P) if s['k'] == L['ks'][0])
    i1 = max(i for i, s in enumerate(P) if s['k'] == L['ks'][1])
    base = cum[i0]
    dur = round(cum[i1] + P[i1]['t'] - base, 3)
    mods = int(L['mods'])
    tact = dur / mods
    rel = lambda i: round(cum[i] - base, 3)
    relend = lambda i: round(cum[i] + P[i]['t'] - base, 3)

    blocks, i = [], i0
    while i <= i1:
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
            while j <= i1 and P[j]['kind'] in ('golden', 'side', 'move'):
                if P[j]['kind'] == 'move' and not (j + 1 <= i1 and P[j + 1]['kind'] in ('golden', 'side')):
                    break
                j += 1
            blocks.append(('aoi', P[i]['mod'], rel(i), relend(j - 1)))
            if j + 3 <= i1 and P[j]['kind'] == 'move':
                blocks.append(('place', P[j]['mod'], rel(j), relend(j + 3)))
                j += 4
            i = j
            continue
        i += 1

    done = sorted(b[3] for b in blocks if b[0] == 'place')
    return dict(d=d, dur=dur, mods=mods, tact=tact, uph=3600 / tact, base=base,
                i0=i0, i1=i1, blocks=blocks, done=done, n_segs=len(P), loop=L)


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


def bar(slide, x, y, w, h, color, label=None):
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(max(w, 0.02)), Inches(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = color
    sh.line.color.rgb = color; sh.line.width = Pt(0.5)
    sh.shadow.inherit = False
    if label:
        tf = sh.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.word_wrap = False
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = label
        r.font.size = Pt(6.5); r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        r.font.name = 'Microsoft YaHei'
    return sh


def vline(slide, x, y0, y1, color=C_GRID, wpt=0.75, dash=True):
    from pptx.enum.dml import MSO_LINE_DASH_STYLE
    ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(y0), Inches(x), Inches(y1))
    ln.line.color.rgb = color; ln.line.width = Pt(wpt)
    if dash:
        ln.line.dash_style = MSO_LINE_DASH_STYLE.DASH
    return ln


def hline(slide, x0, x1, y, color=C_GRID, wpt=0.5):
    ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x0), Inches(y), Inches(x1), Inches(y))
    ln.line.color.rgb = color; ln.line.width = Pt(wpt)
    return ln


def slide_loop(pr, R):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    dur, mods, tact = R['dur'], R['mods'], R['tact']
    add_text(s, 0.55, 0.20, 12.3, 0.42,
             'AR3D 场景节拍甘特（与页面同源）· 稳态循环 %.2f s / %d 件 → %.3f s/件（%.0f UPH）' % (
                 dur, mods, tact, R['uph']), size=17.5, bold=True)
    add_text(s, 0.55, 0.63, 12.3, 0.34,
             '数据源 GET /api/sim_insert（cfg_sha %s · %d 段）与页面 plantCtx 同一份；窗口取 loop.ks=[%d,%d]，节拍=dur/mods。'
             '左臂 3.0 s/件 = 页面 PLANT.feedS。真机零指令。' % (
                 R['d'].get('cfg_sha', '—'), R['n_segs'], R['loop']['ks'][0], R['loop']['ks'][1]),
             size=8, color=C_DIM)

    X0, Y0, W, H = 2.36, 1.32, 9.05, 4.05
    lanes = [('左臂 · 上料摆盘（3.0 s/件）', C_L), ('右臂 · 从孔内拔出（MT-02）', C_PULL),
             ('右臂 · AOI 五点（MT-03）', C_AOI), ('右臂 · 良品落盘（MT-04）', C_PLACE),
             ('右臂 · 补插新模块（MT-01）', C_INS)]
    rh = H / len(lanes)
    sc = W / dur

    k = 0
    while k * tact <= dur + 1e-6:
        vline(s, X0 + k * tact * sc, Y0 - 0.16, Y0 + H, C_NG if k else C_GRID, 0.9 if k else 0.6)
        add_text(s, X0 + k * tact * sc - 0.34, Y0 + H + 0.03, 0.68, 0.22,
                 '%.1fs' % (k * tact), size=6.5, color=C_DIM, align=PP_ALIGN.CENTER)
        k += 1

    for j, (name, col) in enumerate(lanes):
        y = Y0 + j * rh
        add_text(s, 0.55, y + rh / 2 - 0.16, 1.74, 0.34, name, size=8.5, color=C_TXT,
                 align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        if j:
            hline(s, X0, X0 + W, y)
        bar(s, X0 - 0.10, y + rh * 0.30, 0.05, rh * 0.40, col)

    for kind, mod, t0, t1 in R['blocks']:
        j = {'pull': 1, 'aoi': 2, 'place': 3, 'insert': 4}[kind]
        col = {'pull': C_PULL, 'aoi': C_AOI, 'place': C_PLACE, 'insert': C_INS}[kind]
        bar(s, X0 + t0 * sc, Y0 + j * rh + rh * 0.22, (t1 - t0) * sc, rh * 0.56, col,
            label=('M%d' % mod) if kind in ('pull', 'place', 'insert') else None)

    k = 0
    while k * tact + FEED_S <= dur + 1e-6:
        bar(s, X0 + k * tact * sc, Y0 + rh * 0.22, FEED_S * sc, rh * 0.56, C_L,
            label=('上料%d' % (k + 1)) if k < 2 else None)
        k += 1

    for n, tt in enumerate(R['done'], 1):
        add_text(s, X0 + tt * sc - 0.32, Y0 - 0.32, 0.64, 0.22, '件%d完成' % n, size=6.5,
                 bold=True, color=C_TXT, align=PP_ALIGN.CENTER)

    occ = sum(b[3] - b[2] for b in R['blocks'])
    add_text(s, 0.55, 5.58, 12.35, 0.44,
             '节拍 %.3f s/件 → %.0f UPH（目标 300 = 12 s/件，余量 %.2f s/件）　循环 %.2f s / %d 件　'
             '右臂净占用 %.2f s（%.0f%%）　一轮 159.43 s / 14 件只是首轮（含预插 4 孔），之后按本循环无限循环' % (
                 tact, R['uph'], 12.0 - tact, dur, mods, occ, 100.0 * occ / dur), size=9, color=C_TXT)
    add_text(s, 0.55, 6.02, 12.35, 0.95,
             '读数：①一件 = 拔 1.78~1.99 → AOI 4.20 → 落盘 1.39~1.77 s；两件成对落盘（8.74 / 17.44 / 31.60 / 40.04 s），'
             '对间 5.5 s 用来补插两颗新模块（2.70~2.98 s）；②4 件 45.87 s 平均 %.3f s/件 = 竖线节拍，末段无缝接回第 1 件；'
             '③右臂净占用 %.0f%% 是瓶颈，左臂 3.0/%.3f = %.0f%%（料仓 14/14 常满，只在上料）。' % (
                 tact, 100.0 * occ / dur, tact, 100.0 * FEED_S / tact), size=8.5, color=C_DIM)


def slide_piece(pr, R):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    tact = R['tact']
    pull = next(x for x in R['blocks'] if x[0] == 'pull')
    aoi = next(x for x in R['blocks'] if x[0] == 'aoi')
    place = next(x for x in R['blocks'] if x[0] == 'place')
    ins = [x for x in R['blocks'] if x[0] == 'insert']
    ins_avg = sum(x[3] - x[2] for x in ins) / len(ins)
    d_pull, d_aoi, d_place = pull[3] - pull[2], aoi[3] - aoi[2], place[3] - place[2]
    right_busy = d_pull + d_aoi + d_place

    add_text(s, 0.55, 0.22, 12.3, 0.42, '单件分解 · 第 1 件（mod 1）在 %.3f s 节拍里的时间账' % tact,
             size=17.5, bold=True)
    add_text(s, 0.55, 0.64, 12.3, 0.32,
             '同源段表第 %d~%d 段；条长 = 段起止相减。左臂行来自页面常量 PLANT.feedS=3.0 s/件。' % (R['i0'], R['i1']),
             size=8, color=C_DIM)

    X0, Y0, W = 1.90, 1.42, 9.50
    sc = W / tact
    seq = [('右臂 拔出', C_PULL, pull[2], d_pull), ('右臂 AOI 五点', C_AOI, aoi[2], d_aoi),
           ('右臂 落盘', C_PLACE, place[2], d_place)]
    bh = 0.46
    for j, (name, col, t0, dur) in enumerate(seq):
        y = Y0 + j * (bh + 0.34)
        add_text(s, 0.55, y + 0.08, 1.26, 0.30, name, size=8.5, align=PP_ALIGN.RIGHT)
        bar(s, X0 + t0 * sc, y, dur * sc, bh, col, label='%.2f s' % dur)
        add_text(s, X0 + (t0 + dur) * sc + 0.06, y + 0.10, 1.5, 0.26, '→ %.2f s' % (t0 + dur),
                 size=7.5, color=C_DIM)
    y = Y0 + 3 * (bh + 0.34)
    add_text(s, 0.55, y + 0.08, 1.26, 0.30, '左臂 上料', size=8.5, align=PP_ALIGN.RIGHT)
    bar(s, X0, y, FEED_S * sc, bh, C_L, label='%.2f s' % FEED_S)
    add_text(s, X0 + FEED_S * sc + 0.06, y + 0.10, 2.4, 0.26, '与右臂并行（不占节拍）', size=7.5, color=C_DIM)

    vline(s, X0 + tact * sc, Y0 - 0.20, y + bh, C_NG, 1.0)
    add_text(s, X0 + tact * sc - 0.95, Y0 - 0.48, 1.9, 0.26, '节拍 %.3f s' % tact, size=8.5, bold=True,
             color=C_NG, align=PP_ALIGN.CENTER)

    tot = right_busy + ins_avg / 2
    add_text(s, 0.55, 4.95, 12.35, 2.0,
             '平衡表（每件）：右臂 拔 %.2f + AOI %.2f + 落盘 %.2f = %.2f s；补插每两件 2 颗（均值 %.2f s/颗）摊 %.2f s/件\n'
             '　　⇒ 右臂合计 %.2f s / 节拍 %.3f s，余量 %.2f s（每件摊算；loop 全占用口径 %.0f%% 见左页）；左臂 %.2f s 与右臂并行（占 %.0f%%）\n'
             '瓶颈是 AOI 四点：%.2f s 占右臂 %.0f%%。若金手指与 3 个侧面点合并成一次取图（省 1.5~2 s），节拍可降到 %.2f~%.2f s'
             '（≈%.0f~%.0f UPH）—— 该合并尚未仿真验证，仅为理论抓手。' % (
                 d_pull, d_aoi, d_place, right_busy, ins_avg, ins_avg / 2,
                 tot, tact, tact - tot, 100.0 * tot / tact, FEED_S, 100.0 * FEED_S / tact,
                 d_aoi, 100.0 * d_aoi / tot,
                 tact - 1.5, tact - 2.0, 3600 / (tact - 1.5), 3600 / (tact - 2.0)),
             size=10, color=C_TXT)


def main():
    d, src, sha = fetch()
    R = build(d)
    pr = Presentation(DECK)
    while len(pr.slides._sldIdLst) > 5:
        sid = pr.slides._sldIdLst[-1]
        pr.part.drop_rel(sid.rId); pr.slides._sldIdLst.remove(sid)
    slide_loop(pr, R)
    slide_piece(pr, R)
    pr.save(DECK)
    json.dump(dict(source=src, cfg_sha=sha,
                   window=dict(i0=R['i0'], i1=R['i1'], base=R['base'], dur=R['dur'],
                               mods=R['mods'], tact=R['tact'], uph=R['uph']),
                   feed_s=FEED_S,
                   blocks=[dict(kind=a, mod=b, t0=c, t1=e) for a, b, c, e in R['blocks']],
                   done=R['done']),
              open(META, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('页数 %d | 窗口 %.3f s / %d 件 | 节拍 %.3f s/件 | %.1f UPH | 右臂占用 %.2f s | 块 %d' % (
        len(pr.slides._sldIdLst), R['dur'], R['mods'], R['tact'], R['uph'],
        sum(b[3] - b[2] for b in R['blocks']), len(R['blocks'])))
    print('源:', src, '| cfg_sha', sha)


if __name__ == '__main__':
    main()
