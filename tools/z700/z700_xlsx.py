#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""z700_xlsx.py —— 生成 Z700 全流程功能清单 Excel

输出 outputs/z700/Z700_功能清单_EVT_DVT_PVT.xlsx
工作表:
  00_封面      项目信息与统计
  01_总览      七阵 × 三阶段 矩阵
  02_功能清单  165 条全量(主表, 带筛选与冻结)
  03-09_天枢..瑶光  七个分阵视图
  10_EVT阶段   EVT 视角(完整功能开发 + 用户演示能力)
  11_DVT阶段   DVT 视角(环境适应性标定)
  12_PVT阶段   PVT 视角(适应生产流程)
  13_性能指标  实测 vs 待实测
  14_负载计算  光模块/料盘/整箱 三级
  15_国标引用  标准清单与落点
  16_环境矩阵  DVT 环境项 + PVT 生产项
"""
import datetime
import json
import os
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from z700_features import ARRAYS, all_features                       # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "outputs", "z700")
VERSION = "5.50.E-R1"
TODAY = datetime.date.today().isoformat()

# ── 样式 ──
C_DARK = "1F3864"
C_HEAD = "2E5A9A"
C_BAND = "EAF0F8"
C_P0 = "FCE4E4"
C_P1 = "FFF6E0"
C_P2 = "EAF7EA"
C_MEAS = "E3F2E1"
C_TBD = "F2F2F2"
THIN = Side(style="thin", color="B8C4D9")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
F_TITLE = Font(name="微软雅黑", size=18, bold=True, color="FFFFFF")
F_H1 = Font(name="微软雅黑", size=12, bold=True, color="FFFFFF")
F_BODY = Font(name="微软雅黑", size=9)
F_BOLD = Font(name="微软雅黑", size=9, bold=True)
F_SMALL = Font(name="微软雅黑", size=8, color="555555")
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _w(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _title(ws, text, ncol, sub=""):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    c = ws.cell(row=1, column=1, value=text)
    c.fill = PatternFill("solid", fgColor=C_DARK)
    c.font = F_TITLE
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 34
    if sub:
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=ncol)
        c2 = ws.cell(row=2, column=1, value=sub)
        c2.font = F_SMALL
        c2.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[2].height = 18
        return 4
    return 3


def _head(ws, row, cols):
    for j, (name, width) in enumerate(cols, 1):
        c = ws.cell(row=row, column=j, value=name)
        c.fill = PatternFill("solid", fgColor=C_HEAD)
        c.font = F_H1
        c.alignment = CENTER
        c.border = BORDER
        ws.column_dimensions[get_column_letter(j)].width = width
    ws.row_dimensions[row].height = 30


def _rows(ws, start, data, band=True):
    for i, vals in enumerate(data):
        r = start + i
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
            if band and i % 2 == 1:
                c.fill = PatternFill("solid", fgColor=C_BAND)
    return start + len(data)


# ═══════════════════════════════════════════════════════════════════════════
def sheet_cover(wb, feats, met):
    ws = wb.active
    ws.title = "00_封面"
    ws.sheet_view.showGridLines = False
    _w(ws, [26, 30, 30, 22, 22])
    r = _title(ws, "Z700 精细操作机器人 · 全流程功能清单 (EVT / DVT / PVT)", 5,
               "配置中心七阵结构 · 光模块生产工厂插拔工位 · 引用国标 · 数据驱动")

    info = [
        ("项目名称", "Z700 精细操作机器人（光模块生产工厂精细操作）"),
        ("文档编号", "ZMAX-PD-Z700-FL-%s" % VERSION),
        ("版本", VERSION),
        ("编制日期", TODAY),
        ("适用场景", "FW Loading/EEPROM · 上下料搬运 · BI 老化箱 · 热海柜体 · ATS 线外检测"),
        ("目标节拍", "场景1 ≤6s · 场景5 ≤15s · 场景4 ≤20s（物理硬指标）"),
        ("本体形态", "AMR 底盘 + 6 轴协作臂（负载 5kg / 臂展 ≥800mm）+ 力控夹爪"),
        ("数据依据", "真机 MT-08 215 点采集（run replay215_20261115_225309）"),
        ("功能总数", "%d 条（天枢14/天璇27/天玑48/天权20/玉衡22/开阳22/瑶光12）" % len(feats)),
        ("三阶段齐全", "%d 条" % sum(1 for f in feats if f["n_stage"] == 3)),
        ("优先级分布", "P0 %d / P1 %d / P2 %d"
         % (sum(1 for f in feats if f["priority"] == "P0"),
            sum(1 for f in feats if f["priority"] == "P1"),
            sum(1 for f in feats if f["priority"] == "P2"))),
    ]
    for i, (k, v) in enumerate(info):
        rr = r + i
        ck = ws.cell(row=rr, column=1, value=k)
        ck.font = F_BOLD
        ck.fill = PatternFill("solid", fgColor=C_BAND)
        ck.border = BORDER
        ck.alignment = Alignment(vertical="center")
        ws.merge_cells(start_row=rr, start_column=2, end_row=rr, end_column=5)
        cv = ws.cell(row=rr, column=2, value=v)
        cv.font = F_BODY
        cv.border = BORDER
        cv.alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[rr].height = 22
    r += len(info) + 2

    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
    c = ws.cell(row=r, column=1, value="三阶段定义")
    c.font = F_H1
    c.fill = PatternFill("solid", fgColor=C_HEAD)
    c.alignment = CENTER
    r += 1
    stages = [
        ("EVT 工程原型验证", "完整功能开发, 具备用户演示能力",
         "每条功能都要能在 ar3d 场景与真机上演出来; 判据为『能演示 + 单次可复现』"),
        ("DVT 设计验证", "环境适应性标定",
         "温度/湿度/电源/振动/ESD/洁净/光照 七类扰动下, 功能判据不降级; 标定参数固化"),
        ("PVT 生产验证", "适应生产流程",
         "连续 72h / ≥5000 次, 换型 ≤0.5h, 与 MES/AOI 联动, 异常自恢复, 安全合规"),
    ]
    _head(ws, r, [("#", 26), ("阶段", 30), ("目标", 30), ("判据口径", 22), ("", 22)])
    r += 1
    rows = [[s[0], s[1], s[2], "", ""] for s in stages]
    for i, vals in enumerate(rows):
        rr = r + i
        ws.merge_cells(start_row=rr, start_column=3, end_row=rr, end_column=5)
        for j, v in enumerate(vals[:3], 1):
            c = ws.cell(row=rr, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
        for j in (4, 5):
            ws.cell(row=rr, column=j).border = BORDER
        ws.row_dimensions[rr].height = 46
    return ws


def sheet_overview(wb, feats):
    ws = wb.create_sheet("01_总览")
    ws.sheet_view.showGridLines = False
    r = _title(ws, "七阵 × 三阶段 功能分布矩阵", 8,
               "「三阶段条数」= 该阵中同时给出了 EVT/DVT/PVT 要求的功能数")
    cols = [("阵位", 16), ("代号", 8), ("说明", 34),
            ("功能数", 9), ("P0", 7), ("P1", 7), ("P2", 7), ("三阶段齐全", 11)]
    _head(ws, r, cols)
    r += 1
    data = []
    for k, v in ARRAYS.items():
        sub = [f for f in feats if f["array"] == k]
        data.append([v["full"], v["code"], v["desc"], len(sub),
                     sum(1 for f in sub if f["priority"] == "P0"),
                     sum(1 for f in sub if f["priority"] == "P1"),
                     sum(1 for f in sub if f["priority"] == "P2"),
                     sum(1 for f in sub if f["n_stage"] == 3)])
    data.append(["合计", "—", "七个阵位全覆盖", len(feats),
                 sum(1 for f in feats if f["priority"] == "P0"),
                 sum(1 for f in feats if f["priority"] == "P1"),
                 sum(1 for f in feats if f["priority"] == "P2"),
                 sum(1 for f in feats if f["n_stage"] == 3)])
    end = _rows(ws, r, data)
    for j in range(1, 9):
        c = ws.cell(row=end - 1, column=j)
        c.font = F_BOLD
        c.fill = PatternFill("solid", fgColor=C_P0)

    # 阶段覆盖统计
    r = end + 2
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
    c = ws.cell(row=r, column=1, value="阶段覆盖度")
    c.font = F_H1
    c.fill = PatternFill("solid", fgColor=C_HEAD)
    c.alignment = CENTER
    r += 1
    _head(ws, r, [("阶段", 16), ("要求条数", 10), ("占比", 10), ("含义", 34), ("", 9), ("", 7), ("", 7), ("", 11)])
    r += 1
    n = len(feats)
    st = [("EVT 工程原型验证", sum(1 for f in feats if f["evt"] and f["evt"] != "—"),
           "完整功能开发 + 用户演示能力"),
          ("DVT 设计验证", sum(1 for f in feats if f["dvt"] and f["dvt"] != "—"),
           "环境适应性标定（温湿度/电源/振动/ESD/洁净/光照）"),
          ("PVT 生产验证", sum(1 for f in feats if f["pvt"] and f["pvt"] != "—"),
           "适应生产流程（72h/换型/MES/异常恢复/安全）")]
    for i, (a, b, cc) in enumerate(st):
        rr = r + i
        ws.merge_cells(start_row=rr, start_column=4, end_row=rr, end_column=8)
        for j, v in enumerate([a, b, "%.0f%%" % (100.0 * b / n), cc], 1):
            c = ws.cell(row=rr, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
        for j in range(5, 9):
            ws.cell(row=rr, column=j).border = BORDER
    return ws


FEAT_COLS = [("编号", 11), ("阵位", 9), ("层", 6), ("优先级", 8),
             ("功能名称", 26), ("功能描述", 46), ("验收判据", 34),
             ("EVT 工程原型验证（完整功能+演示能力）", 38),
             ("DVT 设计验证（环境适应性标定）", 34),
             ("PVT 生产验证（适应生产流程）", 32),
             ("国标引用", 22), ("证据来源", 26)]


def _feat_sheet(wb, title, feats, subtitle):
    ws = wb.create_sheet(title)
    r = _title(ws, subtitle, len(FEAT_COLS))
    _head(ws, r, FEAT_COLS)
    hdr = r
    r += 1
    for i, f in enumerate(feats):
        vals = [f["id"], f["array"], f["layer"], f["priority"], f["name"], f["desc"],
                f["criteria"], f["evt"], f["dvt"], f["pvt"], f["std"], f["evidence"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r + i, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
            if i % 2 == 1:
                c.fill = PatternFill("solid", fgColor=C_BAND)
        pc = ws.cell(row=r + i, column=4)
        pc.fill = PatternFill("solid", fgColor={"P0": C_P0, "P1": C_P1, "P2": C_P2}[f["priority"]])
        pc.alignment = CENTER
        pc.font = F_BOLD
        ws.cell(row=r + i, column=1).alignment = CENTER
        ws.cell(row=r + i, column=2).alignment = CENTER
        ws.cell(row=r + i, column=3).alignment = CENTER
        ws.row_dimensions[r + i].height = 52
    # 冻结 + 筛选
    ws.freeze_panes = ws.cell(row=hdr + 1, column=5)
    ws.auto_filter.ref = "A%d:L%d" % (hdr, r + len(feats) - 1)
    return ws


def _stage_sheet(wb, title, feats, key, subtitle, note):
    ws = wb.create_sheet(title)
    cols = [("编号", 11), ("阵位", 9), ("功能名称", 28), ("验收判据", 38),
            ("%s 阶段要求" % key.upper(), 62), ("国标引用", 22), ("优先级", 8)]
    r = _title(ws, subtitle, len(cols), note)
    _head(ws, r, cols)
    hdr = r
    r += 1
    sub = [f for f in feats if f.get(key) and f[key] != "—"]
    for i, f in enumerate(sub):
        vals = [f["id"], f["array"], f["name"], f["criteria"], f[key], f["std"], f["priority"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r + i, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
            if i % 2 == 1:
                c.fill = PatternFill("solid", fgColor=C_BAND)
        pc = ws.cell(row=r + i, column=7)
        pc.fill = PatternFill("solid", fgColor={"P0": C_P0, "P1": C_P1, "P2": C_P2}[f["priority"]])
        pc.alignment = CENTER
        pc.font = F_BOLD
        for j in (1, 2):
            ws.cell(row=r + i, column=j).alignment = CENTER
        ws.row_dimensions[r + i].height = 46
    ws.freeze_panes = ws.cell(row=hdr + 1, column=3)
    ws.auto_filter.ref = "A%d:G%d" % (hdr, r + len(sub) - 1)
    return ws


def sheet_perf(wb, met):
    ws = wb.create_sheet("13_性能指标")
    perf = met["performance"]
    cols = [("类别", 10), ("指标", 30), ("目标值", 14), ("实测值", 12),
            ("单位", 8), ("证据来源", 40), ("状态", 16), ("判定", 10)]
    r = _title(ws, "性能指标 · 实测与待实测（数据驱动, 不编数）", len(cols),
               "「实测」= 来自 run %s 的真实采集; 「待实测」= 未测, 已标注实测入口"
               % perf["run_id"])
    _head(ws, r, cols)
    hdr = r
    r += 1
    for i, m in enumerate(perf["metrics"]):
        vals = [m["category"], m["name"],
                "—" if m["target"] in (None, "", "—") else m["target"],
                "" if m["measured"] is None else m["measured"],
                m["unit"], m["source"], m["evidence"], m["verdict"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r + i, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
            c.fill = PatternFill("solid", fgColor=C_MEAS if m["evidence"] == "实测" else C_TBD)
        for j in (1, 2, 5, 8):
            ws.cell(row=r + i, column=j).alignment = CENTER
        vc = ws.cell(row=r + i, column=8)
        if m["verdict"].startswith("PASS"):
            vc.fill = PatternFill("solid", fgColor="C6EFCE")
        elif m["verdict"] == "GAP":
            vc.fill = PatternFill("solid", fgColor=C_P0)
        ws.row_dimensions[r + i].height = 32
    ws.freeze_panes = ws.cell(row=hdr + 1, column=2)
    ws.auto_filter.ref = "A%d:H%d" % (hdr, r + len(perf["metrics"]) - 1)
    return ws


def sheet_payload(wb, met):
    p = met["payload"]
    ws = wb.create_sheet("14_负载计算")
    cols = [("层级", 42), ("负载下限(g)", 12), ("负载上限(g)", 12),
            ("负载利用率", 11), ("臂可搬", 9), ("真约束", 34), ("结论", 46)]
    r = _title(ws, "负载要求 · 光模块重量与料盘搬运", len(cols),
               p["formula"] + " · 额定 5000g / 末端 ≤1500g")
    _head(ws, r, cols)
    r += 1
    for i, lv in enumerate(p["levels"]):
        vals = [lv["level"], lv["load_g"][0], lv["load_g"][1],
                "%.1f%%" % lv["util_pct"], "是" if lv["arm_ok"] else "否",
                lv["real_constraint"], lv["conclusion"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r + i, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
            if not lv["arm_ok"]:
                c.fill = PatternFill("solid", fgColor=C_P0)
            elif i % 2 == 1:
                c.fill = PatternFill("solid", fgColor=C_BAND)
        for j in (2, 3, 4, 5):
            ws.cell(row=r + i, column=j).alignment = CENTER
        ws.row_dimensions[r + i].height = 40
    r += len(p["levels"]) + 2

    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    c = ws.cell(row=r, column=1, value="① 光模块单只重量（分封装族）")
    c.font = F_H1
    c.fill = PatternFill("solid", fgColor=C_HEAD)
    c.alignment = CENTER
    r += 1
    cols2 = [("封装", 20), ("典型外形(mm)", 22), ("典型重量(g)", 12),
             ("下限(g)", 10), ("上限(g)", 10), ("备注", 46), ("", 10)]
    _head(ws, r, cols2)
    r += 1
    for i, m in enumerate(p["module_weights"]):
        vals = [m["pkg"], m["size_mm"], m["typical_g"], m["range_g"][0], m["range_g"][1], m["note"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r + i, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
            if i % 2 == 1:
                c.fill = PatternFill("solid", fgColor=C_BAND)
        for j in (3, 4, 5):
            ws.cell(row=r + i, column=j).alignment = CENTER
    r += len(p["module_weights"]) + 2

    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=7)
    c = ws.cell(row=r, column=1, value="② 载具（料盘）重量 —— 决定臂能否搬盘")
    c.font = F_H1
    c.fill = PatternFill("solid", fgColor=C_HEAD)
    c.alignment = CENTER
    r += 1
    cols3 = [("载具", 30), ("规格", 30), ("空盘(g)", 10), ("满载(g)", 10),
             ("备注", 40), ("", 10), ("", 10)]
    _head(ws, r, cols3)
    r += 1
    for i, t in enumerate(p["trays"]):
        vals = [t["name"], t["spec"], t["empty_g"], t["full_g"], t["note"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r + i, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
            if i % 2 == 1:
                c.fill = PatternFill("solid", fgColor=C_BAND)
        for j in (3, 4):
            ws.cell(row=r + i, column=j).alignment = CENTER
    r += len(p["trays"]) + 2

    ws.merge_cells(start_row=r, start_column=1, end_row=r + 2, end_column=7)
    c = ws.cell(row=r, column=1, value="设计结论：" + p["design_conclusion"])
    c.font = F_BOLD
    c.alignment = WRAP
    c.fill = PatternFill("solid", fgColor=C_P1)
    c.border = BORDER
    return ws


def sheet_env(wb, met):
    ws = wb.create_sheet("16_环境矩阵")
    cols = [("阶段", 8), ("项目", 18), ("量级 / 范围", 30), ("依据标准", 30),
            ("判据", 46), ("", 10), ("", 10)]
    r = _title(ws, "DVT 环境适应性矩阵 + PVT 生产流程矩阵", len(cols),
               "DVT: 七类扰动下判据不降级 · PVT: 生产流程十项")
    _head(ws, r, cols)
    hdr = r
    r += 1
    n = 0
    for e in met["env_matrix_dvt"]:
        vals = ["DVT", e["item"], e["range"], e["standard"], e["criteria"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r + n, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
            if n % 2 == 1:
                c.fill = PatternFill("solid", fgColor=C_BAND)
        ws.cell(row=r + n, column=1).alignment = CENTER
        ws.row_dimensions[r + n].height = 34
        n += 1
    for e in met["pvt_matrix"]:
        vals = ["PVT", e["item"], e["range"], e["standard"], e["criteria"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r + n, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
            c.fill = PatternFill("solid", fgColor="FFF9E6" if n % 2 == 0 else C_BAND)
        ws.cell(row=r + n, column=1).alignment = CENTER
        ws.row_dimensions[r + n].height = 34
        n += 1
    ws.freeze_panes = ws.cell(row=hdr + 1, column=2)
    return ws


def sheet_std(wb, std_rows=None):
    ws = wb.create_sheet("15_国标引用")
    cols = [("序号", 6), ("大类", 16), ("标准号", 26), ("标准名称", 48),
            ("强制性", 10), ("在本项目中的落点", 52)]
    r = _title(ws, "标准引用清单（国标 / 行标 / 国际标准）", len(cols),
               "每条标准给出具体落点, 不做泛泛引用; 拿不准的标准号标「待核实」")
    _head(ws, r, cols)
    hdr = r
    r += 1
    if not std_rows:
        std_rows = DEFAULT_STD
    for i, s in enumerate(std_rows):
        for j, v in enumerate([i + 1] + list(s), 1):
            c = ws.cell(row=r + i, column=j, value=v)
            c.font = F_BODY
            c.alignment = WRAP
            c.border = BORDER
            if i % 2 == 1:
                c.fill = PatternFill("solid", fgColor=C_BAND)
        ws.cell(row=r + i, column=1).alignment = CENTER
        ws.cell(row=r + i, column=5).alignment = CENTER
        ws.row_dimensions[r + i].height = 40
    ws.freeze_panes = ws.cell(row=hdr + 1, column=3)
    ws.auto_filter.ref = "A%d:F%d" % (hdr, r + len(std_rows) - 1)
    return ws


# 兜底标准表（子代理结果未到时用；到了会被替换）
DEFAULT_STD = [
    ("机械电气安全", "GB 5226.1-2019", "机械电气安全 机械电气设备 第1部分：通用技术条件", "强制",
     "电柜设计、接地 ≤4Ω、急停回路、导线截面与防护等级"),
    ("机械安全", "GB/T 15706-2012", "机械安全 设计通则 风险评估与风险减小", "推荐",
     "整机风险评估报告、危险清单与风险减小措施"),
    ("机械安全", "GB/T 16855.1-2018", "机械安全 控制系统安全相关部件 第1部分：设计通则", "推荐",
     "安全回路 PLd 设计与验证"),
    ("工业机器人安全", "GB 11291.1-2011", "工业环境用机器人 安全要求 第1部分：机器人", "强制",
     "机器人本体安全、急停、保护停止、安全相关控制系统性能"),
    ("工业机器人安全", "GB 11291.2-2013", "工业环境用机器人 安全要求 第2部分：机器人系统与集成", "强制",
     "机器人与产线的集成交付、安全距离、围栏与光幕布置"),
    ("协作机器人", "GB/T 36008-2018", "协作机器人 安全要求", "推荐",
     "人机协作工况下的功率与力限制、手动引导安全"),
    ("协作机器人", "ISO/TS 15066:2016", "Robots and robotic devices — Collaborative robots", "推荐",
     "人体各部位准静态接触力/压强阈值，用于碰撞检测阈值设定"),
    ("安全控制系统", "ISO 13849-1:2023", "Safety of machinery — Safety-related parts of control systems", "推荐",
     "PLd 等级达成证明；急停双回路 ≤500ms 的性能等级论证"),
    ("工业机器人安全", "ISO 10218-1/2", "Robotics — Safety requirements（版本待核实）", "推荐",
     "对标国标 GB 11291 的国际一致性（出口机型适用）"),
    ("性能测试", "GB/T 12642-2013", "工业机器人 性能规范及其试验方法", "推荐",
     "重复定位精度 ±0.02mm、位姿准确度、轨迹特性的测试方法"),
    ("性能测试", "ISO 9283:1998", "Manipulating industrial robots — Performance criteria", "推荐",
     "上述性能测试的国际对照口径"),
    ("性能测试", "GB/T 20867-2007", "工业机器人 安全实施规范", "推荐", "现场安装与安全实施"),
    ("环境试验", "GB/T 2423.1/.2", "电工电子产品环境试验 低温/高温", "推荐", "DVT 温度 15-35℃ 与储运 -20~60℃"),
    ("环境试验", "GB/T 2423.3/.4", "电工电子产品环境试验 恒定湿热/交变湿热", "推荐", "DVT 湿度 30-75%RH 无凝露"),
    ("环境试验", "GB/T 2423.10", "电工电子产品环境试验 振动（正弦）", "推荐", "DVT 运输振动 3-100Hz 1g"),
    ("电磁兼容", "GB/T 17799.3", "电磁兼容 居住/商业/轻工业环境 抗扰度", "推荐", "DVT EMC 抗扰度；与产线其他设备共存"),
    ("电磁兼容", "IEC 61000-4-2", "Electromagnetic compatibility — ESD immunity test", "推荐",
     "DVT 接触 ±8kV / 空气 ±15kV 静电放电抗扰"),
    ("防静电", "ANSI/ESD S20.20-2021", "Protection of Electrical and Electronic Parts…", "推荐",
     "整机 ESD 控制程序、接地 ≤4Ω、静电场 ≤100V、离子风布置"),
    ("防静电", "IEC 61340-5-1", "Electrostatics — Protection of electronic devices", "推荐",
     "S20.20 的国际对应；出口机型"),
    ("防静电", "SJ/T 10694-2006", "电子产品制造与应用系统防静电检测通用规范", "推荐",
     "国内电子厂防静电检测口径（光模块厂常用）"),
    ("洁净室", "ISO 14644-1:2015", "Cleanrooms and associated controlled environments — Classification", "推荐",
     "DVT 洁净度 ISO Class 7（万级）；设备发尘量评估"),
    ("洁净室", "GB/T 25915.1-2021", "洁净室及相关受控环境 第1部分：按粒子浓度划分空气洁净度等级", "推荐",
     "ISO 14644-1 的国标对应"),
    ("半导体设备安全", "SEMI S2", "Environmental, Health, and Safety Guideline for Semiconductor Manufacturing Equipment", "推荐",
     "光模块厂常用设备安全评审口径（版本待核实）"),
    ("半导体设备安全", "SEMI S8", "Safety Guidelines for Ergonomics Engineering of Semiconductor Manufacturing Equipment", "推荐",
     "人机工程：维护高度、操作力、照明（版本待核实）"),
    ("噪声", "GB/T 3767-2016", "声压法测定噪声源声功率级 反射面上方近似自由场", "推荐", "IX-19 噪声 ≤70dB(A)"),
]


def main():
    os.makedirs(OUT, exist_ok=True)
    feats = all_features()
    met = json.load(open(os.path.join(OUT, "metrics.json"), encoding="utf-8"))
    std_rows = None
    sp = os.path.join(OUT, "standards_rows.json")
    if os.path.exists(sp):
        try:
            std_rows = [tuple(x) for x in json.load(open(sp, encoding="utf-8"))]
        except Exception:                                                # noqa: BLE001
            std_rows = None

    wb = Workbook()
    sheet_cover(wb, feats, met)
    sheet_overview(wb, feats)
    _feat_sheet(wb, "02_功能清单", feats, "全量功能清单 · 165 条 · 七阵 × 三阶段")
    for k, v in ARRAYS.items():
        sub = [f for f in feats if f["array"] == k]
        idx = list(ARRAYS).index(k) + 3
        _feat_sheet(wb, "%02d_%s" % (idx, k), sub,
                    "%s（%s）· %d 条" % (v["full"], v["code"], len(sub)))
    _stage_sheet(wb, "10_EVT阶段", feats, "evt",
                 "EVT 工程原型验证 · 完整功能开发, 具备用户演示能力",
                 "判据口径: 能在 ar3d 场景与真机上演出来, 且单次可复现")
    _stage_sheet(wb, "11_DVT阶段", feats, "dvt",
                 "DVT 设计验证 · 环境适应性标定",
                 "判据口径: 七类扰动（温/湿/电源/振动/ESD/洁净/光照）下判据不降级, 标定参数固化")
    _stage_sheet(wb, "12_PVT阶段", feats, "pvt",
                 "PVT 生产验证 · 适应生产流程",
                 "判据口径: 72h/≥5000 次, 换型 ≤0.5h, MES/AOI 联动, 异常自恢复, 安全合规")
    sheet_perf(wb, met)
    sheet_payload(wb, met)
    sheet_std(wb, std_rows)
    sheet_env(wb, met)

    p = os.path.join(OUT, "Z700_功能清单_EVT_DVT_PVT.xlsx")
    wb.save(p)
    print(json.dumps({"ok": True, "out": p, "sheets": len(wb.sheetnames),
                      "features": len(feats), "size_kb": round(os.path.getsize(p) / 1024)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
