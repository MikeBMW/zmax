#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_ar_robot_deck.py — AR 场景机器人方案 PPT (外形/结构/尺寸/四视图/透视)。

真源 (全部可复核):
  config/robot/zmax_robot_spec.json                 运动学/限位/质量 (URDF 导出, sha 4e0288ac88042652)
  data/.../moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf   厂家 URDF
  data/.../urdf/meshes/*.stl                        厂家网格 (渲染用)
  config/calib/zmax_calib.json:camera               内参 K/dist (手眼 T_base_cam 未标定, 如实标注)
  config/tasks/ar_meta_tasks.json                   元任务 MT-01~07
图片: docs/6-开阳-工程落地/figs_ar_robot/ (tools/render_robot_views.py 生成)
用法: ./gui-venv311/bin/python tools/build_ar_robot_deck.py
"""
from __future__ import annotations
import os, sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from PIL import Image

REPO = "/home/ubuntu/zmax"
FIG = os.path.join(REPO, "docs/6-开阳-工程落地/figs_ar_robot")
OUT = os.path.join(REPO, "docs/1-天枢-产品边界/deliverables/AR场景机器人方案_5.50.C_20261101.pptx")

INK = RGBColor(0x14, 0x18, 0x1F); SUB = RGBColor(0x5B, 0x64, 0x72)
GOLD = RGBColor(0xC9, 0xA2, 0x27); SOFT = RGBColor(0xF6, 0xF7, 0xF9)
WHITE = RGBColor(0xFF, 0xFF, 0xFF); LINE = RGBColor(0xE2, 0xE5, 0xEA)
FONT = "Microsoft YaHei"; W, H = 13.333, 7.5


def _blank(prs): return prs.slides.add_slide(prs.slide_layouts[6])


def _tb(slide, x, y, w, h, text="", size=16, color=INK, bold=False, align=PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.TOP, spacing=1.25):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, ln in enumerate(str(text).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align; p.line_spacing = spacing
        r = p.add_run(); r.text = ln
        r.font.size = Pt(size); r.font.bold = bold
        r.font.color.rgb = color; r.font.name = FONT
    return box


def _rect(slide, x, y, w, h, fill=SOFT, line=None):
    from pptx.enum.shapes import MSO_SHAPE
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.shadow.inherit = False
    if fill is None: sh.fill.background()
    else: sh.fill.solid(); sh.fill.fore_color.rgb = fill
    if line is None: sh.line.fill.background()
    else: sh.line.color.rgb = line; sh.line.width = Pt(0.75)
    sh.text_frame.text = ""
    return sh


def _rule(slide, x, y, w, color=GOLD, h=0.035): _rect(slide, x, y, w, h, fill=color)


def _head(slide, kicker, title, page, total):
    _tb(slide, 0.75, 0.60, 11.8, 0.3, kicker, 11, GOLD, bold=True)
    _tb(slide, 0.75, 0.92, 11.8, 0.7, title, 27, INK, bold=True)
    _rule(slide, 0.75, 1.66, 1.1)
    _tb(slide, 0.75, 6.98, 6, 0.3, "Z-MAX · 智蜂创元 · AR 场景机器人方案 5.50.C", 9, SUB)
    _tb(slide, W - 1.55, 6.98, 0.8, 0.3, f"{page:02d} / {total:02d}", 9, SUB, align=PP_ALIGN.RIGHT)


def _table(slide, x, y, w, rows, col_w, size=11, head_size=11, row_h=0.32):
    n_r, n_c = len(rows), len(rows[0])
    shp = slide.shapes.add_table(n_r, n_c, Inches(x), Inches(y), Inches(w), Inches(row_h * n_r))
    tbl = shp.table; tbl.first_row = True
    for i, cw in enumerate(col_w): tbl.columns[i].width = Inches(cw)
    for r_i, row in enumerate(rows):
        tbl.rows[r_i].height = Inches(row_h if r_i else row_h + 0.04)
        for c_i, val in enumerate(row):
            c = tbl.cell(r_i, c_i)
            c.margin_left = Inches(0.09); c.margin_right = Inches(0.07)
            c.margin_top = Inches(0.02); c.margin_bottom = Inches(0.02)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            c.fill.solid(); c.fill.fore_color.rgb = INK if r_i == 0 else (WHITE if r_i % 2 else SOFT)
            p = c.text_frame.paragraphs[0]; p.line_spacing = 1.02
            r = p.add_run(); r.text = str(val)
            r.font.size = Pt(head_size if r_i == 0 else size)
            r.font.bold = r_i == 0
            r.font.color.rgb = WHITE if r_i == 0 else INK
            r.font.name = FONT
    return tbl


def _pic(slide, name, x, y, max_w, max_h, frame=True):
    """按比例缩放贴图, 居中放在 (x,y,max_w,max_h) 框内。"""
    p = os.path.join(FIG, name)
    iw, ih = Image.open(p).size
    s = min(max_w / iw, max_h / ih)
    w, h = iw * s, ih * s
    if frame:
        _rect(slide, x, y, max_w, max_h, fill=WHITE, line=LINE)
    slide.shapes.add_picture(p, Inches(x + (max_w - w) / 2), Inches(y + (max_h - h) / 2),
                             Inches(w), Inches(h))
    return p


def build(out=OUT):
    prs = Presentation(); prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    TOTAL = 13

    # 01 封面
    s = _blank(prs); _rect(s, 0, 0, W, H, fill=INK)
    _rule(s, 0.95, 2.30, 1.6, GOLD, h=0.05)
    _tb(s, 0.95, 1.62, 9, 0.4, "AR 场景 · 机器人本体方案", 13, GOLD, bold=True)
    _tb(s, 0.95, 2.55, 10.8, 1.6, "珞石 XMS5-R800-W4G3B4C\n六轴工业机器人与 AR 工位", 36, WHITE, bold=True, spacing=1.2)
    _tb(s, 0.95, 4.55, 10.8, 1.0,
        "外形 · 结构 · 尺寸 · 四视图 · 透视视角\n全部取自厂家 URDF + STL 与真机参数单一真源", 15,
        RGBColor(0xC9, 0xCF, 0xD8), spacing=1.5)
    _tb(s, 0.95, 6.35, 8, 0.35, "智蜂创元 ZFCY · 2026-11 · 版本 5.50.C", 11, RGBColor(0x8E, 0x97, 0xA5))

    # 02 一页看懂
    s = _blank(prs); _head(s, "一页看懂", "这台机器人在 AR 工位做什么", 2, TOTAL)
    for i, (t, body) in enumerate([
        ("本体", "珞石 XMS5-R800-W4G3B4C\n六轴 · 6 DOF · 额定 800 mm 臂展\n本体质量 13.6 kg，负载 1.51 kg"),
        ("干什么", "取料 → 受控插入 47 mm →\n手持五点检测 → 良品摆盘/NG 入废料\n一件 11.4 s"),
        ("现在到哪", "URDF/STL 与真机参数已入单一真源\n外形尺寸与四视图可复现\n手眼外参待标定（本页之后说明）"),
    ]):
        x = 0.75 + i * 4.05
        _rect(s, x, 2.05, 3.75, 2.35, fill=SOFT); _rule(s, x, 2.05, 0.28, GOLD, h=0.05)
        _tb(s, x + 0.22, 2.28, 3.3, 0.35, t, 15, INK, bold=True)
        _tb(s, x + 0.22, 2.74, 3.3, 1.5, body, 12, SUB, spacing=1.35)
    _tb(s, 0.75, 4.75, 11.8, 1.3,
        "本方案只写有出处的东西：尺寸来自厂家 URDF 与 STL，限位与质量来自真机只读采集导出的参数文件；\n"
        "未标定的量（手眼外参）明确标“未标定”并给出标定方法，不拿估计值充实测。", 13, SUB, spacing=1.5)

    # 03 四视图 · 正面与侧面
    s = _blank(prs); _head(s, "外形 · 正视", "正面图 / 侧面图（直立姿态，全零位）", 3, TOTAL)
    _pic(s, "robot_zero_front_dim.png", 0.70, 1.95, 5.75, 4.85)
    _pic(s, "robot_zero_side_dim.png", 6.85, 1.95, 5.75, 4.85)

    # 04 俯视与透视
    s = _blank(prs); _head(s, "外形 · 俯视与透视", "俯视图 / 透视视角（作业姿态）", 4, TOTAL)
    _pic(s, "robot_zero_top_dim.png", 0.70, 1.95, 5.75, 4.85)
    _pic(s, "robot_live_iso.png", 6.85, 1.95, 5.75, 4.85)

    # 05 尺寸总表
    s = _blank(prs); _head(s, "尺寸", "总长 / 总宽 / 总高 与关键长度", 5, TOTAL)
    _table(s, 0.75, 2.00, 7.25, [
        ["项", "数值", "定义"],
        ["总高", "1231.5 mm", "直立位，底座底面到腕部顶端"],
        ["总宽（左右）", "333.6 mm", "含 J2/J3 关节凸台"],
        ["总长（前后）", "272.8 mm", "底座前后方向最大轮廓"],
        ["底座安装面", "240 × 175 mm", "厂家网格实测轮廓"],
        ["法兰 → TCP", "260.4 mm", "真机反解 offset（std 0.0 mm）"],
        ["直立末端高", "1490.2 mm", "全零位时 TCP 高度"],
    ], col_w=[2.05, 2.35, 2.85], row_h=0.52, size=11)
    _tb(s, 8.25, 2.05, 4.3, 1.0, "读数口径", 14, INK, bold=True)
    _tb(s, 8.25, 2.45, 4.3, 3.6,
        "· 总长/总宽/总高 = STL 网格在直立姿态下的轴对齐包围盒\n"
        "· 网格单位为 mm，已按厂家口径换算\n"
        "· 关节零位 = 六轴全部 0 rad\n"
        "· 底座安装面取自 base 网格轮廓，用于工位地脚布置", 11, SUB, spacing=1.4)

    # 06 结构分解
    s = _blank(prs); _head(s, "结构", "六轴串联：链长与质量逐段可查", 6, TOTAL)
    _table(s, 0.75, 2.00, 11.83, [
        ["段", "关节", "长度", "质量", "说明"],
        ["底座 → 腰", "J1（绕 Z）", "328 mm", "—", "回转腰，±360°"],
        ["腰 → 大臂", "J2（绕 Y）", "0 mm", "3.167 kg", "与大臂同点，肩部"],
        ["大臂 → 小臂", "J3（绕 Y）", "400 mm", "4.291 kg", "含 50 mm 前倾偏置"],
        ["小臂 → 腕1", "J4（绕 Z）", "400 mm", "2.018 kg", "含 −50 mm 后倾偏置"],
        ["腕1 → 腕2", "J5（绕 Y）", "136 mm", "2.005 kg", "腕部横摆"],
        ["腕2 → 法兰", "J6（绕 Z）", "103.5 mm", "1.507 kg", "末端旋转"],
        ["法兰 → TCP", "固定", "258.7 mm", "0.634 kg", "末端工具坐标系"],
    ], col_w=[2.1, 2.3, 1.5, 1.5, 4.43], row_h=0.47, size=11)
    _tb(s, 0.75, 5.85, 11.8, 0.6,
        "本体合计 13.622 kg（六连杆质量之和）· 负载 1.51 kg（控制器 setToolset 只读回读）", 12, SUB)

    # 07 关节表
    s = _blank(prs); _head(s, "运动能力", "关节行程 / 速度 / 力矩", 7, TOTAL)
    _table(s, 0.75, 2.00, 11.83, [
        ["关节", "轴", "行程", "最大速度", "额定力矩"],
        ["J1", "Z（回转）", "±360°", "180 °/s", "113 N·m"],
        ["J2", "Y（肩）", "−160° … +150°", "180 °/s", "113 N·m"],
        ["J3", "Y（肘）", "−170° … +140°", "180 °/s", "70 N·m"],
        ["J4", "Z（腕转）", "±360°", "180 °/s", "25 N·m"],
        ["J5", "Y（腕摆）", "±360°", "180 °/s", "25 N·m"],
        ["J6", "Z（末端转）", "±360°", "180 °/s", "19 N·m"],
    ], col_w=[1.4, 2.6, 3.0, 2.4, 2.43], row_h=0.45, size=11)
    _tb(s, 0.75, 5.55, 11.8, 1.0,
        "产线实际不按上限跑：末端速度上限 0.5 m/s、一阶速度伺服 τ = 0.08 s，\n"
        "插入段另有力上限 40 N 与单步 50 mm 的闸门约束。", 12, SUB, spacing=1.45)

    # 08 工作空间
    s = _blank(prs); _head(s, "工作空间", "能到多远、多高，和实际用哪一段", 8, TOTAL)
    _table(s, 0.75, 2.00, 6.6, [
        ["项", "数值"],
        ["最大水平伸展", "1176 mm（含 260 mm 末端）"],
        ["直立末端高度", "1490 mm"],
        ["低伸姿态末端高", "399 mm（同一极值姿态）"],
        ["厂家额定臂展", "800 mm（型号 R800）"],
        ["实际作业区", "半径 450–650 mm · 高度 250–450 mm"],
    ], col_w=[2.2, 4.4], row_h=0.55, size=11)
    _tb(s, 7.55, 2.05, 5.0, 3.4,
        "为什么实际只用中段：\n"
        "· 靠外伸满臂时关节接近奇异区，姿态精度下降\n"
        "· 插拔动作需要腕部有余量做力矩微调\n"
        "· 作业区留出 ±80 mm 的通道余量给对位偏差", 11, SUB, spacing=1.5)

    # 09 AR 场景定义
    s = _blank(prs); _head(s, "AR 场景", "机器人在这个工位上具体做什么", 9, TOTAL)
    _table(s, 0.75, 2.00, 11.83, [
        ["编号", "动作（真机示教口径）", "臂"],
        ["MT-01", "上料槽取模块 → 受控插入目标孔 47 mm", "右"],
        ["MT-02", "沿轴拔出模块 47 mm", "右"],
        ["MT-03", "手持模块五点检测（金手指 + 侧面四点）", "右"],
        ["MT-04 / 05", "良品入下料盘空槽 / NG 入废料盘", "右"],
        ["MT-06", "周转盘取模块 → 摆入上料 Tray 空槽", "左"],
        ["MT-07", "供料 / 取料交接同步（槽 k 交接点，11.4 s/件）", "双"],
    ], col_w=[1.7, 8.3, 1.83], row_h=0.5, size=11)
    _tb(s, 0.75, 5.6, 11.8, 0.9,
        "工位侧：AR 页面 8797 实时渲染机器人姿态与工件框；机械臂画面上叠加 3D 框由 8791 的 arm/gold/surface 三路相机供给。",
        11, SUB, spacing=1.4)

    # 10 相机与标定状态
    s = _blank(prs); _head(s, "感知与标定", "内参已标，手眼未标 —— 如实写明", 10, TOTAL)
    _table(s, 0.75, 2.00, 6.9, [
        ["项", "状态", "数值 / 说明"],
        ["相机内参 fx/fy", "已标定", "394.06 / 393.47"],
        ["主点 cx/cy", "已标定", "318.44 / 238.66"],
        ["畸变", "已标定", "k1 −0.0539，k2 0.0571"],
        ["手眼外参 T_base_cam", "未标定", "需零运动人工拖动采集 10+ 位姿"],
        ["深度单位", "已知", "D405 原始单位 0.1 mm"],
    ], col_w=[2.35, 1.35, 3.2], row_h=0.52, size=11)
    _tb(s, 8.0, 2.02, 4.55, 0.4, "标定怎么做（不猜）", 14, INK, bold=True)
    _tb(s, 8.0, 2.45, 4.55, 3.6,
        "1. 机械臂断电，人工拖动到 10 个以上不同位姿\n"
        "2. 每个位姿拍标定板，记录 TCP 与图像对应点\n"
        "3. 解 T_base_cam，重投影误差 ≤2 px 才取值\n"
        "4. 结果写回 config/calib/zmax_calib.json\n"
        "5. 复核：把已知点 3D 投影到图上，肉眼对得上", 11, SUB, spacing=1.45)

    # 11 安全与约束
    s = _blank(prs); _head(s, "安全与动作约束", "能动手的前提是每层都能拦住", 11, TOTAL)
    _table(s, 0.75, 2.00, 11.83, [
        ["层", "约束", "数值"],
        ["速度", "末端合速度上限", "0.5 m/s"],
        ["速度", "关节指令速度上限", "1–1000 mm/s（档位内可调）"],
        ["力", "插入力上限", "40 N（超限即停）"],
        ["步长", "单步位移 / 向下位移", "50 mm / 20 mm"],
        ["授权", "动作授权来源", "单一来源，过期即拒发"],
        ["停机", "急停 + 光幕", "双路急停、人员靠近降速停机"],
    ], col_w=[1.5, 4.6, 5.73], row_h=0.47, size=11)
    _tb(s, 0.75, 5.55, 11.8, 0.9,
        "所有动作先过闸再下发；被拦下也留证（谁拦的、哪一条、什么值）。", 12, SUB)

    # 12 真源与复现
    s = _blank(prs); _head(s, "真源与复现", "每个数字都能自己跑一遍", 12, TOTAL)
    _table(s, 0.75, 2.00, 11.83, [
        ["文件 / 命令", "作用"],
        ["config/robot/zmax_robot_spec.json", "运动学、限位、质量（URDF 导出，sha 4e0288ac88042652）"],
        [".../moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf", "厂家 URDF 原件"],
        [".../urdf/meshes/*.stl", "厂家外形网格（7 个，含底座）"],
        ["tools/render_robot_views.py --pose zero", "生成四视图与尺寸标注（本 PPT 的图）"],
        ["tools/build_ar_robot_deck.py", "本 PPT 生成脚本，改内容改这里"],
    ], col_w=[5.6, 6.23], row_h=0.55, size=11)
    _tb(s, 0.75, 5.5, 11.83, 0.6,
        "复现：cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/render_robot_views.py --pose zero",
        11, SUB)

    # 13 结尾
    s = _blank(prs); _rect(s, 0, 0, W, H, fill=INK)
    _rule(s, 0.95, 2.35, 1.6, GOLD, h=0.05)
    _tb(s, 0.95, 2.65, 10.6, 1.0, "下一步：标手眼，再谈叠加", 32, WHITE, bold=True)
    _tb(s, 0.95, 3.70, 10.8, 1.7,
        "① 手眼标定（T_base_cam）→ ② 工位场景重建 → ③ AR 页面把机器人姿态与工件框对上真机画面\n"
        "智蜂创元 ZFCY · Z-MAX 具身智能机器人平台", 14, RGBColor(0xC9, 0xCF, 0xD8), spacing=1.6)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    prs.save(out)
    print(f"saved {out} slides={len(prs.slides._sldIdLst)}")
    return out


if __name__ == "__main__":
    build(sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else OUT)
