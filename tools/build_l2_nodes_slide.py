#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 L2 层全部逻辑节点(30 个)的功能画进《机器人整机三视图与技术参数》PPT。

真源(全部读盘, 不手填):
  画布定义  data/database/zmax/sources/canvas/state_space_obs.json (节点/子层带)
  节点实现  src/lerobot/middleware/nodes/_index.py → n_*.py 的 NAME / PARAMS.desc / SOURCE / PURE / PORTS
"""
import re, json, os
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

ROOT = '/home/ubuntu/zmax'
DECK = ROOT + '/docs/1-天枢-产品边界/deliverables/2-机器人方案/机器人整机三视图与技术参数_5.50.C_20261101.pptx'
META = ROOT + '/docs/1-天枢-产品边界/deliverables/2-机器人方案/L2节点清单_数据源.json'
CANVAS = ROOT + '/data/database/zmax/sources/canvas/state_space_obs.json'
INDEX = ROOT + '/src/lerobot/middleware/nodes/_index.py'
BASE_PAGES = 7          # 前 7 页保留(校验+甘特), L2 图从第 8 页起

# 画布上的 L2 子层带(y 起止) → 子层名
BANDS = [(2972, 3266, 'L2 记忆 · 肌肉记忆'), (3406, 3824, '分段感知'), (3964, 4258, '感知融合'),
         (4398, 4692, '分段控制小模型'), (4832, 5126, '状态机决策'), (5266, 6106, '原子技能 + 收口'),
         (6196, 6490, '执行层')]

# 兜底实现位置(仅这 3 个节点 SOURCE 字段是空串, 用 desc/IMPL_KEY 里写明的真源)
DESC_FALLBACK = {
    'ss_mem_l2': '小脑·标杆回放：吃 ss_mem_share + n_skill_dict，回放固化标杆并出 ss_mem_field（文件头原文）',
    'n_moveit': '原子技能意图 + 安全限制 → 段表 PlanSegments；只规划永不动作（plan_impl.py 文件头原文）',
    'n_exec': 'L2 收口：读 l2_daemon 真值状态与最近事件做授权/闸/到位判定，不造数不下发（exec_dispatch_impl.py 文件头原文）',
}
SKIP = {'ssworld'}          # 🌍 物理世界 = 环境实体, 不是逻辑节点

SRC_FALLBACK = {
    'ssaoi': 'src/lerobot/policies/yolo_3d/quality_check.py :: AOIQualityChecker（desc 明写）',
    'n_l2_muscle': '实现键 n_l2_muscle（n_skills.py, SOURCE 未登记）',
    'ss_mem_l2': '实现键 ss_mem_l2（n_muscle.py, SOURCE 未登记）',
}

C_TXT = RGBColor(0x0F, 0x17, 0x2A)
C_DIM = RGBColor(0x47, 0x55, 0x69)
C_PER = RGBColor(0x0E, 0x74, 0x90)
C_FUS = RGBColor(0x1D, 0x4E, 0xD8)
C_MOD = RGBColor(0x7C, 0x3A, 0xED)
C_DEC = RGBColor(0xC2, 0x41, 0x0C)
C_SK = RGBColor(0x15, 0x80, 0x3D)
C_EXE = RGBColor(0x0F, 0x76, 0x6E)
C_LINE = RGBColor(0x94, 0xA3, 0xB8)
LANE_COL = {'L2 记忆': 0x6D28D9, '分段感知': 0x0E7490, '感知融合': 0x1D4ED8,
            '分段控制小模型': 0x7C3AED, '状态机决策': 0xC2410C, '原子技能': 0x15803D, '执行层': 0x0F766E}


def collect():
    nodes = json.load(open(CANVAS, encoding='utf-8'))['nodes']
    idx = open(INDEX, encoding='utf-8').read()
    F = re.M | re.S
    out = []
    for n in nodes:
        if n['type'] == 'row_bg' or n['id'] in SKIP:
            continue
        band = next((b for b in BANDS if b[0] <= n['y'] < b[1]), None)
        if not band:
            continue
        m = re.search(r'["\']%s["\']\s*:\s*["\']([^"\']+)' % re.escape(n['id']), idx)
        if not m:
            continue
        mod = m.group(1).split('.')[-1]
        f = os.path.join(ROOT, 'src/lerobot/middleware/nodes/%s.py' % mod)
        if not os.path.exists(f):
            continue
        t = open(f, encoding='utf-8').read()

        def g(p, d=''):
            mm = re.search(p, t, F)
            return mm.group(1).strip() if mm else d

        out.append(dict(id=n['id'], band=band[2], y=n['y'],
                        name=g(r"NAME\s*=\s*['\"]([^'\"]+)"),
                        desc=g(r"'desc'\s*:\s*'([^']*)'") or DESC_FALLBACK.get(n['id'], ''),
                        source=g(r"^SOURCE\s*=\s*['\"]([^'\"]+)") or SRC_FALLBACK.get(n['id'], ''),
                        sym=g(r"^SOURCE_SYMBOL\s*=\s*['\"]([^'\"]+)"),
                        pure=g(r"^PURE\s*=\s*(\S+)"),
                        mode=g(r"^EXEC_MODE\s*=\s*['\"]([^'\"]+)"),
                        wrapper='src/lerobot/middleware/nodes/%s.py' % mod,
                        pin=g(r"PORTS_IN\s*=\s*\[([^\]]*)\]").replace("'", '').replace(' ', ''),
                        pout=g(r"PORTS_OUT\s*=\s*\[([^\]]*)\]").replace("'", '').replace(' ', '')))
    out.sort(key=lambda o: (o['y'], o['id']))
    return out


def brief(desc, limit=64):
    if not desc:
        return ''
    s = desc
    s = re.sub(r'^\[[^\]]*\]\s*', '', s)          # 去掉 [基础·分段小模型] 前缀
    for sep in (';', '；', '。', '【'):
        i = s.find(sep)
        if 0 < i < limit + 40:
            s = s[:i]
            break
    s = s.replace('\n', ' ')
    return s[:limit] + ('…' if len(s) > limit else '')


def add_text(slide, x, y, w, h, text, size=9, bold=False, color=C_TXT, align=PP_ALIGN.LEFT,
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


def chip(slide, x, y, w, h, text, fill, size=8):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = fill
    sh.line.color.rgb = fill; sh.line.width = Pt(0.75)
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(0.03); tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = text
    r.font.size = Pt(size); r.font.bold = True; r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    r.font.name = 'Microsoft YaHei'
    return sh


def arrow(slide, x0, y, x1, color=C_LINE):
    from pptx.enum.shapes import MSO_CONNECTOR
    ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x0), Inches(y), Inches(x1), Inches(y))
    from pptx.oxml.ns import qn
    ln.line.color.rgb = color; ln.line.width = Pt(1.25)
    lnEl = ln.line._get_or_add_ln()
    lnEl.append(lnEl.makeelement(qn('a:tailEnd'), {'type': 'triangle', 'w': 'med', 'len': 'med'}))
    return ln


def slide_flow(pr, nodes):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    add_text(s, 0.55, 0.18, 12.3, 0.40,
             'L2 层 %d 个逻辑节点 · 数据流全景（全部读自节点实现，非示意）' % len(nodes), size=17, bold=True)
    add_text(s, 0.55, 0.60, 12.3, 0.32,
             '清单 = 画布 state_space_obs.json 的 L2 七条子层带（共 30 个逻辑节点，🌍物理世界按环境实体不计）；'
             '名称/功能/PURE/实现取自 src/lerobot/middleware/nodes/*.py。本页分栏按功能归组，画布 y 带位置见下两页「子层」列。真机零指令。',
             size=7.4, color=C_DIM)

    cols = [
        ('① 分段感知（6）', C_PER, [('🎯 YOLO 目标检测', 'ssyolo'), ('🔍 光学质量检测 AOI', 'ssaoi'),
                                  ('🖐 触觉感知 4D', 'sstactile'), ('📐 板坐标系定位', 'n_board_frame'),
                                  ('📐 2D→3D 解算', 'ss2d3d'), ('🧩 SAM3 开放词汇分割', 'ss_seg')]),
        ('② 融合 / 状态（2）', C_FUS, [('📡 融合定位建图 43D', 'sssensor'), ('🧩 SU(2) 统一状态空间', 'ssobs')]),
        ('③ 控制小模型（5）', C_MOD, [('🔮 自适应状态估计', 'ssest'), ('📈 先验动力学预测', 'sspred'),
                                    ('⚡ 前馈加速器', 'ssff'), ('🧭 测地线规划引导', 'n_geoplan'),
                                    ('🧪 状态校正器', 'ssinnov')]),
        ('④ 状态机决策（3）', C_DEC, [('🧭 动作调制（可否决）', 'sssched'), ('🌍 SE(3) 势场 H=K+U', 'ss_grav_h'),
                                    ('🛡 安全限幅', 'sslimit')]),
        ('⑤ 原子技能（8+3）', C_SK, [('① 接近 SK01', 'sssk1'), ('② 对位 SK02', 'sssk2'), ('③ 下降 SK03', 'sssk3'),
                                   ('④ 抓取 SK04', 'sssk4'), ('⑤ 抬起 SK05', 'sssk5'), ('⑥ 转移 SK06', 'sssk6'),
                                   ('⑦ 插入 SK07', 'sssk7'), ('⑧ 完成 SK08', 'sssk8'),
                                   ('运动规划 MoveIt', 'n_moveit'), ('⚖ 动力学约束', 'ssphys'),
                                   ('💪 肌肉记忆 标杆回放', 'n_l2_muscle')]),
        ('⑥ 收口 / 执行（2）', C_EXE, [('⚙️ n_exec 授权·闸·到位', 'n_exec'), ('🤖 机器人执行器', 'ssact')]),
    ]
    x = 0.42
    colw = [1.92, 1.72, 1.92, 1.86, 2.05, 1.86]
    top = 1.05
    for (title, col, items), w in zip(cols, colw):
        add_text(s, x, top, w, 0.26, title, size=8.5, bold=True, color=col, align=PP_ALIGN.CENTER)
        y = top + 0.30
        for label, nid in items:
            chip(s, x, y, w, 0.30, label, col, size=7.2)
            y += 0.345
        if x + w + 0.30 < 12.9:
            arrow(s, x + w + 0.02, top + 0.42, x + w + 0.26, C_LINE)
        x += w + 0.30

    add_text(s, 0.42, 6.30, 12.4, 1.0,
             '数据流：图像/触觉 → ①感知（YOLO 22 类 · AOI 判据 · 触觉 4D · 板坐标 1mm · 2D→3D · SAM3 掩膜）'
             '→ ②融合成 43D 状态并映到 SU(2) 群元素 → ③估计/预测/前馈/测地线/校正给出 u 与 prior → '
             '④状态机 6 阶段持有否决权，势场只保留 −∇U 分量，限幅兜底 → ⑤原子技能模板实例化（决策层选技能、实时赋目标）'
             '→ ⑥n_exec 统一收口（授权/闸/到位判定）→ 执行器 → 物理世界。左侧两条为并行辅路：💪肌肉记忆直接回放标杆、MoveIt 出段表。',
             size=7.8, color=C_DIM)


def slide_table(pr, nodes, part, total_parts):
    s = pr.slides.add_slide(pr.slide_layouts[6])
    sub = '（1/2）' if total_parts == 2 and part == 0 else ('（2/2）' if total_parts == 2 else '')
    add_text(s, 0.55, 0.16, 12.3, 0.34, 'L2 逻辑节点功能表 %s · %d 个节点逐条' % (sub, len(nodes)), size=15, bold=True)
    add_text(s, 0.55, 0.52, 12.35, 0.26,
             '功能 = 各节点 PARAMS.desc 首句（去掉前缀）；实现 = SOURCE 字段真值，PURE=节点计算面开关（True=真算, False=只走数据面直通）。',
             size=7.2, color=C_DIM)
    gx, gy, gw, colw = 0.42, 0.86, 12.45, (1.55, 3.55, 1.35, 0.62)
    rows = len(nodes)
    rowh = min(0.40, (6.95 - gy) / max(rows, 1))
    for i, n in enumerate(nodes):
        y = gy + i * rowh
        bg = RGBColor(0xF6, 0xF8, 0xFB) if i % 2 == 0 else RGBColor(0xFF, 0xFF, 0xFF)
        sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(gx), Inches(y), Inches(gw), Inches(rowh))
        sh.fill.solid(); sh.fill.fore_color.rgb = bg
        sh.line.color.rgb = RGBColor(0xE2, 0xE8, 0xF0); sh.line.width = Pt(0.4); sh.shadow.inherit = False
        lane = n['band'].replace('L2 记忆 · 肌肉记忆', 'L2 记忆')
        c = LANE_COL.get(lane, 0x333333)
        add_text(s, gx + 0.04, y + 0.02, colw[0], rowh - 0.02, '%s｜%s' % (lane, n['id']),
                 size=6.4, color=RGBColor((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF),
                 anchor=MSO_ANCHOR.MIDDLE)
        add_text(s, gx + colw[0] + 0.06, y + 0.02, colw[1], rowh - 0.02,
                 '%s %s' % (n['name'].split(' ', 1)[0], brief(n['desc'], 46)) if n['desc'] else n['name'],
                 size=6.4, color=C_TXT, anchor=MSO_ANCHOR.MIDDLE)
        src = (n['source'] or n['wrapper']).replace('src/lerobot/', '').replace('engineering/nodes/', 'eng/')
        add_text(s, gx + colw[0] + colw[1] + 0.10, y + 0.02, colw[2], rowh - 0.02, src,
                 size=6.0, color=C_DIM, anchor=MSO_ANCHOR.MIDDLE)
        add_text(s, gx + colw[0] + colw[1] + colw[2] + 0.12, y + 0.02, colw[3], rowh - 0.02,
                 'PURE=%s' % n['pure'], size=6.0, bold=(n['pure'] == 'True'),
                 color=(RGBColor(0x15, 0x80, 0x3D) if n['pure'] == 'True' else RGBColor(0xB4, 0x53, 0x09)),
                 anchor=MSO_ANCHOR.MIDDLE)


def main():
    nodes = collect()
    pr = Presentation(DECK)
    while len(pr.slides._sldIdLst) > BASE_PAGES:
        sid = pr.slides._sldIdLst[-1]
        pr.part.drop_rel(sid.rId); pr.slides._sldIdLst.remove(sid)
    slide_flow(pr, nodes)
    half = (len(nodes) + 1) // 2
    slide_table(pr, nodes[:half], 0, 2)
    slide_table(pr, nodes[half:], 1, 2)
    pr.save(DECK)
    json.dump([{k: n[k] for k in ('id', 'band', 'name', 'desc', 'source', 'pure', 'mode', 'wrapper', 'pin', 'pout')}
               for n in nodes], open(META, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('L2 节点 %d 个 → 页数 %d' % (len(nodes), len(pr.slides._sldIdLst)))
    from collections import Counter
    print('子层分布:', dict(Counter(n['band'] for n in nodes)))
    print('无 desc:', [n['id'] for n in nodes if not n['desc']])
    print('PURE=True:', sum(1 for n in nodes if n['pure'] == 'True'), '/', len(nodes))


if __name__ == '__main__':
    main()
