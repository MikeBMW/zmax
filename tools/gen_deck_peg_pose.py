#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_deck_peg_pose.py — 生成《光模块 3D 位姿检测 · 状态空间功能清单》PPT。

数据口径(全部来自本机实测/真源文件, 不手写估算):
  · 状态空间 55D 分段: src/lerobot/policies/left_right/state_space/unified_state55.py
  · 模块尺寸/槽位:      config/points/tray_slots_14.json
  · 相机内参/深度:      Orin :8794 /intrinsics (848×480, fx436.71 fy436.056 cx422.275 cy238.513)
  · 检出/残差:         本轮实测 (见各页脚注)
"""
from __future__ import annotations

import os

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

OUT = "/home/ubuntu/zmax/zmax_data/reports/光模块3D位姿_状态空间功能清单_v1.pptx"
W, H = 13.333, 7.5
INK = RGBColor(0x1E, 0x29, 0x3B)
MUTED = RGBColor(0x64, 0x74, 0x8B)
ACC = RGBColor(0x0E, 0xA5, 0xE9)
ACC2 = RGBColor(0xF5, 0x9E, 0x0B)
OK = RGBColor(0x16, 0xA3, 0x4A)
BAD = RGBColor(0xDC, 0x26, 0x26)
CJK = "Noto Sans CJK SC"


def _ea(run, name=CJK):
    """CJK 字形必须单独写 <a:ea typeface>, 否则中文回落到主题字体(渲染错)。"""
    from pptx.oxml.ns import qn
    run.font.name = name
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", name)


def txt(slide, x, y, w, h, s, size=14, color=INK, bold=False, align=PP_ALIGN.LEFT, spacing=1.0):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.03)
    tf.margin_top = tf.margin_bottom = 0
    lines = s.split("\n")
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = ln
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        _ea(r)
    return tb


def box(slide, x, y, w, h, fill=None, line=None, lw=1.0):
    from pptx.enum.shapes import MSO_SHAPE
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(lw)
    sh.shadow.inherit = False
    sh.text_frame.word_wrap = True
    return sh


def table(slide, x, y, w, rows, widths=None, head_size=11, body_size=10.5, row_h=0.3, head_fill=ACC):
    nr, nc = len(rows), len(rows[0])
    shape = slide.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(w), Inches(row_h * nr))
    t = shape.table
    if widths:
        tot = sum(widths)
        for i, cw in enumerate(widths):
            t.columns[i].width = Inches(w * cw / tot)
    for ri, row in enumerate(rows):
        t.rows[ri].height = Inches(row_h)
        for ci, val in enumerate(row):
            cell = t.cell(ri, ci)
            cell.margin_left = cell.margin_right = Inches(0.05)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = head_fill if ri == 0 else (RGBColor(0xF8, 0xFA, 0xFC) if ri % 2 else RGBColor(0xFF, 0xFF, 0xFF))
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if ci else PP_ALIGN.CENTER
            r = p.add_run()
            r.text = str(val)
            r.font.size = Pt(head_size if ri == 0 else body_size)
            r.font.bold = ri == 0
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if ri == 0 else INK
            _ea(r)
    return shape


def page(prs, title, sub=None, n=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, 0.06, fill=ACC)
    txt(s, 0.55, 0.30, 11.2, 0.5, title, 24, INK, True)
    if sub:
        txt(s, 0.55, 0.88, 12.2, 0.34, sub, 11.5, MUTED)
    if n is not None:
        txt(s, W - 1.0, H - 0.45, 0.6, 0.3, str(n), 10, MUTED, align=PP_ALIGN.RIGHT)
        txt(s, 0.55, H - 0.45, 7.0, 0.3, "Z-MAX · 统一状态空间 55D · v5.50.782", 9, MUTED)
    return s


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)

    # ── 1 封面 ────────────────────────────────────────────────
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, H, fill=RGBColor(0x0B, 0x14, 0x24))
    box(s, 0.9, 1.55, 0.09, 2.5, fill=ACC)
    txt(s, 1.25, 1.55, 10.8, 0.95, "光模块 3D 位姿检测", 40, RGBColor(0xFF, 0xFF, 0xFF), True)
    txt(s, 1.25, 2.55, 11.0, 0.6, "统一状态空间 55D 的输出 · 功能清单与验收口径", 19, RGBColor(0xC8, 0xD6, 0xE5))
    txt(s, 1.25, 3.55, 11.0, 0.45, "状态源 unified_state55.py · 位姿段 peg_xyz[4:7] + peg_quat[51:55]", 13, ACC)
    txt(s, 1.25, 5.55, 11.0, 0.35, "Z-MAX 550A / 550C · 版本 5.50.782 · 2026-11-22", 12, RGBColor(0x8A, 0x9B, 0xAE))
    txt(s, 1.25, 5.95, 11.0, 0.35, "口径: 所有数字均为本机实测或真源文件取值, 未达标的项按未达标标注", 10.5, RGBColor(0x64, 0x74, 0x8B))

    # ── 2 一页结论 ────────────────────────────────────────────
    s = page(prs, "一页结论", "目标 / 现状 / 缺口 —— 三段式, 数字可复核", 2)
    cols = [
        ("目标", ACC, [
            "光模块 3D 位姿成为统一状态空间的**一等输出**",
            "位置 3 维进 peg_xyz[4:7]，姿态四元数进 peg_quat[51:55]",
            "原点 = 模块金手指端中间；抓取时与 tool1 重合",
            "精度目标：位置 ≤2mm · 姿态 ≤1.0° · 单帧 ≤100ms",
        ]),
        ("现状", OK, [
            "2D 检出：conf 0.78~0.85，判据 conf≥0.5 + 3 帧漂移<10px",
            "深度：848×480@30，单位 0.1mm/unit，内参已取到",
            "3D 框：最长边 72.1mm vs QSFP28 72.0mm，差 0.1mm",
            "原点锚定：实测与检测框边沿差 0~1px",
            "外参：4 点 PnP 残差 RMS 9.36px（≈6~7mm），未达 2mm",
        ]),
        ("缺口", ACC2, [
            "手眼外参未闭环：手工摆放模块致 ±5~10mm 位置不确定度",
            "姿态维尚未接入状态空间（本版只落位置）",
            "3D 框宽/高受槽壁与阴影污染（实测 40.9mm vs 18.35mm）",
            "下一步：模块夹爪上做「已知位姿靶标」标定",
        ]),
    ]
    for i, (name, col, items) in enumerate(cols):
        x = 0.55 + i * 4.15
        box(s, x, 1.45, 3.85, 0.52, fill=col)
        txt(s, x + 0.16, 1.55, 3.5, 0.34, name, 15, RGBColor(0xFF, 0xFF, 0xFF), True)
        box(s, x, 1.97, 3.85, 4.35, fill=RGBColor(0xFA, 0xFB, 0xFD), line=RGBColor(0xE2, 0xE8, 0xF0))
        y = 2.12
        for it in items:
            bold = "**" in it
            clean = it.replace("**", "")
            txt(s, x + 0.16, y, 3.55, 0.9, "· " + clean, 10.5, INK if not bold else col, bold)
            y += 0.34 + 0.19 * max(0, (len(clean) - 26) // 26)

    # ── 3 状态空间 55D 分段表 ─────────────────────────────────
    s = page(prs, "统一状态空间 55D：光模块位姿落在哪一段",
             "真源 src/lerobot/policies/left_right/state_space/unified_state55.py · SLICE 按名取，不许消费端数下标", 3)
    rows = [["段名", "切片", "维", "单位", "来源 / 说明"],
            ["tcp_p", "0:3", "3", "m", "手爪真实位置 = runtime 控制锚"],
            ["grip_scalar", "3:4", "1", "-", "夹爪开合标量"],
            ["peg_xyz", "4:7", "3", "m", "★ 光模块位置（真源: env._gold()[0]）"],
            ["peg_minus_tcp", "7:10", "3", "m", "相对位移（策略主特征）"],
            ["grip_xy", "10:12", "2", "-", "夹爪两指（冗余保留）"],
            ["q_right / dq_right", "12:24", "12", "rad, rad/s", "右臂关节角 / 关节速度"],
            ["tcp_R", "24:33", "9", "-", "TCP 旋转矩阵展平"],
            ["target_xyz", "33:36", "3", "m", "目标位"],
            ["hole_xyz", "36:39", "3", "m", "孔口世界坐标（写死 36:39，不许挪）"],
            ["grasp / contact / dir_x / dir_y", "39:43", "4", "-, N", "触觉力觉（语义一字不动）"],
            ["finger_pressure · temperature · acoustic · current", "43:51", "8", "kPa/°C/dB/A", "预留扩展，零初始化沉睡"],
            ["peg_quat（本次提案）", "51:55", "4", "-", "★ 光模块姿态四元数 wxyz；全 0 = 未观测"]]
    table(s, 0.55, 1.42, 12.2, rows, widths=[2.6, 1.0, 0.55, 1.25, 4.6], row_h=0.365, body_size=10)
    txt(s, 0.55, 6.55, 12.2, 0.5,
        "铁律：每维有名字/单位/来源；validate_layout() 断言 19 段首尾相接覆盖 0:55；老数据 43 维补 0 → 姿态段为 0 表示「未观测」，不破坏在役权重。",
        10, MUTED)

    # ── 4 原点与坐标系 ────────────────────────────────────────
    s = page(prs, "原点与坐标系口径：为什么是「金手指端中间」", "抓取时模块坐标系与 tool1 坐标系重合 —— 这是标定与抓取的共同基准", 4)
    box(s, 0.55, 1.45, 6.0, 4.6, fill=RGBColor(0xFA, 0xFB, 0xFD), line=RGBColor(0xE2, 0xE8, 0xF0))
    txt(s, 0.75, 1.6, 5.6, 0.35, "定义（三条，缺一条就错）", 13, INK, True)
    defs = [
        "① 原点：模块**金手指（连接器）端**的中间，不是绿色拉环端。",
        "② 朝向：长边 72mm 沿 X，宽 18.35mm 沿 Y，厚 8.5mm 沿 Z（槽位规则决定，不由算法自由旋转）。",
        "③ 重合：抓取瞬间，模块坐标系 ≡ tool1 坐标系 ⇒ 控制器给出的 tool1 位姿就是模块位姿真值。",
    ]
    y = 2.02
    for d in defs:
        txt(s, 0.75, y, 5.6, 0.95, d.replace("**", ""), 11, INK)
        y += 0.95
    txt(s, 0.75, 4.95, 5.6, 0.9, "意义：模块夹在爪上时是「位姿已知的 6DOF 靶标」，可用于手眼标定；\n放在料盘里时位置由槽位几何真值给出。", 10.5, MUTED)

    box(s, 6.85, 1.45, 5.9, 2.1, fill=RGBColor(0xF1, 0xF8, 0xFF), line=ACC)
    txt(s, 7.05, 1.6, 5.5, 0.32, "模块尺寸与槽位（真源）", 12, INK, True)
    txt(s, 7.05, 1.98, 5.5, 1.4,
        "QSFP28 · 72.00 × 18.35 × 8.50 mm\n槽10 = (517.0, 404.0, 110.0)，体中心 z = 114.25\n金手指端中间 = (517.0, 394.8, 118.5)（顶面 + 端面中点）", 10.5, INK)
    box(s, 6.85, 3.75, 5.9, 2.3, fill=RGBColor(0xFF, 0xFB, 0xF1), line=ACC2)
    txt(s, 7.05, 3.9, 5.5, 0.32, "实测锚定（画面像素）", 12, INK, True)
    txt(s, 7.05, 4.28, 5.5, 1.6,
        "叠加原点      (426, 322)\n检测框下沿中点 (426, 322)   ← 差 0px\n旧版（上沿中点）差 1px，已纠正为金手指端\n画面 848×480 · 25 fps 实时叠加", 10.5, INK)

    # ── 5 检测链路 ────────────────────────────────────────────
    s = page(prs, "3D 位姿检测链路（7 步，每步都有实测判据）", "从一帧图像到一个写入状态空间的位姿", 5)
    steps = [
        ("① 触发", "到位/节拍事件", "TCP 真值 30Hz"),
        ("② 2D 检出", "YOLO yolo_peg_live.pt", "conf 0.78~0.85"),
        ("③ 深度反投影", "D405 848×480@30 + 去畸变", "0.1mm/unit"),
        ("④ 3D 表达", "图像对齐 AABB 包围盒", "72.1 vs 72.0mm"),
        ("⑤ 外参", "T_base_cam（手眼）", "9.36px / 待闭环"),
        ("⑥ 位姿解算", "位置 + 姿态四元数", "原点=金手指端"),
        ("⑦ 写状态空间", "SLICE['peg_xyz'] / ['peg_quat']", "25Hz 入总线"),
    ]
    x = 0.5
    for i, (t1, t2, t3) in enumerate(steps):
        y = 1.5 + (i % 4) * 1.18
        col = 0.5 + (i // 4) * 6.2
        box(s, col, y, 5.75, 1.0, fill=RGBColor(0xFA, 0xFB, 0xFD), line=RGBColor(0xE2, 0xE8, 0xF0))
        box(s, col, y, 0.07, 1.0, fill=ACC if i < 6 else OK)
        txt(s, col + 0.2, y + 0.1, 1.5, 0.3, t1, 12, INK, True)
        txt(s, col + 1.55, y + 0.12, 2.6, 0.3, t2, 10.5, INK)
        txt(s, col + 4.2, y + 0.12, 1.45, 0.3, t3, 9.5, ACC if i < 6 else OK, True)
    txt(s, 0.55, 6.35, 12.2, 0.55,
        "端到端计时基线（550C 端侧实测）：YOLO 2.19ms(iGPU) / 9.04ms(4060) · INTACT 1.19~2.73ms · 流形 1.0ms ⇒ 进拍链合计 8.33ms / 100ms，占空 8.3%，位姿实时刷新无压力。",
        10, MUTED)

    # ── 6 功能清单 ────────────────────────────────────────────
    s = page(prs, "功能清单 F-H01 ~ F-H10（光模块 3D 位姿 · 状态空间输出）", "判据一律可数值复核；状态列按实测，未达标不写 PASS", 6)
    rows = [["ID", "功能", "判据", "实测 / 状态"],
            ["F-H01", "状态空间位姿段定义", "peg_xyz 4:7 + peg_quat 51:55；19 段覆盖 0:55 无断档", "本次提案 · 待 validate_layout 回归"],
            ["F-H02", "原点与坐标系口径", "原点=金手指端中间；抓取时 ≡ tool1", "✓ 叠加 0~1px"],
            ["F-H03", "2D 检出", "conf ≥0.5 且连续 3 帧框中心漂移 <10px", "✓ 0.78~0.85"],
            ["F-H04", "深度反投影", "0.1mm/unit + 去畸变；848×480@30", "✓ 实测单位 0.1mm"],
            ["F-H05", "3D 包围盒", "最长边与 72.0mm 偏差 ≤1mm", "✓ 72.1mm（差 0.1）· 宽高待收紧"],
            ["F-H06", "外参解算", "重投影 RMS ≤3px", "× 9.36px（4 点 PnP）"],
            ["F-H07", "位姿写状态空间", "按名 SLICE 取值；≥25Hz；单帧 ≤100ms", "✓ 25Hz（8897 流实测）"],
            ["F-H08", "位姿可视化", "station 页叠加，原点+三轴，可用率 ≥99%", "✓ 已上线 :8897"],
            ["F-H09", "姿态四元数合法性", "‖q‖∈[0.99,1.01] 或全 0（未观测）", "待接入（本版仅位置）"],
            ["F-H10", "上游联动", "位姿进 AR(8797) 叠加；与 L2 判据同源", "待接入"]]
    table(s, 0.55, 1.42, 12.2, rows, widths=[0.85, 2.0, 4.6, 3.3], row_h=0.44, body_size=9.8)
    txt(s, 0.55, 6.5, 12.2, 0.45, "符号：✓ 实测通过 · × 实测未达标（按未达标交付，不美化）· 待接入 尚未接线", 10, MUTED)

    # ── 7 实测证据 ────────────────────────────────────────────
    s = page(prs, "实测证据（本轮真机数据）", "每条都能在日志/文件里复核", 7)
    rows = [["项目", "实测", "口径 / 来源"],
            ["模块检出置信", "0.79 / 0.78 / 0.79（连续三帧，槽4）", "YOLO conf≥0.25 原始输出"],
            ["槽位换算", "框中心 x=399/399/400 → 槽4", "(623−x)/77.2+1（848 宽标定）"],
            ["深度单位", "0.1 mm/unit（raw 3044 = 304mm）", "D405 /depth.png"],
            ["内参（848×480）", "fx436.71 fy436.056 cx422.275 cy238.513", "/intrinsics · coeffs 已用于去畸变"],
            ["3D 框最长边", "72.1mm（QSFP28 标称 72.0）", "图像对齐 AABB + 深度"],
            ["外参 4 点 PnP", "残差 13.77 / 12.42 / 2.32 / 1.07 px · RMS 9.36px", "solvePnP + 去畸变"],
            ["捆绑平差（合成自检）", "复原真值 0.000px（t、P_base、旋转全中）", "least_squares 多起点 + 边界"],
            ["捆绑平差（真机 6 位姿）", "RMS 4.58px，P_base z 撞边界 400mm", "输入被手工摆放误差污染"],
            ["原点锚定", "叠加 (426,322) vs 检测框下沿中点 (426,322)", "station 实时帧"],
            ["实时流", ":8897 · 25 fps · 帧龄 0.1~0.3s", "arm_yolo_stream 服务"]]
    table(s, 0.55, 1.42, 12.2, rows, widths=[2.7, 5.0, 4.5], row_h=0.40, body_size=9.8)

    # ── 8 验收标准 ────────────────────────────────────────────
    s = page(prs, "验收标准（KPI 三段式：现状 → 目标 → 卡口）", "不达标不进默认档，这是本轮升级的既定门槛", 8)
    rows = [["指标", "现状（实测）", "目标", "卡口 / 判定方式"],
            ["位置精度", "≈6~7mm（9.36px @300mm）", "≤2.0mm", "手眼标定后逐槽残差，10 次取中位"],
            ["姿态精度", "未接入", "≤1.0°", "与 tool1 真值比对（抓取位姿）"],
            ["单帧延迟", "YOLO 2.19ms + 深度 + PnP", "≤100ms", "io_trace 时间戳，P95"],
            ["刷新率", "25 fps（:8897）", "≥25Hz", "连续 5 分钟统计"],
            ["可用率", "运行期未见丢帧", "≥99%", "30 分钟无断流/无空框"],
            ["数据可回放", "未落盘", "每帧入 io_trace", "抽查 100 帧可复现"]]
    table(s, 0.55, 1.45, 12.2, rows, widths=[1.6, 3.2, 1.6, 4.2], row_h=0.5, body_size=10.5)
    box(s, 0.55, 5.35, 12.2, 1.1, fill=RGBColor(0xFF, 0xFB, 0xF1), line=ACC2)
    txt(s, 0.75, 5.5, 11.8, 0.8,
        "红线：位置 ≤2mm 未达成前，位姿只做「可视化 + 数据采集」，不参与抓取闭环下发。当前状态按此执行。", 12, RGBColor(0x92, 0x40, 0x0E), True)

    # ── 9 缺口与里程碑 ────────────────────────────────────────
    s = page(prs, "缺口与里程碑", "四步收口，每步都有可判定的完成标志", 9)
    ms = [
        ("M1", "状态空间位姿段落地", "peg_quat 51:55 定义 + validate_layout 回归 + 老数据补 0 兼容", "本次交付", OK),
        ("M2", "手眼闭环", "模块夹爪上做已知位姿靶标，走 4 位姿；目标 RMS ≤3px / 位置 ≤2mm", "待执行", ACC),
        ("M3", "姿态接入", "姿态四元数写入 peg_quat；SLERP/测地线用 atan2 形式，避免 NaN", "待执行", ACC2),
        ("M4", "数据回灌 + AR 联动", "每帧位姿落 io_trace；AR(8797) 叠加与 L2 判据同源", "待执行", MUTED),
    ]
    y = 1.5
    for code, name, detail, st, col in ms:
        box(s, 0.55, y, 12.2, 1.12, fill=RGBColor(0xFA, 0xFB, 0xFD), line=RGBColor(0xE2, 0xE8, 0xF0))
        box(s, 0.55, y, 0.09, 1.12, fill=col)
        txt(s, 0.78, y + 0.16, 0.8, 0.4, code, 17, col, True)
        txt(s, 1.55, y + 0.16, 4.2, 0.4, name, 14, INK, True)
        txt(s, 5.9, y + 0.2, 5.0, 0.8, detail, 10.5, MUTED)
        txt(s, 11.0, y + 0.2, 1.6, 0.4, st, 11, col, True, PP_ALIGN.RIGHT)
        y += 1.25

    # ── 10 交付物与复现 ───────────────────────────────────────
    s = page(prs, "交付物与复现命令", "脚本与数据都在仓库里，可重新生成", 10)
    rows = [["交付物", "路径", "说明"],
            ["位姿流服务", "tools/arm_yolo_stream.py · :8897", "25fps，叠加原点+三轴"],
            ["工位页", "tools/web/station.html → 8793/station", "手臂相机格已切到 :8897"],
            ["单点采集/解算", "tools/handeye_point.py（--slot / --pnp）", "2D 中心 + 平面 PnP"],
            ["捆绑平差", "tools/handeye_bundle.py（--run / --draw）", "模块不动，臂走位姿"],
            ["3D 框", "tools/peg3d_box.py", "深度+YOLO→相机系 3D 框"],
            ["状态空间真源", "src/lerobot/policies/left_right/state_space/unified_state55.py", "SLICE 按名取"],
            ["模块位姿图", "zmax_data/percept/module_frame_slot10.png", "槽10 位姿（几何真值）"]]
    table(s, 0.55, 1.42, 12.2, rows, widths=[2.1, 5.4, 4.3], row_h=0.45, body_size=10)
    txt(s, 0.55, 5.35, 12.2, 0.5, "重新生成本 PPT：./gui-venv311/bin/python tools/gen_deck_peg_pose.py", 11, ACC, True)
    txt(s, 0.55, 5.85, 12.2, 0.8,
        "下一步需现场决策：M2 需要机械臂抓一次模块（槽10 → 4 个位姿），全程 z 抬升 ≥50mm 规避，\n动作前需要你确认授权。", 10.5, MUTED)

    prs.save(OUT)
    print("→", OUT, os.path.getsize(OUT) // 1024, "KB", len(prs.slides.__iter__.__self__._sldIdLst), "页")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
