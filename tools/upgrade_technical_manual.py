# -*- coding: utf-8 -*-
"""upgrade_550_v4.py — 在 v3 基础上更新升级状态空间方案（不重写，只在原稿上增改）

依据：
  · 专利 12 件（config/patents/patent_registry.json），其中 ZMP-2026-006 = 视觉触觉融合
  · 现状：画布 79 节点 / fuse_sensors 已在引擎主循环每帧调用（engine/runtime.py:3073）
  · 融合真实状态：触觉 4 维里后 2 维恒为 0；合成触觉 synth_tactile 才给全 4 维

改什么：
  1) 封面版本行 → v4，注明本次增补
  2) 第 43 / 48 页「运行实况」口径 → 改成已接入的实测事实
  3) 末尾新增 8 页：第 06 章 视觉触觉融合（专利 006 为核心）+ 专利映射 + 变更记录
"""
from __future__ import annotations

import os
import re
import shutil

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

SRC = r"C:\Users\Mike\Downloads\Z-MAX以世界模型为核心的状态空间工程_550_v3.pptx"
DST = r"C:\Users\Mike\Downloads\Z-MAX以世界模型为核心的状态空间工程_550_v4.pptx"

W, H = 13.333333333333334, 7.5
M = 0.78
CW = W - 2 * M
INK = "1F2937"
MUTED = "6B7280"
LINE = "E5E7EB"
SOFT = "F8FAFC"
GOOD = "059669"
OKC = "D97706"
RISK = "DC2626"
ACCENT = "1D4ED8"
VIOLET = "7C3AED"
WHITE = "FFFFFF"
EA = "微软雅黑"


def _font(run, size, bold=False, color=INK, latin="Arial"):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.name = latin
    f.color.rgb = RGBColor.from_string(color)
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", EA)


def text(s, x, y, w, h, lines, size=12, color=INK, bold=False,
         align=PP_ALIGN.LEFT, space=5, anchor=MSO_ANCHOR.TOP, line_sp=1.2):
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Emu(0)
    tf.margin_top = tf.margin_bottom = Emu(0)
    if isinstance(lines, str):
        lines = [lines]
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space)
        p.line_spacing = line_sp
        for seg in re.split(r"(\*\*[^*]+\*\*)", str(ln)):
            if not seg:
                continue
            r = p.add_run()
            if seg.startswith("**") and seg.endswith("**") and len(seg) > 4:
                r.text, b = seg[2:-2], True
            else:
                r.text, b = seg, bold
            _font(r, size, b, color)
    return box


def rect(s, x, y, w, h, fill=SOFT, line=None, radius=False):
    sh = s.shapes.add_shape(5 if radius else 1, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = RGBColor.from_string(fill)
    if line:
        sh.line.color.rgb = RGBColor.from_string(line)
        sh.line.width = Pt(0.75)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    sh.text_frame.text = ""
    return sh


_LAYOUT = {"v": None}


def _blank(prs):
    if _LAYOUT["v"] is None:
        cand = []
        for m in prs.slide_masters:
            cand += [l for l in m.slide_layouts]
        tgt = [l for l in cand if l.name.strip().lower() == "blank"] or cand
        if not tgt and len(prs.slides):
            tgt = [prs.slides[-1].slide_layout]
        _LAYOUT["v"] = tgt[0]
        print("插入页使用版式:", _LAYOUT["v"].name, "| 候选数:", len(cand))
    return _LAYOUT["v"]


def page(prs, num, title, lead, dark=False):
    s = prs.slides.add_slide(_blank(prs))
    if dark:
        rect(s, 0, 0, W, H, fill="0F172A")
        return s
    text(s, M, 0.46, 3.0, 0.28, num, 10, ACCENT, True)
    text(s, M, 0.78, CW, 0.60, title, 23, INK, True, line_sp=1.0)
    if lead:
        text(s, M, 1.44, CW, 0.40, lead, 11.5, MUTED, line_sp=1.2)
    rect(s, M, 6.96, CW, 0.008, fill=LINE)
    text(s, M, 7.04, 8.0, 0.24, "以世界模型为核心的状态空间工程 · 技术手册 5.50.D-P2", 8, MUTED)
    return s


def table(s, x, y, w, rows, col_w, head_h=0.34, row_h=0.36, size=9, colors=None):
    nr, nc = len(rows), len(rows[0])
    shp = s.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(w),
                             Inches(head_h + row_h * (nr - 1)))
    t = shp.table
    for i, cw in enumerate(col_w):
        t.columns[i].width = Inches(cw)
    t.rows[0].height = Inches(head_h)
    for i in range(1, nr):
        t.rows[i].height = Inches(row_h)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = t.cell(ri, ci)
            cell.margin_left = cell.margin_right = Inches(0.07)
            cell.margin_top = cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string(
                "1F2937" if ri == 0 else (SOFT if ri % 2 == 0 else WHITE))
            p = cell.text_frame.paragraphs[0]
            p.line_spacing = 1.0
            r = p.add_run()
            r.text = str(val)
            col = WHITE if ri == 0 else INK
            if ri and colors and (ri, ci) in colors:
                col = colors[(ri, ci)]
            _font(r, size, ri == 0, col)
    return shp


# ══════════════════════════════════════════════════════════════════════
def replace_in_slide(slide, pairs):
    """在单页内做文本替换，保留首个 run 的格式。"""
    n = 0
    for sh in slide.shapes:
        if not sh.has_text_frame:
            continue
        tf = sh.text_frame
        for p in tf.paragraphs:
            full = "".join(r.text for r in p.runs)
            new = full
            for old, rep in pairs:
                if old in new:
                    new = new.replace(old, rep)
            if new != full and p.runs:
                p.runs[0].text = new
                for r in p.runs[1:]:
                    r.text = ""
                n += 1
    return n


def main():
    if not os.path.exists(SRC):
        raise SystemExit("源文件不存在: " + SRC)
    if os.path.exists(DST):
        os.remove(DST)
    shutil.copy2(SRC, DST)
    prs = Presentation(DST)
    print("打开 v3：%d 页" % len(prs.slides))

    # ① 封面版本行
    cov = prs.slides[0]
    n1 = replace_in_slide(cov, [
        ("版本基线：\xa02026-11-01 讨论版（涵盖十篇核心内容）",
         "版本基线：\xa02026-11-11 讨论版 v4（新增第 06 章 视觉触觉融合 · 12 件专利映射）"),
    ])
    print("封面改写:", n1)

    # ② 第 43 / 48 页 运行实况口径
    p43 = [("运行实况：内部算法尚未接入常驻循环，这一环目前只按连线把数据交给下游。",
            "运行实况：已接入引擎主循环——每帧在 engine/runtime.py:3073 调 fuse_sensors() 合成 43D；"
            "触觉 4 维中后 2 维仍恒为 0，需 synth_tactile 才补全（见第 06 章）。")]
    p48 = [("运行实况：内部算法尚未接入常驻循环，这一环目前只按连线把数据交给下游。",
            "运行实况：合成触觉 synth_tactile(obs39) 已产出 4 维（夹持/接触/方向），"
            "但在引擎侧触觉仍取 [夹爪开度, 接触标记, 0, 0]——4 维里后 2 维待接真值（见第 06 章）。")]
    print("第43页改写:", replace_in_slide(prs.slides[42], p43))
    print("第48页改写:", replace_in_slide(prs.slides[47], p48))

    # ③ 新增第 06 章
    # 章首页
    s = page(prs, "", "", "", dark=True)
    text(s, 1.15, 2.20, 9.6, 0.38, "06", 15, "93C5FD", True)
    text(s, 1.15, 2.68, 10.8, 0.90, "视觉触觉融合", 40, WHITE, True, line_sp=1.05)
    text(s, 1.15, 3.72, 10.4, 0.80,
         "视觉告诉系统「东西在哪」，触觉告诉系统「碰上了没有、压到什么程度」。"
         "把两者合成一份状态，插拔段才有闭环的依据。", 14, "CBD5E1", line_sp=1.45)
    text(s, 1.15, 4.86, 10.6, 1.0,
         ["本章对应专利 ZMP-2026-006（开放词汇分割前置的视觉触觉融合定位与场景建图）",
          "同时修正前文中「融合尚未接入」的旧口径 —— 该描述基于 5.50.D-M2，已不成立。"],
         11.5, "94A3B8", line_sp=1.55)

    # 现状页
    s = page(prs, "6.01", "现状：两条通道已经合成一份状态，但触觉只有两维是真值",
             "43 维 = 18 当前 + 18 上一帧 + 3 阶段目标 = 39 视觉结构，再加 4 维触觉。")
    rows = [["构成", "维数", "来源", "当前状态"],
            ["视觉结构（当前）", "18", "末端位姿 3 · 夹爪开度 1 · 速度 3 · 工件 3 · 孔位 3 · 姿态占位 3 · 预留 2", "真值"],
            ["视觉结构（上一帧）", "18", "同上，取上一拍快照", "真值"],
            ["阶段目标", "3", "八阶段状态机给出的本段目标点", "真值"],
            ["触觉 4 维", "4", "夹爪开度 · 接触标记 · 方向 2 维", "2 维真值 + 2 维恒 0"]]
    table(s, M, 1.92, CW, rows, [2.06, 0.66, 5.90, 2.94], head_h=0.34, row_h=0.52, size=9,
          colors={(4, 3): RISK})
    text(s, M, 4.72, CW, 1.4,
         ["**合成位置**：`engine/runtime.py:3073` 每帧 `obs = perception.fuse_sensors(visual39, force, tactile4)`；"
          "仿真侧同口径在 `engine/sim.py:362`。",
          "**触觉来源**：`tactile4 = [gripper, grasped, 0, 0]`——合成触觉 `synth_tactile(obs39)` 能给出完整 4 维，"
          "但引擎在役路径还没切过去。"],
         10.5, INK, line_sp=1.45)
    text(s, M, 6.28, CW, 0.50,
         ["**一句话**：融合的「管道」已经通了，融合的「触觉含量」还差一半——这是本章要补的第一件事。"], 11, INK)

    # 专利方案页
    s = page(prs, "6.02", "专利方案：先把背景剥掉，再谈融合",
             "ZMP-2026-006 的核心不是「多一路传感器」，而是「先确定看哪儿，再谈看得准不准」。")
    steps = [
        ("① 开放词汇分割前置", "用文本提示把背景结构分割并剥离，后续检测与定位只在目标区域内进行。",
         "解决：背景干扰导致的定位漂移"),
        ("② 视觉目标坐标", "在目标区域内做检测与 2D→3D 解算，得到工件三维坐标。",
         "解决：纯视觉在遮挡工况下失效"),
        ("③ 触觉接触信息融合", "把接触与否、接触力方向与视觉坐标合成同一状态，形成带语义的定位。",
         "解决：视觉看得见但不知道碰没碰上"),
        ("④ 语义地图与场景资产", "融合结果沉淀为带语义的地图，并以三维重建产出场景资产供仿真复用。",
         "解决：仿真场景与真机场景不一致"),
    ]
    y = 1.86
    for k, (name, what, solve) in enumerate(steps):
        rect(s, M, y, CW, 1.06, fill=SOFT, line=LINE, radius=True)
        rect(s, M, y, 0.055, 1.06, fill=VIOLET)
        text(s, M + 0.26, y + 0.13, 2.55, 0.30, name, 11.5, VIOLET, True)
        text(s, M + 2.92, y + 0.11, CW - 3.20, 0.38, what, 10.5, INK, line_sp=1.3)
        text(s, M + 2.92, y + 0.62, CW - 3.20, 0.30, solve, 9.5, MUTED)
        y += 1.14
    text(s, M, 6.48, CW, 0.40,
         ["**为什么这个顺序不能反**：先剥背景再定位，误差来源单一；先检测再补背景，错误会被融合放大到状态里。"], 10.5, INK)

    # 工程落点页
    s = page(prs, "6.03", "落地：这条链在画布上是四个节点，代码是三段",
             "从像素到 43 维状态，每一步都能指到具体文件与函数，不靠描述。")
    rows = [["环节", "画布节点", "实现文件", "在役状态"],
            ["开放词汇分割", "`ss_seg`", "`middleware/nodes/impl/ss_seg.py` · node_ss_seg", "可运行；分割服务按需调用"],
            ["2D → 3D 解算", "`ss2d3d`", "`impl/yolo_align.py` · node_yolo_align", "可运行"],
            ["触觉合成", "`sstactile`", "`impl/yolo_tactile.py` · node_yolo_tactile（synth_tactile）", "4 维可产出"],
            ["融合成 43D", "`sssensor`", "`impl/ss_sensor.py` · node_ss_sensor → `perception.fuse_sensors`", "每帧在跑，触觉后 2 维待接"]]
    table(s, M, 1.92, CW, rows, [2.06, 1.26, 6.30, 2.10], head_h=0.34, row_h=0.62, size=8.8,
          colors={(4, 3): RISK})
    text(s, M, 5.10, CW, 1.5,
         ["**与专利 003 的接口**：融合出的 43 维状态随后进入 SU(2) 统一表示（`ssobs` 节点），"
          "再由流形引擎做「编码→投影→度量」。",
          "**与专利 005 的边界**：005 管「二维检测 → 三维坐标 → 状态量」的同构链路，"
          "006 管「分割前置 + 触觉融合 + 场景建图」，两者共用同一套状态口径，不重复定义。"],
         10.5, INK, line_sp=1.45)

    # 差距页
    s = page(prs, "6.04", "差距：管道通了，含量不够", "把「已做到」和「还缺」分开列，避免把下一步当已完成。")
    colw = (CW - 0.30) / 2
    rect(s, M, 1.86, colw, 3.30, fill="ECFDF5", line="A7F3D0", radius=True)
    text(s, M + 0.28, 2.04, colw - 0.56, 0.30, "已经做到", 12, GOOD, True)
    text(s, M + 0.28, 2.42, colw - 0.56, 2.6,
         ["· 融合调用已进引擎主循环，每帧都过 `fuse_sensors`（不是旁路）",
          "· 视觉 39 维全真值：位姿、速度、工件、孔位、阶段目标都来自实时状态",
          "· 触觉合成 `synth_tactile` 能产出 4 维（夹持/接触/方向）",
          "· 分割、2D3D、触觉三个节点在画布上独立可运行（9/9 节点冒烟通过）"],
         9.8, INK, line_sp=1.42, space=8)
    rect(s, M + colw + 0.30, 1.86, colw, 3.30, fill="FEF2F2", line="FECACA", radius=True)
    text(s, M + colw + 0.58, 2.04, colw - 0.56, 0.30, "还没做到", 12, RISK, True)
    text(s, M + colw + 0.58, 2.42, colw - 0.56, 2.6,
         ["· 引擎触觉仍取 `[gripper, grasped, 0, 0]` —— 4 维里 2 维恒为 0",
          "· 分割目前按需调用，未进常驻循环（换料场景下才会触发）",
          "· 融合结果尚未落成语义地图资产（地图接口在，数据未生产）",
          "· 真机域触觉真值缺采集口径，无法评估「融合后精度提升多少」"],
         9.8, INK, line_sp=1.42, space=8)
    text(s, M, 5.32, CW, 1.3,
         ["**补的顺序**：先接触觉后 2 维真值（最便宜、收益最直接）→ 再让分割进常驻循环（换型时间的主要成本）→ "
          "最后产出语义地图资产（复用的前提）。",
          "**不建议**跳过第一步直接做地图：触觉缺位的融合结果只能算「视觉单通道」，地图也会继承这个缺口。"],
         10.5, INK, line_sp=1.45)

    # 验收判据页
    s = page(prs, "6.05", "验收：怎么证明融合「真的在用」", "四条判据，每条都能当场跑一遍，不接受口头描述。")
    rows = [["判据", "怎么验", "通过线"],
            ["融合调用在链上", "在 `fuse_sensors` 埋计数，跑 100 帧看计数是否同步增长", "100 帧 = 100 次，缺一即 FAIL"],
            ["触觉 4 维非零", "抓持阶段抓 200 帧，统计第 3/4 维标准差", "标准差 > 0（不是常量 0）"],
            ["分割前置生效", "同一帧对比「有分割」与「无分割」的定位残差", "有分割一侧残差下降"],
            ["融合优于单通道", "同批样本分别用视觉单通道 / 视觉+触觉跑插拔", "融合侧成功率不低于单通道，且接触段误判更少"]]
    table(s, M, 1.92, CW, rows, [2.40, 6.30, 3.02], head_h=0.34, row_h=0.72, size=9.2)
    text(s, M, 5.56, CW, 1.0,
         ["**这四条与专利 006 的权利要求对应**：判据一、二对应「视觉与触觉融合为同一状态」，"
          "判据三对应「分割前置剥离背景」，判据四对应「带语义的定位与建图」。",
          "**未通过之前，对外只说「融合链路已通」，不说「融合已提升精度」**——两者不是一回事。"],
         10.5, INK, line_sp=1.45)

    # 12 件专利映射页
    s = page(prs, "6.06", "12 件专利 ↔ 本手册章节：每条主张都有落点",
             "左侧是本手册的章节，右侧是支撑它的专利；没有落点的章节，说明它还在设计阶段。")
    rows = [["专利", "主张", "本手册落点"],
            ["ZMP-2026-001", "北斗七星配置体系（七类配置面同源）", "第 1 章 整机与工位 · 配置口径"],
            ["ZMP-2026-002", "四系统分层 + 功能/层级/模型三向映射", "第 04 章 五层分工"],
            ["ZMP-2026-003", "SU(2) 统一状态表示与跨层映射", "4.03 观测构成 · 22/30 位 SU(2) 节点"],
            ["ZMP-2026-004", "可行域逐层收窄与势函数收口", "4.12 势函数与可行域 · 4.24 安全闸时序"],
            ["ZMP-2026-005", "2D→3D→状态量同构感知链 + 真机域适应", "4.04 视觉链路 · 28/30 位 2D3D"],
            ["ZMP-2026-006", "分割前置的视觉触觉融合定位与建图", "本手册第 06 章（本次新增）"],
            ["ZMP-2026-007", "世界模型意图-动作分块 + 折叠部署", "4.08 INTACT-JEPA · 4.25 接管契约"],
            ["ZMP-2026-008", "慢决策 + 本地技能包 + 双层否决", "第 05 章 能力分级 · 4.14 安全闸"],
            ["ZMP-2026-009", "原子技能肌肉记忆与标杆直通", "八阶段状态机 · 23/30 位 肌肉记忆"],
            ["ZMP-2026-010", "多层记忆组织与元任务预测", "4.13 五层记忆 · 10/11 位 元任务预测"],
            ["ZMP-2026-011", "人机在环示教 + 伺服小步对位", "第 1 章 标定与对位"],
            ["ZMP-2026-012", "多相机底图 AR 叠加与一致性校验", "4.17 质量判据 · 调试画面证据"]]
    table(s, M, 1.84, CW, rows, [1.62, 5.00, 5.10], head_h=0.32, row_h=0.338, size=8.6,
          colors={(6, 2): VIOLET})
    text(s, M, 6.44, CW, 0.42,
         ["**一条纪律**：新增功能先问「挂哪件专利」；挂不上，要么补专利，要么它只是支撑件。"], 9.5, MUTED)

    # 变更记录页
    s = page(prs, "6.07", "v3 → v4 变更记录", "改了什么、依据是什么、哪些是修正旧口径。")
    rows = [["#", "变更", "依据"],
            ["1", "第 43 页「融合尚未接入常驻循环」→ 改为已接入 `engine/runtime.py:3073`，并注明触觉后 2 维待接",
             "代码实测：`engine/runtime.py` 主循环每帧调用；`tactile4 = [gripper, grasped, 0, 0]`"],
            ["2", "第 48 页触觉节点口径同步修正", "`synth_tactile(obs39)` 可产 4 维，引擎侧未切换"],
            ["3", "新增第 06 章（6.01–6.07 共 7 页）：视觉触觉融合", "专利 ZMP-2026-006 + 画布四节点实测"],
            ["4", "新增 12 件专利 ↔ 章节映射", "`config/patents/patent_registry.json`（12 件）"],
            ["5", "封面版本基线 → 2026-11-11 讨论版 v4", "本次修订"]]
    table(s, M, 1.86, CW, rows, [0.50, 6.60, 4.62], head_h=0.32, row_h=0.86, size=9)
    text(s, M, 6.06, CW, 0.90,
         ["**没改的部分**：55 个控制节点的逐页内容、第 02–03 章技术史与对标、第 05 章产品矩阵均保持原样。",
          "**待确认**：画布现有 79 个节点（含非控制类），与手册「55 个控制节点」不是同一口径，是否需要在第 1 章加一句说明——留给你定。"],
         10, MUTED, line_sp=1.4)

    prs.save(DST)
    print("已保存:", DST)
    print("新页数:", len(prs.slides))


if __name__ == "__main__":
    main()
