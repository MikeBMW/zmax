#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《Z700 项目立项文档 —— 成都储翰工厂插拔工位》。

数字全部取自真源，改数只改本脚本的 DATA 段后重跑：
  · 《Z-MAX 以世界模型为核心的状态空间工程》5.50.D-M2（整机外形/能力分级/型号谱系/三档配置）
  · 《Z700 具身智能方案技术协议 v3》（插拔节拍预算/验收口径/回收期双口径）
  · 《Z-MAX 精细操作机器人 F 系列 立项任务书 20261104》（在役实测/短板）
  · 《双臂协作工位项目立项报告》（轨迹真值节拍/精度/力/视觉）
  · 《Z100L 立项文档 v1.1》（市场与用工现场口径、章节骨架）

用法： ./gui-venv311/bin/python tools/gen_z700_project_doc.py [--out DIR]
"""
import argparse
import os

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG = os.environ.get("Z700_FIG_DIR", "/home/ubuntu/.hermes/cache/scratch/z700fig")

NAVY = RGBColor(0x1F, 0x38, 0x64)
GREY = RGBColor(0x59, 0x59, 0x59)
BODY_FONT = "宋体"
HEAD_FONT = "黑体"

# ---------------------------------------------------------------- 基础排版

def set_run(run, size=10.5, bold=False, color=None, font=BODY_FONT):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font)
    if color is not None:
        run.font.color.rgb = color


def shade(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def para(doc, text="", size=10.5, bold=False, color=None, align=None,
         space_before=0, space_after=5, indent=True, font=BODY_FONT, line=1.4):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.line_spacing = line
    if indent:
        pf.first_line_indent = Pt(size * 2)
    if align is not None:
        p.alignment = align
    if text:
        set_run(p.add_run(text), size=size, bold=bold, color=color, font=font)
    return p


def rich(doc, parts, size=10.5, indent=True, space_after=5, line=1.4):
    """parts = [(text, bold), ...]"""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.line_spacing = line
    if indent:
        pf.first_line_indent = Pt(size * 2)
    for text, bold in parts:
        set_run(p.add_run(text), size=size, bold=bold)
    return p


def h1(doc, text, first=False):
    if not first:
        doc.add_page_break()
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(10)
    p.paragraph_format.keep_with_next = True
    set_run(p.add_run(text), size=16, bold=True, color=NAVY, font=HEAD_FONT)
    pr = p._p.get_or_add_pPr()
    bd = OxmlElement("w:pBdr")
    bt = OxmlElement("w:bottom")
    bt.set(qn("w:val"), "single")
    bt.set(qn("w:sz"), "10")
    bt.set(qn("w:space"), "6")
    bt.set(qn("w:color"), "1F3864")
    bd.append(bt)
    pr.append(bd)
    return p


def h2(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    set_run(p.add_run(text), size=13, bold=True, color=NAVY, font=HEAD_FONT)
    return p


def h3(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(7)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.keep_with_next = True
    set_run(p.add_run(text), size=11, bold=True, font=HEAD_FONT)
    return p


def bullet(doc, text, size=10.5, lead=None):
    p = doc.add_paragraph(style="List Bullet")
    pf = p.paragraph_format
    pf.space_after = Pt(2)
    pf.line_spacing = 1.35
    pf.left_indent = Cm(0.75)
    if lead:
        set_run(p.add_run(lead), size=size, bold=True)
    set_run(p.add_run(text), size=size)
    return p


def caption(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(8)
    set_run(p.add_run(text), size=9, color=GREY)


def table(doc, headers, rows, widths, cap=None, size=9, header_fill="D9E2F3",
          align_center_cols=()):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    hdr = t.rows[0]
    _trPr = hdr._tr.get_or_add_trPr()
    _cs = OxmlElement("w:cantSplit")
    _cs.set(qn("w:val"), "true")
    _trPr.append(_cs)   # 必须排在 tblHeader 之前（OOXML 子元素有序）
    repeat_header(hdr)
    for i, htxt in enumerate(headers):
        c = hdr.cells[i]
        c.width = Cm(widths[i])
        shade(c, header_fill)
        c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        c.paragraphs[0].paragraph_format.space_after = Pt(1)
        c.paragraphs[0].paragraph_format.line_spacing = 1.2
        c.paragraphs[0].paragraph_format.keep_with_next = True
        set_run(c.paragraphs[0].add_run(htxt), size=size, bold=True)
    for row_idx, r in enumerate(rows):
        row = t.add_row()
        trPr = row._tr.get_or_add_trPr()
        cs = OxmlElement("w:cantSplit")
        cs.set(qn("w:val"), "true")
        trPr.append(cs)
        cells = row.cells
        for i, val in enumerate(r):
            c = cells[i]
            c.width = Cm(widths[i])
            p0 = c.paragraphs[0]
            p0.paragraph_format.space_after = Pt(1)
            p0.paragraph_format.line_spacing = 1.2
            if i in align_center_cols:
                p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p0.paragraph_format.keep_with_next = True
            set_run(p0.add_run(str(val)), size=size)
    if cap:
        caption(doc, cap)
    return t


def figure(doc, path, width_cm, cap=None):
    if not os.path.exists(path):
        para(doc, "［图缺失：%s］" % os.path.basename(path), size=9, indent=False,
             align=WD_ALIGN_PARAGRAPH.CENTER)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(path, width=Cm(width_cm))
    if cap:
        caption(doc, cap)


def figure_pair(doc, p1, p2, w_cm, cap1, cap2):
    t = doc.add_table(rows=1, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for idx, (path, cap) in enumerate(((p1, cap1), (p2, cap2))):
        c = t.rows[0].cells[idx]
        c.width = Cm(w_cm + 0.4)
        p0 = c.paragraphs[0]
        p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p0.paragraph_format.space_after = Pt(1)
        if os.path.exists(path):
            p0.add_run().add_picture(path, width=Cm(w_cm))
        else:
            set_run(p0.add_run("［图缺失］"), size=9)
        pc = c.add_paragraph()
        pc.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pc.paragraph_format.space_after = Pt(6)
        set_run(pc.add_run(cap), size=9, color=GREY)


def add_footer(section, text):
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run(text + "    第 "), size=8.5, color=GREY)
    run = p.add_run()
    set_run(run, size=8.5, color=GREY)
    fld1 = OxmlElement("w:fldChar")
    fld1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    fld2 = OxmlElement("w:fldChar")
    fld2.set(qn("w:fldCharType"), "end")
    run._r.append(fld1)
    run._r.append(instr)
    run._r.append(fld2)
    set_run(p.add_run(" 页"), size=8.5, color=GREY)


def setup(doc):
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.left_margin = Cm(2.2)
    sec.right_margin = Cm(2.2)
    sec.top_margin = Cm(2.3)
    sec.bottom_margin = Cm(2.0)
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    add_footer(sec, "Z700 项目立项文档 v1.0 · 成都储翰工厂插拔工位 · 内部")
    return doc


# ---------------------------------------------------------------- 封面

def cover(doc):
    for _ in range(3):
        para(doc, "", indent=False, space_after=0)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("Z700 项目立项文档"), size=30, bold=True, color=NAVY, font=HEAD_FONT)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(18)
    set_run(p.add_run("成都储翰工厂 · 光模块插拔工位"), size=17, bold=True, font=HEAD_FONT)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(26)
    set_run(p.add_run("Z-MAX 精细操作机器人 · 双臂插拔工作站"), size=12, color=GREY)

    t = doc.add_table(rows=0, cols=2)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    rows = [
        ("文档版本", "v1.0（首次立项）"),
        ("项目编号", "ZMAX-PD-Z700-2027-01"),
        ("项目类型", "客户场景导入型自研项目"),
        ("应用场景", "成都储翰工厂 光模块插拔工位（FW Loading / EEPROM 写读）"),
        ("产品型号", "Z700 精细操作机器人（F3 精对位插拔档为基线配置）"),
        ("编制单位", "Z-MAX 产品与工程中心"),
        ("编制日期", "2026-11-05"),
        ("密级", "内部"),
    ]
    for k, v in rows:
        cells = t.add_row().cells
        cells[0].width = Cm(3.6)
        cells[1].width = Cm(10.4)
        shade(cells[0], "D9E2F3")
        set_run(cells[0].paragraphs[0].add_run(k), size=10.5, bold=True)
        set_run(cells[1].paragraphs[0].add_run(v), size=10.5)

    para(doc, "", indent=False, space_after=10)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run("编制依据：《Z-MAX 精细操作机器人 能力分级产品解决方案 5.50.D-M2》·"
                      "《Z700 具身智能方案技术协议 v3》"), size=9, color=GREY)


# ---------------------------------------------------------------- 正文

def ch1_background(doc):
    h1(doc, "1. 项目背景与市场分析")

    h2(doc, "1.1 项目类型")
    para(doc, "自研项目 · 客户场景导入型。由 Z-MAX 产品与工程中心立项，以储翰成都工厂光模块插拔工位为首个落地工位，"
              "在同一产品平台上完成「能力分级（C1–C5）→ 型号族（F1–F5）→ 工位配置」的首次闭环，"
              "形成可复制到同类插拔工位的交付基线。")

    h2(doc, "1.2 项目背景")
    para(doc, "面向精密制造产线中自动化最难覆盖的一环——成品光模块的插拔作业：从料盘取件、扫码、翻转、"
              "对准测试座压入、测试完成后拉出、位姿复检与分拣。该岗位动作本身简单，难点在于每一次都必须一致："
              "来料位置偏 2~3 mm、姿态歪 1~2° 时需要操作者凭手感补偿；力气大一点即压伤金手指与壳体，"
              "插不到位则测试误判。")
    para(doc, "现有自动化手段只能覆盖固定型号、固定来料：专机一型号一套工装，六轴示教遇到来料波动即停机等人。"
              "因此这类工位至今仍是一人一岗，判断「插没插到位」依赖人的手感，缺少可复核的机器判据。")
    para(doc, "储翰成都工厂现有员工约 800 人，计划扩至 1,000 人，仍有 100 人以上缺口，且持续难以补齐；"
              "插拔与目检类岗位两班 12 小时连续作业，招工吸引力低、人员流动性大。"
              "Z700 项目即以力控对位、分段压入与双重到位判定直接接管该工位，把「熟练工的手感」变成可复核、"
              "可追溯的机器判据。")

    h2(doc, "1.3 市场分析")
    h3(doc, "1.3.1 光模块市场与用工缺口")
    para(doc, "2025 年，AI 驱动的数据中心建设推动数通光模块市场营收超过 180 亿美元，2024—2029 年复合增长率预计超过 20%，"
              "2029 年将接近 290 亿美元；400G 及以上高速数通光模块 2025 年总出货量达 4,200 万只，"
              "1.6T 模块 2026 年预计放量至 500 万只以上。")
    para(doc, "订单暴增的同时，产能压力急剧攀升：铜陵旭创因扩产，一线技术操作员单次招聘需求高达 1,000 人，"
              "在职员工已超 5,000 人；储翰成都工厂现约 800 人、计划扩至 1,000 人，仍有 100 人以上缺口。"
              "产线中「取—放—插—检」类动作占据大量工时，劳动内容单调重复，恰是招工最难、流失最快的岗位。")
    table(doc,
          ["口径", "数据", "说明"],
          [["旭创单条产线工站数", "63 个", "物料准备、结构件组装、光学耦合、高低温测试到终检包装全流程"],
           ["旭创单条产线操作人数", "193 人", "所有工站合计"],
           ["苏州单线 DL 人数", "189 人", "OE 段 75 人 + 模块段 114 人"],
           ["其中纯目检岗", "50 人", "占苏州单线 DL 约 26%，当前 100% 靠人眼判读"],
           ["储翰成都用工", "约 800 人 → 计划 1,000 人", "缺口 100 人以上，插拔与目检岗位一人一岗"]],
          [4.2, 4.0, 8.4],
          cap="表 1-1 现场调研口径（来源：旭创铜陵/相城、泰国厂区、储翰成都现场调研）",
          align_center_cols=(1,))

    h3(doc, "1.3.2 插拔工位：核心难点在「插」不在「搬」")
    para(doc, "搬运动作的误差可以由下一次动作吸收，插拔动作的误差只能由接触瞬间的力与位移辨识。"
              "插拔工位的难点可拆成五条，每一条都对应可量测的机器判据：")
    table(doc,
          ["难点", "现场表现", "机器判据"],
          [["横向偏差累积", "抓手先碰到壳体或导向槽口，插不进或插歪", "横向偏差 ≤0.5 mm，姿态偏差 ≤1°"],
           ["无力度反馈", "靠时间开环硬压，压坏模块与金手指", "插入力峰值 ≤40 N，超限即停并退段"],
           ["到位不可判", "目视判断深浅不一，测试误判", "位置误差 ≤1 mm、姿态偏差 ≤0.5°，连续两拍一致"],
           ["视觉深度残差", "2D→3D 转换存在深度误差，对不准孔位", "残差交由力觉与位移闭环补偿"],
           ["金手指零划伤", "一次划痕即整只报废", "力控插拔，全程插拔力曲线留档可追溯"]],
          [3.0, 6.6, 7.0],
          cap="表 1-2 插拔工位的物理难点与判据")

    h3(doc, "1.3.3 切入场景：成都储翰工厂插拔工位")
    para(doc, "工位位于储翰成都工厂光模块测试段，承担成品模块的 FW 写入与 EEPROM 读写测试前后的上下料与插拔："
              "人工从料盘逐颗取模块，扫码、翻转、插入测试座（EVB 子板/测试夹具），等待测试完成后拉出，"
              "位姿复检并按判定结果分拣。测试周期 20~90 s，期间人处于等待状态，是典型「设备节拍主导」工位。")
    table(doc,
          ["数据项", "数值或内容", "口径/备注"],
          [["操作对象", "成品光模块（QSFP-DD / OSFP），单颗 100~200 g", "400G/800G 约 0.1 kg，1.6T 约 0.2 kg"],
           ["来料载具", "吸塑盒 / 料盘，20 只/盘", "现场物料规格"],
           ["目标载具", "测试座（EVB 子板 / 测试夹具）", "需与测试机互锁握手"],
           ["单颗节拍要求", "≤6 s（单颗顺序插拔）", "Z700 技术协议 1.3 节拍硬指标"],
           ["整机节拍基线", "≤12 s/件、300 件/h", "5.50 方案稳态口径（含取放与判定）"],
           ["插入力上限", "40 N", "现场工艺红线，超限即停"],
           ["测试等待", "20~90 s（异步，不占节拍）", "一机看管 2 台测试机"],
           ["追溯要求", "SN 扫码绑定，插拔力曲线留档", "客户 MES 口径"],
           ["工位数 / 班次", "待现场清点（首期 1 台验证）", "未采集项，不代填"]],
          [3.0, 7.6, 6.0],
          cap="表 1-3 储翰插拔工位现场数据")
    para(doc, "单颗插拔全链动作与时间预算如下（硬指标 ≤6.0 s，测试等待异步并行）：")
    table(doc,
          ["步", "动作", "时间预算", "依据"],
          [["1", "从料盘取模块", "0.6 s", "行程 0.15 m、末端 0.5 m/s"],
           ["2", "移至扫码位扫 SN", "1.0 s", "行程 0.3 m、位姿稳定"],
           ["3", "翻转模块（标签朝下）", "0.8 s", "腕部旋转 180°"],
           ["4", "对准测试座、导向槽直推到位", "1.2 s", "对位 0.5 s + 插入 0.7 s（力控）"],
           ["5", "等待自动测试（约 50 s）", "异步", "并行处理另一台机台"],
           ["6", "读取测试结果", "0.2 s", "与测试机联动"],
           ["7", "拉出模块", "0.8 s", "力控拉出"],
           ["8", "AOI 位姿复检（外壳/金手指）", "0.6 s", "旋转 + 平移"],
           ["9", "分拣至 Pass / Fail 料盘", "0.8 s", "行程 0.4 m、末端 1.0 m/s"],
           ["合计", "单颗节拍", "≤6.0 s", "满足硬指标"]],
          [1.2, 6.6, 3.2, 5.6],
          cap="表 1-4 单颗插拔动作序列与节拍预算（来源：Z700 技术协议 2.2）",
          align_center_cols=(0, 2))
    para(doc, "本工位的验收口径按客户与现场共同确认的四条执行：")
    bullet(doc, "连续 72 h、累计有效插拔 ≥5,000 次；成功率 = 成功次数 / 总尝试次数，机器人原因失败允许重试 1 次，"
                "重试成功仍计失败。", lead="稳定性与成功率：")
    bullet(doc, "取中间稳定段 ≥200 颗的平均值；测试等待不计入，但须证明异步能力（一机看管 2 台）。", lead="节拍：")
    bullet(doc, "软件切换型号 ≤0.5 h，兼容 QSFP / OSFP / SFP 系列；金手指零划痕、模块无掉落、无计划外碰撞。", lead="换型与工艺：")
    bullet(doc, "每次动作的插拔力曲线、位姿与判定结果全量记录，可回放追溯。", lead="数据：")

    h3(doc, "1.3.4 市场空间与导入路径")
    para(doc, "导入路径按「单点验证 → 同厂复制 → 集团同类工位」三步走，需求量级按一机看管 2 台测试机折算：")
    table(doc,
          ["阶段", "对象", "台数口径", "依据/状态"],
          [["首期验证", "储翰成都 插拔工位", "1 台", "本项目交付范围"],
           ["同厂复制", "储翰成都 同工序插拔工位", "插拔工位数 ÷ 2", "工位总数待现场清点"],
           ["集团复制", "智禾 COC 测试段、旭创苏州/泰国测试段", "同类测试工位数 ÷ 2", "待客户确认工艺差异与接口"],
           ["行业空间", "光模块及上下游测试/写入工位", "按存量产线改造口径估算", "工位基数与插拔占比待调研，不代填"]],
          [2.9, 6.2, 3.4, 4.1],
          cap="表 1-5 导入路径与需求量级口径")
    para(doc, "首期不设场景门槛，先把一个工位的稳定性与节拍做出来；只有当同一工位连续运行满 6 个月、"
              "并覆盖 3 个以上型号时，才进入同厂复制，避免「样机变成孤岛」。")

    h3(doc, "1.3.5 问题与机遇")
    bullet(doc, "插拔工位对精度与力控的要求高于搬运类工位，单台设备成本与交付复杂度均上一个台阶；", lead="当前问题 · ")
    bullet(doc, "现场来料批次、型号与料盘规格存在差异，换型时间直接决定设备利用率；", lead="当前问题 · ")
    bullet(doc, "客户决策层需要技术验证与 ROI 数据双重支撑，首台必须能出具连续运行证据；", lead="当前问题 · ")
    bullet(doc, "插拔是行业准入门槛，而「力控 + 双重到位判定 + 全过程追溯」是可形成壁垒的部分；", lead="核心机遇 · ")
    bullet(doc, "同一平台可向下覆盖抓放（F1）、向上覆盖近零间隙力控（F4），一套代码基线支撑多档交付；", lead="核心机遇 · ")
    bullet(doc, "工位数据（图像、力曲线、结果）自动沉淀，型号换型与工艺优化可复用，摊薄后续交付成本。", lead="核心机遇 · ")

    h3(doc, "1.3.6 目标工位筛选门槛")
    table(doc,
          ["门槛", "判定条件"],
          [["节拍门槛", "机器人单次插拔时间 ≤ 现场可接受窗口：本工位 ≤6 s；导入其它工位前须取得现场给定窗口"],
           ["覆盖门槛", "单台机器人可服务测试机台数 ≥2（异步看管），否则按固定工位单机核算成本"],
           ["通过门槛", "工位操作空间满足双臂工作站就位与维护净宽；不改动现有料盘与测试机接口"],
           ["力度门槛", "插入力上限 ≤40 N，且超限必须可停止、可退段、可重试"]],
          [3.2, 13.4],
          cap="表 1-6 目标工位筛选门槛")


def ch2_product(doc):
    h1(doc, "2. 项目目标与产品定义")
    h2(doc, "2.1 产品定位")
    para(doc, "Z700 精细操作机器人是面向光模块与精密件的「抓取—对位—插拔」作业的双臂工作站。"
              "本项目采用台面式双臂形态：左臂负责料盘与摆盘，右臂负责插拔与取图，双线并行；"
              "末端模块化（夹爪 + 力觉），整机固定于工位台面，沿用现场料盘与测试座接口，不改动产线布局。")
    table(doc,
          ["特有价值", "说明"],
          [["一机双台", "测试周期 20~90 s 期间机器人空闲，可异步看管 2 台测试机，产能不依赖单机速度"],
           ["免改造部署", "以人的作业姿态直接接管工位，沿用现有料盘、测试座与料架，不需要重排产线"],
           ["能力分级交付", "按 C1–C5 能力档配置，客户先买「够用的一档」，后续升级只换配置项与软件档"],
           ["判据可复核", "对位、力度、到位三项判据逐件记录，替代「凭手感」的人工判断"]],
          [3.4, 13.2],
          cap="表 2-1 Z700 的产品价值构成")

    h2(doc, "2.2 外形与结构")
    h3(doc, "2.2.1 整机外观")
    para(doc, "整机由双臂本体、实验桌台面、料盘与中央顶视相机组成，双臂对称安装于台面后方，"
              "料盘位于台面中部，中央相机由立柱架高俯视作业区，形成「上看下、臂从两侧进」的作业构型。")
    figure(doc, os.path.join(FIG, "外观_urdf.png"), 13.6,
           "图 2-1 整机外观渲染（双臂工作站 + 台面 + 料盘）")
    h3(doc, "2.2.2 三视图与作业姿态")
    para(doc, "台面 1,600 × 600 × 30 mm、台面高 750 mm；双臂间距 500 mm；箱体 600 × 800 × 750 mm。"
              "料盘为 3 组 × 14 槽并配废料盘，中央顶视相机半径 70 mm、俯角 35°。")
    figure_pair(doc, os.path.join(FIG, "正视图.png"), os.path.join(FIG, "侧视图.png"), 6.6,
                "图 2-2 正视图（沿 −X 看）", "图 2-3 侧视图（沿 −Y 看）")
    figure_pair(doc, os.path.join(FIG, "俯视图.png"), os.path.join(FIG, "立体图.png"), 6.6,
                "图 2-4 轴向图（沿 −Z 俯视）", "图 2-5 立体·作业姿态")
    h3(doc, "2.2.3 整机构成与关键尺寸")
    table(doc,
          ["部件", "规格（mm）", "说明"],
          [["底盘箱体", "600 × 800 × 750", "本体 680 + 轮 75；4 轮 Ø150"],
           ["实验桌", "1,600 × 600 × 30", "台面高 750"],
           ["机械臂 ×2", "XMS5-R800", "右臂 y=0，左臂 y=+500；本体 13.622 kg/台"],
           ["料盘", "3 组 × 14 槽 + 废料盘", "场景实测 42 个槽口；槽口 36 × 42"],
           ["中央相机", "r 70，俯角 35°", "立柱高 328（= J1 高），FOV 87° × 58°"]],
          [3.2, 6.2, 7.2],
          cap="表 2-2 整机构成与关键尺寸（来源：整机 3D 场景定义与 URDF）")
    para(doc, "作业姿态（URDF 正运动学复算）：右臂法兰 (493.3, −217.9, 237.4) mm；"
              "左臂法兰 (493.0, 226.9, 237.5) mm（基座系）。")
    h3(doc, "2.2.4 机械臂主要结构参数")
    table(doc,
          ["轴", "关节原点（mm，基座系）", "轴向", "行程", "额定力矩"],
          [["J1", "(0.0, 0.0, 328.0)", "(0,0,1)", "±360°", "113 N·m"],
           ["J2", "(0.0, 0.0, 0.0)", "(0,1,0)", "−160°~+150°", "113 N·m"],
           ["J3", "(50.0, 0.0, 400.0)", "(0,−1,0)", "−170°~+140°", "70 N·m"],
           ["J4", "(−50.0, 0.0, 400.0)", "(0,0,1)", "±360°", "25 N·m"],
           ["J5", "(0.0, 136.0, 0.0)", "(0,−1,0)", "±360°", "25 N·m"],
           ["J6", "(0.0, 0.0, 103.5)", "(0,0,1)", "±360°", "19 N·m"]],
          [1.4, 5.6, 3.0, 3.6, 3.0],
          cap="表 2-3 机械臂主要结构参数（来源：厂家 URDF；各轴最大角速度 180 °/s）",
          align_center_cols=(0, 2, 3, 4))

    h2(doc, "2.3 能力分级：C1–C5")
    para(doc, "产品能力按「替客户省掉什么」分五级，每一级都有三项可测判据，达不到判据不算具备该级能力。"
              "本项目基线为 C3（精对位插拔），即插拔工位真正要买的那一档。")
    table(doc,
          ["级", "能力", "替客户省掉", "进入判据（摘要）", "状态"],
          [["C1", "定位抓放", "一个人的手", "抓取成功率 ≥99%，位置误差 ≤2 mm，单次抓放 ≤3.6 s", "在役"],
           ["C2", "柔性自适应", "换型与调机的人", "偏差 ±10 mm / ±10° 内自恢复 ≥99%，换型 ≤10 min", "规划"],
           ["C3", "精对位插拔", "一个熟练工的手感", "横向 ≤0.5 mm、姿态 ≤1°、插入力 ≤40 N", "在役"],
           ["C4", "力控装配", "装配工的试插经验", "间隙 ≤0.05 mm 可插、深度一致性 ≤0.05 mm、力 ≤30 N", "在研"],
           ["C5", "自主进化", "持续调参的人", "闭环 N 轮指标单调不降，人工只在否决位", "试运行"]],
          [1.0, 3.0, 3.6, 7.4, 1.6],
          cap="表 2-4 五级能力定义与进入判据",
          align_center_cols=(0, 4))
    h3(doc, "2.3.1 C3 精对位插拔：本项目交付的核心能力")
    para(doc, "系统需具备在 0.1~0.5 mm 微小间隙下的精密对位与插拔能力，并具备力觉保护："
              "插入力超限时自动停止并退回重试，绝不强行硬压损坏工件。")
    bullet(doc, "横向偏差 ≤0.5 mm、姿态角度偏差 ≤1°；", lead="对位精度：")
    bullet(doc, "插入过程最大力量峰值 ≤40 N；分段压入每进 0.5 mm 核验一次位移与接触力；", lead="力量控制：")
    bullet(doc, "位置误差 ≤1 mm、姿态偏差 ≤0.5°，且连续两拍一致，方认定到位；", lead="到位判定：")
    bullet(doc, "一次性插拔结果必须与 AOI 判定结果一致，差异件单独隔离复检；", lead="结果一致性：")
    bullet(doc, "来料符合标准前提下单件节拍 ≤12 s（约 300 件/h）。", lead="产能表现：")
    para(doc, "C1/C2 解决「拿得到、放得下」，C3 解决「插得进、不压坏」，C4 才进入「近零间隙」场景。"
              "本项目按 C3 交付，C4 作为下一阶段的在研能力，不在本期对外承诺。")

    h2(doc, "2.4 产品型号谱系：F1–F5")
    para(doc, "同一套代码基线与接口契约，按能力档切出五个型号；硬件差异只影响配置项，不影响交付流程，"
              "这是同平台复制的前提。")
    table(doc,
          ["型号", "能力档", "核心指标", "目标成本", "交付周期"],
          [["F1", "C1 定位抓放", "抓取 ≥99%，位置 ≤1 mm，≤3.6 s/次", "22 万", "2 周"],
           ["F2", "C2 柔性自适应", "±10 mm/±10° 自恢复 ≥99%、换型 ≤10 min", "30 万", "4 周"],
           ["F3", "C3 精对位插拔", "横向 ≤0.5 mm、姿态 ≤1°、力 ≤40 N、300 件/h", "30 万", "4~6 周"],
           ["F4", "C4 力控反馈", "间隙 ≤0.05 mm、深度一致性 ≤0.05 mm、力 ≤30 N", "30 万", "8~10 周"],
           ["F5", "C5 自主进化", "N ≥3 轮闭环指标稳定不降低", "35 万", "项目制"]],
          [1.5, 3.5, 7.4, 2.2, 2.0],
          cap="表 2-5 型号谱系（价格带为硬件 + 软件 + 调试的整单元区间，不含线体与 MES）",
          align_center_cols=(0, 3, 4))
    table(doc,
          ["件", "F1", "F2", "F3", "F4", "F5"],
          [["机械臂", "5 kg / 900 mm", "5 kg / 1300 mm", "5 kg / 1300 mm", "同 F2/F3", "同 F4"],
           ["末端", "二指夹爪", "精对位夹爪", "柔顺 + 六维力", "快换工装", "快换 + 标定套件"],
           ["力觉", "无", "单轴 0–200 N", "六维 0.1 N", "六维", "六维"],
           ["视觉", "单目 1200 万", "手臂相机 + 工位相机", "+3D 视觉", "+多相机标定", "+多相机标定"],
           ["软件档", "抓放档", "柔性", "+精准对位", "+力控反馈", "+进化闭环"]],
          [2.0, 2.8, 3.2, 3.2, 2.8, 2.6],
          cap="表 2-6 硬件差异表（同平台，差在四个件）",
          align_center_cols=(1, 2, 3, 4, 5))
    para(doc, "本项目选 F3 为交付基线：双臂 + 柔顺末端 + 六维力觉 + 3D 视觉得以覆盖插拔工位；"
              "若客户首期只要求取放与摆盘，可下配到 F1，现场仅更换末端与力觉配置，机械与电气接口不变。")

    h2(doc, "2.5 产品性能指标")
    table(doc,
          ["项目", "指标", "口径"],
          [["单件节拍", "≤12 s/件（设计基线），分阶段目标 3.6 s/次", "取放 + 对位 + 压入 + 判定完整循环"],
           ["产能", "≥300 件/h（12 s/件折算）", "节拍折算，非实测产量；OEE 0.85 时约 255 件/h 有效产出"],
           ["插入力上限", "≤40 N，超限即停并退段", "现场工艺红线"],
           ["到位判定", "位置 ≤1 mm、姿态 ≤0.5°，连续两拍一致", "双重到位"],
           ["对位精度", "横向 ≤0.5 mm、姿态 ≤1°", "C3 判据"],
           ["重复定位", "AP ≤0.50 mm、RP ≤0.10 mm", "ISO 9283 §7.2/§7.4，第三方实测前不进验收"],
           ["插入行程", "47.0 mm @156.7 mm/s", "光模块插入段轨迹"],
           ["视觉精度", "0.76 mm/px @300 mm，深度单位 0.1 mm", "工位相机标定口径"],
           ["成功率", "整机全流程 ≥99%，子动作 ≥99.5%", "重试成功后仍计失败"],
           ["连续作业", "≥8 h 无人值守；验收 72 h 连续运行", "现场验收口径"],
           ["单件成本", "0.1 元（人工折算 0.36 元）", "两班 16 h、OEE 0.85"]],
          [3.0, 7.8, 5.8],
          cap="表 2-7 产品性能指标（来源：5.50 方案的稳态口径与整机实测）")

    h2(doc, "2.6 产品形态与配置档位")
    para(doc, "同平台三档配置，按「双臂 / 单臂 + 软件档位」区分，客户按能力档选配：")
    table(doc,
          ["配置", "能力覆盖", "总目标成本", "硬件目标成本", "客户回本周期"],
          [["A 档 · 基本性能", "单任务抓放（C1）", "20 万", "15 万（单臂）", "1 年"],
           ["B 档 · 精细操作", "抓放 + 编排（C2）", "30 万", "23 万（双臂）", "1.5 年"],
           ["C 档 · 专业性能", "抓放 + 编排 + 安全分级（C3 及以上）", "40 万", "23 万（双臂）", "2 年"]],
          [3.4, 5.8, 2.3, 2.6, 2.5],
          cap="表 2-8 三档配置与目标成本",
          align_center_cols=(2, 3, 4))
    para(doc, "本项目按 B 档（双臂精细操作）配置，能力按 C3 交付；C 档的安全分级与 C4 力控档作为后续升级路径，"
              "升级只增加配置项与软件档，不更换本体。")

    h2(doc, "2.7 分阶段目标")
    table(doc,
          ["阶段", "时间", "目标", "判据"],
          [["一阶段 · 实验室", "T0 + 3 个月", "插拔工位单工位跑通", "单件 ≤12 s、成功率 ≥95%、力控通道可用"],
           ["二阶段 · 储翰现场", "T0 + 6 个月", "现场工位稳定运行", "72 h 连续、≥5,000 次插拔、成功率 ≥98%、换型 ≤30 min"],
           ["三阶段 · 复制", "T0 + 12 个月", "同厂复制与能力升级", "成功率 ≥99%、一机双台异步、C4 力控档完成重复性验证"]],
          [3.2, 2.8, 4.2, 6.4],
          cap="表 2-9 分阶段目标（T0 = 项目启动月，2026-12）")

    h2(doc, "2.8 产品开发流程")
    para(doc, "产品化与场景应用分开组织、并行推进：产品化围绕通用能力做工程验证（EVT）、设计验证（DVT）、"
              "生产验证（PVT）；场景应用按客户工位完成适配、数采训练、部署与验收。")
    table(doc,
          ["阶段", "目标", "阶段指标"],
          [["EVT", "本体与软件方案闭环", "功能可用、无 P0 缺陷，样机配置与版本记录齐全"],
           ["DVT", "通用能力与指标验证", "按冻结的能力要求与测试大纲验收，含连续运行与异常恢复"],
           ["PVT", "小批量试产与降本", "装配标定、检验与一致性达标，量产 BOM 与配置清单冻结"],
           ["场景应用", "工位适配与交付", "工位配方、点位与换型参数冻结，验收证据可回放"]],
          [2.4, 5.2, 9.0],
          cap="表 2-10 开发阶段与阶段指标",
          align_center_cols=(0,))


def ch3_business(doc):
    h1(doc, "3. 商业模式与投资回报")
    h2(doc, "3.1 成本构成")
    para(doc, "成本按三档目标成本控制（见表 2-8）。成本控制的四条工程手段："
              "① 端侧推理替代云端算力，单台每年省云算力费用；② 模型量化部署，无需高配边缘硬件；"
              "③ 技能模板复用，新场景只做参数化；④ 通用夹爪 + 软件换型，硬件不换型、只换参数。")
    h2(doc, "3.2 价格体系与对标")
    table(doc,
          ["公司", "产品类型", "市场售价"],
          [["它石智航", "轮式双臂移动", "约 50 万/台"],
           ["星海图", "轮式双臂", "约 40 万/台"],
           ["智元", "具身机器人", "约 65 万/台"],
           ["Z-MAX · Z700（F3）", "双臂插拔工作站", "30 万（F3 目标成本）"]],
          [4.2, 5.4, 5.0],
          cap="表 3-1 同类产品价格对标（2026 年公开市场口径）",
          align_center_cols=(2,))
    para(doc, "F3 定价处于行业主流价格带下沿：与轮式双臂类产品相比低 10~35 万，"
              "差异来自形态（台面式工作站不含移动底盘）与端侧推理架构。对外报价以商务确认为准。")
    h2(doc, "3.3 投资回报")
    para(doc, "客户侧按「替代两班 2 人」口径测算：单个工位白班晚班各 1 人、每人每年 10 万元（含社保公积金），"
              "合计 20 万元/年。设备按 F3 目标成本 30 万元计，静态回本期 1.5 年。")
    table(doc,
          ["口径", "年省人工", "设备价", "回本期", "结论"],
          [["两班替代 2 人", "20 万元", "30 万元", "1.5 年", "客户可接受区间"],
           ["单班替代 1 人", "10 万元", "30 万元", "3.0 年", "多数工厂采购门槛 3 年，需配合运营期让利"],
           ["单件成本对比", "人工 0.36 元/件 → 设备 0.1 元/件", "—", "降幅 70.7%", "按两班 16 h、OEE 0.85 折算"]],
          [3.2, 4.2, 2.2, 2.4, 4.6],
          cap="表 3-2 客户侧投资回报（双口径并列，对外按更保守口径报）")
    para(doc, "结论：Z700 必须按「一机看管 2 台测试机 + 两班倒」销售，回收期才能进入 2 年以内；"
              "单班替代场景只能作为技术验证与战略导入，不作为短期经济性卖点。")


def ch4_tech(doc):
    h1(doc, "4. 技术可行性分析")
    h2(doc, "4.1 技术底座")
    para(doc, "Z700 的软件底座为 Z-MAX 状态空间工程引擎（5.50 版）：把「感知—对位—插入—判定」拆成可独立验收的功能节点，"
              "当前工程内含 85 个节点、171 条输入与 162 条输出接口，各节点带输入/输出契约与可定位实现，"
              "现场问题可按节点定位、按契约复现。数据链路为「采集 → 训练 → 评估 → 部署」闭环，"
              "推理在端侧完成，不依赖云端。")
    h2(doc, "4.2 已验证能力")
    table(doc,
          ["项", "实测值", "口径"],
          [["单件节拍", "11.42 s/件", "392 段轨迹真值，模数 14 件/轮"],
           ["产能", "315.2 件/h", "按 11.42 s/件折算；产线连续跑数 314 件/h（11.468 s/件）"],
           ["对位", "横向 ≤0.5 mm、姿态 ≤1°", "C3 三项判据在役"],
           ["插入力", "上限 40 N，分段 0.5 mm/次核验", "力曲线全程留档"],
           ["重复定位", "AP ≤0.50 mm、RP ≤0.10 mm", "ISO 9283 §7.2/§7.4"],
           ["插入段", "行程 47.0 mm @156.7 mm/s", "轨迹真值"],
           ["视觉", "0.76 mm/px @300 mm", "深度单位 0.1 mm"],
           ["自主进化", "闭环 1 轮通过", "六道门禁齐备，试运行阶段"]],
          [3.2, 7.0, 6.4],
          cap="表 4-1 已验证能力与实测口径")
    h2(doc, "4.3 成功率要求")
    table(doc,
          ["阶段", "取料", "上料", "下料", "分拣", "环境"],
          [["一阶段（实验室）", "95%", "90%", "95%", "95%", "实验室环境"],
           ["二阶段（现场）", "98%", "95%", "98%", "98%", "实验室 + 现场"],
           ["三阶段（复制）", "99%", "98%", "99%", "99%", "客户产线连续运行 ≥24 h"]],
          [4.4, 2.2, 2.2, 2.2, 2.2, 3.4],
          cap="表 4-2 分阶段成功率要求",
          align_center_cols=(1, 2, 3, 4))
    h2(doc, "4.4 验证方法")
    bullet(doc, "每项测试先确定对象、工况、配置版本、计量方法与合格阈值，再执行测试并留档。", lead="测试前置：")
    bullet(doc, "功能完整性、识别定位、负载与可达、精度与接触控制、节拍、成功率、连续运行、安全异常恢复、复用一致性九项逐项记录。",
           lead="验证项：")
    bullet(doc, "首次成功率 = 首次执行成功次数 / 总执行次数；自主任务成功率 = 规定重试范围内无需人工介入的任务次数 / 总任务次数。",
           lead="统计口径：")
    bullet(doc, "连续 72 h、累计有效插拔 ≥5,000 次；中间稳定段 ≥200 颗平均值作为节拍结论。", lead="现场验收：")
    h2(doc, "4.5 尚未闭环的事项")
    table(doc,
          ["事项", "现状", "计划"],
          [["对位阶段耗时", "占总周期 48%~55%，是节拍最大变量", "以精对位前馈与宏微复合压缩，列入 DVT 指标"],
           ["力觉增益", "力对动作精度的增益尚未单独证明", "按同口径消融补齐，未证明前不写入对外承诺"],
           ["C4 近零间隙", "在研，未开工验证", "下一阶段按 0.05 mm 间隙做重复性验证"],
           ["几何标定", "工位相机外参需现场标定", "现场标定 1 天，标定后复测精度"],
           ["安全认证", "安全等级为目标值，未做第三方验证", "按 ISO 13849 走第三方，8~12 周"]],
          [3.4, 7.0, 6.2],
          cap="表 4-3 尚未闭环事项与计划（未闭环项不进入对外承诺）")


def ch5_compute(doc):
    h1(doc, "5. 算力分析")
    para(doc, "本项目的算力问题不是「够不够」，而是「放在哪一层、按什么节拍调用」。控制环要求 20 ms 一拍，"
              "任务级推理是秒级，两者相差两个数量级；方案要做的是让秒级推理不占用 20 ms 的拍，"
              "而不是把更大的算力堆到机器人上。")
    h2(doc, "5.1 时间尺度与单次预算")
    para(doc, "各环节的频率与单次耗时取实测值（工作机同口径，见附录 B）：")
    table(doc,
          ["环节", "时间尺度", "频率", "单次预算 / 实测"],
          [["控制拍（执行收口）", "20 ms", "50 Hz", "回路单周期 0.99 ms（p95 1.46 ms）"],
           ["视觉定位（检测 + 反投影）", "20 ms", "50 Hz", "单层 20.09 ms"],
           ["潜空间预测（端侧）", "4.4 ms", "可每拍", "单次前向 4.4 ms"],
           ["技能编排", "百毫秒", "每步", "单层 0.07 ms"],
           ["任务级推理", "秒级", "异步", "单层 254.27 ms"],
           ["整链（端到端）", "—", "异步消费", "中位 415.05 ms / 最大 13.2 s"],
           ["力觉采集", "10 kHz 采样", "降采样到 50 Hz", "采样不进拍，仅参与融合"]],
          [4.0, 3.2, 3.6, 5.8],
          cap="表 5-1 各环节时间尺度与单次预算（实测口径）")

    h2(doc, "5.2 端侧算力需求测算")
    bullet(doc, "状态预测模型合计 20,976,792 参数（视觉编码器约 5.7M、动作编码约 0.1M、预测头约 14M），"
                "INT8 量化后权重约 21 MB，常驻内存 <1 GB 量级。", lead="模型规模：")
    bullet(doc, "1,000 件/h 时单件 3.6 s，等于 180 个 20 ms 拍；单次前向实测 4.4 ms，"
                "即使每拍都算也只占单件时间预算的 22%（180 × 4.4 ms = 0.79 s）。", lead="单件预算：")
    bullet(doc, "整链实测 415.05 ms/帧，其中任务级推理单层 254.27 ms 占 61%。若按同步串行执行，"
                "单件 180 拍需 74.7 s，是 3.6 s 目标的 20.7 倍——所以任务级推理必须异步，控制侧只在 20 ms 拍内收口。",
           lead="当前瓶颈：")
    bullet(doc, "常驻回路 10 Hz、单周期中位 0.99 ms（p95 1.46 ms），控制侧几乎不占算力，无需为控制单独加卡。",
           lead="控制侧：")

    h2(doc, "5.3 端侧平台选型")
    para(doc, "端侧按 AI 模组分三档，差异不在「能不能算」，而在内存、相机路数与力控通道：")
    table(doc,
          ["档位", "AI 模组", "AI 算力（INT8）", "内存", "相机接口", "力控"],
          [["基线档", "Jetson Orin Nano 8 GB", "40 TOPS", "8 GB", "4 路 GMSL", "外置力传感器"],
           ["增强档", "Jetson AGX Orin 32 GB", "275 TOPS", "32 GB", "8 路 GMSL2", "关节力控 1 kHz"],
           ["旗舰档", "AGX Orin + RK3588", "281 TOPS", "32 + 8 GB", "16 路 GMSL2", "1 kHz + 六维力"]],
          [2.6, 4.0, 2.8, 2.2, 2.6, 2.4],
          cap="表 5-2 端侧算力三档（按 AI 模组与接口配置划分）")
    para(doc, "本项目（F3 双臂插拔）取增强档 32 GB / 275 TOPS：双臂并行时需同时常驻感知、编排与预测模型，"
              "8 GB 档在多模型常驻下余量不足；F1 抓放档可用基线档，F4/F5 再上旗舰档。"
              "AI 模组采购价按供应链报价回填，已含在表 2-8 的硬件目标成本中。")

    h2(doc, "5.4 端侧模型延迟参考")
    table(doc,
          ["模型", "参数量", "部署位置", "延迟"],
          [["动作预测（ACT 系）", "52M", "端侧", "8.4 ms"],
           ["快速原型（MLP）", "14.7M", "端侧", "<5 ms"],
           ["本产品状态预测模型", "20.98M", "端侧", "4.4 ms（单次前向）"],
           ["大模型复核（VLA 系）", "450M", "端侧主节点 gRPC", "215 ms"]],
          [4.4, 2.6, 5.0, 4.6],
          cap="表 5-3 端侧模型延迟参考")
    para(doc, "进拍的是 5~50M 级模型；450M 级模型延迟 215 ms，只能做任务级复核与异常解释，与 5.2 的结论一致。")

    h2(doc, "5.5 三机分工：算力不都堆在机器人上")
    table(doc,
          ["角色", "部署位置", "承担"],
          [["训练与验证", "训练主机（RTX 4060）", "联合训练、消融、量化导出（INT8 / FP16）"],
           ["端侧主节点", "Intel x86 工控机", "引擎服务、页面与网关、AOI 前端、数据落盘"],
           ["机器人侧", "Orin 域控（本体内）", "ROS2 域 0、50 Hz 位姿真值、桥接执行"],
           ["开发编排", "工作站", "画布、AR 页、报告、技能库（8791 / 8793 / 8797 / 8805）"]],
          [3.2, 4.6, 8.8],
          cap="表 5-4 训练、端侧与机器人侧的算力分工")
    para(doc, "跨机只走既有隧道，不新开端口；机器人侧只做实时闭环，训练与页面全部在主机侧，"
              "避免实时控制被推理与页面请求抢占。")

    h2(doc, "5.6 算力瓶颈与处置")
    table(doc,
          ["瓶颈", "证据", "处置"],
          [["任务级推理 254 ms", "单层实测（工作机同口径）", "不进 20 ms 拍：异步调用 + 技能记忆直通 + 提前一拍预测"],
           ["整链 415 ms", "端到端实测中位", "只用于任务切换与异常复核，按 ≤2.4 Hz 消费"],
           ["内存常驻", "登记 14 个模型（感知 5 / 编排 4 / 预测 4 / 场景 1）", "端侧取 32 GB 档；同刻只允许一套模型进程"],
           ["端侧未做同口径实测", "现有逐层实测均在工作机", "M1 内在 Orin 上复测逐层与整链，作为选型复核判据"],
           ["相机带宽", "实配 3 路（手臂 / 工位 / 深度）", "8 路 GMSL2 接口留余量；三路 1080p50 按需降帧"]],
          [4.2, 5.6, 6.8],
          cap="表 5-5 算力瓶颈与处置")

    h2(doc, "5.7 结论")
    para(doc, "算力不是本项目的瓶颈：模型 21 MB、单次前向 4.4 ms、275 TOPS 档余量充足。"
              "真正的瓶颈是调用时序与内存常驻——项目按「20 ms 级检测与收口进拍、254 ms 级任务推理异步」落地，"
              "端侧取 32 GB 档，同刻只允许一套模型进程；端侧 Orin 上的整链实测列入 M1 判据，作为选型复核点。")


def ch6_org(doc):
    h1(doc, "6. 项目成员分工")
    para(doc, "项目按「每条判据一个责任人」组织，不按模块分人；角色与关键交付如下，具体人员由项目启动会任命。")
    table(doc,
          ["角色", "职责", "关键交付"],
          [["项目总负责人", "对项目目标、预算与里程碑负责", "立项决策、阶段评审结论"],
           ["产品经理", "能力档与型号配置、对外口径", "产品定义、验收口径、交付边界"],
           ["项目经理", "计划、资源、风险与周报", "里程碑达成记录、风险台账"],
           ["算法（对位/力控）", "C3 对位收敛、力控压入与到位判定", "判据实测报告、消融记录"],
           ["数采与训练", "工位数据采集管线、模型迭代", "数据集版本、训练与评估报告"],
           ["结构 / 硬件", "本体检修、末端与工装、现场安装", "结构图纸、BOM、安装记录"],
           ["控制器 / 基础软件", "运动控制、通信与现场联锁", "驱动适配、接口联调记录"],
           ["数据平台", "数据入库、回放与追溯", "数据平台上线、追溯演示"],
           ["现场交付", "工位改造、示教、陪产与验收", "现场交付记录、验收证据包"]],
          [3.4, 6.6, 6.6],
          cap="表 6-1 角色与关键交付")


def ch7_plan(doc):
    h1(doc, "7. 项目计划")
    para(doc, "项目周期 12 个月（2026-12 至 2027-11），按五个里程碑推进；每个里程碑先定义「拿什么证明」，"
              "无证据的里程碑不计入进度。")
    table(doc,
          ["阶段", "时间", "工作内容", "里程碑判据"],
          [["M1 平台就位", "2026-12 ~ 2027-01", "本体就位、工位标定、插拔通道打通", "单颗插拔跑通、力控通道可用"],
           ["M2 实验室达标", "2027-02 ~ 2027-04", "对位收敛、节拍优化、连续运行", "单件 ≤12 s、成功率 ≥95%"],
           ["M3 现场导入", "2027-05 ~ 2027-07", "储翰工位安装、示教、陪产", "72 h 连续、≥5,000 次、成功率 ≥98%"],
           ["M4 验收与复制准备", "2027-08 ~ 2027-09", "换型验证、验收证据包、复制方案", "换型 ≤30 min、验收通过"],
           ["M5 能力升级", "2027-10 ~ 2027-11", "一机双台异步、C4 预研", "成功率 ≥99%，C4 验证计划评审通过"]],
          [3.0, 3.4, 5.6, 4.6],
          cap="表 7-1 项目里程碑计划")
    para(doc, "并行安排：结构件与末端加工在 M1 期间完成；数据采集与训练在 M2 起持续进行，"
              "每轮迭代产出同口径对照（节拍、成功率、力曲线），未证明提升的改动不进入默认配置。")


def ch8_risk(doc):
    h1(doc, "8. 风险项")
    table(doc,
          ["No", "类型", "风险描述", "应对方案"],
          [["1", "技术", "对位阶段占总周期 48%~55%，来料波动即击穿节拍承诺",
            "精对位前馈 + 宏微复合；DVT 中按来料偏差 ±10 mm/±10° 做鲁棒性测试"],
           ["2", "技术", "金手指划伤属不可逆损伤，一次即报废",
            "插入力 ≤40 N 硬限 + 分段压入 + 导向槽为先；末端接触面按材质选型并做批次验证"],
           ["3", "工艺", "型号与料盘规格差异导致换型超时",
            "换型参数化（点位/阈值/末端），目标 ≤30 min；首批覆盖 QSFP/OSFP/SFP 系列"],
           ["4", "交付", "客户测试机接口与互锁协议未定",
            "M1 内完成接口确认，预留 IO 与通信适配层；接口未定前不承诺联调节点"],
           ["5", "数据", "现场数据尚未结构化，训练样本不足",
            "按场景采集管线补齐数据集版本；真实示教与数据标注列入 M2 资源"],
           ["6", "安全", "安全等级为目标值，未做第三方验证",
            "按 ISO 13849 走认证，8~12 周；认证前对外只承诺能力边界"],
           ["7", "商务", "客户首台预算与售价口径未闭合",
            "首台按「设备 + 运营期让利」组合报价，待商务确认后回填"],
           ["8", "进度", "关键件（力觉末端、工控机）采购周期不确定",
            "BOM 输出后三家比价，并锁定二供；关键件到货作为 M1 的进入条件"]],
          [1.0, 1.8, 6.6, 7.2],
          cap="表 8-1 风险项与应对",
          align_center_cols=(0,))


def appendix(doc):
    h1(doc, "附录")
    h2(doc, "附录 A 术语与口径")
    table(doc,
          ["术语", "定义"],
          [["C1–C5", "能力分级：定位抓放 / 柔性自适应 / 精对位插拔 / 力控装配 / 自主进化"],
           ["F1–F5", "型号谱系：按能力档切出的五个配置型号"],
           ["分段压入", "插入过程中每进 0.5 mm 核验一次位移与接触力，异常即停"],
           ["双重到位", "位置与姿态两项同时满足，且连续两拍一致，才判定插入到位"],
           ["AP / RP", "ISO 9283 口径的位姿准确度（AP）与重复性（RP）"],
           ["换型", "同系列产品切换型号所需的参数与末端调整，目标 ≤30 min"],
           ["OEE", "设备综合效率，本文件按 0.85 折算产能"]],
          [3.2, 13.4],
          cap="表 A-1 术语表")
    h2(doc, "附录 B 真源索引")
    table(doc,
          ["类别", "文件", "用途"],
          [["整机外形与型号", "Z-MAX 整机与产品方案册 5.50.D-M2（1.28–1.33 / 5.03–5.24 页）",
            "三视图、尺寸、结构参数、能力分级、型号谱系、三档配置"],
           ["插拔工艺与验收", "Z700 具身智能方案技术协议 v3（第 1/2/3/6/9 章）",
            "节拍硬指标、动作预算、验收口径、回收期双口径"],
           ["在役实测与短板", "Z-MAX 精细操作机器人 F 系列 立项任务书 20261104",
            "314 件/h、11.468 s/件、闭环 1 轮、未闭环项"],
           ["轨迹与精度真值", "双臂协作工位项目立项报告（tools/cost_model.py 现算）",
            "11.42 s/件、AP/RP、47 mm 行程、0.76 mm/px"],
           ["算力档位与端侧配置", "docs/1-天枢-产品边界/Z-MAX-硬件平台-L2-L3-L4方案.md",
            "AI 模组、算力、内存、相机路数、力控通道"],
           ["逐层与整链延迟", "reports/perf_report_20261015_214216.md",
            "单层延迟、整链延迟、常驻回路单周期"],
           ["模型规模与前向耗时", "方案册 5.50.D-M2（4.21 / 3.16 页）", "20,976,792 参数、单次前向 4.4 ms、20 ms 拍"],
           ["市场与用工口径", "Z100L 立项文档 v1.1（1.3 节）", "行业规模、现场调研数据、对标价格"],
           ["交付与判据", "交付文档_插拔_TASK-01-FW_5.50.C", "插拔任务的交付口径与判据明细"]],
          [3.0, 7.6, 6.0],
          cap="表 B-1 真源索引（每个数字可回到上表对应文件复核）")
    para(doc, "说明：方案册文件位于 docs/1-天枢-产品边界/deliverables/6-立项与协议/参考/，"
              "本文件只引用其整机外形、能力分级与型号谱系章节，不引用其技术主线章节。", size=9)


def build(out_dir):
    doc = Document()
    setup(doc)
    doc.core_properties.title = "Z700 项目立项文档 · 成都储翰工厂插拔工位"
    doc.core_properties.author = "Z-MAX 产品与工程中心"
    doc.core_properties.subject = "Z700 精细操作机器人立项"
    cover(doc)
    ch1_background(doc)
    ch2_product(doc)
    ch3_business(doc)
    ch4_tech(doc)
    ch5_compute(doc)
    ch6_org(doc)
    ch7_plan(doc)
    ch8_risk(doc)
    appendix(doc)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "Z700项目立项文档_成都储翰插拔工位_v1.0.docx")
    doc.save(out)
    print("OK", out, os.path.getsize(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        ROOT, "docs/1-天枢-产品边界/deliverables/6-立项与协议"))
    build(ap.parse_args().out)
