# -*- coding: utf-8 -*-
"""deck_front.py — 方案册前 12 页（一页一个结论，字大、人话、有据）

设计原则（老倪口径）：
  1. 每页只讲一个结论，标题就是结论，正文只留支撑它的 2~4 条事实；
  2. 正文最小 10.5pt、标题 27pt、关键数字 40pt 以上 —— 远看不吃力；
  3. 所有数字现场从真源算（节拍/成本/工位），不写死，页脚注明来源；
  4. 不堆缩写，不写"本方案旨在"，用工程语言说清楚"凭什么"。
"""

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

INK = RGBColor(0x14, 0x1D, 0x28)
SUB = RGBColor(0x5A, 0x65, 0x74)
ACC = RGBColor(0x1B, 0x64, 0xD1)
WARM = RGBColor(0xB2, 0x3A, 0x0B)
GREEN = RGBColor(0x12, 0x6A, 0x44)
LINE = RGBColor(0xD3, 0xD9, 0xE1)
SOFT = RGBColor(0xF2, 0xF5, 0xF9)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "微软雅黑"

M = 0.82                     # 左边距
CW = 13.333 - 2 * M          # 内容宽 11.69
VER = "5.50.C-R5"
TOTAL = 51
_PB = [0]          # 前置页起点(母版仍排在后面时, 页码要按本册顺序算)
DATE = "2026-11-02"


def _tb(s, x, y, w, h, text, size=12, bold=False, color=INK, align=PP_ALIGN.LEFT,
        spacing=1.25, anchor=MSO_ANCHOR.TOP):
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    for i, ln in enumerate(str(text).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = ln
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        r.font.name = FONT
    return box


def _rect(s, x, y, w, h, fill, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE, adj=None):
    sh = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(1)
    sh.shadow.inherit = False
    if adj is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            sh.adjustments[0] = adj
        except Exception:                                     # noqa: BLE001
            pass
    return sh


def page(pr, kicker, title, sub=None, no=None, foot=None, tsize=27):
    """新建一页：页眉小标 + 结论式大标题 + 可选副标题 + 页脚。

    页码不手填 —— 按当前页序自动取, 中间插页不会把后面的页码写错。
    """
    s = pr.slides.add_slide(pr.slide_layouts[6])
    no = (len(pr.slides) - _PB[0]) if _PB[0] else len(pr.slides)
    _tb(s, M, 0.42, CW, 0.26, kicker, size=10.5, bold=True, color=ACC)
    _tb(s, M, 0.76, CW, 0.62 if tsize <= 23 else 0.86, title, size=tsize, bold=True,
        color=INK, spacing=1.12)
    _rect(s, M, 1.62, 1.5, 0.05, ACC, shape=MSO_SHAPE.RECTANGLE)
    _rect(s, M + 1.5, 1.64, CW - 1.5, 0.012, LINE, shape=MSO_SHAPE.RECTANGLE)
    if sub:
        _tb(s, M, 1.78, CW, 0.34, sub, size=13, color=SUB, spacing=1.25)
    left = ("Z-MAX · 光模块上下料双臂工作站 · %s · %s" % (VER, DATE))
    _tb(s, M, 6.94, 8.6, 0.24, left, size=9.5, color=SUB)
    if no is not None:
        _tb(s, 13.333 - M - 1.2, 6.94, 1.2, 0.24, "%02d / %d" % (no, TOTAL), size=9.5,
            color=SUB, align=PP_ALIGN.RIGHT)
    if foot:
        _tb(s, M, 6.72, CW, 0.22, foot, size=9.5, color=SUB)
    return s


def kpis(s, y, items, h=1.42, gap=0.28, vsize=38, lsize=11.5):
    """一排关键数字： (数值, 单位, 说明, 备注)。"""
    n = len(items)
    w = (CW - gap * (n - 1)) / n
    for i, it in enumerate(items):
        val, unit, label = it[0], it[1], it[2]
        note = it[3] if len(it) > 3 else ""
        x = M + i * (w + gap)
        _rect(s, x, y, w, h, SOFT, shape=MSO_SHAPE.RECTANGLE)
        _rect(s, x, y, 0.06, h, ACC, shape=MSO_SHAPE.RECTANGLE)
        _tb(s, x + 0.26, y + 0.09, w - 0.44, 0.60, val, size=vsize, bold=True, color=INK,
            spacing=1.0)
        if unit:
            _tb(s, x + 0.26, y + 0.72, w - 0.44, 0.24, unit, size=11.5, bold=True, color=ACC)
        _tb(s, x + 0.26, y + (0.98 if unit else 0.74), w - 0.44, 0.24, label, size=lsize,
            bold=True, color=INK)
        if note:
            _tb(s, x + 0.26, y + (1.22 if unit else 0.98), w - 0.44, 0.22, note, size=9.5,
                color=SUB)


def bullets(s, y, items, size=12.5, w=CW, gap=0.52, color=INK, lead="— ", x=None):
    x = M if x is None else x
    for i, t in enumerate(items):
        yy = y + i * gap
        _tb(s, x, yy, 0.22, 0.3, "•", size=size + 1, bold=True, color=ACC)
        _tb(s, x + 0.26, yy, w - 0.26, gap - 0.06, lead + t if lead else t, size=size,
            color=color, spacing=1.26)


def callout(s, y, text, size=13.5, color=WARM, w=CW, h=0.62, label=None):
    _rect(s, M, y, 0.07, h, color, shape=MSO_SHAPE.RECTANGLE)
    if label:
        _tb(s, M + 0.22, y + 0.02, 1.6, 0.24, label, size=10, bold=True, color=color)
        _tb(s, M + 0.22, y + 0.22, w - 0.3, h - 0.24, text, size=size, color=INK, spacing=1.25)
    else:
        _tb(s, M + 0.22, y + 0.10, w - 0.3, h - 0.16, text, size=size, color=INK, spacing=1.25)


def formula(s, y, text, note=""):
    _rect(s, M, y, CW, 0.90, SOFT, shape=MSO_SHAPE.RECTANGLE)
    _tb(s, M + 0.28, y + 0.14, CW - 0.5, 0.44, text, size=17, bold=True, color=INK)
    if note:
        _tb(s, M + 0.28, y + 0.62, CW - 0.5, 0.22, note, size=9.5, color=SUB)


def table(s, y, headers, rows, widths, size=11, hsize=10.5, rowh=0.42, hdrh=0.38,
          highlight_col=None):
    x = M
    _rect(s, M, y, sum(widths), hdrh, RGBColor(0x1F, 0x2B, 0x39), shape=MSO_SHAPE.RECTANGLE)
    for i, h in enumerate(headers):
        _tb(s, x + 0.16, y + 0.08, widths[i] - 0.2, 0.24, h, size=hsize, bold=True, color=WHITE)
        x += widths[i]
    for r, row in enumerate(rows):
        yy = y + hdrh + r * rowh
        _rect(s, M, yy, sum(widths), rowh, WHITE if r % 2 == 0 else SOFT, shape=MSO_SHAPE.RECTANGLE)
        _rect(s, M, yy + rowh - 0.008, sum(widths), 0.008, LINE, shape=MSO_SHAPE.RECTANGLE)
        x = M
        for i, v in enumerate(row):
            bold = (highlight_col is not None and i == highlight_col)
            _tb(s, x + 0.16, yy + 0.09, widths[i] - 0.2, rowh - 0.12, str(v), size=size,
                bold=bold, color=INK if not bold else ACC)
            x += widths[i]


# ─────────────────────────────────────────────── 12 页正文
def build_front(pr, S, cost):
    """追加 13 页（含轨迹页），返回页数。"""
    _PB[0] = len(pr.slides)
    tier = {t["id"]: t for t in cost["tiers"]}
    A, B, C = tier["A"], tier["B"], tier["C"]
    tact = S["tact"]
    uph = S["uph"]
    lo, hi = S["dwell"]

    # ① 封面
    s = pr.slides.add_slide(pr.slide_layouts[6])
    _rect(s, 0, 0, 13.333, 7.5, RGBColor(0x0E, 0x17, 0x24), shape=MSO_SHAPE.RECTANGLE)
    _rect(s, 0, 0, 0.16, 7.5, ACC, shape=MSO_SHAPE.RECTANGLE)
    _tb(s, 1.05, 1.28, 10.8, 0.3, "具身智能 · 精密装配工作站", size=12, bold=True,
        color=RGBColor(0x8F, 0xB6, 0xF0))
    _tb(s, 1.05, 1.72, 11.0, 1.5, "光模块上下料与插拔工作站", size=40, bold=True, color=WHITE,
        spacing=1.1)
    _tb(s, 1.05, 3.30, 10.6, 0.9, "一台双臂机器人，把 0.5 毫米一级的插拔动作\n做到 11.5 秒一件，单件成本不到人工的三分之一",
        size=17, color=RGBColor(0xC9, 0xD4, 0xE2), spacing=1.35)
    for i, (v, u, l) in enumerate([("%.3f" % tact, "秒 / 件", "稳态节拍"),
                                   ("%d" % round(uph), "件 / 小时", "设计目标 300 件"),
                                   ("30", "万元起", "整机含基础软件")]):
        x = 1.05 + i * 3.6
        _tb(s, x, 4.72, 3.2, 0.66, v, size=34, bold=True, color=WHITE)
        _tb(s, x, 5.40, 3.2, 0.26, u, size=11.5, bold=True, color=RGBColor(0x8F, 0xB6, 0xF0))
        _tb(s, x, 5.68, 3.2, 0.26, l, size=10.5, color=RGBColor(0xA6, 0xB2, 0xC2))
    _tb(s, 1.05, 6.62, 11.0, 0.26, "方案版本 %s　·　%s　·　Z-MAX 天枢" % (VER, DATE), size=10.5,
        color=RGBColor(0x8A, 0x97, 0xA8))
    n = 1

    # ② 一页看懂
    s = page(pr, "一页看懂", "这台机器解决什么问题，凭什么值这个钱", no=2)
    kpis(s, 1.80, [("%.3f" % tact, "秒 / 件", "稳态节拍", "%.2f 秒一轮 4 件" % S["dur"]),
                   ("%d" % round(uph), "件 / 小时", "节拍产能", "两班 16 小时 · OEE 0.85"),
                   ("%.3f" % A["client_unit_cost"], "元 / 件", "客户单件成本", "人工折算 0.36 元"),
                   ("%.2f" % A["payback_years"], "年", "投资回收期", "按加工费 0.35 元/件")])
    bullets(s, 3.42, [
        "做的是光模块上下料与插拔：从料盘取件、对准设备孔、压入到位，再交给外观检测判良品与不良品。",
        "两台六轴机械臂分工：左臂负责料盘与摆盘，右臂负责插拔与质检取图，双臂并行、互不等待。",
        "每 100 毫秒算一拍：视觉给位置、力传感器给边界，动作在四道闸门里逐拍放行，任何一道不过就停。",
        "算法不是演示：状态空间里 30 个基础节点、62 条连线每拍都在跑，实测计算量 13.7 毫秒。",
    ], size=13, gap=0.56)
    callout(s, 5.86, "同样的活人工做，单件成本约 0.36 元；这台机器 A 档配置是 %.3f 元，省 %.1f%%。"
                     % (A["client_unit_cost"], A["client_save_pct"]), size=14)
    n += 1

    # ③ 难点
    s = page(pr, "物理分析", "这道工序的难点不在「搬」，在「插」", no=3)
    bullets(s, 1.86, [
        "压入只有 0.5 毫米一步：每进 0.5 毫米核一次位移与接触力，压偏或压过头都会伤到金手指与簧片。",
        "力只能给到 40 牛顿：插入与到位两个阶段力上限最严，超过就停住上报，宁可不进也不硬压。",
        "到位要连续两次确认：位置误差 ≤ 2 毫米、姿态偏差 ≤ 0.5 度，两拍一致才算到位，缺姿态真值就不认。",
        "视觉精度 1.74 毫米：手眼标定后二维转三维的落点误差，剩下的误差靠力与位移闭环兜住。",
    ], size=13, gap=0.62)
    callout(s, 4.52, "0.5 毫米、40 牛顿、2 毫米、0.5 度 —— 四个数字决定了这不是一台「会动」的机器人，"
                     "而是一台知道自己站在哪、用了多大力、有没有真到位的机器人。", size=13.5, h=0.86)
    _tb(s, M, 5.62, CW, 0.3, "由此引出的四个硬要求", size=12, bold=True, color=ACC)
    for i, (v, l) in enumerate([("±0.5", "毫米级落点"), ("40", "牛·力上限"),
                                ("100", "毫秒控制周期"), ("2 次", "到位复核")]):
        x = M + i * 2.95
        _rect(s, x, 5.98, 2.72, 0.78, SOFT, shape=MSO_SHAPE.RECTANGLE)
        _tb(s, x + 0.18, 6.04, 2.4, 0.4, v, size=21, bold=True, color=INK)
        _tb(s, x + 0.18, 6.46, 2.4, 0.24, l, size=10.5, color=SUB)
    n += 1

    # ④ 解法总图
    s = page(pr, "方案总图", "一层管一件事：上层给意图，下层给动作，收口只有一处", no=4)
    layers = [
        ("L5", "理解与编排", "14 个节点", "看画面、读工单，把「做哪件、怎么排」变成任务", ACC),
        ("L4", "自主专家", "16 个节点", "标定、流形世界模型、异常推理，处理现场偏差", RGBColor(0x6B, 0x4C, 0xC4)),
        ("L3", "视觉决策", "4 个节点", "视觉编码 + 动作序列，把场景变成候选动作", RGBColor(0x0E, 0x74, 0x90)),
        ("L2", "基础能力", "30 个节点", "感知、状态估计、规划、技能、执行收口，每拍都在跑", GREEN),
        ("执行", "四道闸门", "1 条通路", "授权 → 逐段核对 → 物理限幅 → 到位复核", WARM),
    ]
    for i, (tag, name, cnt, desc, col) in enumerate(layers):
        y = 1.86 + i * 0.86
        _rect(s, M, y, 0.96, 0.72, col, shape=MSO_SHAPE.RECTANGLE)
        _tb(s, M, y + 0.20, 0.96, 0.3, tag, size=16, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        _tb(s, M + 1.12, y + 0.04, 2.5, 0.3, name, size=15, bold=True, color=INK)
        _tb(s, M + 1.12, y + 0.38, 2.5, 0.26, cnt, size=11, color=col, bold=True)
        _tb(s, M + 3.72, y + 0.16, CW - 3.9, 0.44, desc, size=12, color=SUB, spacing=1.2)
    _tb(s, M, 6.24, CW, 0.26,
        "基础层 30 个节点之间 62 条连线；上层 29 个节点另有 50 条连线接入。每拍数据都在流动，不是画出来的框图。",
        size=11.5, color=SUB)
    callout(s, 6.56, "所有要动机械臂的命令只走一个出口：动作执行器。授权、段号、限幅、到位在这里合并核对，"
                     "任何一处不过就停在这一拍。", size=12, h=0.4, label="收口")
    n += 1

    # ⑤ 感知
    s = page(pr, "能力 · 感知", "先看清楚：3 类目标，落点精确到毫米", no=5)
    kpis(s, 1.82, [("3", "类", "识别目标", "peg · OPT_Gold · 金手指"),
                   ("1.74", "毫米", "手眼落点误差", "TSAI 闭环"),
                   ("4", "路", "相机输入", "臂上含深度")], h=1.28, vsize=36)
    bullets(s, 3.34, [
        "识别：在役权重直接在产线实拍帧上跑 —— 机械臂侧 2 类（peg、OPT_Gold）、外观侧 1 类金手指，输出类别、位置框与朝向，不依赖重新训练。",
        "分割：SAM3 用检测框作提示，把目标细化到像素轮廓，掩膜只取物体内部像素估深度，避开背景干扰。",
        "定位：框中心做反投影，配合相机内参与台面高度，算出基座坐标系下的毫米位置。",
        "质检：外观判据在 5000 微秒曝光下取图，判据图标出缺陷位置，与产线 AOI 同一套判决标准。",
    ], size=13, gap=0.58)
    callout(s, 5.96, "四路画面全部进同一个页面：臂上 D405（640×480 含深度）、金手指相机、表面相机、本机固定相机，"
                     "页面标帧龄，看得到画面就知道数据新不新。", size=12.5, h=0.6)
    n += 1

    # ⑥ 决策
    s = page(pr, "能力 · 决策", "100 毫秒一拍，14 个节点算完只要 13.7 毫秒", no=6)
    kpis(s, 1.82, [("100", "毫秒", "控制周期", "10 次 / 秒"),
                   ("13.7", "毫秒", "全链计算", "占周期 13.7%"),
                   ("43", "维", "统一状态", "视觉 + 触觉 + 质量")], h=1.28, vsize=36)
    bullets(s, 3.34, [
        "估状态 0.25 毫秒：从观测里估出潜状态，预测与校正都拿它当基准。",
        "预测与校正并行：先验模型提前一拍预测，状态校正器用真实观测算残差，顺手给出接触概率。",
        "快通道 2.65 毫秒：不推整条状态机，直接给建议动作按三成权重并入，响应更接近熟练工。",
        "六阶段状态机可否决：阶段不满足就这一拍不发动作；力场按势能下降方向合成，横向分量超过 60 度直接否决。",
    ], size=13, gap=0.58)
    callout(s, 5.96, "算力全部有实测：13.7 毫秒里没有一项是估算，节点级耗时取自常驻循环每 100 毫秒一拍的记录。",
            size=12.5, h=0.6)
    n += 1

    # ⑦ 执行
    s = page(pr, "能力 · 执行", "从算出来到动起来，中间有四道闸，一道都不能省", no=7)
    gates = [("①", "授权核对", "按次授权，超时即失效", "没授权不下发"),
             ("②", "逐段核对", "段号衔接、上一段真到位", "跳段就拒绝"),
             ("③", "物理限幅", "速度、加速度、加加速度、行程、动量、质量变化率", "越界就裁"),
             ("④", "到位复核", "位置 ≤2 毫米、姿态 ≤0.5 度，连续两次", "不认就不走下一段")]
    for i, (tag, name, desc, tail) in enumerate(gates):
        y = 1.86 + i * 1.06
        _rect(s, M, y, 0.62, 0.9, ACC if i < 3 else WARM, shape=MSO_SHAPE.RECTANGLE)
        _tb(s, M, y + 0.28, 0.62, 0.3, tag, size=17, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        _tb(s, M + 0.82, y + 0.06, 3.0, 0.3, name, size=15, bold=True, color=INK)
        _tb(s, M + 3.9, y + 0.04, 5.6, 0.62, desc, size=11.5, color=SUB, spacing=1.2)
        _tb(s, M + 9.7, y + 0.28, 2.0, 0.3, tail, size=11.5, bold=True, color=WARM)
    callout(s, 6.16, "四道闸都在同一条通路上：动作执行器。它是唯一能碰机械臂的出口，其它节点只读回执。",
            size=12.5, h=0.52)
    n += 1

    # ⑧ 力控与安全
    s = page(pr, "能力 · 力控", "力是最后一道保险：给到 40 牛顿，超过就停", no=8)
    formula(s, 1.84, "u = K·ξ − B·ξ̇ + F_d        H = K + U",
            "SE(3) 几何阻抗：刚度 K 收位置误差，阻尼 B 抑制速度冲击，F_d 由分层力场给出；H 是系统能量，用来判动作是否越界")
    bullets(s, 3.02, [
        "力从六维力传感器来，不是从模型猜的；每一拍都带上力的方向与大小。",
        "分层力按势能下降方向合成：与目标方向夹角超过 60 度的横向分量直接否决，不让机器人把工件横向拖走。",
        "插入分三级递进：每级压入后核对位移与力，任何一级超限就停住上报，交给上层决定微调还是换件。",
    ], size=13, gap=0.58)
    callout(s, 5.30, "40 牛顿是工艺给的硬上限，写进限幅与状态机两处；真机上超过就停，仿真里也一样 —— 训练和现场用同一套规则。",
            size=13, h=0.66)
    for i, (v, l) in enumerate([("40 N", "插入力上限"), ("60°", "横向分量否决角"), ("6 维", "力与力矩")]):
        x = M + i * 3.95
        _tb(s, x, 6.16, 3.6, 0.44, v, size=24, bold=True, color=INK)
        _tb(s, x, 6.62, 3.6, 0.24, l, size=10.5, color=SUB)
    n += 1

    # ⑨ 数字孪生
    s = page(pr, "数字孪生", "同一份场景，先在孪生里跑通，再交给真机", no=9)
    kpis(s, 1.82, [("392", "段", "一轮轨迹", "14 件循环"),
                   ("112", "段", "段表接口", "逐段可回放"),
                   ("10", "次 / 秒", "下发力", "与真机同频")], h=1.28, vsize=36)
    bullets(s, 3.34, [
        "孪生和真机用同一套节点代码：差异只在执行最后一层，换成真机时规划和判据逻辑一行不改。",
        "AR 页面把四路相机、三维视图、轨迹与执行相位放在同一屏，帧龄实时显示，动作和数据对得上才算数。",
        "每段动作都有回执：段号、相位、到位残差、授权轮次，出问题能回到具体那一段。",
        "真机现在未连接时，页面如实显示「仿真位置」，不拿仿真结果当现场实测。",
    ], size=13, gap=0.58)
    callout(s, 5.96, "判断真伪的办法很简单：仿真跑出来的节拍，用 AR 台账里同一动作标签的实测值代回，差多少一眼就能看出来。",
            size=12.5, h=0.6)
    n += 1

    # ⑩ 轨迹页：一件光模块在世界坐标系里的整条路径（图由 deck_traj_fig 现算现画）
    import deck_traj_fig as _T
    TR = _T.render()
    s = page(pr, "数字孪生 · 轨迹", "一件光模块，在右臂世界坐标系里走完的一条连续轨迹", no=10,
             tsize=23)
    s.shapes.add_picture(TR["img"], Inches(0.86), Inches(1.46), width=Inches(5.50))
    RX2, RW2 = 6.72, 5.76
    _tb(s, RX2, 1.52, RW2, 0.26, "五个阶段 · 同一件模块 · 段表逐段计时", size=11, bold=True, color=ACC)
    PHN = ["取件", "插入", "拔出", "检测 AOI", "分拣"]
    PHD = ["槽 1 夹起，抬到 218 毫米高度",
           "对到孔口，压入 47 毫米后松爪",
           "孔内重新夹住，反向拔出，转到检测位",
           "金手指 + 4 个侧面，共 9 段取图",
           "送回下料盘，落位后松爪退出"]
    PHC = [GREEN, ACC, RGBColor(0x0E, 0x8A, 0x9B), WARM, RGBColor(0x7A, 0x3F, 0xB8)]
    for i in range(5):
        y = 1.86 + i * 0.86
        _rect(s, RX2, y, 0.06, 0.72, PHC[i], shape=MSO_SHAPE.RECTANGLE)
        _tb(s, RX2 + 0.20, y + 0.02, 1.7, 0.26, PHN[i], size=13, bold=True, color=PHC[i])
        _tb(s, RX2 + 2.05, y + 0.04, 3.4, 0.24,
            "%.2f 秒 · %d 段" % (TR["dur"][i], TR["nseg_ph"][i]), size=10.5, bold=True, color=SUB)
        _tb(s, RX2 + 0.20, y + 0.34, RW2 - 0.3, 0.36, PHD[i], size=10.5, color=INK, spacing=1.2)
    callout(s, 6.20, "这条路径不查视觉也能走完（记忆直通，按段表 11.49 秒/件）；感知在换件或偏位时接管，"
                     "改的是落点，不改这条路径的长度。", size=12, h=0.62)
    n += 1

    # ⑪ 验证
    s = page(pr, "验证", "三处证据：仿真跑通、孪生对得上、真机标得准", no=11)
    ev = [("仿真", "7 段闭环全部走完", "392 步 · 112 段段表", GREEN),
          ("孪生", "台账同标签 112/112 命中", "逐段回执可回放", ACC),
          ("真机", "手眼 1.74 毫米", "AOI 判决与产线同一标准", RGBColor(0x6B, 0x4C, 0xC4))]
    for i, (tag, big, small, col) in enumerate(ev):
        x = M + i * 3.95
        _rect(s, x, 1.86, 3.62, 1.62, SOFT, shape=MSO_SHAPE.RECTANGLE)
        _rect(s, x, 1.86, 3.62, 0.06, col, shape=MSO_SHAPE.RECTANGLE)
        _tb(s, x + 0.26, 2.06, 3.1, 0.26, tag, size=11, bold=True, color=col)
        _tb(s, x + 0.26, 2.36, 3.1, 0.62, big, size=17, bold=True, color=INK, spacing=1.15)
        _tb(s, x + 0.26, 3.04, 3.1, 0.3, small, size=10.5, color=SUB)
    bullets(s, 3.74, [
        "仿真侧：不接上层编排，基础层自己也能跑完整件取放，七段动作一步不缺。",
        "孪生侧：AR 台账里 112 段动作标签全部命中，节拍两本账能逐段对上。",
        "真机侧：手眼标定 1.74 毫米、外观判决与产线 10082/10083 同一标准，指令零下发时也照样判。",
    ], size=13, gap=0.56)
    callout(s, 5.72, "还没闭环的两项如实写：相机外参与台面高度要现场标定，标定前不承诺毫米级；"
                     "「合并取图提速」只是理论，没有仿真验证。", size=12.5, h=0.7)
    n += 1

    # ⑪ 成本
    s = page(pr, "成本与性价比", "三档配置，单件成本是人工的三分之一到二分之一", no=11)
    rows = []
    for t in (A, B, C):
        rows.append(("%s 档 · %s" % (t["id"], t["name"].split("·")[-1].strip()),
                     "%.0f 万" % (t["price_set"] / 10000),
                     "%.2f 万" % (t["capex"] / 10000),
                     "%.3f 元" % t["client_unit_cost"],
                     "省 %.1f%%" % t["client_save_pct"],
                     "%.2f 年" % t["payback_years"]))
    table(s, 1.86, ["配置", "售价", "硬件成本", "客户单件成本", "对比人工", "回本周期"], rows,
          [3.85, 1.45, 1.65, 2.05, 1.4, 1.29], size=11.5, rowh=0.5)
    _tb(s, M, 3.92, CW, 0.3,
        "人工折算 0.36 元/件（一名操作工 9 万元/年），A 档 %.3f 元、B 档 %.3f 元、C 档 %.3f 元。"
        % (A["client_unit_cost"], B["client_unit_cost"], C["client_unit_cost"]),
        size=11.5, color=SUB)
    bullets(s, 4.32, [
        "A 档 30 万元：单任务基础层，两班 16 小时、OEE 0.85，年产能 128.6 万件，14 天交付。",
        "B 档 40 万元：加多任务编排与换型，同产能，28 天交付，适合多品种小批量。",
        "C 档 55 万元：加安全分级与自主恢复，三班 20 小时，年产能 166.4 万件，60 天交付含认证送审。",
    ], size=12, gap=0.5)
    callout(s, 5.96, "报价上限锁在 30 / 40 / 55 万：硬件毛利率 37.2% / 42.9% / 49.0%，"
                     "不靠卖硬件赚钱，靠软件许可与按件运营分享产能收益。", size=12.5, h=0.62)
    n += 1

    # ⑫ 边界
    s = page(pr, "交付边界", "我们承诺什么，不承诺什么，一次说清", no=12)
    _tb(s, M, 1.86, 5.6, 0.32, "承诺", size=14, bold=True, color=GREEN)
    bullets(s, 2.24, [
        "几何、节拍、判据三本账都能逐条复核，每个数字注明来源文件。",
        "交付周期按档：14 / 28 / 60 天，标定、集成、验收分段可查。",
        "四道闸门在真机与仿真里同一套规则，超限即停，不留后门。",
    ], size=12, gap=0.54, w=5.5)
    _tb(s, M + 6.0, 1.86, 5.6, 0.32, "不承诺", size=14, bold=True, color=WARM)
    bullets(s, 2.24, [
        "不做白盒源码交付：给的是可复核的数字与接口，不是整套算法源码。",
        "不在未标定条件下承诺毫米级：相机外参与台面高度是现场前提。",
        "不把理论提速写成已实现：合并取图、抬升加速度都还要真机验证。",
    ], size=12, gap=0.54, w=5.5, lead="", x=M + 6.0)
    _tb(s, M + 6.0, 2.24, 5.5, 0.04, "", size=8)
    callout(s, 4.40, "全册自检逐条回到来源文件重算，当前全部通过；没通过的一项也不会写成通过。",
            size=13, h=0.62)
    _tb(s, M, 5.36, CW, 0.3, "为什么值得先上这一台", size=12.5, bold=True, color=ACC)
    _tb(s, M, 5.70, CW, 1.0,
        "按 A 档算：一台设备 30 万元，替下一名操作工（9 万元/年），0.68 年回本；"
        "设备还能把插拔的一致性固定下来 —— 每一次压入的位移、力与到位判定都留了记录，"
        "良品率不靠人的手感。", size=12, color=INK, spacing=1.35)
    return 12
