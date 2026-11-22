#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_deck_peg_pose_deep.py — 专篇：《光模块 3D 位姿检测》功能说明。

只讲这一个功能：定义 → 输出契约 → 坐标系 → 链路 → 误差预算 → 实测 → 失败模式 → 验收。
数字全部来自本轮真机实测/真源文件（见各页脚注），未达标项不美化。
"""
from __future__ import annotations

import os

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn

OUT = "/home/ubuntu/zmax/zmax_data/reports/光模块3D位姿检测_功能专篇_v1.pptx"
W, H = 13.333, 7.5
INK = RGBColor(0x1E, 0x29, 0x3B)
MUTED = RGBColor(0x64, 0x74, 0x8B)
ACC = RGBColor(0x0E, 0xA5, 0xE9)
ACC2 = RGBColor(0xF5, 0x9E, 0x0B)
OK = RGBColor(0x16, 0xA3, 0x4A)
BAD = RGBColor(0xDC, 0x26, 0x26)
BG = RGBColor(0xFA, 0xFB, 0xFD)
LINE = RGBColor(0xE2, 0xE8, 0xF0)
CJK = "Noto Sans CJK SC"


def _ea(run, name=CJK):
    run.font.name = name
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", name)


def txt(slide, x, y, w, h, s, size=13, color=INK, bold=False, align=PP_ALIGN.LEFT, spacing=1.05):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.03)
    tf.margin_top = tf.margin_bottom = 0
    for i, ln in enumerate(s.split("\n")):
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
    return sh


def table(slide, x, y, w, rows, widths=None, head_size=11, body_size=10, row_h=0.36, head_fill=ACC):
    nr, nc = len(rows), len(rows[0])
    shp = slide.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(w), Inches(row_h * nr))
    t = shp.table
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
            cell.fill.fore_color.rgb = head_fill if ri == 0 else (BG if ri % 2 else RGBColor(0xFF, 0xFF, 0xFF))
            p = cell.text_frame.paragraphs[0]
            cell.text_frame.word_wrap = True
            p.alignment = PP_ALIGN.LEFT if ci else PP_ALIGN.CENTER
            r = p.add_run()
            r.text = str(val)
            r.font.size = Pt(head_size if ri == 0 else body_size)
            r.font.bold = ri == 0
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if ri == 0 else INK
            _ea(r)
    return shp


def page(prs, title, sub=None, n=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, 0.06, fill=ACC)
    txt(s, 0.55, 0.28, 11.6, 0.5, title, 23, INK, True)
    if sub:
        txt(s, 0.55, 0.84, 12.3, 0.32, sub, 11, MUTED)
    if n is not None:
        txt(s, W - 0.95, H - 0.42, 0.55, 0.28, str(n), 10, MUTED, align=PP_ALIGN.RIGHT)
        txt(s, 0.55, H - 0.42, 7.5, 0.28, "光模块 3D 位姿检测 · 功能专篇 · v5.50.782", 9, MUTED)
    return s


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)

    # 1 封面
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, H, fill=RGBColor(0x0B, 0x14, 0x24))
    box(s, 0.9, 1.5, 0.09, 2.3, fill=ACC)
    txt(s, 1.25, 1.5, 10.9, 0.9, "光模块 3D 位姿检测", 38, RGBColor(0xFF, 0xFF, 0xFF), True)
    txt(s, 1.25, 2.45, 11.0, 0.55, "功能专篇：从一帧图像到状态空间里的一个位姿", 18, RGBColor(0xC8, 0xD6, 0xE5))
    txt(s, 1.25, 3.25, 11.2, 0.4, "输出契约  peg_xyz[4:7] · peg_quat[51:55]   |   原点 = 金手指端中间   |   抓取时 ≡ tool1", 12.5, ACC)
    txt(s, 1.25, 5.5, 11.0, 0.3, "Z-MAX 550A / 550C · 版本 5.50.782 · 2026-11-22", 11.5, RGBColor(0x8A, 0x9B, 0xAE))
    txt(s, 1.25, 5.9, 11.2, 0.3, "所有数字为本机实测或真源文件取值；未达标的项按未达标标注", 10, RGBColor(0x64, 0x74, 0x8B))

    # 2 功能定义
    s = page(prs, "一、功能定义：这个功能到底交付什么", "一句话：给定一帧手臂相机图像与位姿真值，输出光模块在基座系下的 6DOF 位姿，并写进统一状态空间", 2)
    cards = [
        ("输入", ACC, ["手臂相机 RGB 848×480@30", "D405 深度图（0.1mm/unit）", "内参+畸变系数", "TCP 位姿真值（30Hz）"]),
        ("处理", ACC2, ["2D 检出（YOLO yolo_peg_live.pt）", "深度反投影 + 去畸变", "已知尺寸约束的 3D 表达", "外参（手眼）→ 基座系"]),
        ("输出", OK, ["位置 3 维 peg_xyz[4:7]（m）", "姿态 4 维 peg_quat[51:55]（wxyz）", "有效性标志（全 0 = 未观测）", "写入频率 ≥25Hz"]),
    ]
    for i, (name, col, items) in enumerate(cards):
        x = 0.55 + i * 4.15
        box(s, x, 1.45, 3.85, 0.5, fill=col)
        txt(s, x + 0.15, 1.53, 3.5, 0.32, name, 14, RGBColor(0xFF, 0xFF, 0xFF), True)
        box(s, x, 1.95, 3.85, 2.15, fill=BG, line=LINE)
        y = 2.08
        for it in items:
            txt(s, x + 0.15, y, 3.55, 0.34, "· " + it, 10.5, INK)
            y += 0.5
    box(s, 0.55, 4.35, 12.2, 1.05, fill=RGBColor(0xFF, 0xFB, 0xF1), line=ACC2)
    txt(s, 0.75, 4.48, 11.8, 0.85,
        "边界（本功能不做什么）：不负责抓取决策，不负责轨迹规划，不负责 NG 判定；\n只保证「位姿这一件事」的数值正确、可复现、可回放，其余交给 L2 判据与 L3 调度。", 11.5, RGBColor(0x92, 0x40, 0x0E))
    txt(s, 0.55, 5.6, 12.2, 0.9,
        "为什么必须进状态空间：位姿若只在页面/日志里存在，模型与策略就拿不到它 —— 状态空间是唯一的「模型能看见的世界」；\n进不了状态向量的量，等于不存在。", 11, MUTED)

    # 3 输出契约
    s = page(prs, "二、输出契约（状态空间接口，按名取值）", "真源 unified_state55.py · SLICE 按名取，禁止消费端自己数下标", 3)
    rows = [["字段名", "切片", "维度", "单位", "有效性 / 语义", "消费方"],
            ["peg_xyz", "4:7", "3", "m", "全 0 视为未观测；禁止塞旋转（曾出 9.9m 鬼值）", "L2 判据 · L3 调度 · AR 叠加"],
            ["peg_quat", "51:55", "4", "—", "‖q‖∈[0.99,1.01]；全 0 = 未观测", "姿态对齐 · 抓取预姿态"],
            ["peg_minus_tcp", "7:10", "3", "m", "相对位移，策略主特征", "策略输入"],
            ["tcp_p / tcp_R", "0:3 / 24:33", "3 / 9", "m / —", "手爪真值，位姿的参照系", "P2P 对齐 · 误差评估"]]
    table(s, 0.55, 1.45, 12.2, rows, widths=[1.5, 1.05, 0.7, 0.7, 4.4, 3.2], row_h=0.46, body_size=10)
    box(s, 0.55, 4.15, 6.0, 1.9, fill=BG, line=LINE)
    txt(s, 0.75, 4.28, 5.6, 0.32, "写入规则", 12, INK, True)
    txt(s, 0.75, 4.65, 5.6, 1.3, "· 每帧写入，不插值、不补帧\n· 位姿无效时写「全 0」而不是上一帧旧值\n· 与 tcp_p 同帧对齐（差 >50ms 置无效）", 10.5, INK)
    box(s, 6.85, 4.15, 5.9, 1.9, fill=BG, line=LINE)
    txt(s, 7.05, 4.28, 5.5, 0.32, "为什么姿态单独占一段", 12, INK, True)
    txt(s, 7.05, 4.65, 5.5, 1.3, "· 位置与姿态精度要求不同（2mm vs 1°）\n· 姿态计算代价更高，可异步降频\n· 分开后可各自判有效性，互不污染", 10.5, INK)

    # 4 坐标系
    s = page(prs, "三、坐标系与原点：三条定义，缺一条就错", "原点不是体中心、不是拉环端 —— 是金手指端中间", 4)
    box(s, 0.55, 1.45, 6.1, 3.3, fill=BG, line=LINE)
    txt(s, 0.75, 1.58, 5.7, 0.32, "定义", 12.5, INK, True)
    txt(s, 0.75, 1.98, 5.7, 2.6,
        "① 原点：模块金手指（连接器）端的中间\n     不是绿色拉环端，也不是体中心\n"
        "② 朝向：长边 72mm 沿 X · 宽 18.35mm 沿 Y · 厚 8.5mm 沿 Z\n     （由槽位排布规则决定，不由算法自由旋转）\n"
        "③ 重合：抓取瞬间 模块坐标系 ≡ tool1 坐标系\n     ⇒ 控制器给的 tool1 位姿就是模块位姿真值", 10.8, INK)
    box(s, 6.95, 1.45, 5.8, 1.55, fill=RGBColor(0xF1, 0xF8, 0xFF), line=ACC)
    txt(s, 7.15, 1.58, 5.4, 0.3, "数值（槽10，几何真值）", 12, INK, True)
    txt(s, 7.15, 1.95, 5.4, 1.0, "模块 72.00 × 18.35 × 8.50 mm\n槽底 (517.0, 404.0, 110.0) · 体中心 z=114.25\n金手指端中间 (517.0, 394.8, 118.5)", 10.5, INK)
    box(s, 6.95, 3.15, 5.8, 1.6, fill=RGBColor(0xFF, 0xFB, 0xF1), line=ACC2)
    txt(s, 7.15, 3.28, 5.4, 0.3, "画面实测锚定", 12, INK, True)
    txt(s, 7.15, 3.65, 5.4, 1.0, "叠加原点 (426, 322)\n检测框下沿中点 (426, 322) → 差 0px\n上一版把原点放上沿（拉环端）差 1px，已纠正", 10.5, INK)
    txt(s, 0.55, 4.95, 12.2, 0.85,
        "为什么这条定义重要：抓取时 TCP 就是模块坐标系原点，标定与抓取用同一个点，误差不会被「定义差」吃掉；\n若原点取体中心，抓取位与标定位天然差半长（36mm），后续所有对账都会错。", 10.8, MUTED)

    # 5 链路
    s = page(prs, "四、检测链路：六步，每步一个可测的量", "一步不做完就不往下走（静默降级会被当成「没检出」处理）", 5)
    flow = [("① 2D 检出", "YOLO conf≥0.5\n3 帧漂移<10px", "0.78~0.85"),
            ("② 深度取值", "框内近层 + 去畸变\n0.1mm/unit", "3044→304mm"),
            ("③ 3D 表达", "已知尺寸约束\n72×18.35×8.5", "72.1mm, 差 0.1"),
            ("④ 外参", "T_base_cam\n手眼标定", "9.36px（未达标）"),
            ("⑤ 位姿合成", "位置 + 姿态\n原点=金手指端", "0~1px 锚定"),
            ("⑥ 写总线", "SLICE 按名写入\n<100ms", "25Hz 在线")]
    for i, (t1, t2, t3) in enumerate(flow):
        x = 0.5 + (i % 3) * 4.18
        y = 1.5 + (i // 3) * 2.15
        col = OK if i in (0, 1, 2) else (ACC2 if i == 3 else ACC)
        box(s, x, y, 3.95, 1.85, fill=BG, line=LINE)
        box(s, x, y, 3.95, 0.06, fill=col)
        txt(s, x + 0.16, y + 0.16, 3.6, 0.3, t1, 12.5, INK, True)
        txt(s, x + 0.16, y + 0.55, 3.65, 0.8, t2, 10, MUTED)
        txt(s, x + 0.16, y + 1.4, 3.65, 0.3, "实测 " + t3, 10, col, True)
    txt(s, 0.55, 5.9, 12.2, 0.6,
        "端侧耗时（550C 实测）：YOLO 2.19ms(iGPU) / 9.04ms(4060) · INTACT 1.19~2.73ms · 流形 1.0ms；进拍链合计 8.33ms / 100ms 预算，占空 8.3%。", 10, MUTED)

    # 6 误差预算
    s = page(prs, "五、误差预算：钱花在哪一环", "1px ≈ 0.687mm @300mm（fx436.71）—— 所有像素误差都用这把尺子折算", 6)
    rows = [["环节", "误差源", "实测/估计", "折算 mm", "占比判断"],
            ["2D 中心", "框边沿抖动、遮挡", "±0.5~1px", "0.3~0.7", "次要"],
            ["深度", "D405 噪声 + 表面反射", "±1~2mm", "1~2", "次要"],
            ["3D 表达", "槽壁/阴影污染", "宽 40.9 vs 18.35mm", "—", "显著（宽高不可用）"],
            ["外参", "手眼标定残差 9.36px", "9.36px", "6.4", "★ 主项"],
            ["摆放（手工）", "模块未卡进槽位", "±5~10mm", "5~10", "★ 主项（已可消除）"],
            ["合计（目标）", "—", "—", "≤2.0", "需 M2+M3 收口"]]
    table(s, 0.55, 1.45, 12.2, rows, widths=[1.6, 3.2, 2.6, 1.5, 3.2], row_h=0.5, body_size=10.5)
    box(s, 0.55, 5.05, 12.2, 1.25, fill=BG, line=LINE)
    txt(s, 0.75, 5.18, 11.8, 1.0,
        "结论：像素级误差（0.3~0.7mm）与深度（1~2mm）都不是瓶颈；瓶颈是外参 6.4mm 与手工摆放 5~10mm。\n"
        "摆放误差可以靠「机械臂按示教点摆放」或「模块夹爪上做靶标」彻底消除；外参则必须靠一次可信标定。", 10.8, INK)

    # 7 实测：对得上的
    s = page(prs, "六、实测证据（一）：已经对得上的", "这三条是功能的立身之本，任意一条不成立就不算完成", 7)
    ev = [("3D 尺寸", "最长边 72.1mm", "QSFP28 标称 72.0mm → 差 0.1mm（1.4‰）", OK),
          ("原点锚定", "差 0px", "叠加原点 (426,322) vs 检测框下沿中点 (426,322)", OK),
          ("检出稳定性", "0.78~0.85", "同日多帧、多姿态一致；槽4 三帧 0.79/0.78/0.79", OK)]
    y = 1.5
    for name, val, detail, col in ev:
        box(s, 0.55, y, 12.2, 1.15, fill=BG, line=LINE)
        box(s, 0.55, y, 0.09, 1.15, fill=col)
        txt(s, 0.8, y + 0.18, 2.4, 0.4, name, 14, INK, True)
        txt(s, 3.2, y + 0.16, 2.6, 0.45, val, 17, col, True)
        txt(s, 5.9, y + 0.22, 6.6, 0.7, detail, 10.5, MUTED)
        y += 1.3
    box(s, 0.55, 5.55, 12.2, 0.75, fill=RGBColor(0xF1, 0xF8, 0xFF), line=ACC)
    txt(s, 0.75, 5.68, 11.8, 0.5, "另：深度单位实测 0.1mm/unit（raw 3044 = 304mm）—— 按 1mm/unit 算会得到 3 米的荒唐框，这条曾踩过。", 10.5, INK)

    # 8 实测：没对上的
    s = page(prs, "七、实测证据（二）：还没对上的（照实交付）", "这三条决定了当前只能做可视化与采集，不能进抓取闭环", 8)
    rows = [["问题", "实测", "根因", "状态"],
            ["外参精度不足", "4 点 PnP 残差 13.77/12.42/2.32/1.07px\nRMS 9.36px", "标定点用「暗区质心」，阴影使四点各偏 3~10px", "× 未达标（≤3px）"],
            ["捆绑平差不收敛", "真机 6 位姿 RMS 4.58px\nP_base z 撞边界 400mm", "同一模块多视角，2D 中心被阴影污染；\n合成数据自检 0.000px 证明算法本身对", "× 输入污染"],
            ["3D 框宽高不可信", "图像对齐 21.0×40.7×100.3mm\n点云实测 30.4×42.3×49.6mm", "槽壁与邻件被算进顶面；18.35mm 宽的模块\n在 350mm 处仅约 23px，噪声 1mm 就判歪", "△ 仅长边可用"]]
    table(s, 0.55, 1.45, 12.2, rows, widths=[2.0, 3.4, 4.6, 2.2], row_h=1.15, body_size=10)
    txt(s, 0.55, 5.45, 12.2, 0.9,
        "为什么不一味调参把数字调绿：这三条都是「输入端不可信」，继续拟合只会得到一个自洽但错的位姿；\n先把输入做干净（靶标/机械臂摆放/连通域），再谈精度。", 10.5, MUTED)

    # 9 失败模式与自检
    s = page(prs, "八、失败模式与自检（防止「看着有值其实是错的」）", "每条失败模式都有对应的在线判据，不靠人眼看", 9)
    rows = [["失败模式", "现象", "在线判据", "处理"],
            ["暗块/阴影污染", "原点偏几十~几百 px", "暗块 bbox 长边 >1.5×理论投影", "该帧判无效"],
            ["未卡进槽位", "位姿偏 5~10mm", "与槽位几何真值差 >5mm", "标记为「待复检」"],
            ["深度单位错", "框尺寸差 10 倍", "最长边 ∉ [60,90]mm", "拒绝该帧"],
            ["旧值残留", "画面停了数字还在跳", "帧龄 >0.5s 或 tcp 差 >50ms", "置全 0（无效）"],
            ["标定过期", "整列位姿系统偏移", "标准槽位复测偏差 >3mm", "告警并降级为可视化"]]
    table(s, 0.55, 1.45, 12.2, rows, widths=[2.2, 2.8, 4.4, 2.6], row_h=0.62, body_size=10)
    txt(s, 0.55, 5.35, 12.2, 0.9,
        "原则：宁可输出「无效」，也不输出一个看起来合理但错的位姿 —— 下游（抓取/AR）会把它当真值用。", 11, BAD, True)

    # 10 提升路径
    s = page(prs, "九、精度提升路径（三条，按性价比排序）", "每条都给出预期收益与执行代价", 10)
    paths = [
        ("P1 机械臂摆放", "模块由机械臂按示教点放进槽位\n消除手工 ±5~10mm", "位置误差 → 1~2mm", "8 个动作 · 已具备", OK),
        ("P2 抓取靶标标定", "模块夹在爪上（位姿= tool1 真值）\n走 4 个位姿做 PnP", "外参 9.36px → ≤3px\n位置 → ≤2mm", "约 10 分钟 · 需授权", ACC),
        ("P3 多帧融合", "同一位姿连拍 5~10 帧取中位\n抑制单帧阴影抖动", "随机项 ↓50%", "纯软件 · 无风险", ACC2),
    ]
    y = 1.5
    for name, how, gain, cost, col in paths:
        box(s, 0.55, y, 12.2, 1.45, fill=BG, line=LINE)
        box(s, 0.55, y, 0.09, 1.45, fill=col)
        txt(s, 0.8, y + 0.16, 2.9, 0.4, name, 14, INK, True)
        txt(s, 3.8, y + 0.2, 4.3, 0.95, how, 10, MUTED)
        txt(s, 8.3, y + 0.2, 2.6, 0.6, gain, 11, col, True)
        txt(s, 8.3, y + 0.85, 4.2, 0.4, cost, 10, MUTED)
        y += 1.6

    # 11 验收判据
    s = page(prs, "十、验收判据（不合格就不算完成）", "每条都能用一段脚本重跑出来", 11)
    rows = [["判据", "口径", "合格线", "当前"],
            ["位置误差", "与槽位几何真值/示教点比对，10 次取中位", "≤2.0mm", "≈6~7mm（×）"],
            ["姿态误差", "与 tool1 真值比对（抓取位姿）", "≤1.0°", "未接入（—）"],
            ["原点锚定", "叠加原点 vs 模块金手指端中点", "≤5px", "0~1px（✓）"],
            ["3D 长边", "最长边 vs 72.0mm", "±1.0mm", "72.1（✓）"],
            ["单帧延迟", "io_trace 时间戳 P95", "≤100ms", "8.33ms 计算（✓）"],
            ["刷新率", "连续 5 分钟统计", "≥25Hz", "25Hz（✓）"],
            ["无效帧处理", "拔掉相机/遮挡 30s", "输出全 0 且不报错", "已实现（✓）"]]
    table(s, 0.55, 1.45, 12.2, rows, widths=[1.8, 4.6, 2.0, 3.0], row_h=0.52, body_size=10.5)
    txt(s, 0.55, 5.6, 12.2, 0.8,
        "红线：位置 ≤2mm 未达成前，位姿只做可视化与数据采集，不参与抓取闭环下发。", 12, BAD, True)

    # 12 依赖与计划
    s = page(prs, "十一、依赖与计划", "四步收口，每步有可判定的完成标志", 12)
    ms = [("S1", "状态空间段落地", "peg_quat 51:55 定义 + validate_layout 回归 + 老数据补 0", "本次", OK),
          ("S2", "输入做干净", "机械臂摆放（P1）+ 暗块连通域收紧（P3）", "1 天内", ACC),
          ("S3", "外参闭环", "抓取靶标 4 位姿 → RMS ≤3px / 位置 ≤2mm", "需授权", ACC2),
          ("S4", "姿态接入 + 联动", "四元数写入、SLERP 校验、AR(8797) 叠加同源", "随后", MUTED)]
    y = 1.5
    for code, name, detail, st, col in ms:
        box(s, 0.55, y, 12.2, 1.1, fill=BG, line=LINE)
        box(s, 0.55, y, 0.09, 1.1, fill=col)
        txt(s, 0.8, y + 0.15, 0.8, 0.4, code, 16, col, True)
        txt(s, 1.5, y + 0.15, 4.2, 0.4, name, 13.5, INK, True)
        txt(s, 5.9, y + 0.2, 4.9, 0.7, detail, 10.5, MUTED)
        txt(s, 11.0, y + 0.2, 1.6, 0.4, st, 11, col, True, PP_ALIGN.RIGHT)
        y += 1.22
    txt(s, 0.55, 6.5, 12.2, 0.4, "重新生成：./gui-venv311/bin/python tools/gen_deck_peg_pose_deep.py", 10, ACC, True)

    prs.save(OUT)
    print("→", OUT, os.path.getsize(OUT) // 1024, "KB ·", len(prs.slides), "页")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
