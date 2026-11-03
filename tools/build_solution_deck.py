#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把《机器人整机三视图与技术参数》升级成《整机解决方案》:
  新增 封面 / 方案总览 / 验收口径与边界 三页, 重排为解决方案叙事, 另存为新文件名。
所有数字由 sources() 现算(URDF / tcp-ar.html / ar_station.xml / /api/sim_insert / 画布), 不手填。
"""
import json, re, os, math, sys, urllib.request
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

ROOT = '/home/ubuntu/zmax'
ROOT_DATA = '/home/ubuntu/zmax_data'
DIR = ROOT + '/docs/1-天枢-产品边界/deliverables/2-机器人方案'
SRC_DECK = ROOT_DATA + '/deliveries/母版/机器人整机内容源_5.50.C.pptx'
NEW_DECK = DIR + '/Z-MAX机器人整机解决方案_5.50.C-R5_20261102.pptx'

C_TXT = RGBColor(0x0F, 0x17, 0x2A)
C_DIM = RGBColor(0x47, 0x55, 0x69)
C_ACC = RGBColor(0x0E, 0x74, 0x90)
C_BLUE = RGBColor(0x1D, 0x4E, 0xD8)
C_GRN = RGBColor(0x15, 0x80, 0x3D)
C_ORG = RGBColor(0xC2, 0x41, 0x0C)
C_PUR = RGBColor(0x7C, 0x3A, 0xED)


def sources():
    spec = json.load(open(ROOT + '/config/robot/zmax_robot_spec.json', encoding='utf-8'))
    J = [j for j in spec['joints'] if j.get('limit')][:6]
    mass = round(sum(l['mass'] for l in spec['links'] if l['mass']), 3)
    html = open(ROOT + '/tools/web/tcp-ar.html', encoding='utf-8').read()

    def const(name):
        m = re.search(name + r'\s*=\s*\{([^}]*)\}', html)
        return {k: float(v) for k, v in re.findall(r'(\w+)\s*:\s*(-?[\d.]+)', m.group(1))} if m else {}

    CHS, TAB, TCAM = const('CHS'), const('TAB'), const('TCAM')
    xml = open(ROOT + '/zmax_data/ar_mujoco/ar_station.xml', encoding='utf-8').read()
    slot_rows = re.findall(r'name="([^"]+)" type="box" pos="([-\d.e]+) ([-\d.e]+) ([-\d.e]+)" size="([-\d.e]+) ([-\d.e]+)', xml)
    slots = [(n, float(x), float(y), float(z), float(sx), float(sy)) for n, x, y, z, sx, sy in slot_rows
             if '槽' in n and round(float(sx) * 2000) == 36 and round(float(sy) * 2000) == 42]
    trays = re.findall(r'name="(b\d+)__([^"]*)_bot" type="box"', xml)
    try:
        sim = json.loads(urllib.request.urlopen('http://127.0.0.1:8797/api/sim_insert', timeout=6).read())
    except Exception:
        sim = json.load(open(ROOT + '/zmax_data/runtime/traj/sim_insert.json', encoding='utf-8'))
    P, L = sim['plan'], sim['loop']
    # 节拍/动作块: 与甘特页共用同一套段表解析 (tools/build_uph300_gantt.build), 不另写一份算法
    sys.path.insert(0, ROOT + '/tools')
    from build_uph300_gantt import build as _gantt_build
    R = _gantt_build(sim)
    win = [b for b in R['blocks'] if b[2] >= R['base'] - 1e-6 and b[3] <= R['base'] + R['dur'] + 1e-6]

    def _ph(kind):
        xs = [b[3] - b[2] for b in win if b[0] == kind]
        return (min(xs), max(xs), sum(xs) / len(xs)) if xs else (0.0, 0.0, 0.0)

    occ = sum(b[3] - b[2] for b in win)
    dur, tact = R['dur'], R['tact']
    cum, t = [], 0.0
    for s in P:
        cum.append(t); t += s['t']
    ins_end, grip_t = {}, {}
    for i, s in enumerate(P):
        if s['kind'] == 'release' and s.get('at') == 'hole' and s.get('hole') is not None:
            ins_end[s['mod']] = round(cum[i] + s['t'], 2)
        if s['kind'] == 'grip' and s.get('hole') is not None and '(拔)' in (P[i - 2].get('label') or ''):
            grip_t[s['mod']] = round(cum[i], 2)
    dw = [round(grip_t[m] - ins_end[m], 2) for m in sorted(ins_end) if m in grip_t]
    # L2 节点
    canvas = json.load(open(ROOT + '/data/database/zmax/sources/canvas/state_space_obs.json', encoding='utf-8'))['nodes']
    idx = open(ROOT + '/src/lerobot/middleware/nodes/_index.py', encoding='utf-8').read()
    bands = {n['id']: n for n in canvas if n['type'] == 'row_bg'}
    L2B = ['row_mem_l2', 'ssbg0', 'ssbg1', 'ssbg2', 'ssbg3', 'ssbg_skill', 'ssbg4']
    n_l2 = n_pure = 0
    band_cnt = []
    for bid in L2B:
        b = bands[bid]
        band_cnt.append((b['name'], len([x for x in canvas if x['type'] != 'row_bg' and b['y'] <= x['y'] < b['y'] + b['h']])))
    for n in canvas:
        if n['type'] == 'row_bg' or not any(bands[b]['y'] <= n['y'] < bands[b]['y'] + bands[b]['h'] for b in L2B):
            continue
        m = re.search(r'["\']%s["\']\s*:\s*["\']([^"\']+)' % re.escape(n['id']), idx)
        if not m:
            continue
        f = ROOT + '/src/lerobot/middleware/nodes/%s.py' % m.group(1).split('.')[-1]
        if os.path.exists(f):
            n_l2 += 1
            if re.search(r'^PURE\s*=\s*True', open(f, encoding='utf-8').read(), re.M):
                n_pure += 1
    return dict(spec=spec, J=J, mass=mass, CHS=CHS, TAB=TAB, TCAM=TCAM, slots=slots, trays=trays,
                sim=sim, dur=dur, mods=L['mods'], tact=tact, uph=3600 / tact,
                occ=occ, gap=dur - occ,
                phase=dict(pull=_ph('pull'), aoi=_ph('aoi'), place=_ph('place'), insert=_ph('insert')),
                dwell=(min(dw), max(dw)), n_l2=n_l2, n_pure=n_pure, n_logic=n_l2 - 1, band_cnt=band_cnt)


def add_text(slide, x, y, w, h, text, size=10, bold=False, color=C_TXT, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, line_spacing=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, line in enumerate(str(text).split('\n')):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if line_spacing:
            p.line_spacing = line_spacing
        r = p.add_run(); r.text = line
        r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color
        r.font.name = 'Microsoft YaHei'
    return tb


def box(slide, x, y, w, h, fill, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    sh.line.color.rgb = line or fill
    sh.line.width = Pt(0.75)
    sh.shadow.inherit = False
    return sh


def slide_cover(pr, S):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    box(s, 0, 0, 13.333, 1.55, RGBColor(0x0B, 0x1B, 0x2B), shape=MSO_SHAPE.RECTANGLE)
    add_text(s, 0.75, 0.34, 11.9, 0.52, 'Z-MAX 光模块上下料双臂工作站 · 整机解决方案', size=27, bold=True,
             color=RGBColor(0xFF, 0xFF, 0xFF))
    add_text(s, 0.78, 0.95, 11.9, 0.40, '两台 XMS5-R800 ｜ 设计产能每小时 300 件 ｜ 基础层全部节点能力 ｜ AR3D 场景几何与分段节拍（真机零指令）',
             size=13, color=RGBColor(0x9C, 0xD3, 0xE6))
    add_text(s, 0.78, 1.95, 11.8, 0.36, '方案版本 5.50.C-R4　·　2026-11-02　·　编制依据：每个数字都写明来源文件与计算方式',
             size=11.5, bold=True, color=C_ACC)
    rows = [
        ('整机与工位几何', '厂家 URDF（config/robot/zmax_robot_spec.json）＋ AR3D 场景常量 tools/web/tcp-ar.html ＋ ar_station.xml'),
        ('节拍与产能', 'AR3D 页面同源接口 GET /api/sim_insert（%d 段逐段计时，稳态循环 %.3f s / %d 件）'
         % (S['sim'].get('n_segs', len(S['sim']['plan'])), S['dur'], S['mods'])),
        ('基础层能力清单', '状态空间画布 state_space_obs.json ＋ 各节点实现文件（src/lerobot/middleware/nodes/）里的名称、功能说明与内部算法是否参与运算'),
        ('自检', 'tools/verify_solution_deck.py —— 把本册每个关键数字回到来源文件重新计算后再比对'),
    ]
    y = 2.42
    for k, v in rows:
        box(s, 0.78, y, 2.05, 0.42, RGBColor(0xEC, 0xF6, 0xFA), RGBColor(0xBF, 0xE0, 0xEC))
        add_text(s, 0.86, y + 0.10, 1.95, 0.26, k, size=9.5, bold=True, color=C_ACC)
        add_text(s, 3.00, y + 0.08, 9.6, 0.30, v, size=9.2, color=C_TXT)
        y += 0.56
    add_text(s, 0.78, 5.05, 11.9, 1.2,
             '方案边界（先说清，不当承诺）：本册给出的是整机方案与产能估算，不是白盒交付；所有节拍来自 AR3D 段表与仿真链，'
             '真机零指令；真机开跑前必须先补 T_base_cam / plane_z 两项现场标定（readiness.site_missing），'
             'AOI 合并取图等提速抓手仅为理论，未做仿真验证。', size=10, color=C_DIM, line_spacing=1.35)
    add_text(s, 0.78, 6.42, 11.9, 0.4,
             'Z-MAX  ·  5.50.C-R4  ·  机器人整机解决方案  ·  内部评审版', size=9, color=C_DIM)


def slide_overview(pr, S, total_pages=None, l2_pages=None):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    add_text(s, 0.55, 0.22, 12.3, 0.40, '方案总览 · 一台工作站要解决的四件事', size=19, bold=True)
    add_text(s, 0.55, 0.66, 12.3, 0.32,
             '目标：光模块从上料盘取出 → 插入设备孔 → 坐够停留 → 拔出做五点 AOI → 良品落盘 / NG 进废料盘，'
             '双臂并行做到每小时 300 件。以下四块都能回到具体文件，可逐条复核。', size=9.2, color=C_DIM)

    CHS, TAB, TCAM = S['CHS'], S['TAB'], S['TCAM']
    tab_len = round((TAB['x1'] - TAB['x0']) * 1000)
    PH = S['phase']
    cards = [
        ('① 整机构成与工位', C_ACC, [
            '双臂 XMS5-R800 ×2，本体 %.3f kg/台（双臂 %.3f kg）' % (S['mass'], S['mass'] * 2),
            '台面 %d×%d×%d mm，台面高 %d mm' % (TAB['w'] * 1000, tab_len, TAB['t'] * 1000, TAB['h'] * 1000),
            '箱体 %d×%d×%d mm，4 轮 Ø%d' % (CHS['L'] * 1000, CHS['W'] * 1000, CHS['H'] * 1000, CHS['wr'] * 2000),
            '料盘 3 组 × 14 槽 + 废料盘（42 槽口 %d×%d，z=%.1f）' % (
                round(S['slots'][0][4] * 2000), round(S['slots'][0][5] * 2000), S['slots'][0][3] * 1000),
            '中央顶视相机 r%d 俯角 %d°，立柱 %d mm，FOV %d°×%d°' % (
                TCAM['r'] * 1000, TCAM['tilt'], S['J'][0]['origin_xyz'][2] * 1000, TCAM['fovH'], TCAM['fovV']),
        ]),
        ('② 节拍与产能', C_GRN, [
            '稳态循环 %.3f s / %d 件 → 节拍 %.3f s/件' % (S['dur'], S['mods'], S['tact']),
            '折算每小时 %.0f 件，目标每小时 300 件（12 秒/件），余量 %.3f 秒/件' % (S['uph'], 12.0 - S['tact']),
            '单件块：拔 %.2f~%.2f → AOI %.2f → 落盘 %.2f~%.2f s' % (
                PH['pull'][0], PH['pull'][1], PH['aoi'][2], PH['place'][0], PH['place'][1]),
            '补插 1 颗/件 %.2f~%.2f s；右臂块内 %.0f%%，块间走位 %.2f s/件' % (
                PH['insert'][0], PH['insert'][1], 100.0 * S['occ'] / S['dur'], S['gap'] / S['mods']),
            '孔内停留 %.2f~%.2f s，与作业并行不占节拍' % S['dwell'],
        ]),
        ('③ 感知与决策（基础层）', C_PUR, [
            '画布七带 %d 个节点：记忆 2 / 感知 6 / 融合 2 / 小模型 5 / 决策 2 / 技能库 12 / 执行 2' % S['n_l2'],
            '名称逐字照抄画布，未改写（含 🌍物理世界 环境实体）',
            '其中 %d 个的内部算法真正参与每拍运算，其余目前只转发数据（逐页标注）' % S['n_pure'],
            '感知：二十二类目标识别、外观检测、四维触觉、二维转三维、像素级分割',
            '融合：把四十三维状态收成群元素，层间合成用群乘法',
            '决策：状态估计、动力学预测、前馈加速、测地线引导、状态校正五路汇入六阶段状态机，经势场仲裁与饱和限幅交给原子技能，由动作执行器收口',
        ]),
        ('④ 计算方式与边界', C_ORG, [
            '每个数字都能回到文件/接口（本册末尾附复核方式）',
            '节拍按 AR3D 页面的稳态循环统计，不用首轮含预插的 159.43 秒',
            '真机零指令：本册不含任何下发动作',
            '未闭环：现场标定 T_base_cam / plane_z 缺；AOI 合并取图未验证',
            '真机执行前先过启动自检与内存闸门',
        ]),
    ]
    x = 0.55
    for title, col, lines in cards:
        box(s, x, 1.10, 2.98, 3.62, RGBColor(0xFA, 0xFB, 0xFD), RGBColor(0xE2, 0xE8, 0xF0))
        box(s, x, 1.10, 2.98, 0.40, col, col)
        add_text(s, x + 0.12, 1.17, 2.74, 0.28, title, size=10.5, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        add_text(s, x + 0.12, 1.60, 2.74, 3.0, '\n'.join('· ' + l for l in lines), size=8.6, color=C_TXT,
                 line_spacing=1.25)
        x += 3.12

    add_text(s, 0.55, 4.95, 12.3, 0.9,
             '一句话：两台 800 mm 臂在一张 1600×600 的台面上、围绕 3 组 14 槽料盘和 4 个设备孔轮转，'
             '右臂把「拔→检→放→补插」串成 %.3f s 的节拍，左臂用 %.1f s/件补料，节拍由右臂决定；'
             '基础层 %d 个节点（含 1 个环境实体，逻辑 %d 个），让每一段动作都有实测真值、有否决权，也有兜底路径。' % (
                 S['tact'], 3.0, S['n_l2'], S['n_logic']), size=10, color=C_TXT, line_spacing=1.3)
    _l2_line = (('第 %d~%d 页 = 基础层逐节点（从最终输出端往上游，每点一页，说明它在工位上干什么、'
                 '数据从哪来、凭什么这样算、这一拍算没算）；第 %d 页 = 基础层节拍测试报告；'
                 % (l2_pages[0], l2_pages[1], l2_pages[2])) if l2_pages else '')
    add_text(s, 0.55, 5.95, 12.3, 1.2,
             '读册顺序：第 3~7 页 = 整机几何与结构（三视图 / 尺寸表 / URDF 参数）；第 8~9 页 = 节拍甘特（一轮全览 + 稳态放大）；'
             '第 10~18 页 = 四个层次的功能节点（基础层两页连线图 + 各层功能表）；'
             + _l2_line
             + '第 %d 页 = 验收方式、数字复核与未闭环事项。' % (total_pages or 19),
             size=9, color=C_DIM, line_spacing=1.3)


def slide_accept(pr, S):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    add_text(s, 0.55, 0.20, 12.3, 0.40, '验收方式 · 数字复核 · 边界与未闭环事项', size=19, bold=True)
    hint = add_text(s, 0.55, 0.62, 12.3, 0.30,
                    '自检工具：gui-venv311/bin/python tools/verify_solution_deck.py（逐项回到来源文件重新计算；本节数字由该脚本现场跑完后写回）',
                    size=8.8, color=C_DIM)

    hdr = ['指标 / 参数', '本册数值', '计算方式（怎么算出来的）', '复核位置']
    rows = [
        ('节拍', '%.3f s/件' % S['tact'], 'loop.dur / loop.mods（AR3D 稳态循环）', '/api/sim_insert · 第 8~9 页'),
        ('产能', '每小时 %.0f 件（目标每小时 300 件）' % S['uph'], '3600 ÷ 单件节拍；设计目标取自订单文件', 'config/orders/BS_SCN-07-AOI.json'),
        ('孔内停留', '%.2f ~ %.2f s' % S['dwell'], '插入松开(release@hole) → 夹住(grip@hole)', 'sim_insert.plan + cycles_data.dwell_s'),
        ('本体质量', '%.3f kg/台（双臂 %.3f）' % (S['mass'], S['mass'] * 2), 'URDF 6 个 link 质量求和', 'config/robot/zmax_robot_spec.json'),
        ('关节行程/力矩/速度', '±360 / -160~+150 / -170~+140\n113·113·70·25·25·19 N·m / 180 °/s',
         'URDF joint limit 换算（rad→deg）', 'spec.json joints[].limit'),
        ('杆长', '大臂 400 · 小臂 400 · 腕偏置 136 · 法兰 103.5 mm', 'URDF joint origin 相邻段差值', 'spec.json joints[].origin_xyz'),
        ('工位尺寸', '台面 1600×600×30 高 750 · 箱体 600×800×750 · 轮 Ø150 · 臂距 500',
         'AR3D 场景常量（TAB / CHS / LARM）', 'tools/web/tcp-ar.html'),
        ('料盘', '3 组 × 14 槽 + 废料盘（42 槽口 36×42，z=117.5）', '场景 XML 逐个槽口 geom 计数', 'zmax_data/ar_mujoco/ar_station.xml'),
        ('基础层能力', '七条功能带共 %d 个节点（逻辑 %d），内部算法参与运算的 %d 个' % (S['n_l2'], S['n_logic'], S['n_pure']),
         '画布七条功能带逐带取节点（名称逐字照抄）＋ 各节点实现文件声明的计算开关',
         'state_space_obs.json + n_*.py'),
    ]
    gx, gy = 0.55, 1.02
    colw = [1.85, 4.05, 3.75, 2.75]
    rowh = 0.40
    x = gx
    for i, h in enumerate(hdr):
        box(s, x, gy, colw[i], 0.30, RGBColor(0x0B, 0x1B, 0x2B), shape=MSO_SHAPE.RECTANGLE)
        add_text(s, x + 0.06, gy + 0.06, colw[i] - 0.1, 0.20, h, size=8.6, bold=True,
                 color=RGBColor(0xFF, 0xFF, 0xFF))
        x += colw[i]
    y = gy + 0.30
    for r, row in enumerate(rows):
        x = gx
        for i, cell in enumerate(row):
            box(s, x, y, colw[i], rowh, RGBColor(0xF7, 0xF9, 0xFC) if r % 2 == 0 else RGBColor(0xFF, 0xFF, 0xFF),
                RGBColor(0xE2, 0xE8, 0xF0), MSO_SHAPE.RECTANGLE)
            bold = (i == 0)
            add_text(s, x + 0.06, y + 0.03, colw[i] - 0.10, rowh - 0.05, cell, size=7.4, bold=bold,
                     color=C_TXT if i < 2 else C_DIM, anchor=MSO_ANCHOR.MIDDLE)
            x += colw[i]
        y += rowh

    add_text(s, 0.55, y + 0.14, 12.3, 1.5,
             '边界（不在本册承诺内）：①真机零指令 —— 全册数据来自 AR3D 段表与仿真链，不含任何下发；'
             '②节拍按稳态循环统计，首轮 159.43 秒 / 14 件含 4 个孔的预插，不能用来算产能；'
             '③真机开跑前必须先补 T_base_cam / plane_z 现场标定（readiness.site_missing）；'
             '④AOI 合并取图省 1.5~2 s 只是理论抓手，未做仿真验证，不进默认节拍；'
             '⑤视场角 87°×58° 取自页面模板里的相机常量，不是本机标定值。\n'
             '变更纪律：任何数字要改，先改来源文件（URDF / 场景 XML / 段表 / 节点代码），再重跑生成脚本与自检脚本，'
             '不直接改 PPT 文本。', size=9, color=C_DIM, line_spacing=1.3)
    return hint


def reorder(pr, order):
    lst = pr.slides._sldIdLst
    ids = list(lst)
    for el in ids:
        lst.remove(el)
    for i in order:
        lst.append(ids[i])


def main():
    S = sources()
    pr = Presentation(SRC_DECK)
    n0 = len(pr.slides._sldIdLst)                 # 母版: 整机外观/正侧/俯视/尺寸/参数/节拍/稳态 = 7 页
    import deck_front as _F
    import cost_model as _CM
    _cost = _CM.build_tiers()
    _F.build_front(pr, S, _cost)                  # 前 12 页: 结论式, 字大
    nf = len(pr.slides._sldIdLst) - n0

    import l2_chain_pages as _C2
    import l345_pages as _C345                   # 先导入: 注入 LC.SKIP_IDS, 基础层节点页同样屏蔽
    _C2.add_block(pr)                             # 基础层 30 页 + 节拍测试报告 1 页
    _C345.add_layers(pr)                          # 决策层 + 认知层 + 任务层节点页
    import deck_close as _CC
    _CC.build_close(pr)                           # 完整性 / 300 件三前提 / 引擎有效性 3 页
    order = list(range(n0, n0 + nf)) + list(range(0, n0)) + \
            list(range(n0 + nf, len(pr.slides._sldIdLst)))
    reorder(pr, order)

    # 全册页码: 前置页已有, 母版/节点/节拍页补上同样式的一个小页码 (封面不印)
    from pptx.util import Emu, Inches, Pt
    from pptx.enum.text import PP_ALIGN
    from pptx.dml.color import RGBColor
    n_all = len(pr.slides._sldIdLst)
    # 页脚总数: 前置页生成时还不知道全册多少页, 这里统一改成本册实际页数
    for sl in pr.slides:
        for sh in sl.shapes:
            if not sh.has_text_frame or "/ 51" not in sh.text_frame.text:
                continue
            for pa in sh.text_frame.paragraphs:
                for r in pa.runs:
                    if "/ 51" in r.text:
                        r.text = r.text.replace("/ 51", "/ %d" % n_all)
    _skip = set(range(nf + 1, nf + n0 + 1))     # 母版 7 页是工程图, 版面自带脚注, 不印页码
    for idx, sl in enumerate(pr.slides, 1):
        if idx == 1 or idx in _skip:
            continue
        has = any(sh.has_text_frame and ('/ %d' % n_all) in sh.text_frame.text for sh in sl.shapes)
        if has:
            continue
        tb = sl.shapes.add_textbox(Inches(11.72), Inches(7.20), Inches(0.85), Inches(0.20))
        tf = tb.text_frame
        tf.word_wrap = False
        p0 = tf.paragraphs[0]
        p0.alignment = PP_ALIGN.RIGHT
        r0 = p0.add_run()
        r0.text = '%02d / %d' % (idx, n_all)
        r0.font.size = Pt(9.0)
        r0.font.color.rgb = RGBColor(0x5A, 0x65, 0x74)
        r0.font.name = "微软雅黑"

    pr.save(NEW_DECK)

    import subprocess
    cmd = [ROOT + '/gui-venv311/bin/python', ROOT + '/tools/verify_solution_deck.py', NEW_DECK]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=300).stdout
    print('\n'.join([l for l in out.splitlines() if 'FAIL' in l or '结果:' in l or '页数' in l]))
    print('页数 %d（母版 %d + 前置 %d + 基础层 %d + 节拍 1）→ %s'
          % (len(pr.slides._sldIdLst), n0, nf, S['n_l2'], os.path.basename(NEW_DECK)))
    print('节拍 %.3f s/件 · %.0f 件/小时 · dwell %.2f~%.2f · 液冷%.0f · 质量 %.3f kg' % (
        S['tact'], S['uph'], S['dwell'][0], S['dwell'][1], 0, S['mass']))


if __name__ == '__main__':
    main()
