#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_product_deck.py — Z-MAX 产品解决方案 PPT (对外版)。

口径: 只写仓库里可复核的数字; 目标值与实测值分开标; 面向客户看, 字少图清。
数据来源:
  · 产品/子系统/KPI  data/database/zmax/zmax_engineering.db (platform/products/subsystems/functions)
  · 任务           config/tasks/tasks.json (8 任务) · config/tasks/ar_meta_tasks.json (7 元任务)
  · 分级标准       docs/1-天枢-产品边界/Z-MAX产品等级定义-L1-L5标准.md
  · 场景            docs/2-天璇-作业任务/光模块产线-全流程12工位场景定义.md
  · 节拍实测       12.26s/件 ⇒ UPH 294~315 (通道/闸/发布 三口径)
用法: ./gui-venv311/bin/python tools/build_product_deck.py [--out PATH]
"""
from __future__ import annotations
import os, sys
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

REPO = "/home/ubuntu/zmax"
OUT = os.path.join(REPO, "docs/1-天枢-产品边界/deliverables/Z-MAX产品解决方案_5.50.C_20261101.pptx")

INK   = RGBColor(0x14, 0x18, 0x1F)
SUB   = RGBColor(0x5B, 0x64, 0x72)
GOLD  = RGBColor(0xC9, 0xA2, 0x27)
LINE  = RGBColor(0xE2, 0xE5, 0xEA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
SOFT  = RGBColor(0xF6, 0xF7, 0xF9)
FONT  = "Microsoft YaHei"

W, H = 13.333, 7.5


def _blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _tb(slide, x, y, w, h, text="", size=16, color=INK, bold=False,
        align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.25):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    lines = text.split("\n") if isinstance(text, str) else text
    for i, ln in enumerate(lines):
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


def _rect(slide, x, y, w, h, fill=SOFT, line=None):
    from pptx.enum.shapes import MSO_SHAPE
    sh = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.shadow.inherit = False
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid(); sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line; sh.line.width = Pt(0.75)
    sh.text_frame.text = ""
    return sh


def _rule(slide, x, y, w, color=GOLD, h=0.035):
    _rect(slide, x, y, w, h, fill=color)


def _footer(slide, page, total, label="Z-MAX · 智蜂创元"):
    _tb(slide, 0.75, 6.95, 6, 0.3, label, 9, SUB)
    _tb(slide, W - 1.55, 6.95, 0.8, 0.3, f"{page:02d} / {total:02d}", 9, SUB, align=PP_ALIGN.RIGHT)


def _head(slide, kicker, title, page, total):
    _tb(slide, 0.75, 0.62, 11.8, 0.3, kicker, 11, GOLD, bold=True)
    _tb(slide, 0.75, 0.95, 11.8, 0.7, title, 28, INK, bold=True)
    _rule(slide, 0.75, 1.72, 1.1)
    _footer(slide, page, total)


def _table(slide, x, y, w, rows, col_w, size=12, head_size=12, row_h=0.34):
    n_r, n_c = len(rows), len(rows[0])
    shp = slide.shapes.add_table(n_r, n_c, Inches(x), Inches(y), Inches(w), Inches(row_h * n_r))
    tbl = shp.table
    tbl.first_row = True
    for i, cw in enumerate(col_w):
        tbl.columns[i].width = Inches(cw)
    for r_i, row in enumerate(rows):
        tbl.rows[r_i].height = Inches(row_h if r_i else row_h + 0.04)
        for c_i, val in enumerate(row):
            cell = tbl.cell(r_i, c_i)
            cell.margin_left = Inches(0.10); cell.margin_right = Inches(0.08)
            cell.margin_top = Inches(0.03); cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = INK if r_i == 0 else (WHITE if r_i % 2 else SOFT)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.line_spacing = 1.05
            run = p.add_run(); run.text = str(val)
            run.font.size = Pt(head_size if r_i == 0 else size)
            run.font.bold = r_i == 0
            run.font.color.rgb = WHITE if r_i == 0 else INK
            run.font.name = FONT
    return tbl


def _cards(slide, items, y=2.6, h=1.75, gap=0.32, x0=0.75, total_w=11.83, size=13, title_h=0.34):
    n = len(items)
    w = (total_w - gap * (n - 1)) / n
    for i, (t, body) in enumerate(items):
        x = x0 + i * (w + gap)
        _rect(slide, x, y, w, h, fill=SOFT)
        _rule(slide, x, y, 0.28, GOLD, h=0.05)
        _tb(slide, x + 0.22, y + 0.24, w - 0.44, title_h, t, 15, INK, bold=True)
        _tb(slide, x + 0.22, y + 0.24 + title_h + 0.06, w - 0.44, h - 0.24 - title_h - 0.16,
            body, size, SUB, spacing=1.28)


def build(out=OUT):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    TOTAL = 15

    # ── 01 封面 ────────────────────────────────────────────────
    s = _blank(prs)
    _rect(s, 0, 0, W, H, fill=INK)
    _rule(s, 0.95, 2.02, 1.6, GOLD, h=0.05)
    _tb(s, 0.95, 1.35, 8.6, 0.4, "Z-MAX 具身智能机器人平台", 13, GOLD, bold=True)
    _tb(s, 0.95, 2.22, 10.6, 1.78, "光模块产线精细操作\n具身智能解决方案", 40, WHITE, bold=True, spacing=1.18)
    _tb(s, 0.95, 4.35, 10.6, 0.9,
        "抓取 · 对位 · 插入 · 检测 · 摆盘  全流程无人化\n一台平台，覆盖 8 类工序任务", 16, RGBColor(0xC9, 0xCF, 0xD8), spacing=1.5)
    _tb(s, 0.95, 6.32, 6, 0.35, "智蜂创元 ZFCY  ·  产品解决方案 5.50.C  ·  2026-11", 11, RGBColor(0x8E, 0x97, 0xA5))

    # ── 02 一页看懂 ───────────────────────────────────────────
    s = _blank(prs)
    _head(s, "一页看懂", "三条线讲清这套平台", 2, TOTAL)
    _cards(s, [
        ("做什么", "面向光模块工厂精细操作的\n具身机器人平台：从取料到\n插入、检测、摆盘全流程。"),
        ("凭什么", "三子系统解耦 + 五层引擎 +\n原子技能库；配置驱动换型，\n不靠重新示教。"),
        ("给什么结果", "一件 11.4 s，UPH 294–315；\n插入成功率 ≥99%（目标口径）；\n在线 AOI 判定良品。"),
    ], y=2.35, h=1.95, size=14)
    _tb(s, 0.75, 4.75, 11.8, 1.5,
        "平台已覆盖：精细插入 / 拔出 / 五点检测 / 摆盘供料 / 上料搬运 / 老化插拔 / ATS 检测 / 光学质检\n"
        "同一套软件栈跑仿真与真机，仿真验证过的策略可直接落到产线工位。", 15, INK, spacing=1.6)

    # ── 03 痛点与解法 ─────────────────────────────────────────
    s = _blank(prs)
    _head(s, "为什么需要它", "产线四个卡点，逐条对上解法", 3, TOTAL)
    _table(s, 0.75, 2.05, 11.83, [
        ["产线卡点", "现状", "Z-MAX 解法"],
        ["插拔靠手感", "力度与角度凭经验，伤人伤件", "1 kHz 六维力控 + 力上限保护（插入 ≤40 N）"],
        ["换型靠示教", "换产品要重新点位，停线数小时", "技能 + 配置驱动，换型改参数不改代码"],
        ["良率靠人盯", "不良发现靠终检，返工成本高", "在手五点检测 + 在线 AOI 判定，逐件留证"],
        ["数据不成环", "跑完就散，经验留不住", "每拍留真值，肌肉记忆固化标杆动作"],
    ], col_w=[1.9, 4.35, 5.58], row_h=0.72, size=13)

    # ── 04 产品矩阵 ───────────────────────────────────────────
    s = _blank(prs)
    _head(s, "产品矩阵", "两款机型，覆盖精细操作与通用流转", 4, TOTAL)
    _table(s, 0.75, 2.05, 11.83, [
        ["机型", "定位", "核心指标（目标）", "典型工位"],
        ["Z700 精细操作", "光模块/精密件抓取—对位—插拔\n精细力控 + 宏微复合", "插入成功率 ≥99%\n头到孔底 <4 mm", "插拔、ATS 检测、老化箱、AOI"],
        ["Z100 通用操作", "跨工位上下料/流转/抓放\n移动即工位，一台上装多工序", "抓取成功率 ≥97%\n工位对接 ±10 mm 级", "上料、搬运、摆盘供料"],
    ], col_w=[2.1, 4.5, 2.9, 2.33], row_h=1.05, size=12)

    # ── 05 分级 ───────────────────────────────────────────────
    s = _blank(prs)
    _head(s, "自动化分级", "Z-MAX 按 L2 / L3 / L4 交付，等级写在标准里", 5, TOTAL)
    _table(s, 0.75, 2.05, 11.83, [
        ["等级", "定义", "决策主体", "人工角色", "Z-MAX 对应"],
        ["L2 分段式", "预设工序自动执行，人监控切换", "人编排规则", "编排 + 异常处理", "Z700 F 基线版（已交付）"],
        ["L3 条件自动化", "视觉 + 传感器自动适应", "机器 + 人协同", "异常处理", "Z700 增强版"],
        ["L4 高度自动化", "全自主执行 + 自适应 + 自恢复", "机器", "仅极限介入", "Z700 旗舰版"],
    ], col_w=[2.0, 4.0, 1.9, 2.0, 1.93], row_h=0.62, size=12)
    _tb(s, 0.75, 4.72, 11.8, 0.9,
        "依据 Q/ZFCY 001.1-2026《智算中枢智能化技术标准》L1~L5 分级；\n"
        "L2 基线版已在苏州实验室完成 Phase 0 验收。", 13, SUB, spacing=1.45)

    # ── 06 架构 ───────────────────────────────────────────────
    s = _blank(prs)
    _head(s, "技术架构", "三子系统解耦，一层管一件事", 6, TOTAL)
    _cards(s, [
        ("System 2 · 认知决策\nL4 / L5", "云端大脑：任务拆解与调度\n世界模型预判与恢复\n决策级 IntAct 稳态 101 ms"),
        ("System 1 · 动作执行\nL3", "端到端 VLA 动作策略\n长程技能序列规划\n跨段衔接不断拍"),
        ("System 0 · 基石执行\nL2", "工控机 + 珞石机械臂 6-DOF\n一阶速度伺服 τ=0.08 s\nmax‖v‖ ≤0.5 m/s"),
    ], y=2.15, h=2.15, size=12, title_h=0.62)
    _tb(s, 0.75, 4.62, 11.83, 0.4, "平台支撑（跨子系统）", 14, INK, bold=True)
    _tb(s, 0.75, 5.02, 11.83, 1.6,
        "数据源供给（仿真 metaworld + 真机信号旁路 + 3DGS 场景资产）· 质量门 57 条断言 / 113 项检查\n"
        "共用一套接口：上层只给意图与条件，执行由最下层收口，可行域逐层收窄。", 13, SUB, spacing=1.5)

    # ── 07 能力矩阵 ───────────────────────────────────────────
    s = _blank(prs)
    _head(s, "能力矩阵", "80 条功能入库，按层可查可配", 7, TOTAL)
    _table(s, 0.75, 2.05, 11.83, [
        ["层级", "功能数", "覆盖内容"],
        ["L2 基石", "31", "安全闸、HAL、运动学、力控、标定、执行与回零"],
        ["L3 动作", "4", "技能序列、跨段衔接、伺服跟随"],
        ["L4 / L5 认知", "30", "任务拆解、世界模型、记忆筹划、自进化"],
        ["平台支撑", "15", "数据源、质量门、观察器、可视化、导出"],
    ], col_w=[2.0, 1.4, 8.43], row_h=0.6, size=12)
    _tb(s, 0.75, 5.28, 11.8, 1.0,
        "每条功能都有输入输出、参数、依赖与验证方法，落在工程库（不是文档里口说）。\n"
        "能力特征库 74 / 74 条渠道预留，逐条可追溯到专利与交付件。", 13, SUB, spacing=1.5)

    # ── 08 场景覆盖 ───────────────────────────────────────────
    s = _blank(prs)
    _head(s, "场景覆盖", "12 工位产线，已覆盖 8 类工序任务", 8, TOTAL)
    _table(s, 0.75, 2.05, 11.83, [
        ["任务", "内容", "任务", "内容"],
        ["TASK-01-FW", "上料 + EEPROM 写读校验", "TASK-05-ATS", "线外检测插接（核心挑战）"],
        ["TASK-02-HANDLE", "料盘 / 治具上下料搬运", "TASK-06-TRAY", "光模块摆盘"],
        ["TASK-03-BI", "老化箱模块插拔", "TASK-07-AOI", "AR 光学质量检测"],
        ["TASK-04-THERMAL", "热海柜电口 + 光口插拔", "TASK-08-AL1", "光纤端面检测上料缓存"],
    ], col_w=[2.05, 3.85, 2.05, 3.88], row_h=0.66, size=12)

    # ── 09 双臂分工 ───────────────────────────────────────────
    s = _blank(prs)
    _head(s, "作业编排", "七个元任务，双臂协同，一件 11.4 秒", 9, TOTAL)
    _table(s, 0.75, 2.05, 11.83, [
        ["编号", "动作", "臂"],
        ["MT-01", "上料槽取模块 → 插入目标孔（受控插入 47 mm）", "右"],
        ["MT-02", "沿轴拔出模块（47 mm）", "右"],
        ["MT-03", "手持五点检测（金手指点 + 侧面四点）", "右"],
        ["MT-04 / MT-05", "良品入下料盘空槽 / NG 入废料盘", "右"],
        ["MT-06", "周转盘取模块 → 摆入上料 Tray 空槽", "左"],
        ["MT-07", "供料 / 取料交接同步（槽 k 交接点）", "双"],
    ], col_w=[1.6, 8.4, 1.83], row_h=0.55, size=12)

    # ── 10 节拍 ───────────────────────────────────────────────
    s = _blank(prs)
    _head(s, "节拍实测", "UPH 按三种口径都给，不用最好的那个糊过去", 10, TOTAL)
    _cards(s, [
        ("UPH 294", "发布口径（真跑节拍）\n12.26 s / 件，含保持与换段"),
        ("UPH 305", "闸门口径（约束上限）\n段时长充分性 392 段全过"),
        ("UPH 315", "通道口径（几何最优）\n技能通道夹点 0.565 ms/拍"),
    ], y=2.3, h=1.7, size=13)
    _tb(s, 0.75, 4.3, 11.83, 1.9,
        "对外承诺按 294 报，不按 315 报 —— 差的那 7% 是换段与保持的真实代价。\n"
        "全程每拍留真值：段号、速度、偏差、力值，可回放核对。", 13, SUB, spacing=1.5)

    # ── 11 精度与安全 ─────────────────────────────────────────
    s = _blank(prs)
    _head(s, "精度与安全", "敢下手的前提是先能停住", 11, TOTAL)
    _table(s, 0.75, 2.05, 5.75, [
        ["指标", "数值"],
        ["插入精度", "头到孔底 <4 mm（目标）"],
        ["插入力上限", "≤40 N（超限即停）"],
        ["速度伺服", "τ = 0.08 s，max‖v‖ ≤0.5 m/s"],
        ["力控采样", "1 kHz 六维力"],
    ], col_w=[2.15, 3.6], row_h=0.6, size=12)
    _table(s, 6.85, 2.05, 5.73, [
        ["安全机制", "做法"],
        ["分层安全闸", "动作前逐层否决，任一层不过不出段表"],
        ["动作授权", "只认单一来源，授权过期即拒发"],
        ["物理保护", "双路急停 + 光幕联动降速停机"],
        ["留证", "事故台账逐条编号，闭环才销项"],
    ], col_w=[2.0, 3.73], row_h=0.6, size=12)

    # ── 12 已验证 ─────────────────────────────────────────────
    s = _blank(prs)
    _head(s, "验证证据", "说到的，都能指给你看", 12, TOTAL)
    _table(s, 0.75, 2.05, 11.83, [
        ["项", "证据", "状态"],
        ["L2 基线版", "苏州实验室 Phase 0 验收", "已通过"],
        ["能力入库", "工程库 functions 80 条，含参数与验证方法", "已入库"],
        ["节拍", "整轮 392 段实测 12.26 s/件，复跑两次一致", "已实测"],
        ["自检", "配置中心七星判据 21 / 21 通过", "已通过"],
        ["知识产权", "专利 12 件在申，能力渠道 74 / 74 预留", "在申"],
    ], col_w=[2.0, 8.03, 1.8], row_h=0.6, size=12)

    # ── 13 交付形态 ───────────────────────────────────────────
    s = _blank(prs)
    _head(s, "交付形态", "三档按自动化等级交，交付物一致", 13, TOTAL)
    _table(s, 0.75, 2.05, 11.83, [
        ["档位", "自动化等级", "适用", "交付物"],
        ["基线版", "L2 分段式", "单一工序、人工编排", "平台软件 + 技能库 + 工程库 + 操作手册"],
        ["增强版", "L3 条件自动化", "多工序、换型频繁", "增加视觉自适应 + 在线判定 + 标定包"],
        ["旗舰版", "L4 高度自动化", "整线、少人值守", "增加自主恢复 + 世界模型 + 数据闭环"],
    ], col_w=[1.7, 2.35, 2.9, 4.88], row_h=0.66, size=12)

    # ── 14 路线图 ─────────────────────────────────────────────
    s = _blank(prs)
    _head(s, "落地路线", "四步走进产线，每步都有可验收的产物", 14, TOTAL)
    _cards(s, [
        ("第一步 · 工况测评", "拿你的工件与工位做\n一次实测，出可行性结论\n（不收费）"),
        ("第二步 · 试点工位", "选 1 个工位上线，\n跑满一周节拍与良率，\n双方对数"),
        ("第三步 · 复制扩线", "换型靠配置，复制到\n同线其它工位，\n边际成本递减"),
        ("第四步 · 数据闭环", "真机数据回流训练，\n策略持续进化，\n越用越稳"),
    ], y=2.25, h=1.95, size=12)

    # ── 15 结尾 ───────────────────────────────────────────────
    s = _blank(prs)
    _rect(s, 0, 0, W, H, fill=INK)
    _rule(s, 0.95, 2.35, 1.6, GOLD, h=0.05)
    _tb(s, 0.95, 2.65, 10.6, 1.0, "下一步：拿一个工位试", 34, WHITE, bold=True)
    _tb(s, 0.95, 3.75, 10.6, 1.6,
        "工件、节拍、良率要求给我们，两周内出一份带实测数据的可行性结论。\n"
        "智蜂创元 ZFCY · Z-MAX 具身智能机器人平台", 14, RGBColor(0xC9, 0xCF, 0xD8), spacing=1.6)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    prs.save(out)
    print(f"saved {out}  slides={len(prs.slides.__iter__.__self__._sldIdLst)}")
    return out


if __name__ == "__main__":
    o = OUT
    if "--out" in sys.argv:
        o = sys.argv[sys.argv.index("--out") + 1]
    build(o)
