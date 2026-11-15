#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""z700_build_pptx.py —— 生成《Z700 解决方案汇报》PPT (16:9)"""
import json
import os
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from z700_docx import OUT, gantt_rows, load                        # noqa: E402
from z700_features import ARRAYS                                    # noqa: E402

NAVY = RGBColor(0x1F, 0x38, 0x64)
BLUE = RGBColor(0x2E, 0x5A, 0x9A)
LBLUE = RGBColor(0x4A, 0x7E, 0xC4)
GREY = RGBColor(0x44, 0x44, 0x44)
LGREY = RGBColor(0x88, 0x88, 0x88)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ORANGE = RGBColor(0xC0, 0x5A, 0x00)
GREEN = RGBColor(0x2E, 0x7D, 0x32)
RED = RGBColor(0xB0, 0x30, 0x30)
BG = RGBColor(0xF7, 0xF9, 0xFC)

W, H = Inches(13.333), Inches(7.5)
FONT = "微软雅黑"


class Deck:
    def __init__(self):
        self.p = Presentation()
        self.p.slide_width = W
        self.p.slide_height = H
        self.n = 0

    def _blank(self):
        return self.p.slides.add_slide(self.p.slide_layouts[6])

    def _rect(self, s, x, y, w, h, color, line=None):
        from pptx.enum.shapes import MSO_SHAPE
        sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
        sh.fill.solid()
        sh.fill.fore_color.rgb = color
        if line is None:
            sh.line.fill.background()
        else:
            sh.line.color.rgb = line
            sh.line.width = Pt(0.75)
        sh.shadow.inherit = False
        return sh

    def _text(self, s, x, y, w, h, text, size=16, bold=False, color=GREY,
              align=PP_ALIGN.LEFT, anchor_top=True, line_spacing=1.25):
        from pptx.enum.text import MSO_ANCHOR
        tb = s.shapes.add_textbox(x, y, w, h)
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.TOP if anchor_top else MSO_ANCHOR.MIDDLE
        tf.margin_left = tf.margin_right = Emu(0)
        tf.margin_top = tf.margin_bottom = Emu(0)
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.alignment = align
            para.line_spacing = line_spacing
            r = para.add_run()
            r.text = ln
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = color
            r.font.name = FONT
        return tb

    # ── 版式 ──
    def title_slide(self, title, subtitle, meta):
        s = self._blank()
        self._rect(s, 0, 0, W, H, NAVY)
        self._rect(s, 0, Inches(4.15), W, Inches(0.06), LBLUE)
        self._text(s, Inches(1.0), Inches(1.7), Inches(11), Inches(1.0),
                   title, 40, True, WHITE)
        self._text(s, Inches(1.0), Inches(2.9), Inches(11), Inches(1.0),
                   subtitle, 19, False, RGBColor(0xC5, 0xD6, 0xEE))
        self._text(s, Inches(1.0), Inches(4.45), Inches(11), Inches(1.6),
                   meta, 13, False, RGBColor(0x9F, 0xB6, 0xD8), line_spacing=1.6)
        self.n += 1

    def section(self, num, title, sub=""):
        s = self._blank()
        self._rect(s, 0, 0, W, H, BG)
        self._rect(s, 0, Inches(2.6), Inches(0.14), Inches(1.5), BLUE)
        self._text(s, Inches(1.0), Inches(2.5), Inches(2.0), Inches(1.0),
                   num, 54, True, RGBColor(0xD3, 0xDF, 0xEF))
        self._text(s, Inches(1.5), Inches(2.85), Inches(10), Inches(0.8),
                   title, 32, True, NAVY)
        if sub:
            self._text(s, Inches(1.5), Inches(3.7), Inches(10), Inches(0.6),
                       sub, 15, False, LGREY)
        self.n += 1

    def slide(self, title, kicker=""):
        s = self._blank()
        self._rect(s, 0, 0, W, Inches(0.92), NAVY)
        self._text(s, Inches(0.55), Inches(0.2), Inches(10.4), Inches(0.55),
                   title, 21, True, WHITE)
        if kicker:
            self._text(s, Inches(0.55), Inches(0.62), Inches(11), Inches(0.28),
                       kicker, 10.5, False, RGBColor(0xA8, 0xC0, 0xE0))
        self._text(s, Inches(12.3), Inches(6.98), Inches(0.9), Inches(0.3),
                   str(self.n + 1), 9, False, LGREY, PP_ALIGN.RIGHT)
        self.n += 1
        return s

    def bullets(self, s, items, x=Inches(0.65), y=Inches(1.25),
                w=Inches(12.0), size=15, gap=0.52):
        for i, it in enumerate(items):
            if isinstance(it, tuple):
                text, lvl = it
            else:
                text, lvl = it, 0
            yy = y + Inches(gap * i)
            self._rect(s, x + Inches(0.12 * lvl), yy + Inches(0.09),
                       Inches(0.09), Inches(0.09), BLUE if lvl == 0 else LBLUE)
            self._text(s, x + Inches(0.34 + 0.3 * lvl), yy, w, Inches(0.5),
                       text, size - (1 if lvl else 0),
                       lvl == 0, GREY if lvl == 0 else RGBColor(0x5A, 0x5A, 0x5A))

    def table(self, s, headers, rows, widths, y=Inches(1.3), size=10.5,
              head_h=0.42, row_h=0.34):
        n = len(headers)
        tot = sum(widths)
        xs = []
        cur = 0.62
        for wd in widths:
            xs.append(Inches(cur))
            cur += wd * (12.1 / tot)
        yy = y
        # 表头
        cur = 0.62
        for j, h in enumerate(headers):
            ww = Inches(widths[j] * (12.1 / tot))
            self._rect(s, Inches(cur), yy, ww, Inches(head_h), BLUE)
            self._text(s, Inches(cur + 0.08), yy + Inches(0.07), ww, Inches(head_h),
                       h, size, True, WHITE)
            cur += widths[j] * (12.1 / tot)
        yy += Inches(head_h)
        for i, row in enumerate(rows):
            if yy > Inches(6.75):
                break
            cur = 0.62
            bgc = WHITE if i % 2 == 0 else RGBColor(0xEF, 0xF4, 0xFA)
            for j, v in enumerate(row):
                ww = Inches(widths[j] * (12.1 / tot))
                self._rect(s, Inches(cur), yy, ww, Inches(row_h), bgc,
                           line=RGBColor(0xD5, 0xDF, 0xEC))
                self._text(s, Inches(cur + 0.08), yy + Inches(0.05), ww, Inches(row_h),
                           str(v), size - 0.5, False, GREY)
                cur += widths[j] * (12.1 / tot)
            yy += Inches(row_h)

    def kpis(self, s, items, y=Inches(1.35), h=Inches(1.5)):
        """items: [(数值, 单位, 标签, 颜色)]"""
        n = len(items)
        gap = 0.2
        w = (12.1 - gap * (n - 1)) / n
        for i, (val, unit, label, col) in enumerate(items):
            x = Inches(0.62 + i * (w + gap))
            self._rect(s, x, y, Inches(w), h, WHITE,
                       line=RGBColor(0xD5, 0xDF, 0xEC))
            self._rect(s, x, y, Inches(w), Inches(0.06), col)
            self._text(s, x, y + Inches(0.22), Inches(w), Inches(0.6),
                       str(val), 27, True, col, PP_ALIGN.CENTER)
            self._text(s, x, y + Inches(0.82), Inches(w), Inches(0.3),
                       unit, 10, False, LGREY, PP_ALIGN.CENTER)
            self._text(s, x, y + Inches(1.08), Inches(w), Inches(0.32),
                       label, 10.5, False, GREY, PP_ALIGN.CENTER)

    def note(self, s, text, y=Inches(6.5)):
        self._rect(s, Inches(0.62), y, Inches(12.1), Inches(0.62),
                   RGBColor(0xFF, 0xF6, 0xE0))
        self._text(s, Inches(0.78), y + Inches(0.12), Inches(11.8), Inches(0.45),
                   text, 11, False, ORANGE)

    def save(self, path):
        self.p.save(path)
        return path


def build():
    met, feats = load()
    perf = met["performance"]
    pay = met["payload"]
    gon, gtotal = gantt_rows()

    def M(name):
        for m in perf["metrics"]:
            if m["name"] == name:
                return m["measured"]
        return None

    d = Deck()

    # 1 封面
    d.title_slide("Z700 精细操作机器人\n解决方案",
                  "光模块生产工厂 · 插拔工位全套环境 · EVT / DVT / PVT 全流程",
                  "版本 5.50.E-R1　|　数据基线：真机 215 点采集\n"
                  "功能清单 165 条　|　引用国标 25 项　|　Z-MAX 产品与工程中心")

    # 2 一句话结论
    s = d.slide("一句话结论", "如果只能记住一页")
    d._text(s, Inches(0.7), Inches(1.5), Inches(11.9), Inches(1.4),
            "把「插没插到位」从人的手感，变成可测量、可记录、可验收的机器判据。",
            27, True, NAVY, line_spacing=1.35)
    d.kpis(s, [
        (str(len(feats)), "条功能", "七阵 × 三阶段全覆盖", BLUE),
        ("%.2f" % perf["s_per_point"], "s/点", "真机实测单点耗时", LBLUE),
        ("%.2f" % perf["uph_single_arm"], "UPH", "单臂逐点回放", ORANGE),
        ("%.1f" % (pay["usable_payload_g"] / 1000), "kg", "可用负载", GREEN),
    ], y=Inches(3.2), h=Inches(1.55))
    d.note(s, "三阶段：EVT 把功能全做出来并演得出来；DVT 证明在哪都能做；PVT 证明能一直做下去。", Inches(5.2))

    # 3 痛点
    s = d.slide("为什么是这个工位", "搬运已高度自动化，难的是手上有感觉的工序")
    d.bullets(s, [
        "插拔、压装、拧紧、贴装 —— 这类工位现在普遍一人一岗",
        "原因不是机器人动不了，而是「插没插到位」依赖人的手感",
        "缺少可复核的机器判据 → 无法验收、无法交接、无法持续改进",
        "光模块是这类工位里付费意愿最强的：件单价高",
        "插坏一件的损失远大于设备差价 —— 这是客户愿意为「稳」付钱的场景",
    ], size=16, gap=0.72)

    # 4 五大场景
    s = d.slide("五大场景", "每个场景独立作业流程与判据，可单独验收")
    d.table(s, ["#", "场景", "作业对象", "单颗节拍", "成功率"], [
        ["1", "FW Loading + EEPROM 读写", "QSFP-DD / OSFP 成品模块", "≤6 s", "≥99%"],
        ["2", "上下料搬运", "料盘 / 料箱（多载具）", "按趟 ≤5min", "≥99.5%"],
        ["3", "BI 老化箱模块插拔", "QSFP ~10颗/屉 · OSFP ~16颗/屉", "单颗 ≤60 s", "≥99%"],
        ["4", "热海柜体电口+光口", "QSFP / OSFP", "≤20 s", "≥99%"],
        ["5", "ATS / 线外检测插接", "100G C4 等", "≤15 s", "≥99%"],
    ], widths=[1, 5, 6, 3, 2.5], y=Inches(1.5), size=13, row_h=0.62)

    # 5 节拍硬指标
    s = d.slide("节拍是物理指标，不是商务承诺", "它反推了本体尺寸与重量")
    d.bullets(s, [
        "节拍由行程、速度、加速度、负载惯量、控制周期共同决定",
        "负载越大 → 惯量越大 → 加速度越低 → 节拍越慢",
        "6s 节拍要求末端平均速度 ≥0.5m/s、峰值 ≥1.5m/s",
        "末端惯量 I ∝ m·L² ⇒ 末端必须轻（≤1.5kg）",
        "臂 25kg 满载静载约 100Nm ⇒ 必须自重补偿",
        "结论：整机 ≤250kg、臂 ≤25kg、末端 ≤1.5kg —— 这是 6s 的物理前提",
    ], size=15, gap=0.62)

    # 6 形态论证
    s = d.slide("形态论证：为什么是 AMR + 协作臂", "唯一同时满足异步看管 + 跨工位 + 6s 的形态")
    d.table(s, ["形态", "节拍", "多工位", "占地", "结论"], [
        ["固定工位 6 轴臂", "最优（无移动损耗）", "✗ 单工位", "小", "固定测试台最优，但每工位一台"],
        ["AMR + 6 轴协作臂", "6s 可行", "✓ 1 机看管 2-4 台", "0.7×0.6m", "主推"],
        ["龙门 / 直线模组", "快", "线内", "大", "仅批量产线，不灵活"],
        ["人形 / 双足", "慢", "✓", "大", "节拍不达标，排除"],
    ], widths=[4, 3.5, 3.5, 2.5, 5], y=Inches(1.5), size=12.5, row_h=0.66)
    d.note(s, "异步是关键手段：测试等待的 20-90s 期间去另一台上下料，机台利用率翻倍，不用把单机速度推到极限。",
           Inches(5.6))

    # 7 负载计算（关键页）
    s = d.slide("负载要求：光模块重量与料盘搬运", "额定 5000g − 末端 1500g = 可用 3500g")
    d.table(s, ["层级", "负载(g)", "利用率", "臂可搬", "结论"], [
        ["① 单颗模块抓取", "15 ~ 200", "5.7%", "是", "真约束是夹持力下限与金手指零划伤"],
        ["② 吸塑满盘 QSFP-DD", "180 ~ 1880", "53.7%", "是", "可搬"],
        ["② 吸塑满盘 OSFP", "260 ~ 2460", "70.3%", "是", "可搬"],
        ["② 金属满盘 24 位", "950 ~ 2990", "85.4%", "是", "临界，需核算重心偏移"],
        ["③ 整箱周转", "1400 ~ 8920", "254.9%", "否", "超可用负载 → 必须 AMR 搬"],
    ], widths=[4.5, 3, 2, 2, 7], y=Inches(1.5), size=12.5, row_h=0.6)
    d.note(s, "负载不是瓶颈。真正要卡的是夹持力 0.1N 的分辨率，以及末端惯量对 6s 节拍的影响。",
           Inches(5.5))

    # 8 七阵
    s = d.slide("能力架构：七阵怎么落到六层", "每一阵都落在一个具体工程层，不存在只在文档里的功能")
    d.table(s, ["阵位", "代号", "回答什么", "落到哪层", "条数"], [
        [v["full"], v["code"], v["desc"],
         {"天枢": "产品定义", "天璇": "L4 任务规划", "天玑": "L1-L3 感知/动作/决策",
          "天权": "L2 模型", "玉衡": "验收与监督", "开阳": "工程实施",
          "瑶光": "数据追溯"}[k],
         str(len([f for f in feats if f["array"] == k]))]
        for k, v in ARRAYS.items()
    ], widths=[3.5, 1.4, 6, 3.5, 1.5], y=Inches(1.45), size=11.5, row_h=0.56)

    # 9 六层
    s = d.slide("六层架构：上层给意图，L2 收口", "新能力通过 L2 闸门接入，不改上层契约")
    d.table(s, ["层", "职责", "关键功能"], [
        ["L4 任务规划", "场景编排、异步多机台调度", "OP-10 异步看管 · CF-29 调度 · CF-30 优先级"],
        ["L3 技能编排", "状态机分段、原子技能、失败重试", "CF-27 阶段调制 · CF-28 失败分类 · CF-31 自恢复"],
        ["L2 决策与收口", "动作生成 + 世界模型 + 约束收口", "MA-01~03 双脑 · MA-20 势场约束"],
        ["L1 感知", "视觉/力觉/触觉融合、状态向量", "CF-01~16 · MA-04 状态向量"],
        ["L0 执行", "臂、夹爪、AMR、力控", "CF-17~26 动作 · CF-41~48 硬件"],
        ["数据闭环", "采集 → 训练 → 评估 → 部署", "MA-09 进化闭环 · MA-15 数据闭环"],
    ], widths=[3, 6, 8], y=Inches(1.5), size=12.5, row_h=0.6)
    d.note(s, "代价：L2 必须真的每帧被调用，不能是「画在图上、实际空口」——这条要单独取证。", Inches(5.6))

    # 10 功能清单总览
    s = d.slide("功能清单：165 条 × 三阶段", "EVT 121 条 P0 优先")
    d.table(s, ["阵位", "功能数", "P0", "P1", "P2", "三阶段齐全"],
            [[v["full"],
              str(len([f for f in feats if f["array"] == k])),
              str(len([f for f in feats if f["array"] == k and f["priority"] == "P0"])),
              str(len([f for f in feats if f["array"] == k and f["priority"] == "P1"])),
              str(len([f for f in feats if f["array"] == k and f["priority"] == "P2"])),
              str(len([f for f in feats if f["array"] == k and f["n_stage"] == 3]))]
             for k, v in ARRAYS.items()],
            widths=[5, 2, 1.6, 1.6, 1.6, 3], y=Inches(1.45), size=12.5, row_h=0.56)
    d._text(s, Inches(0.65), Inches(6.0), Inches(12), Inches(0.5),
            "配套 Excel《Z700_功能清单_EVT_DVT_PVT.xlsx》17 个工作表：全量主表（可筛选）+ 七阵分视图 + 三阶段视角 + 性能指标 + 负载计算 + 国标引用",
            12, False, LGREY)

    # ── EVT ──
    d.section("01", "EVT 工程原型验证", "完整功能开发，具备用户演示能力")

    s = d.slide("EVT 的判据：能不能演出来", "不是「代码写完了」，而是当着客户面跑一遍，每次都能复现")
    d.bullets(s, [
        "每条功能都要写成「已实现 · 演示 X 次」这样一种可验证的形态",
        "演示环境 = ar3d 场景 + 真机，两者状态要能对上",
        "场景里的游标跟着真机走，甘特条光标同步移动",
        "对照的是状态与真值，不是动画好不好看",
    ], size=16, gap=0.66)
    d.table(s, ["演示", "内容", "通过标准"], [
        ["D1 单点插拔", "取料 → 对位 → 插入 → 拉出 → 分拣", "连续 20 次一次通过"],
        ["D2 全链回放", "215 点完整动作链", "单轮跑完，误差全部 ≤0.6°"],
        ["D3 双臂并行", "左右臂按元任务节拍协同", "节拍达成，左臂不越界"],
        ["D4 换型", "QSFP-DD → OSFP → SFP 切换", "每次 ≤30min，换后首件通过"],
    ], widths=[3, 7, 5], y=Inches(4.2), size=12.5, row_h=0.5)

    # ── DVT ──
    d.section("02", "DVT 设计验证", "环境适应性标定")

    s = d.slide("DVT：七类扰动下判据不降级", "车间不是恒温恒湿实验室")
    d.table(s, ["类别", "量级 / 范围", "判据"], [
        [e["item"], e["range"], e["criteria"]] for e in met["env_matrix_dvt"]
    ], widths=[2.5, 6, 7], y=Inches(1.45), size=10.5, row_h=0.44)
    d._text(s, Inches(0.65), Inches(6.7), Inches(12), Inches(0.4),
            "标定项：手眼 / TCP / 工件坐标系 / AOI 双路外参 / 力传感器零点 / 光照基准", 11.5, False, LGREY)

    # ── PVT ──
    d.section("03", "PVT 生产验证", "适应生产流程")

    s = d.slide("PVT：连续 72h / ≥5000 次", "看的不再是单次动作，而是能不能一直做下去")
    d.table(s, ["项目", "要求", "判据"], [
        [e["item"], e["range"], e["criteria"]] for e in met["pvt_matrix"]
    ], widths=[2.8, 6, 6.5], y=Inches(1.45), size=10.5, row_h=0.44)

    # ── 数据 ──
    d.section("04", "实测数据", "本次真机 215 点采集")

    s = d.slide("实测性能：215 点全到位", "run replay215_20261115_225309")
    d.kpis(s, [
        ("215/215", "点", "全部到位", GREEN),
        ("%.2f" % perf["measured_total_s"], "s", "纯运动耗时", BLUE),
        ("%.3f" % perf["s_per_point"], "s/点", "单点平均", LBLUE),
        ("%.2f°" % (M("单点到位误差(关节角)") or 0), "最大误差", "0 个超差", GREEN),
    ], y=Inches(1.4), h=Inches(1.5))
    d.table(s, ["项", "数值", "说明"], [
        ["采集起止", "14:52:59 → 15:00:18", "墙钟 438.9s"],
        ["全程 TCP 路程", "%.1f mm" % perf["tcp_path_mm"], "逐点位移求和"],
        ["平均线速度", "%.2f mm/s" % perf["speed_mm_s"], "含启停"],
        ["速度利用率", "%.1f%%" % (M("速度利用率") or 0), "相对计划速度 60mm/s"],
        ["到位误差 平均", "%.3f °" % (M("到位误差平均值") or 0), "关节角"],
        ["超差点", "0 个", "全部 ≤0.6°"],
    ], widths=[4, 4, 6], y=Inches(3.3), size=12, row_h=0.45)

    s = d.slide("14 段甘特：瓶颈在哪", "实测逐点求和，不是按点数均分")
    top = sorted(gon, key=lambda r: -float(r[3]))[:8]
    d.table(s, ["段", "区间", "点数", "耗时(s)", "占比", "s/点"],
            [r[:6] for r in top], widths=[4, 2.5, 1.5, 2, 1.8, 1.8],
            y=Inches(1.45), size=12, row_h=0.5)
    d._text(s, Inches(0.65), Inches(5.9), Inches(12), Inches(0.9),
            "前三段（转运/举升 25.2% + 表面检测 16.7% + 扫码 14.6%）= 56.5%。\n"
            "瓶颈是大范围运动与多姿态检测，不是点数最多的插入段（1.70 s/点，反而更快）。",
            14, True, NAVY, line_spacing=1.5)

    s = d.slide("两套口径必须分清，不能混算", "混算就会得出不存在的节拍")
    d.table(s, ["口径", "单点/单件", "一轮", "UPH", "来源"], [
        ["录制真值（物理记录）", "0.199 s/点", "42.85 s", "84.0", "frames[].t，5Hz 录制"],
        ["实跑真值（单臂逐点）", "%.3f s/点" % perf["s_per_point"],
         "%.2f s" % perf["measured_total_s"], "%.2f" % perf["uph_single_arm"], "本次 215 点实测"],
        ["双臂并行（仿真口径）", "11.37 s/件", "11.37 s", "%.1f" % perf["dual_arm_uph"],
         "392 段 / 159.15s / 14 件"],
    ], widths=[4.5, 3, 2.5, 2, 5], y=Inches(1.5), size=12.5, row_h=0.6)
    d.note(s, "逐点比录制慢 10 倍的原因：控制器只接受逐条 append + 逐条 moveStart，每点固定开销 ~0.33s。",
           Inches(4.0))
    d.bullets(s, [
        "提速出路不是调速度参数，而是减少启停次数或换连续插补",
        "连续插补（多条 append + 单次 moveStart）已被 -60611 + 急停证伪，需重新设计",
    ], y=Inches(5.0), size=14, gap=0.55)

    # ── 标准与安全 ──
    d.section("05", "标准与安全", "引用国标要落到具体位置")

    s = d.slide("标准符合性（摘）", "不做「符合国标」这种泛泛承诺")
    d.table(s, ["标准号", "名称", "落点"], [
        ["GB 5226.1-2019", "机械电气安全 通用技术条件", "电柜、接地 ≤4Ω、急停回路"],
        ["GB 11291.1/2", "工业机器人 安全要求 1/2", "本体安全、集成安全距离、围栏光幕"],
        ["GB/T 36008-2018", "协作机器人 安全要求", "人机协作功率与力限制"],
        ["ISO 13849-1", "安全相关控制系统", "PLd 达成证明、急停 ≤500ms"],
        ["GB/T 12642-2013", "工业机器人 性能规范及试验", "重复定位 ±0.02mm 测试方法"],
        ["ANSI/ESD S20.20", "静电敏感器件防护", "接地 ≤4Ω、静电场 ≤100V、离子风"],
        ["ISO 14644-1", "洁净室分级", "ISO Class 7 发尘量评估"],
        ["GB/T 2423.x", "环境试验", "DVT 温湿度/振动试验"],
    ], widths=[3.5, 6, 7], y=Inches(1.45), size=11.5, row_h=0.5)

    s = d.slide("安全四道闸，全在 L2 收口", "上层可以说「我要插」，不能说「别管力」")
    d.table(s, ["闸", "触发条件", "动作", "响应"], [
        ["1 力限", "插入力 > 40N（金手指 > 2N）", "立即停止并退让", "≤10ms"],
        ["2 碰撞", "异常碰撞力 / 电流突变", "停止 + 反向退让 100mm", "≤10ms"],
        ["3 区域", "光幕遮挡 / 人手进入", "降速 50% 或停止", "≤100ms"],
        ["4 急停", "急停按钮 / 软件急停", "双回路断电停机", "≤500ms"],
    ], widths=[2, 6, 6, 2.5], y=Inches(1.6), size=13.5, row_h=0.7)

    # ── 商业 ──
    d.section("06", "投资回报与实施", "回收期 ≤2 年是客户决策的底线")

    s = d.slide("投资回报", "必须按「1 机看管 2 台 + 两班倒」卖")
    d.table(s, ["替代模式", "售价", "年省人工", "回收期", "结论"], [
        ["单班替代（1 人）", "35 万", "12-15 万", "2.3-2.9 年", "偏长"],
        ["两班替代（2 人）", "35-45 万", "24-30 万", "1.2-1.9 年", "可接受"],
        ["三班 + 良率提升", "45 万", "36+ 万", "<1.3 年", "最优"],
    ], widths=[4, 2.5, 3, 3, 2.5], y=Inches(1.5), size=13, row_h=0.6)
    d.kpis(s, [
        ("24-40", "万", "整机成本", BLUE),
        ("35-50", "万", "目标售价", LBLUE),
        ("30-40", "%", "毛利率", GREEN),
    ], y=Inches(4.0), h=Inches(1.35))
    d.note(s, "只有把异步能力用起来，回收期才能压到 2 年以内，工厂决策层才会批。", Inches(5.7))

    s = d.slide("实施计划：24 周六个里程碑", "三阶段与里程碑对齐")
    d.table(s, ["里程碑", "时间", "内容", "验收节点"], [
        ["M1", "T0+4w", "硬件平台集成（臂+AMR+夹爪+力觉）", "运动学标定报告"],
        ["M2", "T0+8w", "感知融合 + 双脑训练 + 手眼/AOI 标定", "checkpoint + 8/8·7/8"],
        ["M3", "T0+12w", "原子技能库 + 状态机；EVT 演示", "D1-D4 全过"],
        ["M4", "T0+16w", "异步双机台 + 大屏监督 + DVT", "节点 A：≤30s/颗 · ≥99%"],
        ["M5", "T0+20w", "节拍优化 + PVT 试产 + 换型验证", "节点 B：≤15s/颗 · 72h 5000 次"],
        ["M6", "T0+24w", "方案交付 + 系统验收 + 能力证书", "五场景验收通过"],
    ], widths=[2, 2.5, 7, 5], y=Inches(1.45), size=12, row_h=0.55)

    # 收尾
    s = d.slide("三件需要决策的事", "其余可以按计划推进")
    d.bullets(s, [
        "两班倒销售模式 —— 这是回收期 ≤2 年的前提，也是产品定价的锚",
        "手眼与 AOI 外参标定必须 M2 前完成 —— 否则料盘视觉识别这条能力无法验收",
        "连续插补提速方案需单独立项验证 —— 已被一次急停证伪，不能再拿生产机器试",
    ], size=16, gap=0.85)
    d._text(s, Inches(0.65), Inches(5.6), Inches(12), Inches(0.9),
            "其余 165 条功能已按 EVT / DVT / PVT 拆好，判据、国标、证据来源齐备。",
            15, False, LGREY)

    p = os.path.join(OUT, "05_Z700_解决方案汇报.pptx")
    d.save(p)
    return p, d.n


if __name__ == "__main__":
    p, n = build()
    print(json.dumps({"ok": True, "out": p, "slides": n,
                      "size_kb": round(os.path.getsize(p) / 1024)}, ensure_ascii=False))
