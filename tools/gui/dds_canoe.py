#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 全局数据空间 —— CANoe 主窗口范式 (2026-09-29 老倪「参考 Vector CANoe demo 重新设计 UI」)

版式**照 CANoe 16 主界面逐像素基准**(子代理读官方截图所得):
  · 顶部测量组 (CANoe: Start 黄闪电 / Stop 灰八边形 / Step / Online Mode / dec|hex|sym|num)
  · 上排左 **Data 面板 = 信号表**  (CANoe 列: Name | Value | Unit | Last Value Time [s] | Bar)
  · 上排右 详情/判据面板
  · 中 **Trace 整宽** (CANoe 列: Time | Name | Object Type | Classification | Probability [%] |
                        Sender Name | Sender Id | Tracking Id | Group) + 面板工具条(⏸/Δt/🔍/🗑/导出)
  · 底 标签栏 (CANoe: Configuration | Measurement | Data Window) → 质量告警 + 右下计时/拍照
    (🗑 2026-10-17 老倪: 「全局数据空间, 删除 数据闭环 页面」⇒ 闭环页签已删;
     只留质量告警 —— 闭环门本来就是质量判据的一部分, 数据面不再单开一页)
数据全真实: busdb.json(画布 DBC 74节点/182信号/14报文) · live.json(每话题质量) ·
trace.jsonl(总线帧)。缺测一律 '—' (不许 0 冒充); 实时量带帧龄与拍照时间。
busdb 的真源是**状态空间工程库**(mw_*) —— 画布保存时同口落库, 数据空间只读库, 不再另抄一份。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "src"))
try:                                     # 话题 → 信号清单 (实测/声明/画布/占位 四级证据)
    from lerobot.middleware import signals as _signals
except Exception:                                                        # noqa: BLE001
    class _SG:
        @staticmethod
        def signals_of(topic):
            return [("value", "", "占位")]
    _signals = _SG()

try:                                     # 中文短名 / DDS 标准 QoS 显示
    from lerobot.middleware import cn_names as _cn_names
    from lerobot.middleware import signal_en as _signal_en
    from lerobot.middleware import attribution as _attrib
    from lerobot.middleware import qos_names as _qos_names
except Exception:                                                        # noqa: BLE001
    class _CN:
        @staticmethod
        def cn_of(topic, port=""):
            return str(topic or "").split("/")[-1][:5]

        @staticmethod
        def cn_of_node(nid, fallback=""):
            return (fallback or str(nid))[:5]
    class _QN:
        @staticmethod
        def standard(qos):
            return str(qos or "—")
    _cn_names, _qos_names = _CN(), _QN()

try:                                     # 物理量质检 (质量告警真依据)
    from lerobot.middleware import quality as _quality
except Exception:                                                        # noqa: BLE001
    class _QualityFallback:
        @staticmethod
        def check_field(name, value, unit=None, vmin=None, vmax=None):
            return "unknown", ""

        @staticmethod
        def scan_frames(frames, jump_span=10.0):
            return []
    _quality = _QualityFallback()

try:                                     # 节点名归一 (Tx/Rx 只放本名)
    from lerobot.middleware import naming as _naming
except Exception:                                                        # noqa: BLE001
    class _NamingFallback:                       # 兜底: 至少有 clean/unique_map 两个口
        @staticmethod
        def clean(x, fallback=""):
            return str(x or fallback)

        @staticmethod
        def unique_map(pairs):
            return {k: v for k, v in pairs}
    _naming = _NamingFallback()

from PyQt5.QtCore import Qt, QRectF, QTimer
from PyQt5.QtGui import QColor, QFont, QGuiApplication, QPainter
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QPushButton, QSplitter, QStyledItemDelegate, QTableWidget,
                             QTableWidgetItem, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                             QWidget)

# ── 调色板(与控制台主色一致) ──
C_BG, C_BG2, C_CARD, C_BORDER = "#0d1117", "#161b22", "#1c2333", "#30363d"
C_WHITE, C_GRAY, C_DIM, C_BLUE = "#ffffff", "#8b949e", "#6e7681", "#58a6ff"
C_HEAD = "#b6c2cf"          # 表头文字: 原 #8b949e 在表头条上仅 5.1:1(质检最弱文本) → 提亮  # C_DIM 提亮: 原 #484f58 对比度仅 2.3:1(质检: 几乎看不见)
C_GREEN, C_YELLOW, C_RED, C_PURPLE = "#3fb950", "#d29922", "#f85149", "#bc8cff"
C_BAR = "#2f81f7"     # CANoe 的 Bar 是实心蓝 #0072C5, 深色主题里提亮
C_SEL = "#243a52"     # CANoe 选中行浅蓝 #AFD7F1 的深色对应

DS_DIR = os.environ.get("ZMAX_DATASPACE_DIR", "/home/ubuntu/zmax/zmax_data/dataspace")
LIVE, TRACE = os.path.join(DS_DIR, "live.json"), os.path.join(DS_DIR, "trace.jsonl")
LOOP, BUSDB = os.path.join(DS_DIR, "loop.json"), os.path.join(DS_DIR, "busdb.json")

LV_COLOR = {"L5": C_PURPLE, "L4": C_BLUE, "L3": "#2fc4b2", "L2": C_GREEN, "meta": C_GRAY}
VERDICT_COLOR = {"ok": C_GREEN, "pass": C_GREEN, "warn": C_YELLOW, "fail": C_RED,
                 "unknown": C_GRAY, "stale": C_YELLOW}
LAMP_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴", "black": "⚫"}
MONO, UI = "Consolas", "Arial"


def _j(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                        # noqa: BLE001
        return default if default is not None else {}


def _blank(v):
    """缺测(-1/-1.0/None/空) → '—' (全空间统一: 不许用 0 冒充)"""
    if v is None or v == "":
        return "—"
    try:
        if isinstance(v, (int, float)) and float(v) < 0:
            return "—"
    except Exception:                                                        # noqa: BLE001
        pass
    return v


def _num(v, nd=2, suffix=""):
    v = _blank(v)
    if v == "—":
        return "—"
    try:
        return f"{float(v):.{nd}f}{suffix}"
    except Exception:                                                        # noqa: BLE001
        return f"{v}{suffix}"


def _short_val(v, keep=3):
    """详情面板里把"长序列"折成一行 —— 否则 ss_plan 的 joints_path(768 个数) 会把 24 个字段名额占满,
    真正要看的 n_points / end_err_mm / gate_* 全被挤出去。"""
    if isinstance(v, (list, tuple)) and len(v) > keep * 2:
        body = ", ".join(("%.4g" % x) if isinstance(x, float) else str(x) for x in list(v)[:keep])
        return "[%s, …] (共 %d 个)" % (body, len(v))
    return str(v)


def _pad(label, width=14):
    """中文按 2 列宽补齐 → 详情面板的值列能对齐成一竖线(质检: 破折号 x2560-2576 漂移)"""
    w = sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(label))
    return str(label) + " " * max(1, width - w)


def _hhmmss(t):
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(t)))
    except Exception:                                                        # noqa: BLE001
        return "—"


def _rel(t0, t):
    """相对测量起点的秒 (CANoe Trace 的 Time 列 = 测量时间, 3 位小数)"""
    try:
        return "%9.3f" % (float(t) - float(t0))
    except Exception:                                                        # noqa: BLE001
        return "—"


def _en_name(topic, field):
    """与「信号分析」完全同一个取名函数 (middleware.signal_en.en_of_key)。"""
    try:
        from lerobot.middleware import attribution as _A2
        return _signal_en.en_of_key(_A2.LIVE_PREFIX.get(str(topic), ""), field)
    except Exception:                                                   # noqa: BLE001
        return _signal_en.en_of(field, topic)


def _f3(v):
    """纯数值格式化 — **不能**用 _num(): 那个把负值当"缺测"返回 '—',
    会吃掉 -0.233 这种完全正常的坐标/tcp_path 数值。

    🆕 2026-10-01: 实测 live.json 里 ss_plan.tcp_path[1] = -0.2334 被显示成 '—' ⇒ 加这个。
    """
    try:
        return ("%.3f" % float(v)).rstrip("0").rstrip(".")
    except Exception:                                                           # noqa: BLE001
        return str(v)


class BarDelegate(QStyledItemDelegate):
    """CANoe 的 Bar 列: 实心蓝条 = 实测值 / 设计值, 0 或无量纲不画。"""

    def paint(self, p, opt, idx):
        super().paint(p, opt, idx)
        try:
            ratio = float(idx.data(Qt.UserRole))
        except Exception:                                                    # noqa: BLE001
            ratio = -1.0
        if ratio <= 0:
            return
        r = opt.rect
        w = max(2, int((r.width() - 26) * min(1.0, ratio)))
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C_CARD))                                    # 底轨(质检: 无轨道无法判满格)
        p.drawRoundedRect(QRectF(r.x() + 6, r.y() + r.height() * 0.28,
                                 max(6, r.width() - 26), r.height() * 0.44), 2, 2)
        p.restore()
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C_BAR))
        p.drawRoundedRect(QRectF(r.x() + 4, r.y() + r.height() * 0.28, w, r.height() * 0.44), 2, 2)
        p.restore()


def _sig_type_txt(topic, default=None):
    """topic → 语义类型 (与信号表 Type 列同源: config/platform/dds_topic_types.json)。

    default: 非 ss.node.* 形态的话题 (如连线总线 zmax/link_value) 用它自己声明的类型兜底,
             不要显示成 "— (非节点话题)" —— 连线数据也是有类型的。
    """
    try:
        from lerobot.middleware import topic_types as _tt
        d = _tt.describe(topic)
        t = d.get("type") or default or "—"
        cn = d.get("cn") or ""
        return ("%s  (%s)" % (t, cn)) if (cn and d.get("type")) else t
    except Exception:                                                        # noqa: BLE001
        return default or "—"


class BusView(QWidget):
    """CANoe 范式的多窗格数据空间视图"""

    def __init__(self, main_win=None, parent=None, standalone=False):
        super().__init__(parent)
        self.main = main_win
        self.standalone = bool(standalone)   # 独立窗口模式: 无需主窗口里那套「经典视图」切换
        self._busdb, self._live, self._loop = {}, {}, {}
        self._t0 = None
        self._sel_kind = self._sel_obj = None
        self._trace_rows = []
        self._filter = ""
        self._dt_mode = False
        self.setObjectName("DdsCanoeView")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#DdsCanoeView {{ background:{C_BG}; }}")
        self._build()
        self.reload(force_tree=True)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.reload)
        self._timer.start(800)      # ⚡ 实时: 0.8s 一拍 (老倪要「实时运行」)

    # ─────────────────── 骨架 ───────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        # ✂️ 2026-10-17 老倪: 「数据空间上面的一排字, 档位 拍照 灯 这些字, 有用么? 都删掉;
        #    start stop 按钮也删掉; 只保留一个搜索信号功能, 放在 trace 窗口的按钮区」
        #   ⇒ 顶部测量条整行移除; 搜索统一到 Trace 工具条 (见 _trace_panel)。

        vs = QSplitter(Qt.Vertical)
        vs.setChildrenCollapsible(False)
        hs = QSplitter(Qt.Horizontal)
        hs.setChildrenCollapsible(False)
        hs.addWidget(self._data_panel())
        hs.addWidget(self._detail_panel())
        hs.setStretchFactor(0, 3)
        hs.setStretchFactor(1, 2)
        hs.setSizes([1700, 1000])
        # 🎯 2026-10-17 老倪「信号表这些列要对齐, 字都显示不全, 太乱」——
        #   真根因之一: Data 面板在 3:2 分栏里只有 ~640px, 7 列(其中 Tx/Rx 是中文节点名)根本放不下。
        #   给面板一个**下限宽度**(920px): 窗口够宽时按 3:2, 不够时优先保住信号表, 详情面板让位。
        self._data_panel_widget = hs.widget(0) if hasattr(hs, "widget") else None
        vs.addWidget(hs)
        vs.addWidget(self._trace_panel())
        vs.addWidget(self._bottom_tabs())
        vs.setStretchFactor(0, 3)
        vs.setStretchFactor(1, 3)
        vs.setStretchFactor(2, 2)
        vs.setSizes([760, 720, 470])
        root.addWidget(vs, 1)

    def _panel(self, title, color=C_BLUE):
        box = QFrame()
        box.setStyleSheet(f"QFrame {{ background:{C_BG2}; border:1px solid {C_BORDER}; border-radius:6px; }}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel(title)
        t.setFont(QFont(UI, 10, QFont.Bold))
        t.setStyleSheet(f"color:{color}; background:transparent; border:none;")
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)
        return box, lay, head

    def _sm_btn(self, txt, tip, fn, color=C_GRAY, checkable=False, width=None):
        b = QPushButton(txt)
        b.setFont(QFont(UI, 9))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        if width:
            b.setFixedWidth(width)
        b.setStyleSheet(
            f"QPushButton {{ background:{C_CARD}; color:{color}; border:1px solid {C_BORDER};"
            f" border-radius:4px; padding:4px 10px; }}"
            f"QPushButton:hover {{ border-color:{C_BLUE}; color:{C_WHITE}; }}"
            f"QPushButton:checked {{ color:{C_YELLOW}; border-color:{C_YELLOW}; }}")
        b.clicked.connect(fn)
        return b

    # (顶部测量条已删: Start/Stop/档位/拍照/灯/计时 —— 老倪 2026-10-17)

    def _data_panel(self):
        """CANoe 的 Data 面板: 信号表(Name | Value | Unit | Last Value Time [s] | Bar)"""
        box, lay, head = self._panel("📋 Data", C_BLUE)
        self.chk_only_alive = QCheckBox("只看活报文")
        self.chk_only_alive.setFont(QFont(UI, 9))
        self.chk_only_alive.setStyleSheet(f"color:{C_GRAY}; background:transparent;")
        self.chk_only_alive.stateChanged.connect(lambda *_: self.reload(force_tree=True))
        head.addWidget(self.chk_only_alive)
        head.addWidget(self._sm_btn("展开/收起", "展开或收起 报文/信号/节点 三组", self._toggle_all))
        head.addWidget(self._sm_btn("↺ 列宽", "恢复自动列宽 (手动拖过的宽度会失效)", self._reset_cols))
        _hint = QLabel("Drag · hover")
        _hint.setStyleSheet(f"color:{C_DIM}; background:transparent; border:none;")
        _hint.setFont(QFont(UI, 8))
        _hint.setToolTip("列宽可拖; 单元格放不下的字只是显示省略, 悬停即显示全文 (数据本身不被截断)")
        head.addWidget(_hint)
        self.tree = QTreeWidget()
        # 🧭 2026-10-17 老倪: 「信号表, 增加 Tx Rx 两列」+ 随后「这些列要对齐啊…字都显示不全, 太乱了」
        #   实测病根三条 (改前): ① 7 列列宽和 1122 > 面板 1043 ⇒ 挤压 + 横向滚动;
        #   ② 表头 "Last Value Time [s]" 要 224px 却只给 180 ⇒ 表头自己就被裁;
        #   ③ 数值列左对齐 + 空 Cells, 数字和单位看起来"各在各的" ⇒ 根本对不上。
        #   改法: 短表头(全称进 tooltip) + 按内容定宽(总和 < 面板宽) + 数值右对齐/单位居中
        #        + 单元格 ElideRight 且**每格都带全文 tooltip** (裁的是显示, 不是数据)。
        #   CANoe 原 5 列语义不动, Tx/Rx 接在后面。
        # 🧭 2026-10-17 老倪: 「增加一个 type 列, 显示 topic 的名字; 发送/接收的中文去掉; 控制字数, 简单清晰」
        #   8 列全英文短名: Name(短名) · Type(topic 全名) · Value · Unit · Age s · Bar · Tx · Rx
        self.tree.setColumnCount(8)
        self._cols = ["Name", "Type", "Value", "Unit", "Age s", "Bar", "Tx", "Rx"]
        self._col_tt = ["Name — 短名 (报文=节点.端口 / 连线=源→目的 / 节点=名字)",
                        "Type — topic 的语义类型 (由主要发送节点决定, 例 zmax::FeedforwardAction)",
                        "Value — 实测值 (报文 = 实测 Hz)",
                        "Unit — 单位 (报文 = Hz)",
                        "Age s — 最后一帧距现在多少秒",
                        "Bar — 实测/设计, 满格 = 100%",
                        "Tx — 发送节点 (报文产生者 / 连线源 / 节点发包数)",
                        "Rx — 接收节点 (报文消费者 / 连线目的 / 节点收包数)"]
        _fm = self.tree.fontMetrics() if hasattr(self, "tree") else None
        self.tree.setHeaderLabels(self._cols)
        for _i, _t in enumerate(self._col_tt):
            self.tree.headerItem().setToolTip(_i, _t)
        self.tree.setTextElideMode(Qt.ElideNone)      # 不省略: 列宽按内容算, 放不下横向滚动
        self.tree.setWordWrap(False)
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background:{C_BG}; color:{C_WHITE}; border:none; font-family:{UI}; font-size:9pt; }}"
            f"QTreeWidget::item {{ padding:6px 2px; }}"                        # 行高与 Trace/闭环表齐(质检: 46.5px vs 60px)
            f"QTreeWidget::item:selected {{ background:{C_SEL}; }}"
            f"QHeaderView::section {{ background:{C_CARD}; color:{C_HEAD}; border:none; padding:4px; }}")
        self.tree.setUniformRowHeights(True)
        self.tree.setItemDelegateForColumn(5, BarDelegate(self.tree))
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setMinimumSectionSize(40)
        _fm = self.tree.fontMetrics()
        # 每列至少放得下表头 (实测过 "Last Value Time[s]" 给 180px 就自己裁掉一半)
        # 最小值按**表头实测宽**给 (9pt 下 7 列合计 631px ⇒ 640px 宽的 Data 面板正好放得下, 表头永不裁)
        # 🐛 必须在样式表(polish)之后量, 否则量的是默认字体的宽度 ⇒ 列比表头还窄 (实测 Value/Unit/Bar 又被裁)
        self.tree.ensurePolished()
        _fm = self.tree.header().fontMetrics()
        self._col_min = [max(170, _fm.width(self._cols[0]) + 16), max(120, _fm.width("Type") + 90)] + \
                        [_fm.width(self._cols[i]) + 16 for i in range(2, 8)]
        for i in range(7):
            h.setSectionResizeMode(i, QHeaderView.Interactive)   # 🐛 卡顿真根因: ResizeToContents
            self.tree.setColumnWidth(i, self._col_min[i])
        self.tree.header().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        # 🖱 2026-10-17 老倪: 「用鼠标调整, 怎么调整完了又自动还原了? 要能用鼠标调整每列宽度」
        #   真根因: 每拍 reload() 都调 _fit_columns() 重算列宽 ⇒ 手拖的结果一秒钟就被抹掉。
        #   口径: 用户拖过 = 以用户为准 (写 QSettings 持久化), 自动分配只在"用户没拖过"时生效;
        #        想回到自动就给一个明确的 ↺ 按钮, 不再偷偷还原。
        self._user_cols = {}
        self._applying_cols = False
        try:
            from PyQt5.QtCore import QSettings
            _v = QSettings("ZMAX", "studio").value("canoe/data_cols")
            if isinstance(_v, str):
                _v = [int(x) for x in _v.split(",") if x.strip().isdigit()]
            if _v and len(_v) == 8:
                self._user_cols = {i: int(x) for i, x in enumerate(_v) if int(x) > 0}
        except Exception:                                                        # noqa: BLE001
            self._user_cols = {}
        self.tree.header().sectionResized.connect(self._on_data_col_resized)
        box.setMinimumWidth(920)          # 7 列 (Name/Value/Unit/帧龄/Bar/Tx/Rx) 的最小可用宽度
        self.tree.itemClicked.connect(self._on_tree_click)
        lay.addWidget(self.tree, 1)
        return box

    def _detail_panel(self):
        box, lay, head = self._panel("🔎 Detail", C_YELLOW)
        head.addWidget(self._sm_btn("📋 复制", "复制右侧详情文本(可直接粘到 CLI / 邮件)", self.copy_detail))
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont(MONO, 10))
        self.detail.setStyleSheet(f"QTextEdit {{ background:{C_BG}; color:{C_WHITE}; border:none; }}")
        self.detail.setText("点左侧 Data 表 或 Trace 任意一行 → 这里显示该对象的完整属性与质量判据(逐条)。")
        lay.addWidget(self.detail, 1)
        return box

    def _trace_panel(self):
        """CANoe 的 Trace 面板: 整宽 + 自带工具条(刷新/清除/暂停/Δt/搜索/导出)"""
        box, lay, head = self._panel("📋 Trace", C_GREEN)
        # 🆕 2026-10-01 老倪: 「默认是 topic 固定, 时间变动; 现在的滚动模式看着太累了, 默认不滚动」
        self._mode = "fixed"
        self.btn_mode = self._sm_btn("📌 固定行",
                                     "显示模式 ⇄ 「📌 固定行」(默认: 一行一个话题, 位置不动, 只有时间/数值在变)"
                                     " / 「▶ 滚动」(帧流, 最新在顶)",
                                     self._toggle_mode, checkable=True)
        self.btn_mode.setChecked(True)
        head.addWidget(self.btn_mode)
        self.btn_pause = self._sm_btn("⏸ 暂停", "暂停/恢复 Trace 刷新(数据照收, 只冻结视图)",
                                      self._toggle_pause, checkable=True)
        self.btn_dt = self._sm_btn("Δt", "Time 列切「与同话题上一帧的时间差」(CANoe Δt)",
                                   self._toggle_dt, checkable=True)
        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("🔎 搜索信号 / topic (如 ss_plan · grasp_prob · tcp_x)")
        self.ed_search.setFont(QFont(MONO, 9))
        self.ed_search.setFixedWidth(360)
        self.ed_search.setStyleSheet(f"QLineEdit {{ background:{C_BG}; color:{C_WHITE};"
                                     f" border:1px solid {C_BORDER}; border-radius:4px; padding:4px 8px; }}")
        self.ed_search.textChanged.connect(self._on_filter)
        head.addWidget(self.btn_pause)
        head.addWidget(self.btn_dt)
        head.addWidget(self.ed_search)
        head.addWidget(self._sm_btn("🗑 清屏", "只清 Trace 视图, 不动 trace.jsonl 原始记录", self._clear_trace))
        head.addWidget(self._sm_btn("📤 导出 CSV", "导出当前 Trace 表(Excel 可开)", self.export_trace))
        self.lb_live = QLabel("⚡ 实时 —")
        self.lb_live.setFont(QFont(MONO, 9))
        self.lb_live.setStyleSheet(f"color:{C_GRAY}; background:transparent; border:none;")
        head.addWidget(self.lb_live)

        self.tb = QTableWidget(0, 11)   # Time · Layer · Signal · Value · Unit · Phys · Type · Tx · Rx · QoS · Hz
        self.tb.setHorizontalHeaderLabels(
            # 🆕 2026-10-01 老倪: 「trace里得实时显示数值啊…不是静态的变量, 是动态的数据, 给我高亮显示出来」
            #   ⇒ 第 2 列「实时值」= live.json 里该话题的 fields 压成一行, 值变了变绿(动态), 没变灰;
            #   「搜索之后就在 trace 窗口里置顶」⇒ 命中关键词的话题帧永远排在最上面 + 整行高亮。
            # 🆕 2026-10-01 老倪: 「时间第一列, name第二列」+「默认 topic 固定、时间变动, 不要滚动」
            ["Time·abs", "Layer", "Signal", "Value", "Unit", "Phys", "Type", "Tx", "Rx", "QoS", "Hz"])
        self.tb.setStyleSheet(
            f"QTableWidget {{ background:{C_BG}; color:{C_WHITE}; border:none; gridline-color:#21262d;"
            f" font-family:{MONO}; font-size:10pt; }}"
            f"QTableWidget::item {{ padding:2px 6px; }}"
            f"QTableWidget::item:selected {{ background:{C_SEL}; color:{C_WHITE}; }}"
            f"QHeaderView::section {{ background:{C_CARD}; color:{C_HEAD}; border:none; padding:4px;"
            f" font-family:{UI}; }}")
        self.tb.verticalHeader().setVisible(False)
        self.tb.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tb.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tb.setShowGrid(True)
        self.tb.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        # 🖱 2026-10-17 老倪: 「用鼠标滚轮, 要可以上下滚动窗口」
        #   默认 ScrollPerItem 在 1946 行时一滚就跳一格、且体感像没动; 按像素滚才跟手。
        self.tb.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tb.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._tb_filters = {}
        th = self.tb.horizontalHeader()
        for i, w in ((0, 150), (1, 64), (2, 250), (3, 150), (4, 90), (5, 70),
                     (6, 210), (7, 130), (8, 150), (9, 240), (10, 110)):
            th.setSectionResizeMode(i, QHeaderView.Interactive)  # 🐛 同上(卡死根因)
            self.tb.setColumnWidth(i, w)
        # 🎚 2026-10-17 老倪: 「列表头, 要增加信号滤波功能, 现在信号太多了, 不好选择」
        #   点任一列头 ⇒ 弹该列所有取值+条数 ⇒ 选中即过滤 (可叠列);「全部」取消, 支持清空。
        th.setSectionsClickable(True)
        th.sectionClicked.connect(self._on_header_filter)
        th.setSectionsMovable(False)
        # 🕒 2026-10-17 老倪: 「Time 要能显示和 3D 场景一样的相对时间, 同步时间显示; 当然也可以绝对时间;
        #    要在 Time 列可以切换」⇒ 点 Time 表头切 相对/绝对 (同一根钟: 相对 = 快照里的 时间_s)
        self._time_mode = "abs"
        th.sectionClicked.connect(self._on_hdr_click)
        self._col_user = set()
        th.sectionResized.connect(self._on_col_resized)      # 🖱 用户拖过 ⇒ 以后不再自动适配
        self.tb.itemClicked.connect(self._on_trace_click)
        lay.addWidget(self.tb, 1)
        return box

    def _bottom_tabs(self):
        """CANoe 底部标签栏 → 数据闭环 | 质量告警 (+ 右下计时/拍照)"""
        box = QFrame()
        box.setStyleSheet(f"QFrame {{ background:{C_BG2}; border:1px solid {C_BORDER}; border-radius:6px; }}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)
        tabrow = QHBoxLayout()
        tabrow.setSpacing(6)
        self._btns = {}
        for key, txt in (("alert", "⚠ 质量告警"),):        # 🗑 数据闭环页已删 (老倪 2026-10-17)
            b = QPushButton(txt)
            b.setFont(QFont(UI, 10, QFont.Bold))
            b.setCheckable(True)
            b.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{C_GRAY}; border:none;"
                f" border-bottom:2px solid transparent; padding:4px 12px; }}"
                f"QPushButton:checked {{ color:{C_BLUE}; border-bottom:2px solid {C_BLUE}; }}")
            b.clicked.connect(lambda _=False, k=key: self._show_bottom(k))
            self._btns[key] = b
            tabrow.addWidget(b)
        self._btns["alert"].setChecked(True)
        tabrow.addStretch()
        # ✂️ 2026-10-17 老倪: 「拍照 … 这些字都删掉」—— 底部右角的"拍照 <时刻>"也一并去掉
        lay.addLayout(tabrow)

        self.tb_alert = QTableWidget(0, 3)
        self.tb_alert.setHorizontalHeaderLabels(["Level", "Object", "Issue"])
        for t in (self.tb_alert,):
            t.setStyleSheet(
                f"QTableWidget {{ background:{C_BG}; color:{C_WHITE}; border:none; gridline-color:#21262d;"
                f" font-family:{UI}; font-size:9pt; }}"
                f"QTableWidget::item {{ padding:2px 6px; }}"
                f"QTableWidget::item:selected {{ background:{C_SEL}; }}"
                f"QHeaderView::section {{ background:{C_CARD}; color:{C_HEAD}; border:none; padding:4px; }}")
            t.verticalHeader().setVisible(False)
            t.setEditTriggers(QAbstractItemView.NoEditTriggers)
            t.setSelectionBehavior(QAbstractItemView.SelectRows)
            lay.addWidget(t, 1)
        self.tb_alert.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ah = self.tb_alert.horizontalHeader()
        for i, w in ((0, 130), (1, 280)):
            ah.setSectionResizeMode(i, QHeaderView.Interactive)
            self.tb_alert.setColumnWidth(i, w)
        ah.setSectionResizeMode(2, QHeaderView.Stretch)
        self.tb_alert.show()
        return box

    def _show_bottom(self, key):
        for k, b in self._btns.items():
            b.setChecked(k == key)
        self.tb_alert.setVisible(True)      # 唯一保留的页: 质量告警

    def _toggle_all(self):
        roots = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        want = not all(r.isExpanded() for r in roots if r)
        for r in roots:
            if r:
                r.setExpanded(want)

    def _toggle_pause(self):
        """暂停/继续 Trace 视图 (顶部测量条已删: 不再联动 Start/Stop/状态灯)。"""
        on = self.btn_pause.isChecked()
        self.btn_pause.setText("▶ 继续" if on else "⏸ 暂停")
        if not on:
            self.reload()

    def _toggle_dt(self):
        self._dt_mode = self.btn_dt.isChecked()
        self._fill_trace()

    def _on_filter(self, txt):
        """🐛 2026-10-01 修: 原来调 _fill_trace() 没带 force ⇒ 只要 trace.jsonl 签名没变
        (1 秒内刚填过) 就直接 return ⇒ 老倪「我搜索 plan 了, 啥都没有」= 搜索框没反应的真根因。
        搜索必须**立即重填**。"""
        self._filter = (txt or "").strip().lower()
        self._fill_trace(force=True)
        self._apply_find()          # Data 树同步过滤 (左表/右表同一个搜索词)

    def _clear_trace(self):
        self.tb.setRowCount(0)
        self._trace_rows = []

    def export_trace(self):
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 Trace CSV",
            os.path.expanduser("~/zmax/zmax_data/dataspace/trace_%s.csv" % time.strftime("%Y%m%d_%H%M%S")),
            "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(",".join('"%s"' % self.tb.horizontalHeaderItem(c).text()
                                 for c in range(self.tb.columnCount())) + "\n")
                for r in range(self.tb.rowCount()):
                    vals = []
                    for c in range(self.tb.columnCount()):
                        it = self.tb.item(r, c)
                        vals.append('"%s"' % ((it.text() if it else "").replace('"', '""')))
                    f.write(",".join(vals) + "\n")
            QMessageBox.information(self, "导出完成", "已导出 %d 行:\n%s" % (self.tb.rowCount(), path))
        except Exception as e:                                               # noqa: BLE001
            QMessageBox.warning(self, "导出失败", repr(e))

    # ─────────────────── 经典视图切换 ───────────────────
    def _toggle_classic(self):
        cb = getattr(self.main, "_canoe_classic_cb", None)
        if cb:
            cb(self.btn_classic.isChecked())

    # ─────────────────── 数据刷新 ───────────────────
    def reload(self, force_tree=False):
        # 注意: 不能在"不可见"时直接 return —— 构建期 (还没 show) 会把首刷也吃掉,
        # 表现为打开数据空间是空表。省 CPU 只在**值刷新**上做, 骨架/树照建。

        # 🐛 2026-09-29 老倪「全局数据空间怎么卡住了」真根因: 1s 定时器**无条件**重建 500 行×9 列的表
        #   (每轮 4500 个 QTableWidgetItem + 整页重排) ⇒ 进程 CPU 实测 81.7%, 页面像冻住。
        #   修法三条: ①不在看的页直接不刷新 ②trace 没变(体积+mtime)就整轮跳过 ③行数 500→150。
        if not self.isVisible():
            return
        try:
            self._fit_columns()      # 每拍都按当前面板宽校正 (树被分栏改宽时不一定有 resizeEvent)
            self._live = _j(LIVE, {}) or {}
            self._loop = {}      # 🗑 闭环页已删, 不再读 loop.json
            if force_tree or self.tree.topLevelItemCount() == 0:
                self._fit_columns()
                if not self._busdb:
                    self._busdb = _j(BUSDB, {})
                self._fill_tree()
            self._update_values()
            if self._sel_obj is None and self.tree.topLevelItemCount():
                _root = self.tree.topLevelItem(0)
                if _root is not None and _root.childCount():
                    _it = _root.child(0)
                    self.tree.setCurrentItem(_it)          # 默认选中第一条报文(详情面板立刻有内容)
                    _d = _it.data(0, Qt.UserRole)
                    if _d:
                        self._sel_kind, self._sel_obj = _d
                        self._it_default = _it
            # (顶部测量条已删: 不再刷新档位/拍照/灯/计时)
            if not self.btn_pause.isChecked():
                self._fill_trace(force=bool(force_tree))
            self._fill_alerts()
            if self._sel_obj:
                self._fill_detail()
        except Exception as e:                                               # noqa: BLE001
            import traceback
            self.detail.setText("⚠ 刷新异常: %r\n%s" % (e, traceback.format_exc()[-800:]))

    def _topics(self):
        return (self._live or {}).get("topics") or {}

    def _read_trace(self, n=300):
        rows = []
        if os.path.exists(TRACE):
            try:
                with open(TRACE, "rb") as f:      # 有界读: 只取尾部 256KB(文件长大也不会拖慢)
                    f.seek(0, os.SEEK_END)
                    f.seek(max(0, f.tell() - 262144))
                    _tail = f.read().decode("utf-8", "replace").splitlines()
                for ln in _tail[-n:]:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            rows.append(json.loads(ln))
                        except Exception:                                    # noqa: BLE001
                            continue
            except Exception:                                                # noqa: BLE001
                rows = []
        return rows

    def _last_frame(self):
        """每话题最后一帧时刻 → Data 表 Last Value Time 列"""
        out = {}
        for rec in self._trace_rows[-600:]:
            t = rec.get("topic")
            if not t:
                continue
            out[t] = rec.get("t")                       # 全路径 zmax/xxx
            out[str(t).split("/")[-1]] = rec.get("t")   # 🐛 短名 xxx —— live.json 的键是短名(质检: 整列 '—')
        return out

    def _on_data_col_resized(self, idx, old, new):
        """用户手动拖列宽 → 记住 (写 QSettings), 之后自动分配不再覆盖。"""
        if getattr(self, "_applying_cols", False) or new <= 0:
            return
        if not self._user_cols:                      # 第一次拖动: 先把当前 8 列全部快照, 免得其余列被自动改
            snap = {}
            try:
                from PyQt5.QtCore import QSettings
                _v = QSettings("ZMAX", "studio").value("canoe/data_cols")
                if isinstance(_v, str):
                    _v = [int(x) for x in _v.split(",") if x.strip().isdigit()]
                if _v and len(_v) == 8:
                    snap = {i: int(x) for i, x in enumerate(_v) if int(x) > 0}
            except Exception:                                                    # noqa: BLE001
                snap = {}
            self._user_cols = snap or {i: self.tree.columnWidth(i) for i in range(8)}
        self._user_cols[idx] = int(new)
        try:
            from PyQt5.QtCore import QSettings
            QSettings("ZMAX", "studio").setValue(
                "canoe/data_cols", ",".join(str(self._user_cols.get(i, 0)) for i in range(8)))
        except Exception:                                                        # noqa: BLE001
            pass

    def _reset_cols(self):
        """↺ 列宽: 清掉手动列宽, 回到自动分配。"""
        self._user_cols = {}
        try:
            from PyQt5.QtCore import QSettings
            QSettings("ZMAX", "studio").remove("canoe/data_cols")
        except Exception:                                                        # noqa: BLE001
            pass
        self._fit_columns()

    def _measure_cols(self):
        """按**内容实测宽**算每列该多宽 (文本一个都不截)。

        老倪 2026-10-17: 「你的字符不要显示... Tx Rx 都看不全, 不要截断省略」⇒
        放弃"挤成一屏/隐藏列"的做法: 列宽 = max(表头, 该列最长文本) + 内边距,
        整表比面板宽就出横向滚动条 —— 宁可滚, 也不要省略号。
        """
        from PyQt5.QtGui import QFont as _QF, QFontMetrics as _QFM
        _f = _QF(UI)
        _f.setPointSizeF(9.0)                       # 与 QTreeWidget 样式表 font-size:9pt 一致
        fm = _QFM(_f)
        hfm = fm
        need = [hfm.width(self._cols[i]) + 22 for i in range(8)]
        for i in range(self.tree.topLevelItemCount()):
            stack = [self.tree.topLevelItem(i)]
            while stack:
                it = stack.pop()
                stack.extend(it.child(j) for j in range(it.childCount()))
                if it.data(0, Qt.UserRole) is None and it.childCount() == 0:
                    continue                    # 分组标题 (不是数据行) 不参与撑列
                for c in range(8):
                    t = it.text(c)
                    if t:
                        need[c] = max(need[c], fm.width(t) + 26)   # +26: 留够 padding/抗锯齿, 实测 +18 会差 1~14px 被切
        # 上限按列语义给 (Tx/Rx 可能是 3~5 个节点名的完整清单 ⇒ 给足, 宁可横向滚动也不截字)
        cap = [1200, 900, 300, 220, 300, 300, 2400, 2400]
        return [min(int(need[i]), cap[i]) for i in range(8)]

    def _fit_columns(self):
        """列宽: 用户拖过就完全听用户的; 没拖过就按内容宽铺开 (放不下 → 横向滚动, 不省略)。"""
        try:
            if getattr(self, "_user_cols", None):
                self._applying_cols = True
                try:
                    for _i, _w in self._user_cols.items():
                        if 0 <= _i < self.tree.columnCount():
                            self.tree.setColumnWidth(_i, int(_w))
                finally:
                    self._applying_cols = False
                return                        # 用户拖过 ⇒ 一个像素都不许自己动
            if getattr(self, "_need_dirty", True) or not getattr(self, "_col_need", None):
                self._col_need = self._measure_cols()
                self._need_dirty = False
            need = list(self._col_need)
            avail = max(320, self.tree.viewport().width() - 2)
            # 富余宽度给 Name / Tx / Rx (它们是长文本列), 仍有余量就平铺
            spare = avail - sum(need)
            if spare > 0:
                for _c in (0, 6, 7):
                    _add = min(int(spare / 3), max(0, [1200, 900, 300, 220, 300, 300, 2400, 2400][_c] - need[_c]))
                    if _add > 0:
                        need[_c] += _add
                        spare -= _add
            for _c in range(8):
                self.tree.setColumnHidden(_c, False)      # 不再藏列 (藏了就跟"要能看全"矛盾)
            self._applying_cols = True
            try:
                for i in range(8):
                    self.tree.setColumnWidth(i, int(need[i]))
            finally:
                self._applying_cols = False
        except Exception:                                                        # noqa: BLE001
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_columns()

    def showEvent(self, e):
        super().showEvent(e)
        # 树是懒布局的: 显示后再量一次 (否则量到的是"还没分配宽度"的值, 隐藏列/列宽都不生效)
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self._fit_columns)
        QTimer.singleShot(250, self._fit_columns)

    _ALIGN = {0: Qt.AlignLeft | Qt.AlignVCenter,      # Name
              1: Qt.AlignLeft | Qt.AlignVCenter,      # Type (topic)
              2: Qt.AlignRight | Qt.AlignVCenter,     # Value
              3: Qt.AlignHCenter | Qt.AlignVCenter,   # Unit
              4: Qt.AlignRight | Qt.AlignVCenter,     # Age s
              5: Qt.AlignHCenter | Qt.AlignVCenter,   # Bar
              6: Qt.AlignLeft | Qt.AlignVCenter,      # Tx
              7: Qt.AlignLeft | Qt.AlignVCenter}      # Rx

    def _align_item(self, it, tips=None):
        """每列对齐规则 + 全文 tooltip (列宽只影响显示, 数据永远看得到)。"""
        for c in range(self.tree.columnCount()):
            it.setTextAlignment(c, self._ALIGN.get(c, Qt.AlignLeft | Qt.AlignVCenter))
            t = it.text(c)
            if t and t != "—":
                it.setToolTip(c, (tips or {}).get(c, t))

    def _fill_tree(self):
        """CANoe 的 Symbols 树: 报文(话题) → 信号(画布连线, 按层) → 节点(按层)"""
        self.tree.clear()
        self._need_dirty = True          # 树内容变了 ⇒ 列宽要重算 (老倪: 不许省略, 那就把列铺到够宽)
        db = self._busdb or {}
        topics = self._topics()
        only_alive = bool(self.chk_only_alive.isChecked())
        f_tr = QFont(UI, 10, QFont.Bold)

        msgs = db.get("messages") or {}
        # Tx/Rx 名字表: 节点 id → 节点名; 话题 → 下游节点名 (工程库连线派生, 供没有 consumers 字段的报文用)
        # 🧹 2026-10-17 老倪: 「Tx Rx 显示节点的名字, 太乱了, 怎么 L5 L4 都冒出来了? 还有横向箭头;
        #    改清晰, 只要这个节点的名字; 全局搜索, 规范名称」
        #    真根因: Tx/Rx 直接用画布**长名** (带 emoji / L2~L5 前缀 / ①序号 / " · 解释" / "→ 下游")。
        #    口径: 统一走 middleware.naming.clean() —— 只留节点本名, 重名补短 id; 端口说明不进 Tx/Rx。
        try:
            from lerobot.middleware import naming as _naming
            _names = _naming.unique_map([(k2, (v2 or {}).get("name", k2))
                                         for k2, v2 in (db.get("nodes") or {}).items()])
        except Exception:                                                    # noqa: BLE001
            _names = {k2: (v2 or {}).get("name", k2) for k2, v2 in (db.get("nodes") or {}).items()}
        _rx_by_topic = {}
        for _sg in (db.get("signals") or []):
            _t = _sg.get("topic")
            if not _t:
                continue
            _d = _names.get(_sg.get("dst"), _sg.get("dst"))
            _l = _rx_by_topic.setdefault(_t, [])
            if _d and _d not in _l:
                _l.append(_d)
        _rx_by_topic = {k: ", ".join(v) for k, v in _rx_by_topic.items()}
        _c = {}
        for _m in msgs.values():
            _c[(_m or {}).get("layer") or "meta"] = _c.get((_m or {}).get("layer") or "meta", 0) + 1
        _brk = " · ".join("%s %d" % (k if k != "meta" else "系统", _c[k])
                          for k in ["L5", "L4", "L3", "L2", "L1", "meta"] if k in _c)
        root_m = QTreeWidgetItem(["🚌 报文 %d · %s" % (len(msgs), _brk), "", "", "", "", "", "", ""])
        root_m.setFont(0, f_tr)
        root_m.setForeground(0, QColor(C_BLUE))
        root_m.setToolTip(0, "按层分组 (层 = 端口所属节点在工程里的层):\n"
                             "L5 造数据 · L4 认知 · L3 调度 · L2 检测 · L1 硬件(本工程未用该分组) · 系统=meta 功能节点")
        self.tree.addTopLevelItem(root_m)
        # 🔴 活跃在前: 左面板高度有限(实测只放得下 ~8 行/15 条), 纯字母序会把正在跑的 ss_plan
        #   排到第 12 行 ⇒ 老倪在页面上根本看不到他要"逐帧对"的那条。活跃的排前面,
        #   组内再按字母序(顺序仍然可预期)。
        def _alive_rank(k):
            _t = topics.get(k) or {}
            _hz = _t.get("hz")
            return (0 if isinstance(_hz, (int, float)) and _hz > 0 else 1, str(k))

        # 🗂 2026-10-17 老倪: 「报文也应该先按照 L1~L5 分类, 要不不好找」
        #   报文 = 输出端口, 层 = 该端口所属节点所在的层 ⇒ 报文天生带层, 直接按层分组。
        #   组顺序 L5→L1 + 系统(meta); 层内仍"活跃在前, 再字母序"。
        _by_m = {}
        for key, m in msgs.items():
            if only_alive and not topics.get(key):
                continue
            _by_m.setdefault((m or {}).get("layer") or "meta", []).append(key)
        # L1: 只有真有 L1 报文时才出现 (本工程层分组里没有 L1, 硬造一个空组只会更难找)
        _order = ["L5", "L4", "L3", "L2", "L1", "meta"]
        _seen = [x for x in _order if x in _by_m]
        _seen += [x for x in sorted(_by_m) if x not in _order]
        for ly in _seen:
            keys = sorted(_by_m[ly], key=_alive_rank)
            lyr = QTreeWidgetItem(["%s · %d" % (ly if ly != "meta" else "系统", len(keys)),
                                   "", "", "", "", "", "", ""])
            lyr.setFont(0, QFont(UI, 10, QFont.Bold))
            lyr.setForeground(0, QColor(LV_COLOR.get(ly, C_GRAY)))
            self._align_item(lyr)
            root_m.addChild(lyr)
            for key in keys:
                m = msgs[key] or {}
                _tx_full = str(m.get("producer") or "—")
                _tx_port = ""
                if "." in _tx_full:                  # producer 形如 n_dsvl.out1 → 只取节点名
                    _pre, _tx_port = _tx_full.split(".", 1)
                    _tx_full = _names.get(_pre, _pre)
                else:                                # 注册表类话题的 producer 是一句说明, 只留主名
                    _tx_full = _naming.clean(_tx_full, fallback=_tx_full)
                _tx_full = _naming.clean(_tx_full, fallback=_tx_full)   # 兜底: 任何残留说明都砍掉
                _rx_full = ", ".join(_names.get(x, x) for x in (m.get("consumers") or [])) or _rx_by_topic.get(m.get("topic"), "—")
                _tx = _tx_full            # 已是归一后的短名, 不再拼端口/不再截断
                _rxl = [short_name(x) for x in _rx_full.split(", ") if x and x != "—"]
                # 下游 ≤6 个: 全部列出 (不省略); 更多就是一个广播话题 (实测有 100+ 个消费者),
                # 逐个列出来 14000px 也读不了 ⇒ 只给个数, 全名单在 tooltip 里 (这是聚合不是截断)
                _rx = (", ".join(_rxl) if len(_rxl) <= 6 else "%d 个下游" % len(_rxl)) if _rxl else "—"
                _short = _naming.clean(str(m.get("producer") or m.get("topic", key)),
                                       fallback=str(key))                  # 例: n_dsvl.out1
                # 🎯 2026-10-17 老倪: 「type 列显示的不对, 应该是 topic 的类型」
                #   Type = 数据类型 (zmax::SSNodePort 等); topic 全名放 Name 的 tooltip, 不占列
                # 🔴 类型以**语义注册表**为准 (busdb.json 是快照, 可能还是旧的 SSNodePort)
                #    真源: config/platform/dds_topic_types.json ← tools/gen_topic_types.py
                _type, _type_cn = str(m.get("type") or "—"), ""
                try:
                    from lerobot.middleware import topic_types as _tt
                    _d = _tt.describe(m.get("topic") or key)
                    _type = _d.get("type") or _type          # 非节点话题: 用它自己的声明类型
                    _type_cn = (_d.get("cn") or "") if _d.get("type") else ""
                except Exception:                                        # noqa: BLE001
                    pass
                it = QTreeWidgetItem([_short, _type, "—", "—", "—", "—", _tx, _rx])
                it.setData(0, Qt.UserRole, ("topic", key))
                it.setFont(0, QFont(MONO, 10))
                self._align_item(it, {0: "topic: %s" % m.get("topic", key), 1: "type: %s" % _type,
                                      6: "Tx: %s%s" % (_tx_full, (" · " + _tx_port) if _tx_port else ""),
                                      7: "Rx: %s" % _rx_full})
                if len(_rxl) > 6:
                    it.setToolTip(7, "Rx 共 %d 个:\n%s" % (len(_rxl), _rx_full))
                it.setToolTip(1, "type %s\n%s" % (_type, _type_cn or "—"))
                _n_sig = m.get("n_signals")
                it.setToolTip(0, "topic %s\n层 %s · 类型 %s · 设计 %sHz · QoS %s\n信号 %s · 生产者 %s" % (
                    m.get("topic", key),
                    m.get("layer", "—"), m.get("type", "—"),
                    ("%.2f" % float(m["hz_design"])) if m.get("hz_design") else "—",
                    m.get("qos", "—"), _n_sig if _n_sig is not None else "—", m.get("producer", "—")))
                lyr.addChild(it)
            lyr.setExpanded(ly in ("L5", "L4"))     # 先展开最上两层, 下层按需点开
        root_m.setExpanded(True)

        # ✂️ 2026-10-17 老倪: 「信号列表, 没必要再显示 信号和节点, 都删掉; 具体的信号再 Trace 窗口显示」
        #   口径: Data 面板只留**报文** (一个输出端口一条); 信号级明细在 Trace (带单位/物理量);
        #        节点的收发关系在 Tx / Rx 两列与详情面板里, 不再单独开一个"节点"树占地方。
        self._fit_columns()          # 树建完再按当前面板宽收窄/隐藏次要列
        self._apply_find()          # 🔎 树重建后(含「只看活报文」勾选) 立刻重放搜索词, 不让筛选丢

    def _apply_find(self):
        """按搜索词/「只看活报文」过滤 Data 树 (重建后立刻重放, 筛选不丢)。

        🐛 2026-10-17 修: 删「信号/节点」两组时把本方法一起删了 ⇒ Trace 面板 reload 抛
        AttributeError('BusView' object has no attribute '_apply_find'), 页面直接不刷新。
        """
        q = (getattr(self, "_filter", "") or "").strip().lower()
        try:
            only_alive = bool(self.chk_only_alive.isChecked())
        except Exception:                                                    # noqa: BLE001
            only_alive = False
        live = self._topics() or {}
        root = self.tree.topLevelItem(0)
        if root is None:
            return
        alive_keys = set()
        for k, t in live.items():
            if (isinstance(t.get("hz"), (int, float)) and t.get("hz") >= 0) or (t.get("count") or 0) > 0:
                alive_keys.add(str(t.get("topic") or k))
                alive_keys.add(str(k))
        for i in range(root.childCount()):
            lyr = root.child(i)
            shown = 0
            for j in range(lyr.childCount()):
                it = lyr.child(j)
                data = it.data(0, Qt.UserRole) or ()
                key = str(data[1]) if len(data) > 1 else ""
                txt = " ".join(it.text(c) for c in range(min(3, self.tree.columnCount()))).lower()
                ok = (not q) or (q in txt) or (q in key.lower())
                if ok and only_alive:
                    ok = key in alive_keys
                it.setHidden(not ok)
                shown += 0 if not ok else 1
            lyr.setHidden(shown == 0)
            if q and shown:
                lyr.setExpanded(True)
        root.setHidden(all(lyr.isHidden() for lyr in (root.child(i) for i in range(root.childCount()))))

    def _update_values(self):
        if not self._trace_rows:                   # 🐛 质检: Last Value Time 整列 '—' —— 首刷顺序问题
            self._trace_rows = self._read_trace()  #   (值更新早于 trace 读取) ⇒ 这里补读一次
        """Data 表: Value=实测 Hz · Unit=Hz · Last Value Time=该话题最后一帧 · Bar=实测/设计(CANoe 实心蓝条)"""
        topics = self._topics()
        last = self._last_frame()
        root_m = self.tree.topLevelItem(0)
        if root_m is None:
            return
        for i in range(root_m.childCount()):
            it = root_m.child(i)
            data = it.data(0, Qt.UserRole)
            if not data:
                continue
            _, key = data
            t = topics.get(key) or {}
            m = ((self._busdb.get("messages") or {}).get(key) or {})
            hz_d = float(m.get("hz_design") or 0) or 0.0
            for _c in (2, 3, 4, 5):
                it.setTextAlignment(_c, self._ALIGN[_c])
            if not t:
                it.setText(2, "—")
                it.setText(3, "Hz")
                it.setText(4, "—")
                it.setText(5, "")
                it.setData(5, Qt.UserRole, -1.0)
                it.setForeground(2, QColor(C_DIM))
                it.setForeground(4, QColor(C_DIM))
                continue
            hz = float(t.get("hz") or -1)
            it.setText(2, _num(hz, 2))
            it.setText(3, "Hz")
            tsp = last.get(key)
            if tsp:
                age = time.time() - float(tsp)
                it.setText(4, _num(age, 2) if age >= 0 else "—")
                it.setToolTip(4, "last frame %s" % _hhmmss(tsp))
            else:
                it.setText(4, "—")
                it.setToolTip(4, "no frame in window")
            ratio = (hz / hz_d) if (hz > 0 and hz_d > 0) else -1.0
            it.setData(5, Qt.UserRole, ratio)
            it.setText(5, "%d%%" % int(min(1.0, ratio) * 100) if ratio > 0 else "")
            it.setForeground(2, QColor(VERDICT_COLOR.get(t.get("verdict", "unknown"), C_WHITE)))
            it.setForeground(4, QColor(C_GRAY))

    def _trace_sig(self):
        try:
            st = os.stat(TRACE)
            return (st.st_size, int(st.st_mtime))
        except Exception:                                                        # noqa: BLE001
            return None

    @staticmethod
    def _sig_names(src, limit=10):
        """🆕 2026-10-11 老倪: 「在 trace 里, 增加 信号名称 列」——该行携带的**信号名**。

        Name 列是话题名, 信号名称列是这一帧/这一话题里面的信号 (fields 键名 / digest 键名);
        digest 在 trace.jsonl 里是**截断**存的, 所以用正则抠键名而不是 json.loads。
        取不到就 '—' (不装)。
        """
        names = []
        try:
            if isinstance(src, dict):
                names = [_signal_en.en_of(k) for k in src.keys()]
            elif src:
                import re as _re
                names = [_signal_en.en_of(k) for k, _v in _re.findall(
                    r'"([^"]{1,40})"\s*:\s*(-?\d+\.?\d*(?:[eE][-+]?\d+)?)', str(src))]
        except Exception:                                                       # noqa: BLE001
            names = []
        if not names:
            return "—"
        return ", ".join(names[:limit]) + (" …(%d)" % len(names) if len(names) > limit else "")

    @staticmethod
    def _digest_vals(dg):
        """trace 帧 digest → 「键=数值」一行 (回退用)。

        为什么不能 json.loads: trace.jsonl 里的 digest 是**截断**存的(~200 字),
        直接 loads 会抛; 而且 -1.0 在本仓 = 该字段缺测, 不该占视觉名额。
        """
        import re as _re
        s = str(dg or "")
        if not s:
            return ""
        out = []
        for k, v in _re.findall(r'"([^"]{1,40})"\s*:\s*(-?\d+\.?\d*(?:[eE][-+]?\d+)?)', s):
            try:
                f = float(v)
            except Exception:                                                   # noqa: BLE001
                continue
            if f == -1.0:                                    # -1 = 缺测(本仓约定)
                continue
            out.append("%s=%s" % (_signal_en.en_of(k), _f3(f)))   # 键也用英文变量名 (与 Signal 列一致)
            if len(out) >= 4:
                break
        if out:
            return " · ".join(out)
        return "全缺测(-1)" if ":" in s else ""

    def _on_col_resized(self, idx, _old, _new):
        """🖱 用户手动拖过某列 ⇒ 记下来, 后续自动适配不再覆盖它。"""
        try:
            u = set(getattr(self, "_col_user", None) or set())
            u.add(int(idx))
            self._col_user = u
        except Exception:                                                       # noqa: BLE001
            pass

    def _fit_name_col(self, names):
        """Name 列默认**按内容适配**(老倪 2026-10-01: 「name 这列太宽了, 默认适配一下宽度」)。

        用 QFontMetrics 真量宽度(192DPI 下 pt 字形的实际像素宽 ≠ 1x, 必须量不能猜) + 24px 内边距,
        夹在 90~340; 用户拖过(在 _col_user 里)就不动。
        ⚠️ 绝不用 `ResizeToContents` —— 高频表逐格量列宽会烧 CPU(实测 81%), 这是本文件记过的坑。
        """
        self.tb.setColumnWidth(1, 64)        # 🏷 Layer 列恒窄 (只有 L2~L5/SYS)
        if 2 in (getattr(self, "_col_user", None) or set()):
            return
        try:
            from PyQt5.QtGui import QFontMetrics                     # noqa: PLC0415
            fm = QFontMetrics(QFont(MONO, 10))
            ws = [fm.horizontalAdvance(str(x)) for x in names if x] or [0]
            self.tb.setColumnWidth(2, max(90, min(340, max(ws) + 24)))
        except Exception:                                                       # noqa: BLE001
            pass

    def _live_doc(self):
        """读 live.json(1s 缓存) —— 值列/固定行都自己取数, 不依赖上层是否喂过 self._live。"""
        now = time.time()
        c = getattr(self, "_lvf_cache", None)
        if not c or (now - c[0]) > 1.0:
            try:
                with open(LIVE, encoding="utf-8") as f:
                    c = (now, json.load(f))
            except Exception:                                                   # noqa: BLE001
                c = (now, (c[1] if c else {}))
            self._lvf_cache = c
        return c[1] or {}

    def _live_topics(self):
        """live.json → topics 字典(1s 缓存)"""
        return (self._live_doc().get("topics") or {})

    def _live_fields(self, key):
        """直接读 live.json 取该话题的 fields(1s 缓存)。

        🐛 2026-10-01 实测: 冷启动/离屏时 self._live 为空 ⇒ 值列退化成 digest 的「全缺测(-1)」,
        老倪看到的仍然是"没有数值"。值列必须**自己取数**, 不能依赖上层是否喂过 self._live。
        """
        tp = self._live_topics()
        return ((tp.get(key) or tp.get("zmax/" + str(key)) or {}).get("fields") or {})

    def _mark_search(self, n, q):
        """搜索框边缘报命中: 绿=有命中(o), 红=0 命中 — 省得把"没反应"当成"没数据"。

        🆕 2026-10-01 老倪: 「我搜索 plan 了, 啥都没有」⇒ 搜索框自身给出命中数 + 建议关键词。
        """
        try:
            if not q:
                self.ed_search.setStyleSheet(
                    f"QLineEdit {{ background:{C_BG}; color:{C_WHITE}; border:1px solid {C_BORDER};"
                    f" border-radius:4px; padding:4px 8px; }}")
                self.ed_search.setToolTip("🔎 搜索话题 → 命中帧置顶并高亮 (试: ss_plan / ss_action / ss_state)")
                return
            col = C_GREEN if n else C_RED
            self.ed_search.setStyleSheet(
                f"QLineEdit {{ background:{C_BG}; color:{C_WHITE}; border:2px solid {col};"
                f" border-radius:4px; padding:3px 7px; }}")
            self.ed_search.setToolTip(("命中 %d 帧 · 已置顶并高亮" % n) if n else
                                      "本窗口 0 命中 —— 关键词不在 DDS 总线名里。\n"
                                      "可用: ss_plan(规划,含 xyzabc) / ss_action(动作) / ss_state(状态) / "
                                      "ss_calib(标定) / ss_diag(诊断) / link_value / hw_state / heartbeat。\n"
                                      "注: ROS 的 /move_action 不在本总线(trace 只镜像 zmax/*)。")
        except Exception:                                                       # noqa: BLE001
            pass

    def _live_vals(self, lt):
        """live.json 的 fields → 一行可读**实时值**。

        🆕 2026-10-01 老倪: 「trace里得实时显示数值啊…不是静态的变量, 是动态的数据」。
        长序列(如 tcp_path 330 个数)压成「首3 …(N)」; 缺测(-1)照原样显示, 绝不装成 0。
        """
        f = (lt or {}).get("fields") or {}
        if not isinstance(f, dict) or not f:
            return ""
        out = []
        for k in ("goal_xyz", "tcp_pose6", "end_xyzabc", "tcp_path", "joints_path", "start_joints",
                  "xyz", "pose", "action", "state", "end_err_mm", "n_points", "plan_code",
                  "gate_same_source", "hz", "count", "latency_ms", "frame_age_s"):
            if k not in f or len(out) >= 3:
                continue
            v = f.get(k)
            if isinstance(v, (list, tuple)):
                hd = " ".join(_f3(x) for x in v[:3])          # ⚠️ 不能用 _num: 它把负值当缺测
                out.append("%s=[%s%s]" % (k, hd, (" …(%d)" % len(v)) if len(v) > 3 else ""))
            elif isinstance(v, float):
                out.append("%s=%s" % (k, _f3(v)))
            elif isinstance(v, (int, str, bool)):
                out.append("%s=%s" % (k, v))
        return " · ".join(out)[:150]

    def _toggle_mode(self, _checked=False):
        """📌 固定行 ⇄ ▶ 滚动 (老倪 2026-10-01: 默认固定行, 滚动看着太累)

        🚫 2026-10-11 老倪: 「你怎么把 trace 的表格全给改了? 只是让你增加信号名称, 没让你增加波形显示啊。改回去」
          ⇒ 撤掉「📈 信号分析」波形模式, Trace 面板恢复成**只有这张表**, 两种显示模式 (固定行/滚动) 不变;
            本轮唯一保留的改动 = 表里新增的「信号名称」列。
        """
        self._mode = "roll" if getattr(self, "_mode", "fixed") == "fixed" else "fixed"
        self.btn_mode.setText("📌 固定行" if self._mode == "fixed" else "▶ 滚动")
        self.btn_mode.setChecked(self._mode == "fixed")
        self._trace_sig_last = None
        self._lv_last = {}
        self._fill_trace(force=True)

    def _time_hdr(self):
        return "Time·rel" if getattr(self, "_time_mode", "abs") == "rel" else "Time·abs"

    def _on_hdr_click(self, idx):
        """点 Time 表头 ⇒ 绝对/相对 切换 (混着看容易误判: 3D 场景 HUD 是相对秒)。"""
        if idx != 0:
            return
        self._time_mode = "rel" if getattr(self, "_time_mode", "abs") == "abs" else "abs"
        self._hdr_last = None                 # 逼表头重设 (改 Time 标题)
        self._set_trace_header()
        try:
            self._fill_trace_fixed(force=True)
        except Exception:                                                    # noqa: BLE001
            pass

    def _set_trace_header(self, mode=None):
        """设置表头。🖱 2026-10-01: **表头没变就不要重设** —— setHorizontalHeaderLabels
        会把各列宽度复位 ⇒ 用户拖动过的列宽下一次刷新就被抹掉(表现=拖动不了)。"""
        mode = mode or getattr(self, "_mode", "fixed")
        # 🆕 2026-10-11 老倪: 「在 trace 里, 增加 信号名称 列」—— 该行这一帧/这个话题携带的信号名 (Name=topic, 信号名称=里面的信号)
        # 🧭 2026-10-17 老倪: 「trace 每列的中文改成英文, 控制字数, 不要写太多」→ 全英文短表头
        # 🧭 2026-10-17 老倪: 「trace 窗口都是 signal, 改成 Name 列…增加 Type / Tx / Rx,
        #    删 Lamp / Count / Age, QoS 要跟 DDS 标准对上」⇒ 固定行与滚动**同一套列**, 不再两套口径
        _labs = [self._time_hdr(), "Layer", "Signal", "Value", "Unit", "Phys",
                 "Type", "Tx", "Rx", "QoS", "Hz"]
        if _labs == getattr(self, "_hdr_last", None):
            return
        self.tb.setHorizontalHeaderLabels(_labs)
        self._hdr_last = _labs
        return

    def _set_trace_header0(self, mode=None):
        self.tb.setHorizontalHeaderLabels(
            ["Time·abs", "Layer", "Signal", "Value", "Unit", "Phys", "Type", "Tx", "Rx", "QoS", "Hz"])

    def _layer_map(self):
        """节点 id → 层 (L2~L5 / meta), 来自工程库。"""
        if getattr(self, "_lvlmap", None) is None:
            m = {}
            try:
                from lerobot.middleware import db as _db
                for r in _db.node_rows():
                    m[str(r.get("node_id"))] = str(r.get("layer") or "")
            except Exception:                                                # noqa: BLE001
                pass
            self._lvlmap = m
        return self._lvlmap

    def _layer_of(self, topic, t=None):
        """话题的层: 话题自带 layer 优先; ss.node.* 查节点; 注册表类话题 = SYS。"""
        lay = str((t or {}).get("layer") or "")
        if lay:
            return "SYS" if lay == "meta" else lay
        tp = str(topic or "")
        if tp.startswith("ss.node."):
            lay = self._layer_map().get(tp[len("ss.node."):].split(".")[0], "")
            return ("SYS" if lay == "meta" else lay) or "—"
        return "SYS"

    def _cons_map(self):
        """话题 → 下游节点 id 清单 (来自 busdb 的 consumers; 没有就空)。"""
        if getattr(self, "_consmap", None) is None:
            m = {}
            try:                        # 真源: 工程库连线 (node_rows.outs[].to) —— 不依赖 busdb 是否已加载
                from lerobot.middleware import db as _db
                for r in _db.node_rows():
                    for o in (r.get("outs") or []):
                        if o.get("topic") and o.get("to"):
                            m[str(o["topic"])] = list(o["to"])
            except Exception:                                                # noqa: BLE001
                pass
            for _k, v in ((self._busdb or {}).get("messages") or {}).items():
                tpc = (v or {}).get("topic")
                if tpc and (v or {}).get("consumers") and tpc not in m:
                    m[tpc] = list(v["consumers"])
            self._consmap = m
        return self._consmap

    def _tx_of(self, topic, t):
        """Tx = 主发送节点的中文短名 (注册表类话题没有节点, 用它自己的中文名)。"""
        prod = str((t or {}).get("producer") or "")
        if prod.startswith("ss.node."):
            return _cn_names.cn_of_node(prod[len("ss.node."):].split(".")[0], prod)
        if prod and "." in prod and " " not in prod and not prod.startswith("画布"):
            return _cn_names.cn_of_node(prod.split(".")[0], prod.split(".")[0])
        return _cn_names.cn_of(topic)

    def _rx_of(self, topic, t):
        cons = (t or {}).get("consumers") or self._cons_map().get(topic) or []
        names = [_cn_names.cn_of_node(str(x), str(x)) for x in cons]
        return ", ".join(names) if names else "—"

    def _type_of(self, topic, t):
        try:
            from lerobot.middleware import topic_types as _tt
            d = _tt.describe(topic)
            if d.get("type"):
                return d["type"]
        except Exception:                                                    # noqa: BLE001
            pass
        return str((t or {}).get("type") or "—")

    def _sig_meta(self, topic, sig):
        """(unit, vmin, vmax) —— 单位/量程只从工程库 mw_signal 取 (参数中心同源), 不猜。"""
        if getattr(self, "_sigm", None) is None:
            self._sigm, self._sigm_by_name = {}, {}
            try:
                from lerobot.middleware import db as _db
                for r in _db.signals():
                    key = (str(r.get("node_id")), str(r.get("port")), str(r.get("signal")))
                    val = (r.get("unit"), r.get("vmin"), r.get("vmax"))
                    self._sigm[key] = val
                    self._sigm_by_name.setdefault(str(r.get("signal")), val)
            except Exception:                                            # noqa: BLE001
                pass
        t = str(topic or "")
        if t.startswith("ss.node."):
            rest = t[len("ss.node."):]
            if "." in rest:
                nid, port = rest.rsplit(".", 1)
                return self._sigm.get((nid, port, str(sig)), (None, None, None))
        return self._sigm_by_name.get(str(sig), (None, None, None))

    _TB_HDR = ["Time·abs", "Layer", "Signal", "Value", "Unit", "Phys", "Type", "Tx", "Rx", "QoS", "Hz"]
    _TB_FILTERABLE = (1, 2, 4, 6, 7, 8, 9)      # 能过滤的列 (时间/数值不列)

    def _on_header_filter(self, idx):
        """点列头 → 选一个取值 → 只看这些行 (与信号分析窗口同一套交互)。"""
        if idx not in self._TB_FILTERABLE:
            self._log("这一列不适合过滤 (时间是逐帧变的); 点 Layer / Signal / Unit / Type / Tx / Rx / QoS")
            return
        cnt = {}
        for r in range(self.tb.rowCount()):
            it = self.tb.item(r, idx)
            v = it.text() if it is not None else ""
            cnt[v] = cnt.get(v, 0) + 1
        if not cnt:
            return
        from PyQt5.QtWidgets import QMenu
        m = QMenu(self.tb)
        a_all = m.addAction("全部 (%d)" % sum(cnt.values()))
        a_all.setData(None)
        m.addSeparator()
        acts = []
        for v, n in sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:80]:
            a = m.addAction("%s (%d)" % (v or "—", n))
            a.setData(v)
            acts.append(a)
        m.addSeparator()
        a_clr = m.addAction("清除所有列的过滤")
        cur = self._tb_filters.get(idx)
        if cur is not None:
            for a in acts:
                if a.data() == cur:
                    a.setText("● " + a.text())
        pick = m.exec_(self.tb.mapToGlobal(self.tb.rect().topLeft()))
        if pick is a_clr:
            self._tb_filters.clear()
        elif pick in acts or pick is a_all:
            v = pick.data()
            if v is None:
                self._tb_filters.pop(idx, None)
            else:
                self._tb_filters[idx] = v
        else:
            return
        self._apply_col_filters()

    def _apply_col_filters(self):
        """按列过滤条件隐藏行 + 列头标注当前值 (行集合变了也保持过滤)。"""
        th = self.tb.horizontalHeader()
        for c in range(self.tb.columnCount()):
            it = self.tb.horizontalHeaderItem(c)
            if it is None:
                continue
            # Time 列的表头是 Time·abs / Time·rel 可切的 ⇒ 以当前文本为底, 别被固定表覆盖
            base = (it.text().split(" ▾")[0] if c == 0 else self._TB_HDR[c])
            v = self._tb_filters.get(c)
            it.setText(base + (" ▾ %s" % v if v else " ▾"))
        if not getattr(self, "_tb_filters", None):
            for r in range(self.tb.rowCount()):
                self.tb.setRowHidden(r, False)
            return
        for r in range(self.tb.rowCount()):
            hide = False
            for c, v in self._tb_filters.items():
                it = self.tb.item(r, c)
                if it is None or it.text() != v:
                    hide = True
                    break
            self.tb.setRowHidden(r, hide)

    def _fill_trace_fixed(self, force=False):
        """📌 固定行模式(默认): 一行一个话题, **位置不动**, 只有时间/数值在变。

        老倪 2026-10-01: 「默认是 topic 固定, 时间变动; 现在的滚动模式, 看着太累了, 默认不是滚动」。
        行序: 搜索命中(置顶关键词)最前 → 其余按话题名; 缺测(-1)一律显式写 '—', 不装 0。
        """
        # 🔌 2026-10-12 老倪: 单步运行 ⇒ 当前节点输出的 topic 高亮 (数据源: 全局数据空间/数据总线)
        _cur_topics = set()
        try:
            import ss_bus_topics as _bt
            _cur_topics = _bt.highlight_topics()
            self._cur_step = _bt.read_current()
        except Exception:                                                  # noqa: BLE001
            pass
        tp = self._live_topics()
        # 🔌 2026-10-12 老倪: 单步 ⇒ 当前节点的**输出 topic 作为一行实时话题**进表 (数据源: 全局数据空间)。
        #   路径: 单步执行 → ss_bus_topics.publish() 真序列化 → step_current.json → 这里并入 live topics
        #   (live.json 只有真 DDS 流量的话题, 单步的节点输出 topic 不在其中; 视图侧并入 ⇒ 不被发布进程覆盖)
        try:
            _cur = getattr(self, "_cur_step", None) or {}
            if _cur.get("serialized") and _cur.get("topics"):
                tp = dict(tp)
                # 值列口径: _live_vals 只渲染白名单键 ⇒ 把单步载荷压成 "state=[…]" 数字序列 (真值, 不装)
                def _nums(v, acc=None, cap=12):
                    acc = [] if acc is None else acc
                    if len(acc) >= cap:
                        return acc
                    if isinstance(v, bool):
                        acc.append(float(v))
                    elif isinstance(v, (int, float)):
                        acc.append(float(v))
                    elif isinstance(v, (list, tuple)):
                        for x in v:
                            _nums(x, acc, cap)
                    elif isinstance(v, dict):
                        for x in v.values():
                            _nums(x, acc, cap)
                    return acc
                _numv = _nums(_cur.get("payload"))
                for _t in _cur["topics"]:
                    tp[_t] = {"topic": _t, "type": "zmax::SSNodeOut", "qos": "step", "allowed": True,
                              "hz": 0.0, "hz_design": 1.0, "count": 1, "matched_pubs": 1, "jitter_ms": 0.0,
                              "loss_pct": 0.0, "bytes": len(str(_cur.get("payload"))), "age_s": 0.0,
                              "verdict": "step", "score": 100.0, "source": "单步 debug",
                              "producer": "单步运行 (studio · 标定用)", "publisher": "studio",
                              "fields": {"state": _numv, "count": len(_numv),
                                         "payload": _cur.get("payload") or {}},
                              "digest": "🔌 单步节点: %s" % (_cur.get("node_name") or _cur.get("node_id")),
                              "link_topics": _cur.get("link_topics") or []}
        except Exception:                                                  # noqa: BLE001
            pass
        # 🗂 2026-10-17 老倪: 「怎么就这么少的信号? L1~L5 层所有的 topic 的所有信号, 都要加载」
        #   ⇒ Trace 不再只显示"有实时流量"的 topic, 工程库里注册的全部话题 (含入口) 都进表;
        #     没数据的话题照常列信号名, 值显 "—" (未实测), 不隐藏。
        try:
            from lerobot.middleware import db as _db2
            _lvl = {r["node_id"]: str(r.get("layer") or "") for r in _db2.node_rows()}
            tp = dict(tp)
            for r in _db2.topics():
                tpc = str(r.get("topic") or "")
                if not tpc or tpc in tp:
                    continue
                _is_out = str(r.get("dir") or "") == "out"
                tp[tpc] = {"topic": tpc, "type": r.get("type"), "qos": r.get("qos"),
                           "hz": -1.0, "hz_design": None, "count": 0, "age_s": -1.0,
                           "fields": {}, "layer": _lvl.get(str(r.get("node_id")), ""),
                           "dir": str(r.get("dir") or ""),
                           "producer": ("ss.node.%s" % r.get("node_id")) if _is_out else "",
                           "enabled": bool(r.get("enabled"))}
        except Exception:                                                # noqa: BLE001
            pass
        # ⚡ 2026-10-17 老倪: 「数据空间的信号怎么不动? 要实时运行啊」+「与信号分析窗口的数据保持一致」
        #   实时源 = 「信号分析」窗口正在读的那三份本机文件 (trace_live / engine_trace / gravity_trace),
        #   同一个模块读同一拍数据 ⇒ 两个窗口数值天然一致, 不再等 DDS 桥 (那边此刻 0 发布者)。
        try:
            from lerobot.middleware import live_signals as _livesig
            _rs = _livesig.topics()
            if _rs:
                _short = {t.split("/")[-1] for t in _rs}
                _keep = {}
                for _k, _v in tp.items():
                    _nm = str(_v.get("topic") or _k)
                    if _nm in _rs or _k in _rs or _nm.split("/")[-1] in _short or _k in _short:
                        continue                     # 同名话题让位给实时源, 不出现两行
                    _keep[_k] = _v
                _keep.update(_rs)
                tp = _keep
        except Exception:                                                # noqa: BLE001
            pass
        self._set_trace_header("fixed")
        if not tp:
            self.tb.setRowCount(1)
            self.tb.setItem(0, 0, QTableWidgetItem("—"))
            self.tb.setItem(0, 1, QTableWidgetItem("读不到 live.json (总线未运行 / 数据空间未启动)"))
            return
        pin = (self._filter or "").strip().lower()
        items = list(tp.items())
        n_hit = sum(1 for k, t in items if pin and (pin in str(t.get("topic") or k).lower()
                                                    or pin in str(t.get("type") or "").lower()))
        if pin:
            self._mark_search(n_hit, pin)
        # 🧷 2026-10-17 老倪: 「固定行模式, 每行是固定的, 你不要乱动每个 signal, 别跳」
        #   以前按帧龄排序 ⇒ 每拍 age 变、行序跟着变 (看着像信号在跳)。现在行序**只由常量决定**:
        #   ① 三路实时源恒定置顶 ② 层 L2→L5→SYS ③ 话题名; 与时间/数值完全无关。
        _LAY_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5, "SYS": 9}

        def _alive(_t, _key=""):
            _tp = str(_t.get("topic") or _key)
            _live = 0 if _tp in _attrib.LIVE_TOPICS else 1
            _lay = str(_t.get("layer") or "")
            _lay = "SYS" if _lay in ("", "meta") else _lay
            if _tp in _attrib.LIVE_TOPICS:               # 实时话题的层按生产节点取 (与信号分析一致)
                try:
                    _lay = _attrib.layer_of(_attrib.LIVE_PREFIX[_tp] + ".")
                except Exception:                                        # noqa: BLE001
                    pass
            return (_live, _LAY_ORDER.get(_lay, 8), _tp)
        items.sort(key=lambda kv: _alive(kv[1], kv[0]))       # 只按常量排, 行序不随时间变

        # 🧪 2026-10-17 老倪: 「具体的信号再 Trace 窗口显示, 有物理量显示」
        #   一个话题展开成 N 行信号: Signal=字段名 · Value=数值 · Unit=单位 · Phys=物理判据(✔/✘ 原因)
        rows = []
        # 🕒 相对时间的零点: 同一批实时帧里最早的那个 ts (与 3D 场景同源同一根钟;
        #    有 时间_s 的话题直接用快照里的回放秒, 和 3D HUD 逐字一致)
        if getattr(self, "_time_base", None) is None:
            _tss = []
            for _k, _t in items:
                _v = _t.get("ts")
                if isinstance(_v, (int, float)) and _v > 0:
                    _tss.append(float(_v))
            self._time_base = min(_tss) if _tss else None
        # 🕒 3D 场景那根钟 = 快照里的 时间_s (ss_state)。所有行共用这一个时刻 ⇒
        #    Trace 的相对时间与 3D HUD 逐字对得上 (各话题自己的 时间_s 有引擎开机秒, 不能直接用)
        _scene_t = None
        try:
            _v0 = ((tp.get("zmax/ss_state") or {}).get("fields") or {}).get("时间_s")
            if isinstance(_v0, (int, float)):
                _scene_t = float(_v0)
        except Exception:                                                # noqa: BLE001
            _scene_t = None
        self._scene_t = _scene_t
        for k, t in items:
            f = (t.get("fields") or {}) or self._live_fields(k) or {}
            ts = (f.get("ts") if isinstance(f, dict) else None) or t.get("ts")
            tt = "—"
            if getattr(self, "_time_mode", "abs") == "rel":
                if getattr(self, "_scene_t", None) is not None:
                    tt = "%.3f" % float(self._scene_t)      # 与 3D 场景同一拍
                elif ts and getattr(self, "_time_base", None):
                    tt = "%.3f" % (float(ts) - float(self._time_base))
            else:
                try:
                    tt = (time.strftime("%H:%M:%S", time.localtime(float(ts))) + ".%03d"
                          % int((float(ts) % 1) * 1000)) if ts else "—"
                except Exception:                                           # noqa: BLE001
                    tt = "—"
            age = t.get("age_s")
            hz, hzd = t.get("hz"), t.get("hz_design")
            _h = ("%s / %s" % (_f3(hz), _f3(hzd))) if (isinstance(hz, (int, float)) and hz >= 0) else "—"
            nm = str(t.get("topic") or k)
            _is_hit = bool(pin) and (pin in nm.lower() or pin in str(t.get("type") or "").lower())
            _is_step = (k in _cur_topics) or (nm in _cur_topics)
            # 🏷 2026-10-17 老倪: 「Name 列给中文名 (≤5 字); Signal 是程序里的真实变量;
            #    增加 Type (对应 topic 的类型) 和 Tx / Rx; 删 Lamp/Count/Age; QoS 要跟 DDS 标准对上」
            base = dict(time=tt, layer=self._layer_of(nm, t), name=_cn_names.cn_of(nm, ""), topic=nm,
                        hz=_h, count=str(t.get("count", "—")),
                        age=(_f3(age) if isinstance(age, (int, float)) and age >= 0 else "—"),
                        qos=_qos_names.standard(t.get("qos")),
                        pin=_is_hit, step=_is_step, key=k,
                        tx=self._tx_of(nm, t), rx=self._rx_of(nm, t), type=self._type_of(nm, t))
            _META = {"ts", "t", "count", "bytes", "n", "age_s", "seq", "sample_info", "__ts"}
            sig_fields = [(str(sn), sv) for sn, sv in (f or {}).items()
                          if isinstance(sv, (int, float)) and not isinstance(sv, bool)
                          and str(sn).lower() not in _META and not _signal_en.is_meta(sn)]
            if pin:
                if _is_hit:                   # 话题命中 ⇒ 该话题下所有信号都显示
                    pass
                else:                         # 只留信号名命中的那几行
                    sig_fields = [(sn, sv) for sn, sv in sig_fields if pin in sn.lower()]
                    if not sig_fields:
                        continue
            if sig_fields:
                for sn, sv in sorted(sig_fields):
                    unit, lo, hi = self._sig_meta(nm, sn)
                    _inferred = False
                    if not unit:                        # 没声明单位 → 按名字后缀推断, 显示加 * 标明
                        unit = _quality.infer_unit(sn)
                        _inferred = bool(unit)
                    verdict, why = _quality.check_field(sn, sv, unit, lo, hi)
                    _pk = (nm, sn)
                    _prev = (getattr(self, "_prev_vals", None) or {}).get(_pk)
                    _ak = _attrib.key_of(nm, sn)
                    _vtxt = _attrib.fmt_value(sv, _ak) if _ak else _f3(float(sv))
                    if _ak:
                        unit = _attrib.display_unit(_ak, unit)
                        _inferred = False
                    rows.append(dict(base, name=_cn_names.cn_of_signal(sn, nm),
                                     signal=_en_name(nm, sn), raw=sn,
                                     cn=_cn_names.cn_of_signal(sn, nm), value=_vtxt, vraw=float(sv),
                                     layer=(_attrib.layer_of(_ak) if _ak else base["layer"]),
                                     tx=(_attrib.tx_of(_ak) if _ak else base["tx"]),
                                     rx=(_attrib.rx_of(_ak) if _ak else base["rx"]),
                                     unit=((unit or "") + ("*" if _inferred else "")) or "—",
                                     lo=lo, hi=hi, prev=_prev,
                                     phys={"ok": "✔", "warn": "🟡", "fail": "✘", "unknown": "?"}.get(verdict, "?"),
                                     why=why, bad=verdict in ("warn", "fail")))
            else:
                # 📋 2026-10-17 老倪: 「signal列的信号呢? 每个 topic 的 signal 哪里去了? 添加」
                #   +「L1~L5 层所有的 topic 的所有信号, 都要加载」⇒ 没有实时载荷也把该话题的
                #   每个信号逐条列出来: 名字来自 端口标签/实现/上游继承, 值显 — 并标"未实测"。
                _vals = self._live_vals({"fields": f}) or self._digest_vals(t.get("digest")) or ""
                for _sn, _u, _src in _signals.signals_of(nm):
                    if _signal_en.is_meta(_sn):        # ts/topic/json/src 不是信号, 不列
                        continue
                    _unit2, _lo2, _hi2 = self._sig_meta(nm, _sn)
                    _unit2 = _unit2 or _u or _quality.infer_unit(_sn)
                    _ak2 = _attrib.key_of(nm, _sn)
                    rows.append(dict(base, name=_cn_names.cn_of_signal(_sn, nm),
                                     signal=_en_name(nm, _sn), raw=_sn,
                                     cn=_cn_names.cn_of_signal(_sn, nm),
                                     layer=(_attrib.layer_of(_ak2) if _ak2 else base["layer"]),
                                     tx=(_attrib.tx_of(_ak2) if _ak2 else base["tx"]),
                                     rx=(_attrib.rx_of(_ak2) if _ak2 else base["rx"]),
                                     value=(_vals or "—"), unit=(_unit2 or "—"), lo=_lo2, hi=_hi2,
                                     prev=None, phys="?", bad=False, src=_src,
                                     why=("信号来源: %s · 当前无实测值 (总线未跑/未上线)" % _src)))

        # ⚡ 2026-10-17 老倪: 「Trace 窗口的操作, 为什么延迟这么大?」
        #   根因: 每拍 (0.8s) 把 1946 行 × 11 格全部 delete+重建 (≈2.1 万 item), 单次 0.62s,
        #   占空比 75% ⇒ 滚轮/点行都在等主线程。行序已固定, 行集合没变时只改 5 个会变的格子。
        _sig = tuple((x.get("topic"), x.get("raw") or x.get("signal")) for x in rows)
        _same = (_sig == getattr(self, "_trace_sig", None)
                 and self.tb.rowCount() == len(rows)
                 and self.tb.columnCount() == 11)
        if _same:
            self.tb.setUpdatesEnabled(False)
            for r, x in enumerate(rows):
                for c, key in ((0, "time"), (3, "value"), (5, "phys"), (9, "qos"), (10, "hz")):
                    it = self.tb.item(r, c)
                    if it is None:
                        continue
                    txt = str(x[key])
                    if it.text() != txt:
                        it.setText(txt)
                it3 = self.tb.item(r, 3)
                if it3 is not None:
                    _fg = C_RED if x["bad"] else C_WHITE
                    if it3.foreground().color().name() != QColor(_fg).name():
                        it3.setForeground(QColor(_fg))
                it5 = self.tb.item(r, 5)
                if it5 is not None:
                    _fg5 = (C_RED if x["phys"] == "✘" else C_YELLOW if x["phys"] == "🟡" else C_GREEN)
                    if it5.foreground().color().name() != QColor(_fg5).name():
                        it5.setForeground(QColor(_fg5))
            self.tb.setUpdatesEnabled(True)
            self._apply_col_filters()
            return
        self._trace_sig = _sig
        self.tb.setUpdatesEnabled(False)
        # 🗑 2026-10-17 老倪: 「Trace 的 SYS 层是啥? 没有用, 删掉」
        #   SYS = 没有画布节点的信号 (派发服务计数/文件元数据/未归属话题) —— 对现场判读没用, 直接不列。
        _pre_n = len(rows)
        try:
            rows = [x for x in rows if str(x.get("layer") or "").upper() != "SYS"]
        except Exception:                                                     # noqa: BLE001
            pass
        self._trace_dropped = _pre_n - len(rows)
        self.tb.setRowCount(len(rows))
        # ♻️ 2026-10-17: 重建时**复用已有 item** (只 setText), 不再每拍 new 2 万个 QTableWidgetItem。
        #   颜色/字体只在首建或状态位 (bad/phys/pin/step) 变化时重设。
        _prev_flags = getattr(self, "_trace_flags", [])
        _new_flags = []
        for r, x in enumerate(rows):
            cells = [x["time"], x["layer"], x["signal"], x["value"], x["unit"],
                     x["phys"], x["type"], x["tx"], x["rx"], x["qos"], x["hz"]]
            _flags = (bool(x["bad"]), x["phys"], bool(x["pin"]), bool(x["step"]))
            _restyle = (r >= len(_prev_flags)) or (_prev_flags[r] != _flags)
            _new_flags.append(_flags)
            for c, txt in enumerate(cells):
                item = self.tb.item(r, c)
                if item is None:
                    item = QTableWidgetItem()
                    item.setFont(QFont(MONO if c in (0, 1, 2, 3, 4, 6, 7, 8) else UI, 10))
                    if c == 1:
                        item.setTextAlignment(Qt.AlignCenter)
                    self.tb.setItem(r, c, item)
                    _restyle = True
                txt = str(txt)
                if item.text() != txt:
                    item.setText(txt)
                if c == 2:
                    _tip = "%s\n话题: %s\n中文: %s" % (x.get("raw") or x["signal"],
                                                      x.get("topic") or "", x.get("cn") or "")
                    if item.toolTip() != _tip:
                        item.setToolTip(_tip)
                if not _restyle:
                    continue
                if c == 2:                    # tooltip 已在上面按内容更新 (行复用时不会留旧信号名)
                    pass
                if c == 0:
                    item.setForeground(QColor(C_BLUE))
                elif c == 1:                                   # Layer
                    item.setForeground(QColor(C_YELLOW))
                elif c == 2:
                    item.setForeground(QColor("#7ee787" if x["pin"] else "#9db4d0"))
                elif c == 3:
                    item.setForeground(QColor(C_RED if x["bad"] else C_WHITE))
                elif c == 4:
                    item.setForeground(QColor(C_GRAY))
                elif c == 5:
                    item.setForeground(QColor(C_RED if x["phys"] == "✘" else
                                              C_YELLOW if x["phys"] == "🟡" else C_GREEN))
                    if x["why"] and item.toolTip() != x["why"]:
                        item.setToolTip(x["why"])
                if x["step"]:
                    item.setBackground(QColor("#2b2611"))
                    if c in (2, 3):
                        item.setForeground(QColor("#ffd700"))
                elif x["pin"]:
                    item.setBackground(QColor("#1b2c1e") if c == 3 else QColor("#16202b"))
                elif r % 2:
                    item.setBackground(QColor("#12171e"))
                else:
                    item.setBackground(QColor(C_BG))
        self._trace_flags = _new_flags
        # ⚡ 实时状态: 有几路在本拍真有数、最老帧龄多少 (老倪判"有没有在动"看这一行, 不用数格子)
        try:
            _lv = _livesig.topics() if "_livesig" in dir() else {}
            if _lv:
                _fresh = {k2: v for k2, v in _lv.items() if float(v.get("age_s") or 0) < 60}
                _ages = [float(v.get("age_s") or 0) for v in _fresh.values()]
                _nsig = sum(len(v.get("fields") or {}) for v in _fresh.values())
                self.lb_live.setText("⚡ 实时 %d 话题 · %d 信号 · 帧龄 %.2fs"
                                     % (len(_fresh), _nsig, max(_ages) if _ages else 0)
                                     + ((" · 另有 %d 个旧文件源 (龄>60s)" % (len(_lv) - len(_fresh)))
                                        if len(_lv) > len(_fresh) else ""))
                self.lb_live.setStyleSheet(f"color:{C_GREEN}; background:transparent; border:none;")
            else:
                self.lb_live.setText("⚡ 实时 0 话题 (live_signals 无数据)")
                self.lb_live.setStyleSheet(f"color:{C_RED}; background:transparent; border:none;")
        except Exception:                                                # noqa: BLE001
            pass
        self._trace_frames = rows               # 给质量告警用: 最新一帧的逐信号值
        try:                                    # 存"上一帧值"给跳变判据
            self._prev_vals = {(r.get("topic"), r.get("raw") or r["signal"]):
                               float(r.get("vraw", r["value"])) for r in rows
                               if r.get("signal") not in (None, "—")}
        except Exception:                                                # noqa: BLE001
            pass
        self.tb.setUpdatesEnabled(True)
        self._apply_col_filters()        # 重建后保持列头过滤

    def _fill_trace(self, force=False):
        if getattr(self, "_mode", "fixed") == "fixed":         # 📌 默认固定行(不滚动)
            return self._fill_trace_fixed(force=force)
        self._set_trace_header("roll")
        sig = self._trace_sig()
        if not force and sig == getattr(self, "_trace_sig_last", None):
            return self.tb.rowCount()            # 文件没动 ⇒ 不重建(卡顿根因就是这里每秒重建)
        self._trace_sig_last = sig
        rows = self._read_trace()
        # ⚡ 2026-10-17: 滚动模式也必须走实时源 —— 它原来只读 trace.jsonl (DDS 桥此刻 0 发布者),
        #   用户切到「▶ 滚动」后看到的就是一潭死水。这里把 live_signals 的每一拍合成帧并入。
        try:
            from lerobot.middleware import live_signals as _ls
            _recs = []
            for _tp, _rv in (_ls.topics() or {}).items():
                _recs.append({"_live": True, "t": float(_rv.get("ts") or 0.0), "topic": _tp,
                              "type": str(_rv.get("type") or ""),
                              "n": 0, "bytes": 0,
                              "digest": json.dumps(_rv.get("fields") or {}, ensure_ascii=False)})
            if _recs:
                rows = _recs + [r for r in rows if str(r.get("topic")) not in
                                {x["topic"] for x in _recs}]
        except Exception:                                                # noqa: BLE001
            pass
        try:                        # 实时帧按时间排序 (后面统一"最新在顶", 不排序会被历史帧压到底部)
            rows.sort(key=lambda r: float(r.get("t") or 0.0))
        except Exception:                                                # noqa: BLE001
            pass
        if not rows:
            self._trace_rows = []
            self.tb.setRowCount(1)
            self.tb.setItem(0, 0, QTableWidgetItem("—"))
            self.tb.setItem(0, 1, QTableWidgetItem("没有 trace 帧(总线未记录 / trace.jsonl 为空)"))
            return
        self._trace_rows = rows
        if self._t0 is None:
            try:
                self._t0 = min(float(r.get("t") or 0) for r in rows)
            except Exception:                                                # noqa: BLE001
                self._t0 = None
        prev_t = {}
        for r in rows:
            prev_t[r.get("topic")] = r.get("t")
        rows = rows[::-1]                                    # 最新在顶
        # 📌 2026-10-01 老倪: 「搜索之后, 就在 trace 窗口里置顶」⇒ 命中关键词的话题**整段提到最上面**
        #   (不再隐藏其它帧 —— 置顶即可, 其它帧还在下面, 不丢信息)
        _pin = (self._filter or "").strip().lower()
        if _pin:
            _hit = [r for r in rows if _pin in str(r.get("topic", "")).lower()
                    or _pin in str(r.get("type", "")).lower()]
            if _hit:                                          # 有命中才重排(没命中就别乱动)
                rows = _hit + [r for r in rows if r not in _hit]
            self._mark_search(len(_hit), _pin)                 # 🆕 搜索框自己报命中数
        topics = self._topics()
        _cur_topics = set()
        try:
            _bt = getattr(self, "_bt", None)
            if _bt is not None and hasattr(_bt, "highlight_topics"):
                _cur_topics = _bt.highlight_topics()
        except Exception:                                                    # noqa: BLE001
            _cur_topics = set()
        self._fit_name_col([str(x.get("topic", "")) for x in rows[:150]])    # 📏 Name 列按内容适配
        self.tb.setUpdatesEnabled(False)
        self.tb.setRowCount(min(len(rows), 150))
        for r, rec in enumerate(rows[:150]):
            topic = str(rec.get("topic", "?"))
            key = topic.split("/")[-1]
            live_t = {} if rec.get("_live") else (topics.get(key) or topics.get(topic) or {})
            try:
                t = float(rec.get("t") or 0)
            except Exception:                                                # noqa: BLE001
                t = 0.0
            if self._dt_mode:
                p = prev_t.get(topic)
                tt = _num(t - float(p), 3) if p and float(p) < t else "—"
            else:
                tt = ("%.3f" % float(self._scene_t)) if (getattr(self, "_time_mode", "abs") == "rel"
                                                          and getattr(self, "_scene_t", None) is not None) \
                    else _rel(self._t0, t)
            score = live_t.get("score")
            _vkey = "%s|%s" % (topic, str(rec.get("n", "")))
            if not (live_t or {}).get("fields"):                 # 上层没喂 self._live ⇒ 自己取
                _f = self._live_fields(key)
                if _f:
                    live_t = dict(live_t or {}, fields=_f)
            vals = (self._digest_vals(rec.get("digest")) if rec.get("_live") else None) \
                or self._live_vals(live_t) or self._digest_vals(rec.get("digest"))
            _prev = (getattr(self, "_lv_last", {}) or {}).get(topic)
            _changed = bool(vals) and vals != _prev and vals != "—"
            _unit = "—"
            _phys = str(live_t.get("verdict") or "—")
            _hz = live_t.get("hz")
            cells = [
                tt,
                self._layer_of(topic, live_t),          # 🏷 Layer (L2~L5 / SYS)
                self._sig_names((live_t.get("fields") or {}) or rec.get("digest")),
                vals if vals else "—",
                _unit,
                _phys,
                self._type_of(topic, live_t),
                self._tx_of(topic, live_t),
                self._rx_of(topic, live_t),
                _qos_names.standard(live_t.get("qos")),
                ("%.1f" % _hz) if isinstance(_hz, (int, float)) else "—",
            ]
            _step_hit = topic in _cur_topics                         # 🔌 单步当前节点的输出 topic
            _hitrow = _step_hit or (bool(_pin) and (_pin in topic.lower()
                                                   or _pin in str(rec.get("type", "")).lower()))
            for c, txt in enumerate(cells):
                item = QTableWidgetItem(str(txt))
                item.setFont(QFont(MONO if c in (0, 1, 2, 3, 7, 9) else UI, 10))
                if c == 0:
                    item.setForeground(QColor(C_BLUE))
                elif c == 1:                                           # 话题名
                    item.setToolTip(topic)
                    item.setForeground(QColor(C_WHITE))
                elif c == 2:                                           # 🆕 信号名称
                    item.setForeground(QColor("#9db4d0"))
                elif c == 3:                                           # 实时值列
                    item.setForeground(QColor(C_GREEN if _changed else C_GRAY))
                    item.setToolTip("实时值(来自 live.json fields)\n"
                                    + ("本次刷新有变化 ⇒ 动态数据" if _changed else "与上一帧相同"))
                elif c == 6:
                    try:
                        v = float(score) * 100
                        item.setForeground(QColor(C_GREEN if v >= 99 else C_YELLOW if v > 0 else C_GRAY))
                    except Exception:                                        # noqa: BLE001
                        pass
                if _step_hit:                                          # 🔌 单步: 金色高亮 (与画布单步节点同色)
                    item.setBackground(QColor("#2b2611"))
                    if c == 1:
                        item.setForeground(QColor("#ffd700"))
                    elif c == 3:
                        item.setForeground(QColor("#ffd700"))
                        item.setToolTip("🔌 单步调试: 这是当前单步节点输出的 topic (载荷已序列化)")
                elif _hitrow:                                          # 📌 置顶命中: 整行高亮
                    item.setBackground(QColor("#1b2c1e") if c == 3 else QColor("#16202b"))
                    if c == 3:
                        item.setForeground(QColor("#7ee787"))
                elif r % 2:                                            # 质检: 斑马纹
                    item.setBackground(QColor("#12171e"))
                self.tb.setItem(r, c, item)
            if _vkey:
                lv = getattr(self, "_lv_last", None) or {}
                lv[topic] = vals
                self._lv_last = lv
        self.tb.setUpdatesEnabled(True)

    def _fill_alerts(self):
        alerts = []
        # ① 总线层 (频率/丢包/配对/帧龄)
        for key, t in (self._topics() or {}).items():
            for r in (t.get("rules") or []):
                if not r.get("ok"):
                    alerts.append((r.get("level", "warn"), t.get("topic", key),
                                   "%s: %s" % (r.get("rule", "—"), r.get("msg", ""))))
        # ② 物理层 (2026-10-17 老倪: 「报警要面向物理值不符合物理规律, 超最大/最小值」)
        try:
            # 只对**实测数值**做物理判据: 占位/信封(未上线)与 "—" 不是越界, 否则整表刷红 (实测 1429 条假警)
            frames = [{"topic": r["name"], "name": r["signal"], "value": r["value"],
                       "unit": None if r.get("unit") in (None, "—") else r["unit"],
                       "vmin": r.get("lo"), "vmax": r.get("hi"), "prev": r.get("prev")}
                      for r in (getattr(self, "_trace_frames", None) or [])
                      if r.get("signal") not in (None, "—", "value")
                      and r.get("src") not in ("占位", "信封")
                      and str(r.get("value")) not in ("—", "")]
            for a in _quality.scan_frames(frames):
                alerts.append((a.get("level", "warn"), a.get("object", "—"),
                               "%s: %s" % (a.get("rule", "rule"), a.get("msg", ""))))
        except Exception:                                                    # noqa: BLE001
            pass
        # ③ 3D 场景 ↔ 原子技能位姿一致性 (老倪 2026-10-17: 「每个信号如果与 3D 动画不符合,
        #    都要在全局数据空间 QoS 报警」) —— 判据在 middleware/pose_check.py, 可单测。
        try:
            from lerobot.middleware import pose_check as _pc
            _ss = os.path.join(os.path.dirname(DS_DIR), "ss_live")
            with open(os.path.join(_ss, "trace_live.json"), encoding="utf-8") as _f:
                _tl = json.load(_f)
            with open(os.path.join(_ss, "skill_phys.json"), encoding="utf-8") as _f:
                _sp = json.load(_f)
            for _lv, _ob, _msg in _pc.check(_tl, _sp, tol_mm=5.0):
                alerts.append((_lv, _ob, _msg))
        except Exception:                                                    # noqa: BLE001
            pass
        seen, uniq = set(), []
        for a in alerts:                                                       # 质检: 同一规则+同文本重复出现 ⇒ 去重
            k = (a[0], a[1], a[2])
            if k not in seen:
                seen.add(k)
                uniq.append(a)
        alerts = uniq
        if not alerts:      # 空表要说清"是真没有, 不是没接上" —— 否则没人信这个窗口在工作
            alerts = [("info", "—", "无告警 · 判据: 超上限/低于下限(声明量程) · 物理规律(概率≤1·质量≥0·"
                                 "温度≥-273.15·压力≥0·角度|≤720|) · NaN/inf/非数值 · 无单位 · 跳变")]
        rank = {"fail": 0, "error": 0, "warn": 1, "unknown": 2, "info": 3}
        alerts.sort(key=lambda a: rank.get(a[0], 9))
        self.tb_alert.setRowCount(len(alerts))
        for i, (lvl, obj, msg) in enumerate(alerts):
            icon = {"fail": "🔴", "error": "🔴", "warn": "🟡", "info": "⚪"}.get(lvl, "⚪")
            col = {"fail": C_RED, "error": C_RED, "warn": C_YELLOW}.get(lvl, C_GRAY)
            for c, txt in enumerate([f"{icon} {lvl}", obj, msg]):
                item = QTableWidgetItem(str(txt)[:300])
                if c == 0:
                    item.setForeground(QColor(col))
                if c == 1:
                    item.setFont(QFont(MONO, 9))
                self.tb_alert.setItem(i, c, item)
        _n_bad = sum(1 for a in alerts if a[0] in ("fail", "error", "warn"))
        self._btns["alert"].setText("⚠ 质量告警 (%d)" % _n_bad)    # info 行不算"有告警"

    # ─────────────────── 选中 → 详情 ───────────────────
    def _on_tree_click(self, it, _col):
        data = it.data(0, Qt.UserRole)
        if not data:
            return
        self._sel_kind, self._sel_obj = data
        self._fill_detail()

    def _on_trace_click(self, it):
        top = self.tb.item(it.row(), 2)
        if top is not None:
            self._sel_kind, self._sel_obj = "topic", top.text()
            self._fill_detail()

    def _detail_text(self):
        if not self._sel_obj:
            return "点左侧 Data 表 或 Trace 任意一行 → 这里显示该对象的完整属性与质量判据(逐条)。"
        kind, key = self._sel_kind, self._sel_obj
        topics, db = self._topics(), (self._busdb or {})
        out = []
        if kind == "topic":
            t = topics.get(key) or {}
            m = (db.get("messages") or {}).get(key) or {}
            lamp_txt = "%s %s" % (LAMP_ICON.get(t.get("lamp") or "", "—"),
                                  t.get("lamp_reason") or "")
            # 🔴 2026-10-17 老倪: 「信号表右侧的详细信息 topic类型 怎么都没改? 要数据一致, 改一样」
            #   真根因: 左表读注册表, 详情读 live.json/busdb 快照里的旧 type ⇒ 同一行两个说法。
            #   口径: 两边都走 topic_types.describe(), 表格与详情只有一个真源。
            _dt, _dcn = "", ""
            try:
                from lerobot.middleware import topic_types as _tt
                _d = _tt.describe(t.get("topic") or m.get("topic") or key)
                _dt, _dcn = (_d.get("type") or ""), (_d.get("cn") or "")
            except Exception:                                                # noqa: BLE001
                pass
            _ttype = _dt or str(t.get("type") or m.get("type", "—"))
            out += ["🚌 报文  %s" % (t.get("topic") or m.get("topic") or key),
                    "─" * 52,
                    _pad("类型", 14) + _ttype,
                    _pad("类型含义", 14) + (_dcn or "—"),
                    _pad("QoS", 14) + str(t.get("qos") or m.get("qos", "—")),
                    _pad("设计频率", 14) + _num(t.get("hz_design") or m.get("hz_design"), 2, " Hz"),
                    _pad("实测频率", 14) + _num(t.get("hz"), 2, " Hz"),
                    _pad("抖动", 14) + _num(t.get("jitter_ms"), 2, " ms"),
                    _pad("丢包", 14) + _num(t.get("loss_pct"), 1, " %"),
                    _pad("帧龄", 14) + _num(t.get("age_s"), 2, " s"),
                    _pad("累计报文", 14) + str(t.get("count", "—")),
                    _pad("字节", 14) + str(t.get("bytes", "—")),
                    _pad("匹配发布者", 14) + str(t.get("matched_pubs", "—")),
                    _pad("质量判决", 14) + "%s (score %s)" % (t.get("verdict", "—"), _num(t.get("score"), 2)),
                    _pad("灯", 14) + lamp_txt.strip(),
                    _pad("生产者", 14) + str(m.get("producer", "—")),
                    "", "质量判据(逐条)"]
            for r in (t.get("rules") or []):
                out.append("  %s %-12s %s" % ("✔" if r.get("ok") else "✘", r.get("rule", ""), r.get("msg", "")))
            # 最近一帧摘要(来自 trace.jsonl 的 digest —— 探针对 ss_plan 写的是一行可读摘要,
            # 而不是 768 个数字; 老倪要"逐帧对", 这行就是他直接读的那行)
            _dg = ""
            for _rec in reversed(self._trace_rows[-600:]):
                if str(_rec.get("topic", "")).split("/")[-1] in (key, str(t.get("topic", "")).split("/")[-1]) \
                        and _rec.get("digest"):
                    _dg = str(_rec["digest"])
                    break
            if _dg:
                out += ["", "🧾 最近一帧摘要 (trace digest)", "  " + _dg]
            f = t.get("fields") or {}
            if f:
                out += ["", "载荷字段(实测值)"]
                for k in list(f)[:24]:
                    out.append("  " + _pad(k, 18) + _short_val(f[k]))
        elif kind == "signal":
            for s in (db.get("signals") or []):
                if s.get("sid") == key:
                    out += ["🔗 信号  %s  (连线 %s)" % (key, s.get("link_id", "—")), "─" * 52,
                            _pad("来源", 14) + "%s . %s" % (s.get("src"), s.get("src_port", "?")),
                            _pad("", 14) + str(s.get("src_name", "")),
                            _pad("去向", 14) + "%s . %s" % (s.get("dst"), s.get("dst_port", "?")),
                            _pad("", 14) + str(s.get("dst_name", "")),
                            _pad("标签", 14) + str(s.get("label", "—")),
                            _pad("层级", 14) + str(s.get("layer", "—")),
                            _pad("话题", 14) + str(s.get("topic", "—")),
                            _pad("类型", 14) + _sig_type_txt(s.get("topic"), "zmax::LinkValue")]
                    break
        else:
            n = (db.get("nodes") or {}).get(key) or {}
            out += ["🧩 节点  %s" % key, "─" * 52,
                    _pad("名称", 14) + str(n.get("name", "—")),
                    _pad("类型", 14) + str(n.get("type", "—")),
                    _pad("层级", 14) + str(n.get("layer", "—")),
                    _pad("画布坐标", 14) + "(%s, %s)" % (n.get("x"), n.get("y")),
                    _pad("出/入线数", 14) + "tx %s / rx %s" % (n.get("tx", 0), n.get("rx", 0))]
        return "\n".join(out)

    def _fill_detail(self):
        self.detail.setText(self._detail_text())

    def copy_detail(self):
        try:
            QGuiApplication.clipboard().setText(self._detail_text())
            self.detail.setToolTip("已复制到剪贴板")
        except Exception:                                                    # noqa: BLE001
            pass


_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")


def short_name(x, n=12):
    """节点显示名: 去 emoji / 去括号注释, **不截断** (老倪 2026-10-17: 「你的字符不要显示...
    Tx Rx 都看不全, 不要截断省略」)。列宽按内容算, 放不下就走横向滚动, 不拿省略号糊弄。"""
    t = _EMOJI.sub("", str(x or "")).strip()
    t = t.split("(")[0].split("（")[0].strip()
    return t


def build_view(main_win=None, standalone=False) -> QWidget:
    return BusView(main_win=main_win, standalone=standalone)
