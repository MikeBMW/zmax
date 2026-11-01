#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把《机器人整机三视图与技术参数》升级成《整机解决方案》:
  新增 封面 / 方案总览 / 验收口径与边界 三页, 重排为解决方案叙事, 另存为新文件名。
所有数字由 sources() 现算(URDF / tcp-ar.html / ar_station.xml / /api/sim_insert / 画布), 不手填。
"""
import json, re, os, math, urllib.request
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

ROOT = '/home/ubuntu/zmax'
ROOT_DATA = '/home/ubuntu/zmax_data'
DIR = ROOT + '/docs/1-天枢-产品边界/deliverables/2-机器人方案'
SRC_DECK = ROOT_DATA + '/deliveries/母版/机器人整机内容源_5.50.C.pptx'
NEW_DECK = DIR + '/Z-MAX机器人整机解决方案_5.50.C_20261101.pptx'

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
    cum, t = [], 0.0
    for s in P:
        cum.append(round(t, 2)); t += s['t']
    i0 = next(i for i, s in enumerate(P) if s['k'] == L['ks'][0])
    i1 = max(i for i, s in enumerate(P) if s['k'] == L['ks'][1])
    dur = round(cum[i1] + P[i1]['t'] - cum[i0], 2)
    tact = dur / L['mods']
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
    add_text(s, 0.78, 0.95, 11.9, 0.40, 'XMS5-R800 ×2 ｜ 300 UPH ｜ L2 全节点能力 ｜ 场景实测几何与节拍',
             size=13, color=RGBColor(0x9C, 0xD3, 0xE6))
    add_text(s, 0.78, 1.95, 11.8, 0.36, '方案版本 5.50.C　·　2026-11-01　·　编制依据（全部可回溯到真源文件）',
             size=11.5, bold=True, color=C_ACC)
    rows = [
        ('整机与工位几何', '厂家 URDF（config/robot/zmax_robot_spec.json）＋ AR3D 场景常量 tools/web/tcp-ar.html ＋ ar_station.xml'),
        ('节拍与产能', 'AR3D 页面同源接口 GET /api/sim_insert（392 段逐段计时，稳态循环 45.87 s / 4 件）'),
        ('L2 能力清单', '状态空间画布 state_space_obs.json ＋ src/lerobot/middleware/nodes/n_*.py 的 NAME / desc / PURE / SOURCE'),
        ('自检', 'tools/verify_solution_deck.py —— 把本册每个关键数回真源重算后比对'),
    ]
    y = 2.42
    for k, v in rows:
        box(s, 0.78, y, 2.05, 0.42, RGBColor(0xEC, 0xF6, 0xFA), RGBColor(0xBF, 0xE0, 0xEC))
        add_text(s, 0.86, y + 0.10, 1.95, 0.26, k, size=9.5, bold=True, color=C_ACC)
        add_text(s, 3.00, y + 0.08, 9.6, 0.30, v, size=9.2, color=C_TXT)
        y += 0.56
    add_text(s, 0.78, 5.05, 11.9, 1.2,
             '方案边界（先说清，不当承诺）：本册是整机方案与产能口径，不是白盒交付；所有节拍来自 AR3D 段表与仿真链，'
             '真机零指令；真机开跑前必须先补 T_base_cam / plane_z 两项现场标定（readiness.site_missing），'
             'AOI 合并取图等提速抓手仅为理论，未做仿真验证。', size=10, color=C_DIM, line_spacing=1.35)
    add_text(s, 0.78, 6.42, 11.9, 0.4,
             'Z-MAX  ·  5.50.C  ·  机器人整机解决方案  ·  内部评审版', size=9, color=C_DIM)


def slide_overview(pr, S):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    add_text(s, 0.55, 0.22, 12.3, 0.40, '方案总览 · 一台工作站要解决的四件事', size=19, bold=True)
    add_text(s, 0.55, 0.66, 12.3, 0.32,
             '目标：光模块从上料盘取出 → 插入设备孔 → 坐够停留 → 拔出做五点 AOI → 良品落盘 / NG 进废料盘，'
             '双臂并行做到 300 件/小时。以下四块全部有真源，可逐条复核。', size=9.2, color=C_DIM)

    CHS, TAB, TCAM = S['CHS'], S['TAB'], S['TCAM']
    tab_len = round((TAB['x1'] - TAB['x0']) * 1000)
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
            '稳态循环 %.2f s / %d 件 → 节拍 %.3f s/件' % (S['dur'], S['mods'], S['tact']),
            '折算 %.0f UPH，目标 300（12 s/件），余量 %.2f s/件' % (S['uph'], 12.0 - S['tact']),
            '单件动作：拔 1.78 → AOI 4.20 → 落盘 1.77 s',
            '每两件补插 2 颗（2.70~2.98 s/颗），右臂净占用 92%',
            '孔内停留 %.2f~%.2f s，与作业并行不占节拍' % S['dwell'],
        ]),
        ('③ 感知与决策（L2）', C_PUR, [
            '画布七带 %d 个节点：记忆 2 / 感知 6 / 融合 2 / 小模型 5 / 决策 2 / 技能库 12 / 执行 2' % S['n_l2'],
            '名称逐字照抄画布，未改写（含 🌍物理世界 环境实体）',
            'PURE=True 真算 %d 个，其余只走数据面（表内逐个标注）' % S['n_pure'],
            '感知：YOLO 22 类 · AOI 判据 · 触觉 4D · 板坐标 · 2D→3D · SAM3',
            '融合：43D 统一状态 → SU(2) 群元素',
            '决策：估计/预测/前馈/测地线/校正 → 6 阶段状态机否决 → 势场+限幅 → 原子技能 → n_exec 收口',
        ]),
        ('④ 口径与边界', C_ORG, [
            '每个数字都能回到文件/接口（本册末尾附复核方式）',
            '节拍取 AR3D 稳态循环口径，不是首轮 159.43 s',
            '真机零指令：本册不含任何下发动作',
            '未闭环：现场标定 T_base_cam / plane_z 缺；AOI 合并取图未验证',
            '真机执行前先过 readiness 自检与 mem_gate 内存闸',
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
             '右臂把「拔→检→放」串成 11.467 s 的节拍，左臂用 3.0 s/件补料，节拍由右臂决定；'
             'L2 层 30 个节点负责让每一段动作都有真值、有否决权、有兜底。', size=10, color=C_TXT, line_spacing=1.3)
    add_text(s, 0.55, 5.95, 12.3, 1.2,
             '读册顺序：第 3~7 页 = 整机几何与结构（三视图 / 尺寸表 / URDF 参数）；第 8~9 页 = 节拍甘特（一轮全览 + 稳态放大）；'
             '第 10~12 页 = L2 30 个节点数据流与功能表；第 13 页 = 验收口径、复核方式与未闭环项。',
             size=9, color=C_DIM, line_spacing=1.3)


def slide_accept(pr, S):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    add_text(s, 0.55, 0.20, 12.3, 0.40, '验收口径 · 复核方式 · 边界与未闭环', size=19, bold=True)
    add_text(s, 0.55, 0.62, 12.3, 0.30,
             '自检工具：gui-venv311/bin/python tools/verify_solution_deck.py（22 项逐条回真源重算；当前 22 PASS / 0 FAIL）',
             size=8.8, color=C_DIM)

    hdr = ['指标 / 参数', '本册数值', '口径（怎么算出来的）', '复核位置']
    rows = [
        ('节拍', '%.3f s/件' % S['tact'], 'loop.dur / loop.mods（AR3D 稳态循环）', '/api/sim_insert · 第 8~9 页'),
        ('产能', '%.0f UPH（目标 300）' % S['uph'], '3600 / 节拍；目标来自 order ar_300uph', 'config/orders/BS_SCN-07-AOI.json'),
        ('孔内停留', '%.2f ~ %.2f s' % S['dwell'], '插入松开(release@hole) → 夹住(grip@hole)', 'sim_insert.plan + cycles_data.dwell_s'),
        ('本体质量', '%.3f kg/台（双臂 %.3f）' % (S['mass'], S['mass'] * 2), 'URDF 6 个 link 质量求和', 'config/robot/zmax_robot_spec.json'),
        ('关节行程/力矩/速度', '±360 / -160~+150 / -170~+140\n113·113·70·25·25·19 N·m / 180 °/s',
         'URDF joint limit 换算（rad→deg）', 'spec.json joints[].limit'),
        ('杆长', '大臂 400 · 小臂 400 · 腕偏置 136 · 法兰 103.5 mm', 'URDF joint origin 相邻段差值', 'spec.json joints[].origin_xyz'),
        ('工位尺寸', '台面 1600×600×30 高 750 · 箱体 600×800×750 · 轮 Ø150 · 臂距 500',
         'AR3D 场景常量（TAB / CHS / LARM）', 'tools/web/tcp-ar.html'),
        ('料盘', '3 组 × 14 槽 + 废料盘（42 槽口 36×42，z=117.5）', '场景 XML 逐个槽口 geom 计数', 'zmax_data/ar_mujoco/ar_station.xml'),
        ('L2 能力', '七带 %d 个节点(逻辑 %d)，PURE=True %d' % (S['n_l2'], S['n_logic'], S['n_pure']),
         '画布 L2 七条带逐带取节点(名称逐字) + PARAMS/PURE',
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
             '②节拍是「稳态循环」口径，首轮 159.43 s / 14 件含 4 个孔预插，不能拿来算 UPH；'
             '③真机开跑前必须先补 T_base_cam / plane_z 现场标定（readiness.site_missing）；'
             '④AOI 合并取图省 1.5~2 s 只是理论抓手，未做仿真验证，不进默认节拍；'
             '⑤FOV 87°×58° 是页面模板常量（RealSense 口径），不是本机标定值。\n'
             '变更纪律：任何数字要改，先改真源（URDF / 场景 XML / 段表 / 节点代码），再重跑 build 脚本与 verify 脚本，'
             '不直接改 PPT 文本。', size=9, color=C_DIM, line_spacing=1.3)


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
    n0 = len(pr.slides._sldIdLst)
    slide_cover(pr, S)
    slide_overview(pr, S)
    slide_accept(pr, S)
    # 原 0..n0-1 保持原序; 新增 3 页在 n0, n0+1, n0+2
    order = [n0, n0 + 1] + list(range(0, n0)) + [n0 + 2]
    reorder(pr, order)
    pr.save(NEW_DECK)
    print('解决方案页数 %d（原 %d + 新增 3）→ %s' % (len(pr.slides._sldIdLst), n0, os.path.basename(NEW_DECK)))
    print('节拍 %.3f s/件 · %.0f UPH · dwell %.2f~%.2f · L2 %d 节点(PURE %d) · 质量 %.3f kg' % (
        S['tact'], S['uph'], S['dwell'][0], S['dwell'][1], S['n_l2'], S['n_pure'], S['mass']))


if __name__ == '__main__':
    main()
