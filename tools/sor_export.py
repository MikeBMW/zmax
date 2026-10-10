#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SOR 导出器 — 由「配置中心」的配置生成 Word 需求规格说明书 (2026-10-10)

设计原则
  · 数据全部取自**单一工程库** + 平台真源, 不在文档里写死数字 (要与配置一致, 不能第二份真相)
  · 配置里没有的项, 显式写「待确认」并汇总到附录 C —— 不编造
  · 性能参数 (第 5 章 + 附录 B) 与 功能配置 (第 4 章 + 附录 A) 是两张主表, 给供应商逐条报价/验收
  · 附录 D 记录导出所用的真源路径与 sha256, 使文档可复现、可追责

用法:
  python3 tools/sor_export.py                 # 默认: System 1 / 摆盘任务
  python3 tools/sor_export.py --system all    # 整单元口径 (Sys-2/1/0 全列)
  python3 tools/sor_export.py --task TASK-06-TRAY
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sys1_delivery import (CONTRACT, GAPS, METRICS, PROD, PROJ, SCOPE_IN,  # noqa: E402
                           SCOPE_OUT, SYS_ID, load)

from docx import Document  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.enum.table import WD_ALIGN_VERTICAL  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import project_profile  # noqa: E402  项目档案: 根据配置适配不同项目

DB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
OUT_ROOT = os.path.join(ROOT, "outputs", "sor")
DOC_NO = "SOR-OM-ROBOT-" + time.strftime("%Y%m%d")
VERSION = "V1.0"
CN_FONT = "微软雅黑"

# ── 模板静态段 (供应商要求, 与配置无关的采购条款) ─────────────────────
SUPPLY_SCOPE = [
    ("系统类型", "光模块自动上下料单元 (取放 + 摆盘)"),
    ("供料方式", "料盘供料 (周转盘 → 上料 Tray 盘)"),
    ("机器人类型", "双臂协作机器人 (Z100 平台) / 供应商方案待确认"),
    ("末端执行器", "真空吸嘴 (带真空检测与断气保护) + 可选夹爪"),
    ("是否含视觉定位", "是 —— 腕部相机 (0.1–0.6m, ±1mm/±1°) + 全局定位相机 + 胸部相机"),
    ("是否含料盘供料机构", "是 (需料盘到位检测 / 空满三态检测)"),
    ("是否含下料收料机构", "是 (满盘移出 / 空盘回收, 人工或自动换盘)"),
    ("是否含输送线/对接机构", "待确认 (与现有产线对接方式见第 9 章)"),
    ("交付地点", "待确认"),
    ("交付周期", "待确认"),
    ("是否需现场安装调试", "是"),
]
PRODUCT_SPEC_STATIC = [
    ("光模块外形尺寸", "待确认 (12+ 型号: 100G/400G/800G · QSFP-DD/OSFP)"),
    ("光模块重量", "待确认 (单位 g)"),
    ("光模块材质", "金属外壳 + 塑料件 (待确认)"),
    ("光模块敏感面", "金手指、光口端面、标签面 —— 抓取不得压伤"),
    ("料盘规格", "上料 Tray 盘 30 槽 / 4# 周转盘 (槽距与盘尺寸待确认)"),
    ("单盘装载数量", "上料 Tray 盘 30 槽; 周转盘待确认"),
    ("料盘材质", "待确认"),
    ("料盘定位方式", "视觉识别 + 盘面槽位标定 (定位销/边定位待确认)"),
]
ROBOT_REQ = [
    "机器人负载需满足光模块、治具及末端执行器总重量要求, 并预留安全余量。",
    "机器人重复定位精度需满足插测试座、料位放置的工艺要求 (摆盘取放: 单边 ≤1mm · 角 ≤1°)。",
    "末端执行器需适配光模块外形, 抓取时不得压伤金手指、光口端面、标签及外壳。",
    "真空吸嘴需提供真空检测 (吸附建立 ≤200ms 判据) 及断气保护。",
    "夹爪需控制夹持力, 避免光模块变形或表面损伤。",
    "末端执行器应具备快换或易维护设计。",
]
VISION_REQ = [
    "识别料盘位置、料位位置、光模块姿态及缺料状态 (空/满/异常三态)。",
    "适应现场光照变化与堆叠遮挡; 极端情况回退预设轨迹与固定逻辑, 保证产线不中断。",
    "相机安装位置、光源类型及标定方式需在方案中明确。",
    "视觉结果需与机器人坐标系完成标定 —— 盘面槽位几何为坐标类参数的唯一真源。",
    "腕部相机工作距离 0.1–0.6m 内保证 ±1mm/±1°; 头部双目 @1m、胸部 @0.5m 为 ±5mm 级, 不得混用口径。",
]
TRAY_REQ = [
    "料盘供料机构需保证料盘定位稳定, 重复精度满足抓取要求。",
    "供料机构需具备料盘到位检测、空盘/满盘/异常三态检测功能。",
    "料盘流转过程中不得造成光模块磕碰、划伤或掉落。",
    "多规格料盘切换方式及定位适配方案需明确 (换型 ≤30min)。",
]
ELEC_REQ = [
    "控制系统需支持与现有设备通信, 协议: Modbus TCP / TCP-IP / IO 硬接线 (Ethernet-IP 待确认)。",
    "需提供完整 IO 点位表、通信协议说明及操作手册。",
    "系统需具备急停 (PLd · Cat.3, ISO 13849-1)、安全门、光栅等安全防护 —— 安全由底层独立收口, 上层无否决权。",
    "机器人程序、视觉程序及 PLC 程序需开放或提供备份, 具体方式待确认。",
    "HMI 需显示运行状态、报警、产量、节拍, 并标注数据时间戳与帧龄。",
]
ENV_TABLE = [
    ("安装方式", "台式 / 集成到产线 (待确认)"),
    ("工作温度", "待确认 (℃)"),
    ("工作湿度", "待确认"),
    ("电源要求", "待确认 (如 AC 220V/380V)"),
    ("气源要求", "待确认 (如 0.4~0.6 MPa)"),
    ("洁净度要求", "洁净室 Class 10000 / ISO 7 (与光模块产线一致) · 是否防静电待确认"),
    ("占地面积", "待确认 (mm)"),
]
QUALITY_REQ = [
    "光模块接触部位需采用防划伤材料 (PEEK、POM、橡胶、软质吸嘴等)。",
    "系统运行不得产生金属屑、油污或其他污染物 (洁净室 Class 10000 / ISO 7)。",
    "关键运动部件需具备防护罩, 防止人员误触。",
    "设备外观整洁, 线束布置规范, 标识清晰。",
    "供应商需提供关键部件清单: 机器人品牌型号、相机、光源、夹爪、真空发生器、PLC 等。",
]
DELIVERABLES = [
    "机器人上下料系统整机", "末端执行器", "料盘供料/收料机构", "控制系统及软件",
    "电气原理图、气路图、机械图纸", "IO 点位表及通信协议说明", "操作手册、维护手册",
    "备件清单", "出厂验收报告", "现场安装调试记录", "培训资料", "质保承诺书",
    "System 1 配置包 (功能清单 / 配置项 / 性能指标 / 接口契约, 机器可读 JSON + sha256)",
]
ACCEPTANCE = [
    ("FAT 工厂验收", "供应商现场按本规格书做功能、节拍、成功率、安全性测试; 节拍以 CT 起止口径 (吸取离盘 → 下一位就位) 计量。"),
    ("SAT 现场验收", "我方现场连续运行 ≥20h / ≥12 盘周转盘, 节拍/成功率/损伤率/稳定性达标。"),
    ("外观验收", "设备无损伤, 标识齐全, 布线规范。"),
    ("功能验收", "上料→取件→转运对位→放入→判态循环→下料收料→报警→急停 全链正常; 断点续作可恢复。"),
    ("性能验收", "按第 5 章性能参数逐条验收, 分 EVT / DVT / PVT 三阶段取值。"),
    ("兼容性验收", "稳定处理指定光模块型号 (12+ 型号) 及料盘规格 (≥6 种摆放方式)。"),
    ("不合格处理", "验收不合格时, 供应商需在 X 个工作日内提供整改方案并免费整改。"),
]
WARRANTY = [
    "质保期: 12/24 个月 (待确认), 自 SAT 通过之日起算。",
    "质保期内设备故障, 供应商需提供远程或现场支持。",
    "供应商需提供操作培训和维护培训。",
    "关键备件需提供推荐清单及供货周期。",
]
CHANGE_MGMT = [
    "任何影响节拍、精度、兼容性、安全性、控制接口、关键部件品牌型号的变更, 供应商必须提前书面确认, 不得擅自更改。",
    "变更须同步更新 System 1 配置 (配置中心) 并重新导出交付包, 保持文档与配置一致。",
]


# ── docx 基础工具 ─────────────────────────────────────────────
def _font(run, size=10.5, bold=False, color=None):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.name = CN_FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
    if color:
        run.font.color.rgb = color


def h(doc, text, level=1):
    p = doc.add_heading(level=level)
    r = p.add_run(text)
    _font(r, size={0: 20, 1: 14, 2: 12}.get(level, 11), bold=True)
    return p


def page_setup(doc, margins=(2.2, 2.0)):
    """A4 纵向 + 统一页边距 + 中文字体 —— 供应商要打印, python-docx 默认 Letter 会错版 (实测 pdftoppm 出 612x792pt)。"""
    st = doc.styles["Normal"]
    st.font.name = CN_FONT
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
    for s in doc.sections:
        s.page_width = Cm(21.0)
        s.page_height = Cm(29.7)
        s.left_margin = s.right_margin = Cm(margins[0])
        s.top_margin = s.bottom_margin = Cm(margins[1])
    return doc


def para(doc, text, size=10.5, bold=False, italic=False, space_before=None, keep_lines=False):
    p = doc.add_paragraph()
    r = p.add_run(text)
    _font(r, size=size, bold=bold)
    r.font.italic = italic
    if space_before is not None:
        p.paragraph_format.space_before = Pt(space_before)
    if keep_lines:                      # w:keepLines —— 单条不许被页切开
        p.paragraph_format.keep_together = True
    return p


# ── 表格视觉规范 (2026-10-10 老倪: 「表格显示的非常不友好, 用眼睛看非常费劲」⇒ 全部走这个函数) ──
TBL_HEAD_FILL = "1F3864"   # 表头深蓝底 + 白字 (视线锚点)
TBL_BAND_FILL = "EEF3FA"   # 隔行浅蓝 (长表眼睛有落脚点, 不会串行)
TBL_BORDER = "9DB2CE"      # 细灰蓝边框 (不用黑粗线压字)
TBL_TOTAL_CM = 16.0        # A4 纵向可用宽度


def _shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def _cell_margins(t, top=60, bottom=60, left=120, right=120):
    """单元格留白 (dxa): 默认值太挤, 文字贴着边框很难读。"""
    mar = OxmlElement("w:tblCellMar")
    for tag, val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        e = OxmlElement("w:" + tag)
        e.set(qn("w:w"), str(val))
        e.set(qn("w:type"), "dxa")
        mar.append(e)
    t._tbl.tblPr.append(mar)


def _borders(t, color=TBL_BORDER, sz=6):
    b = OxmlElement("w:tblBorders")
    for tag in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement("w:" + tag)
        e.set(qn("w:val"), "single")
        e.set(qn("w:sz"), str(sz))
        e.set(qn("w:space"), "0")
        e.set(qn("w:color"), color)
        b.append(e)
    t._tbl.tblPr.append(b)


def _repeat_header(row):
    """跨页时表头自动重复 —— 长表翻页后不用回头找列名。"""
    e = OxmlElement("w:tblHeader")
    e.set(qn("w:val"), "true")
    row._tr.get_or_add_trPr().append(e)


def _auto_widths(headers, rows, total_cm=TBL_TOTAL_CM):
    """没给列宽时按内容长度分配: 长的宽、短的窄 —— 避免某列被挤成一字一行。"""
    n = len(headers)
    if n == 0:
        return []
    w = []
    for i in range(n):
        vals = [len(str(headers[i]))] + [len(str(r[i])) if i < len(r) else 0 for r in rows[:40]]
        avg = sum(vals) / max(1, len(vals))
        w.append(max(2.5, min(avg, 45.0)))
    s = sum(w)
    return [round(total_cm * x / s, 2) for x in w]


def _set_col_widths(t, widths_cm):
    """把列宽**真正写进表格**: tblLayout=fixed + tblGrid(gridCol) + 每格 tcW。

    2026-10-10 实测坑: 只设 cell.width(=tcW) 不写 tblLayout/tblGrid, Word 与 LibreOffice 都按**等分**排,
    于是 "五列表一律 20%" "两列表 50:50" —— 复核看到的『逐行孤字换行』就是这么来的。
    """
    dxa = [int(round(w * 567)) for w in widths_cm]      # 1cm = 567 twips
    tblPr = t._tbl.tblPr
    for tag in ("w:tblLayout",):
        for e in tblPr.findall(qn(tag)):
            tblPr.remove(e)
    lay = OxmlElement("w:tblLayout")
    lay.set(qn("w:type"), "fixed")
    tblPr.append(lay)
    w = OxmlElement("w:tblW")
    w.set(qn("w:w"), str(sum(dxa)))
    w.set(qn("w:type"), "dxa")
    tblPr.append(w)
    grid = t._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        cols = grid.findall(qn("w:gridCol"))
        for i, gc in enumerate(cols):
            if i < len(dxa):
                gc.set(qn("w:w"), str(dxa[i]))
    for r_ in t.rows:
        for i, c in enumerate(r_.cells):
            if i < len(widths_cm):
                c.width = Cm(widths_cm[i])


def _cant_split(t):
    """行内不允许跨页断开 —— 否则会出现半页的孤儿碎片 (复核: PF-Z100-11 跨页后只剩『与选槽』孤行)。"""
    for r_ in t.rows:
        trPr = r_._tr.get_or_add_trPr()
        e = OxmlElement("w:cantSplit")
        e.set(qn("w:val"), "true")
        trPr.append(e)


def _col_is_short(headers, rows, i):
    """整列都短才居中 (原来逐格判短, 同一列里有的居中有的左对齐, 多行时更乱)。"""
    vals = [str(headers[i])] + [str(r[i]) if i < len(r) else "" for r in rows]
    return all(len(v) <= 6 for v in vals)


def table(doc, headers, rows, widths=None, size=9.5, band=True, first_col_bold=True, center_cols=None):
    """一个**给人看**的表: 深色表头(白字) + 隔行浅底 + 细边框 + 固定列宽 + 留白 + 跨页重复表头。

    center_cols=None ⇒ 自动: 内容短的列居中(编号/数量/状态一类), 长的列左对齐(说明/口径一类)。
    以后所有文档表格一律走这个入口, 不要再手写 doc.add_table (否则又回到'费劲'的表)。
    """
    n = len(headers)
    t = doc.add_table(rows=1, cols=n)
    t.style = "Table Grid"
    t.autofit = False
    _set_col_widths(t, widths or _auto_widths(headers, rows))
    _cell_margins(t)
    _borders(t)

    hr = t.rows[0]
    _repeat_header(hr)
    for i, htxt in enumerate(headers):
        c = hr.cells[i]
        c.text = ""
        p = c.paragraphs[0]
        p.paragraph_format.space_before = Pt(1)
        p.paragraph_format.space_after = Pt(1)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _font(p.add_run(str(htxt)), size=size + 0.5, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        _shade(c, TBL_HEAD_FILL)
        c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for i in range(n):
            v = row[i] if i < len(row) else ""
            c = cells[i]
            c.text = ""
            p = c.paragraphs[0]
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(1)
            txt = "" if v is None else str(v)
            p.alignment = (WD_ALIGN_PARAGRAPH.CENTER
                           if ((center_cols and i in center_cols)
                               or (center_cols is None and _col_is_short(headers, rows, i) and len(headers) > 2))
                           else WD_ALIGN_PARAGRAPH.LEFT)
            _font(p.add_run(txt), size=size, bold=bool(first_col_bold and i == 0))
            if band and ri % 2 == 1:
                _shade(c, TBL_BAND_FILL)
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    _cant_split(t)          # 必须等数据行都加完再打 —— 行内不跨页 (否则出现孤儿碎片)
    return t


def footer_pagenum(doc, text):
    p = doc.sections[0].footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(p.add_run(text + "    第 "), size=8)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    p._p.append(fld)
    _font(p.add_run(" 页"), size=8)


def sha(p):
    hh = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            hh.update(b)
    return hh.hexdigest()


def load_all_systems():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    out = {}
    for r in c.execute("select system_id,name,level,role,hardware,kpi,rows from subsystems order by ord"):
        d = dict(r)
        for k in ("kpi", "rows"):
            try:
                d[k] = json.loads(d[k]) if d[k] else (
                    {} if k == "kpi" else [])
            except Exception:
                pass
        out[d["system_id"]] = d
    return out


def load_task(task_id):
    p = os.path.join(ROOT, "config", "tasks", "tasks.json")
    if not os.path.isfile(p):
        return None
    for t in json.load(open(p, encoding="utf-8"))["tasks"]:
        if t["task_id"] == task_id:
            return t
    return None


def build(system="sys1", task_id="TASK-06-TRAY"):
    sys1, feats, fns, axes, params, axes_node = load()
    systems = load_all_systems()
    task = load_task(task_id)
    doc = page_setup(Document())
    footer_pagenum(doc, "%s · %s            " % (DOC_NO, VERSION))

    # 封面
    t = doc.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(t.add_run("机器人光模块上下料系统\n需求规格说明书 (SOR)"), size=22, bold=True)
    para(doc, "文件编号: %s" % DOC_NO, size=11)
    para(doc, "版本号: %s" % VERSION, size=11)
    para(doc, "项目名称: %s" % PROJ, size=11)
    para(doc, "适用对象: 供应商技术、质量、交付团队", size=11)
    para(doc, "导出方式: 配置中心自动导出 (数据源 = 单一工程库 zmax_engineering.db + 平台真源)", size=11)
    para(doc, "导出时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"), size=11)
    para(doc, "说明: 文中「待确认」项为配置中尚无真值的项, 已在附录 C 汇总。", size=10, italic=True)

    # 1 背景
    h(doc, "1. 项目背景与用途", 1)
    para(doc, "本需求用于采购/定制一套机器人光模块自动上下料系统。系统通过机器人从料盘 (周转盘) 抓取光模块, "
              "放入上料 Tray 盘或目标工位, 完成上料/下料或工位间搬运, 并与现有产线设备对接。")
    para(doc, "供应商应确保系统满足本规格书规定的功能、性能、接口、质量、安全及验收要求。"
              "本规格书由配置中心按当前 System 1 配置导出, 任何配置变更后须重新导出并对齐版本。")

    # 2 采购范围
    h(doc, "2. 采购范围", 1)
    table(doc, ["项目", "要求"], SUPPLY_SCOPE, widths=[4.5, 11.5])

    # 3 产品规格
    h(doc, "3. 光模块与料盘产品规格", 1)
    table(doc, ["参数", "要求"], PRODUCT_SPEC_STATIC, widths=[4.5, 11.5])

    # 4 功能需求 + 功能配置
    h(doc, "4. 功能需求与功能配置", 1)
    para(doc, "4.1 功能需求 (供应商系统需实现)", bold=True)
    fnum = 1
    for x in SCOPE_IN:
        para(doc, "%d) %s" % (fnum, x))
        fnum += 1
    para(doc, "4.2 System 1 功能清单 (在役功能节点)", bold=True)
    table(doc, ["功能 ID", "名称", "层", "类型"],
          [[f["fn_id"], f["name"], f["layer"], f["kind"]] for f in fns],
          widths=[2.8, 9.6, 1.6, 2.0])
    para(doc, "4.3 摆盘产品功能条目 (可逐条报价/逐条验收)", bold=True)
    table(doc, ["条目 ID", "名称", "适用子系统", "关联平台能力", "指标"],
          [[f["pf_id"], f["title"], "·".join(f.get("subsys") or []),
            f.get("capability_ref") or "", f.get("kpi") or ""] for f in feats],
          widths=[1.9, 3.8, 1.9, 4.2, 4.2])          # 复核建议 12/24/12/26/26
    para(doc, "4.4 任务工艺步骤 (配置中心任务配置)", bold=True)
    if task:
        para(doc, "任务 %s · %s · 类型 %s · 适用段 %d 段 · 排除段 %s"
             % (task["task_id"], task["name"], task["recipe_type"],
                len(task["applies_segments"]), "、".join(task["excluded_segments"]) or "无"))
        table(doc, ["#", "步骤", "描述"],
              [[i + 1, s.get("name"), s.get("desc")] for i, s in enumerate(task.get("steps", []))],
              widths=[1.3, 3.2, 11.5])          # 复核建议 # 8% / 步骤 20% / 描述 72%
        para(doc, "循环: %s" % task.get("loop", ""), size=10)
        para(doc, "触发: %s" % task.get("trigger", ""), size=10)
        para(doc, "工单: %s" % task.get("orders_rule", ""), size=10)
    else:
        para(doc, "任务 %s 未在配置中找到 —— 待确认。" % task_id)

    # 5 性能指标 (性能参数主表)
    h(doc, "5. 性能指标 (性能参数)", 1)
    para(doc, "以下指标已按配置中心口径统一; 「阶段」列区分 EVT/DVT/PVT, 验收按阶段取值。", size=10)
    table(doc, ["指标", "目标值", "口径 / 判据", "来源条目", "处理"],
          [list(m) for m in METRICS],
          widths=[2.6, 4.0, 5.4, 2.3, 1.7])   # 指标列 2.6: 最长'二值柔性退出'估 2.01+边距
    para(doc, "5.1 System 1 子系统指标 (配置真源)", bold=True)
    table(doc, ["指标", "值"], sorted(sys1.get("kpi", {}).items()), widths=[4.0, 12.0])

    # 5.2~ 光模块精细操作性能指标体系 (真源 config/platform/zmax_perf_spec.json, 6 组)
    _ps = json.load(open(os.path.join(ROOT, "config/platform/zmax_perf_spec.json"), encoding="utf-8"))
    _n_ps = sum(len(g["metrics"]) for g in _ps["groups"])
    para(doc, "5.2 光模块精细操作性能指标体系 (6 组 · 机器人学口径 + 光模块工艺口径)", bold=True)
    para(doc, "指标定义与目标值已进配置中心「性能配置」域 (共 %d 条)。表内为目标值(规格); 实测值在各阶段验收时"
              "填入并由配置中心收口 —— 未实测的项不填数, 不以设计值冒充实测值。" % _n_ps, size=10)
    para(doc, "引用标准: " + " · ".join("%s (%s)" % (k, v.split(":")[0]) for k, v in _ps["standards"].items()), size=9)
    for _i, _g in enumerate(_ps["groups"]):
        para(doc, "5.2.%d %s %s" % (_i + 1, _g["gid"], _g["name"]), bold=True)
        # 4 列 (2026-10-10 第二轮复核: 「口径/标准」列留白最多, 而「目标值」列最吃紧 ⇒
        #   把口径并进下面每条指标的行首, 宽度让给目标值, 目标值就不必拦腰断词)
        table(doc, ["指标", "单位", "目标值 (规格)", "阶段"],
              [[m["cn"], m.get("unit") or "-", str(m.get("target") or "待确认"), m.get("stage", "-")]
               for m in _g["metrics"]],
              widths=[5.3, 1.7, 7.5, 1.5])        # 5.3+1.7+7.5+1.5 = 16.0 (A4 可用宽)
        for _m in _g["metrics"]:
            _std = _m.get("std") or "-"
            para(doc, "· %s%s · 测法: %s"
                 % (_m["id"], ("  [%s]" % _std) if _std != "-" else "", _m.get("how", "")),
                 size=9.0, space_before=2, keep_lines=True)

    # 6 机器人末端
    h(doc, "6. 机器人与末端执行器要求", 1)
    for x in ROBOT_REQ:
        para(doc, "· " + x)

    # 7 视觉
    h(doc, "7. 视觉与定位要求", 1)
    for x in VISION_REQ:
        para(doc, "· " + x)

    # 8 料盘供料
    h(doc, "8. 料盘与供料机构要求", 1)
    for x in TRAY_REQ:
        para(doc, "· " + x)

    # 9 电气与控制接口 (接口契约)
    h(doc, "9. 电气、控制与接口要求", 1)
    for x in ELEC_REQ:
        para(doc, "· " + x)
    para(doc, "9.1 接口契约 (上游给意图不给轨迹; 坐标真值由底层提供)", bold=True)
    for k, rows in CONTRACT.items():
        para(doc, "【%s】" % k, bold=True)
        for r in rows:
            src = r.get("from") or r.get("to") or "—"
            extra = ("  → %s" % r["value"]) if r.get("value") else ""
            para(doc, "   - %s: %s%s" % (src, r.get("item", ""), extra), size=10)

    # 10 环境
    h(doc, "10. 环境与安装要求", 1)
    table(doc, ["项目", "要求"], ENV_TABLE, widths=[4.5, 11.5])

    # 11 质量与防护
    h(doc, "11. 质量与防护要求", 1)
    for x in QUALITY_REQ:
        para(doc, "· " + x)

    # 12 交付物
    h(doc, "12. 交付物清单", 1)
    for i, x in enumerate(DELIVERABLES, 1):
        para(doc, "%d. %s" % (i, x))

    # 13 验收
    h(doc, "13. 验收标准", 1)
    table(doc, ["验收项", "要求"], ACCEPTANCE, widths=[4.0, 12.0])

    # 14 质保
    h(doc, "14. 质保与售后", 1)
    for x in WARRANTY:
        para(doc, "· " + x)

    # 15 变更管理
    h(doc, "15. 变更管理", 1)
    for x in CHANGE_MGMT:
        para(doc, "· " + x)

    # 附录 A 功能配置明细
    doc.add_page_break()
    h(doc, "附录 A. 功能配置明细 (配置中心 cfg/cal/dia 轴)", 1)
    para(doc, "以下为 System 1 每个功能节点持有的配置项, 可在配置中心逐项修改; 供应商按此实现可配置化。", size=10)
    for axis, label in (("cfg", "A.1 可配置项 (cfg)"), ("cal", "A.2 标定项 (cal)"), ("dia", "A.3 诊断项 (dia)")):
        items = axes.get(axis, [])
        para(doc, "%s — %d 项 (每节点各持一份)" % (label, len(items)), bold=True)
        for i, it in enumerate(items, 1):
            para(doc, "   %d. %s" % (i, it), size=10)
    para(doc, "A.4 在役开关参数", bold=True)
    table(doc, ["参数 ID", "中文", "当前值", "单位", "状态"],
          [[p["param_id"], p["cn"], p["value"], p["unit"] or "-", p["status"]] for p in params],
          widths=[4.0, 3.6, 2.4, 1.6, 3.4])
    if axes_node:
        para(doc, "A.5 节点实现参数 (引擎侧, 仅供追溯 — 不属于供应商配置项)", bold=True)
        n = 0
        for _axis, items in axes_node.items():
            for it in items:
                n += 1
                para(doc, "   %d. %s" % (n, it), size=9)

    # 附录 B 系统清单 (整单元口径)
    h(doc, "附录 B. 系统组成 (Sys-2 / Sys-1 / Sys-0)", 1)
    table(doc, ["系统", "层", "名称", "角色", "硬件"],
          [[s["system_id"], s["level"], s["name"], (s["role"] or "")[:60], s["hardware"]] for s in systems.values()],
          widths=[1.8, 1.4, 3.4, 7.0, 2.4])

    # 附录 C 待确认
    h(doc, "附录 C. 待确认项与缺口 (发放前须闭环)", 1)
    table(doc, ["项", "现状", "处置"],
          [list(g) for g in GAPS], widths=[2.6, 7.4, 6.0])
    para(doc, "另: 本文件中凡标注「待确认」的静态采购条款 (交付地点/交付周期/电源/气源/温湿度等) 需我方填入后再发版。", size=10)

    # 附录 D 可复现信息
    h(doc, "附录 D. 导出可复现信息", 1)
    table(doc, ["项", "值"], [
        ["导出工具", "tools/sor_export.py (配置中心 sys1 导出)"],
        ["数据源 (单一工程库)", os.path.relpath(DB, ROOT) + "  sha256=" + sha(DB)[:16] + "…"],
        ["平台真源", "config/platform/zmax_platform.json"],
        ["任务真源", "config/tasks/tasks.json (flows/scenes_5jobs.json → task_build.py)"],
        ["子系统口径", "%s (%s)" % (sys1.get("name"), sys1.get("level"))],
        ["导出时间", time.strftime("%Y-%m-%d %H:%M:%S")],
    ], widths=[4.5, 11.5])
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None, help="项目档案 pid ⇒ 项目名/采购范围/manifest 随项目变")
    ap.add_argument("--system", default="sys1")
    ap.add_argument("--task", default="TASK-06-TRAY")
    ap.add_argument("--json", action="store_true", help="同时导出结构化 JSON")
    a = ap.parse_args()
    _prov = {}
    if a.project:
        _bom, _prov = project_profile.load(a.project)
        globals()["PROJ"] = _bom["project"]["name"]                 # 项目名随档案变
        _sc = (_bom.get("scope") or {}).get("采购范围") or []
        if _sc:
            globals()["SCOPE_IN"] = list(SCOPE_IN) + list(_sc)      # 采购范围追加本项目特有项
        print("📁 项目档案 %s (合并 sha %s)" % (a.project, _prov.get("merged_sha256")))
    doc = build(a.system, a.task)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUT_ROOT, ts)
    os.makedirs(out, exist_ok=True)
    base = "%s_%s" % (DOC_NO, VERSION)          # 文件名 = 文件编号 + 版本 (对外稳定命名)
    fp = os.path.join(out, base + ".docx")
    doc.save(fp)
    files = {os.path.basename(fp): fp}
    if a.json:
        sys1, feats, fns, axes, params, _ = load()
        jp = os.path.join(out, base + ".json")
        json.dump({"doc_no": DOC_NO, "version": VERSION, "project": PROJ,
                   "system": sys1, "functions": fns, "features": feats, "axes": axes,
                   "params": params, "contract": CONTRACT,
                   "metrics": [dict(zip(("指标", "目标", "口径", "来源条目", "处理"), m)) for m in METRICS],
                   "gaps": [dict(zip(("项", "现状", "处置"), g)) for g in GAPS],
                   "scope_in": SCOPE_IN, "scope_out": SCOPE_OUT},
                  open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        files[os.path.basename(jp)] = jp
    man = {"doc_no": DOC_NO, "version": VERSION, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "source_db": os.path.relpath(DB, ROOT), "source_db_sha256": sha(DB), "files": {},
           "project": PROJ, "project_profile": _prov or None}
    for n, p in sorted(files.items()):
        man["files"][n] = {"bytes": os.path.getsize(p), "sha256": sha(p)}
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(man, f, ensure_ascii=False, indent=1)
    print("✅ SOR (Word): %s" % fp)
    print("   大小 %.1f KB · 章节: 1-15 + 附录 A(功能配置)/B(系统组成)/C(待确认)/D(可复现)" % (os.path.getsize(fp) / 1024.0))
    print("   目录: %s" % out)
    for n in man["files"]:
        print("   - %s" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
