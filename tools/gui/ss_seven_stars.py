#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_seven_stars.py — 状态空间工程 · 北斗七星阵配置体系 (配置中心的「阵」数据 + 顶部阵图条)。

老倪 2026-10-15:
  「改变配置中心左侧窗口的排列顺序 …… 1.产品配置 2.任务配置 3.功能配置 4.模型配置 5.性能配置 6.工单配置 7.文档配置,
   注意前面要显示一个序号。这里有一个隐藏思想, 北斗七星阵 —— 我的状态空间工程, 实际上是一个阵法, 是有完备的结构的。
   …… 将这个思想, 贯穿配置中心, 在每个配置中心打开的主页面的最上顶部, 写上这样的说明, 你来设计 UI」

设计 (只做真结构, 不做装饰):
  ① 七类配置 = 七颗星, 次序/别号/主司/**定义**/**关系** 全部留在这一个数据模块里 (唯一真源, 页面与左树共用);
  ② 每页最顶一条**阵图条**: 「一、产品配置 · 天枢(贪狼)」 + 该星一句 + 定义 + 关系 + 五行色 + 定什么;
  ③ 阵图条第 4 行是**七星星图**, 当前页那颗高亮, 点别的星就跳到那一页 (真联动, 不是画着好看);
  ④ 不是七星的页 (工程库/文档预览/模型匹配这类视图) 显示**阵法总览** (序 + 七阵联动), 并如实说明它不属于七星。

为什么 7 而不是 8: 北斗七星是完备结构 ⇒ 左树顶层就是 7 项。原有「工程配置」域不再单列顶层,
  作为「功能配置·天玑(定能力)」下的**第 4 特征域**入口保留 (功能没丢, 只是归位)。

五行色 (给阵法一条可解释的视觉线索, 不是随手配色):
  贪狼木 / 巨门水 / 禄存土 / 文曲水 / 廉贞火 / 武曲金 / 破军水 —— 星色即五行色。
"""
from __future__ import annotations

# ── 七颗星 (次序 = 左树次序 = 配置体系的传导次序) ─────────────────────────────────
STARS = (
    dict(idx=1, key="prod", no_cn="一", name="产品配置", star="天枢", alias="贪狼",
         role="主引领、主导", bind="定边界", wuxing="木", color="#4ea36b",
         q="天枢为北斗第一星，又称贪狼，主引领、主导。",
         define="产品配置定义整个工程对外提供的产品形态。包括机器人型号、硬件选型、应用场景范围、交付边界。"
                "产品配置回答“交付的是什么”。",
         rel="产品配置为其他六类配置提供顶层约束。任何功能、任务、性能指标，都必须在产品配置确定的范围内。",
         tab="产品配置"),
    dict(idx=2, key="task", no_cn="二", name="任务配置", star="天璇", alias="巨门",
         role="主沟通、传达", bind="定作业", wuxing="水", color="#4a90e0",
         q="天璇为北斗第二星，又称巨门，主沟通、传达。",
         define="任务配置定义每一项具体作业任务。包括任务名称、工序步骤、启用功能、参数覆盖、触发条件、循环方式。",
         rel="任务配置回答“要完成什么作业”。任务配置从产品配置继承边界，从功能配置选择能力，向性能配置提出指标要求。",
         tab="任务配置"),
    dict(idx=3, key="func", no_cn="三", name="功能配置", star="天玑", alias="禄存",
         role="主承载、执行", bind="定能力", wuxing="土", color="#c9a227",
         q="天玑为北斗第三星，又称禄存，主承载、执行。",
         define="功能配置定义每一个独立功能单元。包括功能名称、输入输出、参数定义、依赖关系、验证方法、归属层级。",
         rel="功能配置回答“具备什么能力”。功能配置是任务配置的积木，任务通过选择功能子集并覆盖参数来完成配置。",
         tab="功能·性能·模型"),
    dict(idx=4, key="model", no_cn="四", name="模型配置", star="天权", alias="文曲",
         role="主智慧、变化", bind="定算法", wuxing="水", color="#5aa9d6",
         q="天权为北斗第四星，又称文曲，主智慧、变化。",
         define="模型配置定义每一个算法模型。包括模型类型、推理框架、权重文件、输入输出格式、算力要求、更新方式。",
         rel="模型配置回答“用什么算法实现”。模型配置服务于功能配置，功能通过模型配置获得实际计算能力。",
         tab="模型配置"),
    dict(idx=5, key="perf", no_cn="五", name="性能配置", star="玉衡", alias="廉贞",
         role="主衡量、权衡", bind="定指标", wuxing="火", color="#d1604a",
         q="玉衡为北斗第五星，又称廉贞，主衡量、权衡。",
         define="性能配置定义所有可量化指标。包括节拍、成功率、精度、力控范围、连续运行时间、损伤标准。",
         rel="性能配置回答“达到什么水平”。性能配置为任务配置提供验收依据，为功能配置提供参数边界。",
         tab="功能·性能·模型"),
    dict(idx=6, key="order", no_cn="六", name="工单配置", star="开阳", alias="武曲",
         role="主调度、执行", bind="定调度", wuxing="金", color="#c8b06a",
         q="开阳为北斗第六星，又称武曲，主调度、执行。",
         define="工单配置定义每一次实际作业的调度信息。包括工单编号、产品型号、数量、批次、设备分配、开始时间、结束时间、状态流转。",
         rel="工单配置回答“谁在什么时候做什么”。工单配置从任务配置生成，从性能配置获取验收标准，从文档配置获取追溯依据。",
         tab="工单配置"),
    dict(idx=7, key="doc", no_cn="七", name="文档配置", star="瑶光", alias="破军",
         role="主记录、收束", bind="定记录", wuxing="水", color="#6f7fd0",
         q="瑶光为北斗第七星，又称破军，主记录、收束。",
         define="文档配置定义所有交付文档与记录。包括操作手册、维护手册、验收报告、测试记录、变更记录、追溯档案。",
         rel="文档配置回答“留下了什么记录”。文档配置为其他六类配置提供归档、追溯与审计依据。",
         tab="文档交付"),
)

BY_KEY = {s["key"]: s for s in STARS}
BY_NAME = {s["name"]: s for s in STARS}

# ── 阵法总览 (非七星视图用; 与 paste_7 序/联动两段一致) ───────────────────────────
OVERVIEW = dict(
    title="北斗七星阵 · 状态空间工程配置体系",
    q="北斗七星由天枢、天璇、天玑、天权、玉衡、开阳、瑶光七星组成，古称“斗柄”，指向北极，定四时，辨方位。"
      "七星各司其位，共同构成一个完整的导航与定序系统。",
    define="状态空间工程同样需要一个完整的结构来定方向、定次序、定职责。将七类配置映射为北斗七星，"
           "形成一个自洽的配置体系，使工程实践有章可循。",
    rel="七阵联动：产品配置定边界 · 任务配置定作业 · 功能配置定能力 · 模型配置定算法 · 性能配置定指标 · "
        "工单配置定调度 · 文档配置定记录。七类配置相互约束、相互支撑，形成闭环。",
    color="#e0b64a",
)

# ── 页签 → 该页覆盖的星 (子串匹配; 先匹配先生效; 元组第一个 = 打开该页默认显示的星) ──────────
# ⚠️ 一致性口径 (老倪 2026-10-15 实测报错): 页签覆盖多颗星时, **只点亮当前那一颗** ——
#    点天玑就只亮天玑, 点玉衡就只亮玉衡。原来"一页三星全亮"是错的(点天玑时天权/玉衡跟着亮),
#    因为"这页装着三颗星"≠"这三颗星同时是当前星"。
TAB_STAR_RULES = (
    ("产品配置", ("prod",)),
    ("任务配置", ("task",)),
    ("功能·性能·模型", ("func", "perf", "model")),   # 一页三星: 功能/性能/模型 共用
    ("功能配置", ("func",)),
    ("性能配置", ("perf",)),
    ("模型配置", ("model",)),
    ("模型匹配", ("model",)),
    ("工单配置", ("order",)),
    ("文档交付", ("doc",)),
    ("文档预览", ("doc",)),
)

# ── 不属于七星的视图: 如实说明它是什么 (不硬塞进阵法) ─────────────────────────────
EXTRA_VIEWS = (
    ("工程配置", "「工程配置」是**工程库视图**（工程文件 / 参数注册表 / 工程-模型匹配），"
               "它是七阵共同依赖的工程容器（真源 zmax/sources/），不在北斗七星之列。"),
    ("模型匹配", "「模型匹配」是**模型↔工程/任务的匹配校验视图**，属于天权·模型配置的执行明细。"),
    ("文档预览", "「文档预览」是天瑶光·文档配置的正文预览，属于七星。"),
)


def keys_for_tab(title):
    """页签标题 → 该页覆盖的星 key 元组 (取不到返回 ())。"""
    t = str(title or "")
    for sub, keys in TAB_STAR_RULES:
        if sub in t:
            return tuple(keys)
    return ()


def star_for_tab(title):
    """页签标题 → 该页**默认**显示的星 dict (取不到返回 None ⇒ 显示阵法总览, 不猜)。"""
    keys = keys_for_tab(title)
    return BY_KEY[keys[0]] if keys else None


def extra_note_for_tab(title):
    """非七星视图的如实说明 (取不到返回 "")。"""
    t = str(title or "")
    for sub, note in EXTRA_VIEWS:
        if sub in t:
            return note
    return ""


def focus_keys_for_tab(title, focus_key=None):
    """本页当前要亮的那**一颗**星 (老倪: 点天玑就只亮天玑)。

    一页覆盖多颗星时 (功能·性能·模型): 用 focus_key 指定当前这颗; 不指定 / 指定了不属于本页的星,
    就取本页默认星 (keys[0])。**绝不一次亮多颗** —— 那是"这页装着几颗星", 不是"当前是哪颗星"。
    """
    keys = keys_for_tab(title)
    if not keys:
        return ()
    return (focus_key if focus_key in keys else keys[0],)


def star_line(key):
    """左树/标题用的短名: 「N. 名称 · 星名」 (序号在最前 —— 老倪要求)"""
    s = BY_KEY.get(key)
    return "%d. %s · %s" % (s["idx"], s["name"], s["star"]) if s else ""


# ── UI: 阵图条 ────────────────────────────────────────────────────────────────
def _lbl(text, color, size=10, bold=False, wrap=True, parent=None):
    from PyQt5.QtWidgets import QLabel, QSizePolicy
    from PyQt5.QtGui import QFont
    from PyQt5.QtCore import Qt
    w = QLabel(text, parent)
    f = QFont("Arial", size)
    f.setBold(bool(bold))
    w.setFont(f)
    w.setStyleSheet("color:%s;background:transparent;" % color)
    w.setWordWrap(wrap)
    w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # 不按全文撑宽 ⇒ 顶栏按钮不被挤出去
    w.setMinimumWidth(0)
    w.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)   # 可选中可复制
    return w


class StarBanner(object):
    """阵图条 (构造式, 不是 QWidget 子类 —— 便于在不装 Qt 的环境里做纯数据判据)。

    用 build_banner(th, on_chip) 得到 QWidget; 之后调 set_tab(title) 让整条跟着页签走。
    """

    def __init__(self, th, on_chip=None, on_expand=None):
        self.th = th
        self.on_chip = on_chip
        self.on_expand = on_expand
        self._build()

    # ── 构建 ──
    def _build(self):
        from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QPushButton,
                                     QSizePolicy, QLabel)
        from PyQt5.QtGui import QFont
        th = self.th
        self.w = QWidget()
        self.w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        v = QVBoxLayout(self.w)
        v.setContentsMargins(10, 7, 10, 7)
        v.setSpacing(3)

        # 行 1: 左竖色条 + 标题 + 别号/五行 + 定什么 (右)
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        self.bar = QFrame()
        self.bar.setFixedWidth(4)
        self.bar.setStyleSheet("background:%s;border:none;" % th["C_YELLOW"])
        r1.addWidget(self.bar)
        self.t_title = _lbl("", th["C_WHITE"], 11, True, wrap=False)
        r1.addWidget(self.t_title)
        self.t_meta = _lbl("", th["C_GRAY"], 9, False, wrap=False)
        r1.addWidget(self.t_meta)
        r1.addStretch()
        self.t_bind = _lbl("", th["C_YELLOW"], 10, True, wrap=False)
        r1.addWidget(self.t_bind)
        v.addLayout(r1)

        # 行 2: 该星一句
        self.t_q = _lbl("", th["C_WHITE"], 10, wrap=True)
        v.addWidget(self.t_q)
        # 行 3: 定义 + 关系 (合成一段, 用 · 分段, 不截断)
        self.t_def = _lbl("", th["C_GRAY"], 9, wrap=True)
        v.addWidget(self.t_def)
        # 行 3b: 非七星视图的如实说明 (平时隐藏)
        self.t_note = _lbl("", th["C_YELLOW"], 9, wrap=True)
        self.t_note.hide()
        v.addWidget(self.t_note)

        # 行 4: 七星星图 (点击跳页)
        r4 = QHBoxLayout()
        r4.setSpacing(4)
        self.chips = {}
        for s in STARS:
            b = QPushButton("%s%s" % (_circ(s["idx"]), s["star"]), self.w)
            b.setFont(QFont("Arial", 9))
            b.setCursor(b.cursor())
            b.setFlat(True)
            b.setToolTip("%s、%s · %s（%s）— %s\n%s\n%s"
                         % (s["no_cn"], s["name"], s["star"], s["alias"], s["role"], s["q"], s["define"]))
            b.clicked.connect(lambda _, k=s["key"]: (self.on_chip and self.on_chip(k)))
            self.chips[s["key"]] = b
            r4.addWidget(b)
        r4.addStretch()
        self.t_tail = _lbl("斗柄指极 · 定四时 · 辨方位", th["C_GRAY"], 9, False, wrap=False)
        r4.addWidget(self.t_tail)
        v.addLayout(r4)

        self.w.setStyleSheet("QWidget{background:%s;border:1px solid %s;}"
                            % (th["C_BG2"], th["C_BORDER"]))
        self.set_tab("")

    # ── 更新 ──
    def _paint_chips(self, focus=()):
        """点亮 focus 里的星; 其余星保持可点但不抢眼 (含五行色描边, 有语义)。"""
        th = self.th
        focus = tuple(focus or ())
        for k, b in self.chips.items():
            s = BY_KEY[k]
            on = k in focus
            b.setStyleSheet(
                "QPushButton{background:%s;color:%s;border:1px solid %s;border-radius:9px;padding:1px 8px;}"
                % (s["color"] if on else "transparent",
                   "#0b0f14" if on else th["C_GRAY"],
                   s["color"]))
            b.setToolTip("%s、%s · %s（%s）%s\n%s\n%s\n五行·%s"
                         % (s["no_cn"], s["name"], s["star"], s["alias"],
                            "  ← 当前页" if on else "", s["q"], s["define"], s["wuxing"]))

    def set_tab(self, title, focus_key=None):
        """按当前页签刷新整条 (七星页 → **当前这一颗星**的说明; 非七星页 → 阵法总览 + 如实说明)。

        focus_key: 一页多星时用户当前点的那颗 (点天玑=func / 点玉衡=perf); 不传则用本页默认星。
        """
        th = self.th
        keys = keys_for_tab(title)
        s = BY_KEY[focus_key] if (keys and focus_key in keys) else star_for_tab(title)
        note = extra_note_for_tab(title)
        if s is not None:
            self.t_title.setText("%s、%s · %s（%s）" % (s["no_cn"], s["name"], s["star"], s["alias"]))
            self.t_meta.setText("五行·%s · %s · 配置中心第 %d 阵" % (s["wuxing"], s["role"], s["idx"]))
            self.t_q.setText(s["q"])
            self.t_def.setText("%s  %s" % (s["define"], s["rel"]))
            self.t_bind.setText(s["bind"])
            self.bar.setStyleSheet("background:%s;border:none;" % s["color"])
            self.t_bind.setStyleSheet("color:%s;background:transparent;" % s["color"])
        else:
            o = OVERVIEW
            self.t_title.setText(o["title"])
            self.t_meta.setText("七类配置 · 定方向 · 定次序 · 定职责")
            self.t_q.setText(o["q"])
            self.t_def.setText("%s  %s" % (o["define"], o["rel"]))
            self.t_bind.setText("北斗所指 · 工程所向")
            self.bar.setStyleSheet("background:%s;border:none;" % o["color"])
            self.t_bind.setStyleSheet("color:%s;background:transparent;" % o["color"])
        if note:
            self.t_note.setText("说明：" + note)
            self.t_note.show()
            self._note_on = True
        else:
            self.t_note.hide()
            self._note_on = False
        self._paint_chips(focus_keys_for_tab(title, focus_key))

    # ── 判据用 (纯文本快照, 不依赖截图) ──
    def snapshot(self):
        return dict(title=self.t_title.text(), meta=self.t_meta.text(), q=self.t_q.text(),
                    define=self.t_def.text(), bind=self.t_bind.text(),
                    note=self.t_note.text() if getattr(self, "_note_on", False) else "",
                    lit=[k for k, b in self.chips.items() if "transparent" not in b.styleSheet()],
                    chips=[b.text() for b in self.chips.values()])


def _circ(n):
    """1..7 → ①②③④⑤⑥⑦"""
    return "①②③④⑤⑥⑦⑧⑨"[(n - 1) % 9]
