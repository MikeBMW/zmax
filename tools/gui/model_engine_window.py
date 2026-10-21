#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 模型引擎窗口 — L2~L5 训练与推理状态 · 集中查看 + 控制 + 执行任务工程

老倪 2026-10-14 原话:
> 「改变模型配置，L2~L5 在模型引擎窗口，要能方便的查看控制所有模型的训练状态，执行任务工程」

本窗口做三件事 (全部走真源, 不编数):
  ① 看   : 一屏列出 L2/L3/L4/L5 —— 在役模型 · 版本 · 本层产物数 · 推理中 · 训练中(进度) · 最近训练 · 权重路径
            数据真源: tools/model_inventory.py --json (nvidia-smi + 四层清单 + 训练进程)
                      http://127.0.0.1:8796/status/all (在役/候选/推理中标记)
  ② 控   : 选中一层 → ▶ 训练本层 / ■ 停止 / 📄 训练日志 / 📂 权重目录
            命令真源: config/mcd/param_registry.json 的 model.train_entry (与配置中心「模型配置」逐字一致)
  ③ 执行 : 🚀 执行任务工程 = tools/zmax_open.py step2 --activate --task <当前任务>
            (与主窗口右下角「🚀 启动工程」同一执行体)

纪律 (老倪口径):
  · 同刻只允许一个训练进程 (8GB 卡: 两个模型同刻常驻会 OOM) —— 有任务在跑时 ▶ 变灰
  · 停不下来不许假装: 停止是真 SIGTERM 进程组, 并回读进程是否真没了
  · 训练输出逐行落日志面板 + tools/joint_train_*/<层>.log, 不吞错误

自检 (离屏, 不碰真训练):
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/gui/model_engine_window.py --selftest --shot /tmp/me.png
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QDialog, QHBoxLayout, QHeaderView, QLabel,
                            QSizePolicy,
                             QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
sys.path.insert(0, os.path.join(ROOT, "tools"))
try:                                     # 候选行真源 = 与配置中心「模型配置」/配置通道同一份
    from model_config_matrix import candidate_rows as _candidate_rows
except Exception:                                                            # noqa: BLE001
    def _candidate_rows(models, st_models=(), layers=None):
        return []
if not os.path.exists(PY):
    PY = sys.executable

# 配色 (与 status_panel / hw_widgets 同一套口径)
C_BG, C_BG2, C_CARD, C_BORDER = "#0d1117", "#161b22", "#161b22", "#30363d"
C_WHITE, C_GRAY, C_DIM = "#e6edf3", "#8b949e", "#6e7681"
C_GREEN, C_YELLOW, C_RED, C_CYAN, C_BLUE = "#3fb950", "#d29922", "#f85149", "#39d0d8", "#58a6ff"
UI, MONO = "Noto Sans CJK SC", "Consolas"
LAYERS = ("L2", "L3", "L4", "L5")


def _short_path(p, keep=64):
    """显示用短路径: 家目录缩成 ~ 并保留**尾部** (路径区分度在尾部: .../s3072/weights_epoch_xx)。
    完整路径永远进 tooltip + 双击复制 + 📋复制状态 ⇒ 省略号只影响"一眼看", 不影响"能拿到"。"""
    s = str(p or "")
    s = s.replace("/home/" + os.environ.get("USER", "ubuntu") + "/zmax/", "~/zmax/")
    if len(s) <= keep:
        return s
    t = s[-(keep - 1):]
    if "/" in t:                                   # 从**目录分隔符**处切, 不把目录名切一半 (读屏实测: la-lew/ 看着像另一层目录)
        t = t[t.index("/") + 1:]
    return "…" + t

def _pid_alive(pid):
    """pid 是否还在 (真源 inventory 会留陈旧训练行 ⇒ 不判活就会写出"训练中"骗人)。"""
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except Exception:                                                                  # noqa: BLE001
        return False


def _train_cell(t):
    """训练状态一格: 真源 inventory.training[] 的进度在 **progress 子字典** 里
    (progress={found,raw,step,total}), 也不一定有顶层 pct ⇒ 先看 progress 再回退顶层, 都缺才写"进度未报"
    (不能写出 "None% (None/None)" —— 那是"看着像有数据其实是坏数据")。"""
    if not t:
        return "否"
    p = t.get("progress") or {}
    step = p.get("step", t.get("step"))
    total = p.get("total", t.get("total"))
    pct = t.get("pct")
    if pct is None and step is not None and total:
        try:
            pct = int(round(100.0 * float(step) / float(total)))
        except Exception:                                                              # noqa: BLE001
            pct = None
    if pct is None:
        # 有些训练器 (如 YOLO 的 yolo_annot_train) 不产出 inventory 能解析的进度行 ⇒ 退到"已跑多久"
        # (真源 elapsed_s), 再不行才写"进度未报"。**不编百分比**。
        el = t.get("elapsed_s")
        return ("训练中 · 已 %ds" % int(el)) if el else "训练中 · 进度未报"
    return "▶ %s%% (%s/%s)" % (pct, step, total)


def _text_px(s, px=18):
    """显示串在表字号 (18px) 下的像素宽 —— 用来按预算收显示串 (不用 ElideNone 硬切)。"""
    global _FMC
    try:
        fm = _FMC[px]
    except NameError:
        _FMC = {}
        fm = None
    if fm is None:
        f = QFont()
        f.setPixelSize(px)
        from PyQt5.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        _FMC[px] = fm
    return fm.horizontalAdvance(str(s))


def _fit_cell(s, budget):
    """把显示串按像素预算收进列宽: 先去尾部括号限定词, 还超再按宽度截断带 "…"。

    完整串始终进 tooltip (老倪: 内容要看得全/可复制, 但不许把列挤变形)。
    """
    s = str(s or "")
    if _text_px(s) <= budget:
        return s
    import re as _re
    s2 = _re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", s).strip()
    if not s2:
        s2 = s
    if _text_px(s2) <= budget:
        return s2
    out = ""
    for ch in s2:                                     # 逐字加, 超预算就停 (CJK/ASCII 混排也准)
        if _text_px(out + ch + "…") > budget:
            break
        out += ch
    return (out + "…") if out else s2[:1] + "…"


def _inservice_name(ly, a, sm, mine):
    """在役行的「模型名」= **真名** (老倪 2026-10-14: 「要改成真实模型的名字, 例如 L2 YOLO」)。

    真源优先级(与主界面「配置通道」model_config_matrix 完全同一条规则 ⇒ 两处同值):
      ① 8796 /status/all 里该层**引擎实际加载**的在役模型名 (L5 = "DeepSeek 视觉规划 (L5 大模型主路)")
      ② tools/model_inventory.py 在役行名 (原 ① 为空的兜底; 它自己也是读 models/active_models.json 真名)
    返回 (显示串, 完整串) —— 显示串按列宽像素预算收, 完整串只进 tooltip。
    """
    full = ""
    for m in (sm or []):
        nm = str(m.get("name") or "").strip()
        if nm:
            full = nm
            break
    if not full:
        full = str(a.get("name") or "").strip()
    full = re.sub(r"^L\d\s*[·:：]\s*", "", full) if full else ""
    if not full:
        full = "—"
    return _fit_cell(full, 340 - 20), full


def _disk_name(a):
    """本层**磁盘上**在役产物的真名 (inventory 走的 models/active_models.json / ckpt 自身 config.json)。"""
    return re.sub(r"^L\d\s*[·:：]\s*", "", str((a or {}).get("name") or "").strip())


def _fam(s):
    """粗取模型家族词 (串首的 ASCII 段, 如 YOLO / SmolVLA+LEW / INTACT-JEPA / SmolVLM / DeepSeek)。"""
    m = re.match(r"[A-Za-z0-9][A-Za-z0-9\-\+._]*", str(s or "").strip())
    return (m.group(0).lower() if m else "")


def _short_ts(s):
    """列里只放 MM-DD HH:MM (完整时间戳进 tooltip) — 列宽 132px 放不下 2026-10-14 08:09:33。

    2026-10-14 读屏实测: L5 这层的"最近训练"是**产物目录名** `20261014_141727` (不是 ts),
    与 L2/L3/L4 的 `10-14 08:09` 格式不一致 ⇒ 这里一并归一成 MM-DD HH:MM (认不出来就原样返回)。
    """
    import re as _re
    t = str(s or "")
    r = _re.search(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2})", t)
    if r:
        return "%s-%s %s" % (r.group(2), r.group(3), r.group(4))
    r = _re.search(r"(\d{4})(\d{2})(\d{2})[_T](\d{2})(\d{2})", t)     # 20261014_141727 → 10-14 14:17
    if r:
        return "%s-%s %s:%s" % (r.group(2), r.group(3), r.group(4), r.group(5))
    return t


INV_CMD = [PY, os.path.join(ROOT, "tools", "model_inventory.py"), "--json"]
STATUS_URL = os.environ.get("ZMAX_STATUS_URL", "http://127.0.0.1:8796/status/all")
REG_JSON = os.path.join(ROOT, "config", "mcd", "param_registry.json")

BTN = (f"QPushButton{{background:{C_BG2};color:{C_WHITE};border:1px solid {C_BORDER};"
       f"border-radius:6px;padding:7px 14px;font-size:19px}}"
       f"QPushButton:hover{{border-color:{C_CYAN}}}"
       f"QPushButton:disabled{{color:{C_DIM};border-color:{C_BORDER}}}")


def _train_entries():
    """逐层训练命令 —— 真源 = 配置中心「模型配置」的 model.train_entry (不另写一份)。"""
    try:
        with open(REG_JSON, encoding="utf-8") as f:
            reg = json.load(f)
        for p in reg.get("params", []):
            if p.get("id") == "model.train_entry" and isinstance(p.get("value"), dict):
                return p["value"]
    except Exception:                                                                    # noqa: BLE001
        pass
    return {}


def _active_task():
    """当前任务 = 绑定真源 config/ss_task_binding.json 的 active_task (取不到返回空)。"""
    for p in ("config/ss_task_binding.json", "config/tasks/active.json"):
        fp = os.path.join(ROOT, p)
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
            return d.get("active_task") or d.get("task_id") or ""
        except Exception:                                                                # noqa: BLE001
            continue
    return ""


def _conv_short(txt):
    """'tools/edge/ov_export_torch.py → tools/edge/ov_convert.py' → 'ov_export_torch → ov_convert'。
    窄列只放得下这个长度; 完整命令行在 tooltip 与双击单元格里 (可复制)。"""
    s = str(txt or "—")
    if "tools/edge/" in s:
        return (s.replace("tools/edge/", "").replace(".py", "").split(" (")[0].strip() or "—")
    if "torch 直跑" in s:
        return "无 · torch 直跑"
    if "云端 API" in s:
        return "无 · 云端 API"
    if "独立服务" in s:
        return "无 · 服务内"
    return s.split(" (")[0].strip() or "—"


class _Fetcher(threading.Thread):
    """后台取数: model_inventory --json + 8796 /status/all (阻塞 I/O 绝不进 GUI 线程)。"""

    def __init__(self, out, interval=5.0):
        super().__init__(daemon=True)
        self.out, self.interval = out, float(interval)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            inv, st = {}, {}
            try:
                r = subprocess.run(INV_CMD, cwd=ROOT, capture_output=True, text=True, timeout=120)
                inv = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip().startswith("{") else {}
            except Exception as e:                                                        # noqa: BLE001
                inv = {"_err": "%s: %s" % (type(e).__name__, e)}
            try:
                with urllib.request.urlopen(STATUS_URL, timeout=1.2) as r:
                    st = json.loads(r.read(262144).decode("utf-8", "replace"))
            except Exception:                                                             # noqa: BLE001
                st = {}
            self.out.put((inv, st, time.time(), self._runtime(inv)))
            self._stop.wait(self.interval)

    def _runtime(self, inv=None):
        """运行位置/权重/转换工具/推理-训练 的真源 (60s 一次: 里面要 hash 权重, 不能每 tick 都做)。"""
        try:
            if time.time() - getattr(self, "_rt_ts", 0) < 60 and getattr(self, "_rt_d", None):
                return self._rt_d
            sys.path.insert(0, os.path.join(ROOT, "tools"))
            import model_runtime_map as mrm                                        # noqa: PLC0415
            d = mrm.build(inv)
            if d.get("ok"):
                try:
                    os.makedirs(os.path.dirname(mrm.OUT_J), exist_ok=True)
                    with open(mrm.OUT_J + ".tmp", "w", encoding="utf-8") as f:
                        json.dump(d, f, ensure_ascii=False, indent=1)
                    os.replace(mrm.OUT_J + ".tmp", mrm.OUT_J)
                except Exception:                                                  # noqa: BLE001
                    pass
            self._rt_d, self._rt_ts = d, time.time()
            return d
        except Exception as e:                                                     # noqa: BLE001
            return {"_err": "%s: %s" % (type(e).__name__, e), "items": []}


class ModelEnginePanel(QWidget):
    """🧠 模型引擎 (L2~L5) —— **主界面「模型引擎」功能区与独立窗口共用的同一个界面**。

    老倪 2026-10-14: 「现在的模型引擎，与主界面功能区的模型引擎，界面应该是一个」
    ⇒ 这一个类就是那个界面 (四层状态表 + 控制按钮 + 日志), 页面里内嵌它,
      独立窗口 (`ModelEngineWindow`) 只是把它装进 QDialog 弹出来 —— 不存在第二套布局。
    """

    def __init__(self, parent=None, poll=True, interval=5.0):
        super().__init__(parent)
        self.setObjectName("modelEnginePanel")
        self._proc = None                 # 正在跑的训练进程
        self._proc_layer = ""
        self._q = queue.Queue()
        self._log_q = queue.Queue()
        self._inv, self._st, self._age = {}, {}, None
        self._rt = {}                     # 运行位置/运行权重/转换工具 真源 (model_runtime_map)
        self._logdir = os.path.join(ROOT, "reports")
        self._build()
        if poll:
            self._fetcher = _Fetcher(self._q, interval)
            self._fetcher.start()
            self._t = QTimer(self)
            self._t.timeout.connect(self._drain)
            self._t.start(600)
            self._lt = QTimer(self)
            self._lt.timeout.connect(self._drain_log)
            self._lt.start(250)

    # ─────────────────────────── UI ───────────────────────────
    def _build(self):
        self.setStyleSheet(f"#modelEnginePanel{{background:{C_BG}}}"
                           f" #modelEnginePanel QLabel{{color:{C_WHITE}}}"
                           f" #modelEnginePanel QTableWidget{{background:{C_BG2}}}")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(8)

        head = QHBoxLayout()
        self.lb_head = QLabel("🧠 模型引擎 · L2~L5（读取中…）")
        self.lb_head.setStyleSheet(f"color:{C_WHITE};font-size:23px;font-weight:700;background:transparent")
        head.addWidget(self.lb_head)
        head.addStretch()
        self.lb_task = QLabel("任务: %s" % (_active_task() or "—"))
        self.lb_task.setStyleSheet(f"color:{C_CYAN};font-size:18px")
        head.addWidget(self.lb_task)
        v.addLayout(head)

        # 2026-10-21 老倪: 「在模型引擎, 增加 每个模型在哪里运行, 运行的是哪个权重, 对应的转换工具,
        #   是正在推理, 还是在训练」。⇒ 插三列 (运行位置/运行权重/转换工具), "推理" 升为 "状态" (推理中/训练中/空闲),
        #   真源 = config/platform/model_runtime_map.json (tools/model_runtime_map.py 现算, 界面不自己猜设备)。
        cols = ("层", "在役模型", "在役版本", "运行位置", "运行权重", "转换工具",
                "本层产物", "状态", "训练中", "最近训练", "在役权重路径")
        self.tb = QTableWidget(len(LAYERS), len(cols))
        self.tb.setHorizontalHeaderLabels(cols)
        self.tb.verticalHeader().setVisible(False)
        self.tb.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tb.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tb.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tb.setStyleSheet(
            f"QTableWidget{{background:{C_CARD};color:{C_WHITE};border:1px solid {C_BORDER};"
            f"border-radius:8px;font-size:18px;gridline-color:{C_BORDER}}}"
            f"QHeaderView::section{{background:{C_BG2};color:{C_GRAY};border:none;padding:6px;font-size:17px}}"
            f"QTableWidget::item:selected{{background:{C_BLUE}33;color:{C_WHITE}}}")
        hh = self.tb.horizontalHeader()
        # 列宽按"真实文字不被省略号截断"定 (2026-10-14 实测: 1360 宽时代码 190px 的版本列与路径列全被截断)
        # (层, 在役模型, 在役版本, 本层产物, 推理, 训练中, 最近训练) — 逐列按真实文字定宽;
        # 训练中列要放得下 "训练中 · 进度未报"(140px) 与 "45% (9/20)"; 版本列留 ≥24px 余量(ElideNone 余量不足会硬切)
        # 2026-10-14: 层列 56→132 (候选行要写 "🔎 L2 · 候选", 56px 会硬切); 在役模型列 258→340 (候选行
        #   "SAM3基座848M · 适配器annot_v1 +1" 要放得下) —— 两处都服从"宁可挤别列, 不许截断"
        # 2026-10-21 新三列按真实文字定宽 (运行位置 "NPU×2 97% · GPU×1 96%" / 运行权重 "yolo_peg_live 61f9541d" /
        #   转换工具 "ov_export_torch → ov_convert"); 路径列仍 Stretch, 窄屏走横滚不截断。
        for i, wdt in enumerate((132, 320, 210, 268, 330, 234, 92, 96, 150, 170)):
            hh.setSectionResizeMode(i, QHeaderView.Fixed)
            self.tb.setColumnWidth(i, wdt)
        hh.setSectionResizeMode(10, QHeaderView.Stretch)
        self.tb.setTextElideMode(Qt.ElideNone)      # 宁可横滚也不截断 (老倪: 内容要看得全/可复制)
        self.tb.setWordWrap(False)
        self.tb.itemSelectionChanged.connect(lambda: self._sync_btns())
        self.tb.itemDoubleClicked.connect(self._copy_cell)
        # 表格高度 = 表头 + 4 行 (2026-10-14 读屏实测: 写死 168/210 时页面里只显示得下 2 行, L4/L5 被挤出视口;
        #   而写死更大值在独立窗口里留一大片空行) ⇒ 改成按内容自适应, 在 _render 里按真实行高算。
        v.addWidget(self.tb, 0)
        # 2026-10-14 老倪: 「单独打开的模型引擎窗口 与 功能区模型引擎标签打开的界面 要保持一致」。
        #   末列(权重路径)是 Stretch ⇒ 表宽跟随父容器 ⇒ 两个界面**被裁的位置不同**。实测三种情形:
        #     窗口(1900) 路径列 622px · 窄容器(1400) 只剩 100px · **功能区页面会撑到 2497px(路径列 1253px, 全不裁)**
        #   ⇒ 用户看到"同一个模型引擎, 两个地方显示两个样"。
        #   口径: 设计宽**钉死** = 窗口设计宽 1900 (setFixedWidth, 不是 SetMinimum: minimum 挡不住页面把它撑大)。
        #   页面侧放不下就整页横向滚 —— 宁可滚/留白, 不许两处显示两个样。
        # 🖥 2026-10-14 老倪: 「独立打开的模型引擎窗口无法调宽度, 横向都出单个屏幕了, 而且无法最大化」
        #   真因: `setFixedWidth(1900)` 把宽度钉死 ⇒ 既拖不动, 也把最大化的可能性一起锁死。
        #   口径改成: 1900 只是**设计宽/默认宽**, 窗口可自由拖宽/最大化; 列宽按设计比例随宽度重算
        #   (`_refit`), 窄到放不下就走横滚 —— 内容永远不用省略号截断。
        self.DESIGN_W = 2212
        self._base_cols = (132, 320, 210, 268, 330, 234, 92, 96, 150, 170)
        self.setMinimumWidth(980)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        row = QHBoxLayout()
        self.btn_train = QPushButton("▶ 训练本层")
        self.btn_train.setToolTip("执行配置中心「模型配置」里该层的训练入口 (model.train_entry, 逐字一致)")
        self.btn_stop = QPushButton("■ 停止")
        self.btn_stop.setToolTip("真 SIGTERM 该训练进程组, 并回读是否真停")
        self.btn_log = QPushButton("📄 训练日志")
        self.btn_log.setToolTip("打开/尾随 tools/joint_train_*/<层>.log")
        self.btn_dir = QPushButton("📂 权重目录")
        for b in (self.btn_train, self.btn_stop, self.btn_log, self.btn_dir):
            b.setStyleSheet(BTN)
            row.addWidget(b)
        row.addStretch()
        self.btn_task = QPushButton("🚀 执行任务工程")
        self.btn_task.setToolTip("tools/zmax_open.py step2 --activate --task <当前任务>: 应用场景→启动工程/信号/场景")
        self.btn_task.setStyleSheet(BTN)
        self.btn_copy = QPushButton("📋 复制状态")
        self.btn_copy.setStyleSheet(BTN)
        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.setStyleSheet(BTN)
        for b in (self.btn_task, self.btn_copy, self.btn_refresh):
            row.addWidget(b)
        v.addLayout(row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        f = QFont(MONO)
        f.setPixelSize(13)
        self.log.setFont(f)
        self.log.setStyleSheet(f"QPlainTextEdit{{background:{C_BG2};color:{C_GRAY};border:1px solid {C_BORDER};"
                               f"border-radius:8px;padding:6px}}")
        self.log.setPlaceholderText("训练 / 执行任务工程的实时输出会落在这里（逐行，不吞错误）")
        v.addWidget(self.log, 2)

        self.btn_train.clicked.connect(self._on_train)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_log.clicked.connect(self._on_log)
        self.btn_dir.clicked.connect(self._on_dir)
        self.btn_task.clicked.connect(self._on_task)
        self.btn_copy.clicked.connect(self._on_copy)
        self.btn_refresh.clicked.connect(self._force_refresh)
        self._sync_btns()

    # ─────────────────────────── 取数 ───────────────────────────
    @staticmethod
    def default_w():
        """默认宽: 设计宽 1900 与屏幕可用宽取小 —— 窗口与功能区页面**默认就用这一个宽度**,
        用户可在此基础上把窗口拖宽/最大化 (这才叫"能调宽度", 同时两处默认视图仍然一致)。"""
        try:
            _scr = QApplication.primaryScreen()
            _av = _scr.availableGeometry() if _scr else None
            return max(980, min(1900, (_av.width() - 80) if _av else 1900))
        except Exception:                                                        # noqa: BLE001
            return 1900

    def _refit(self, w=None):
        """列宽按**设计比例**随面板宽度重算 (不缩到设计宽以下 —— 再窄就走横滚, 不省略号)。"""
        w = int(w or self.width() or self.DESIGN_W)
        k = max(1.0, (w - 34) / float(self.DESIGN_W - 34))
        hh = self.tb.horizontalHeader()
        for i, base in enumerate(self._base_cols):
            hh.setSectionResizeMode(i, QHeaderView.Fixed)
            self.tb.setColumnWidth(i, int(round(base * k)))

    def resizeEvent(self, e):                                        # noqa: N802
        super().resizeEvent(e)
        try:
            self._refit(self.width())
        except Exception:                                            # noqa: BLE001
            pass

    def feed(self, inv, st=None, age=None, rt=None):
        """外部注入数据 (自检用) —— 与后台取数走同一条渲染路径。"""
        self._inv, self._st = inv or {}, st or {}
        self._rt = rt if rt is not None else getattr(self, "_rt", {})
        self._age = age if age is not None else time.time()
        self._render()

    def _drain(self):
        got = None
        while not self._q.empty():
            got = self._q.get()
        if got:
            self.feed(got[0], got[1], got[2], got[3] if len(got) > 3 else None)

    def _force_refresh(self):
        threading.Thread(target=lambda: self._q.put(self._fetch_once()), daemon=True).start()

    @staticmethod
    def _fetch_once():
        inv, st, rt = {}, {}, {}
        try:
            r = subprocess.run(INV_CMD, cwd=ROOT, capture_output=True, text=True, timeout=120)
            inv = json.loads(r.stdout) if r.returncode == 0 else {}
        except Exception as e:                                                            # noqa: BLE001
            inv = {"_err": "%s: %s" % (type(e).__name__, e)}
        try:
            with urllib.request.urlopen(STATUS_URL, timeout=1.2) as r:
                st = json.loads(r.read(262144).decode("utf-8", "replace"))
        except Exception:                                                                 # noqa: BLE001
            st = {}
        try:                                     # 运行位置/权重/转换工具 (与界面同一真源)
            sys.path.insert(0, os.path.join(ROOT, "tools"))
            import model_runtime_map as mrm                                            # noqa: PLC0415
            rt = mrm.build(inv)
        except Exception as e:                                                             # noqa: BLE001
            rt = {"_err": "%s: %s" % (type(e).__name__, e), "items": []}
        return inv, st, time.time(), rt

    # ─────────────────────────── 渲染 ───────────────────────────
    def _rows(self):
        """四层一行: 真源 model_inventory.models[] (+ 8796 的在役/推理标记 + training[] 进度)。"""
        inv = self._inv or {}
        models = [m for m in (inv.get("models") or []) if isinstance(m, dict)]
        st = self._st or {}
        st_models = [m for m in (st.get("models") or []) if isinstance(m, dict)]
        # 训练进程: 真源 inventory.training[]。实测它有 3 类脏数据 ⇒ 这里一次收口:
        #   ① 同一层多行 (L3 一个训练会带出 10+ 个同 config 的 pid 行) ② 层名有 "JOINT(L2)" 这种包裹
        #   ③ 有的行 progress.found=False (只有 pid, 没进度) —— 不能让它盖掉有进度的行。
        tr, tr_cnt = {}, {}
        for t in (inv.get("training") or []):
            if not isinstance(t, dict):
                continue
            pid = t.get("pid")
            if pid and not _pid_alive(pid):
                continue                     # 进程已死 ⇒ 这条是陈旧行, 不能算"训练中"
            # 联合训练编排器(joint_train_all)整轮都在跑, 它的行会带**上一层留下的进度文本**
            # ⇒ 再用"该层日志是否还在写"判活 (90s 内), 否则会出现"L2 和 L3 同时 70% (14/20)"这种假象。
            _lg = str(t.get("log") or "")
            if _lg and os.path.exists(_lg) and (time.time() - os.path.getmtime(_lg)) > 90:
                continue                     # 日志 90s 没动 ⇒ 这一层不在训练
            ly = str(t.get("layer") or "")
            m = re.match(r"^JOINT\((\w+)\)$", ly)
            if m:
                ly = m.group(1)
            if ly not in LAYERS:
                continue
            tr_cnt[ly] = tr_cnt.get(ly, 0) + 1
            cur = tr.get(ly)
            has_p = bool((t.get("progress") or {}).get("found"))
            cur_has = bool((cur or {}).get("progress", {}).get("found")) if cur else False
            if cur is None or (has_p and not cur_has):
                tr[ly] = t
        out = []
        for ly in LAYERS:
            mine = [m for m in models if str(m.get("layer")) == ly]
            act = [m for m in mine if m.get("active")] or []
            a = act[0] if act else (mine[0] if mine else {})
            sm = [m for m in st_models if str(m.get("layer")) == ly and str(m.get("state")) == "in_service"]
            infer = any(bool(m.get("inferring")) for m in sm)
            ver = ""
            for m in sm:
                ver = str(m.get("version") or "")
                break
            ln = ""
            for m in mine:
                ln = (m.get("last_train") or {}).get("ts") or ln
            t = tr.get(ly) or {}
            if mine:
                nm_cell, nm_full = _inservice_name(ly, a, sm, mine)
            else:
                nm_cell, nm_full = "—", "—"
            # 8786 报的名 vs 磁盘产物真名**家族不同**时留下来 (实测 L5: 引擎在役 = DeepSeek 视觉规划(云端 API 主路),
            #   磁盘另有本地合并产物 SmolVLM) ⇒ 不许让"名字"和"权重路径"指向两个不相干的东西还不说。
            _dk = _disk_name(a)
            nm_disk = _dk if (_dk and _fam(_dk) and _fam(_dk) != _fam(nm_full)) else ""
            out.append({
                "layer": ly,
                "name": nm_cell,                       # 真名 (8796 引擎在役 > inventory 真源), 按列宽收
                "name_full": nm_full,                  # 完整名 → tooltip (不丢信息)
                "name_disk": nm_disk,                  # 磁盘产物名 (家族不同才填; 见 tooltip)
                "ver": ver or "—",
                "n": len(mine),
                "infer": infer,
                # 2026-10-14: inventory 的 training[] 可能只报了 pid/层没报进度 ⇒ 不能拼出 "None% (None/None)"
                "train": _train_cell(t),
                "train_raw": (json.dumps(t, ensure_ascii=False)[:200] if t else "无训练进程"),
                "train_n": tr_cnt.get(ly, 0),
                "last": ln or "无训练记录",
                "path": (a.get("realpath") or a.get("path") or "—") if mine else "—",
                "active": bool(act),
                "layer_key": ly,
            })
        # 🧩 2026-10-14 老倪: 「每层模型都服役」—— extra_in_service 的条目 = **在役扩展行** (LoRA 适配层 /
        #   SAM3 感知原语 / L5 本地技能包), 与基座行并列显示, 不再是"灰 = 未切在役"。真源同 active_models.json。
        for ly in LAYERS:
            mine = [m for m in models if str(m.get("layer")) == ly]
            act = [m for m in mine if m.get("active")]
            for m in act[1:]:
                _e = m.get("serving_ext") or {}
                # 显示名必须放得进「在役模型」列 (340px 预算) —— 名字长了就压短, 完整名进 tooltip
                #   (老倪: 关键列不许省略号截断; 同一行两处界面裁切位置要一致 ⇒ 显示串必须定长预算)
                _short = {"L2": "SAM3 开放词汇分割 (在役原语)",
                          "L3": "LoRA 适配层 · 基座不动",
                          "L4": "LoRA 适配层 · 基座不动",
                          "L5": "本地 tool 技能包 (在役)"}.get(ly) or str(m.get("name") or "")
                out.append({
                    "layer": "   ↳ " + ly, "layer_key": ly, "ext": True,
                    "name": _short, "name_full": m.get("name"), "name_disk": "",
                    "ver": str(_e.get("kind") or "在役扩展"), "n": len(mine), "infer": False,
                    "train": "否", "train_raw": "在役扩展 (非候选) · %s" % str(_e.get("note") or ""),
                    "last": ((m.get("last_train") or {}).get("ts") or "无训练记录"),
                    "path": (m.get("realpath") or m.get("path") or "—"), "active": True,
                    "ext_role": _e.get("role"), "ext_note": _e.get("note"), "since": _e.get("since"),
                })
        # 🔎 候选行 (老倪 2026-10-14: 「在模型引擎里要增加 SAM3, 位置 L2」) —— 每层一条, 有候选才出。
        #    🧩 SAM3 就在 L2 这一行; 数据与配置中心「模型配置」/主界面「配置通道」**同源现算** (不另写一份)。
        try:
            for c in _candidate_rows(models, st_models, LAYERS):
                out.append({
                    "layer": c["layer_tag"], "layer_key": c["layer"], "cand": True,
                    "name": c["models"], "ver": c.get("ver") or "—", "n": c["n"],
                    "infer": False, "train": "否", "train_raw": "候选未在役 ⇒ 无训练进程",
                    "last": c["ts"], "path": c["path"], "active": False, "note": c["note"],
                })
        except Exception:                                                    # noqa: BLE001
            pass
        # ── 运行位置 / 运行权重 / 转换工具 / 状态 ────────────────────────────────────────
        # 老倪 2026-10-21: 「每个模型在哪里运行, 运行的是哪个权重, 对应的转换工具, 是正在推理, 还是在训练」
        #   真源 = config/platform/model_runtime_map.json (tools/model_runtime_map.py 现算: Intel /models 的 sha16 +
        #   /pipeline 的设备归属 + 本机在役 ckpt + 转换脚本)。界面**不自己猜**设备, 采集失败就写 "未加载"。
        by_ly = {}
        for it in ((getattr(self, "_rt", {}) or {}).get("items") or []):
            if isinstance(it, dict):
                by_ly.setdefault(str(it.get("layer")), []).append(it)
        for r in out:
            if r.get("cand"):
                r.update(where="未部署", weights="—", conv="—", statxt="—")
                continue
            if r.get("ext"):
                r.update(where="本机 8796 · torch/服务", weights="— 不进 IR", conv="无 (未转 IR)",
                         statxt="空闲")
                continue
            parts, wts, cvs = [], [], []
            for it in by_ly.get(str(r.get("layer_key")), []):
                seg = []
                for x in (it.get("runs") or []):
                    d = str(x.get("dev") or "")
                    duty = x.get("duty_pct")
                    if d == "云端":
                        seg.append("云端 API")
                    else:
                        _d = ("Intel " + d) if d in ("NPU", "GPU") else d
                        seg.append("%s%s%s" % (_d, ("×%s" % x.get("streams")) if x.get("streams") else "",
                                               (" %.0f%%" % duty) if isinstance(duty, (int, float)) else ""))
                parts.append(" · ".join(seg) or "未加载")
                irs = it.get("ir") or []
                if irs:
                    wts.append(" + ".join("%s %s" % (i.get("name"), i.get("sha16") or "?") for i in irs))
                elif it.get("kind") == "api":
                    wts.append("云端权重 · 本机 smolvlm 备用未转 IR" if it.get("note") else "云端权重 (无端侧)")
                elif it.get("source"):
                    _p = str(it["source"]).rstrip("/").split(os.sep)
                    _b = _p[-1] if _p else "—"
                    if _b in ("pretrained_model", "model", "last") and len(_p) >= 2:
                        _b = "%s/%s" % (_p[-2], _b)
                    wts.append(_b)
                else:
                    wts.append("—")
                cvs.append(_conv_short(it.get("converter")))
            _w = " · ".join(parts) or "未加载"
            r["where"] = _w.replace(" · Intel ", " · ")      # 只留一个 Intel 前缀 (窄列)
            r["weights"] = " · ".join(wts) or "—"
            r["conv"] = " · ".join(dict.fromkeys(cvs)) or "—"
            _rt_items = by_ly.get(str(r.get("layer_key")), [])
            _rt_infer = any(str(it.get("status")) == "inferring" for it in _rt_items)
            _rt_train = any(str(it.get("status")) == "training" for it in _rt_items)
            r["statxt"] = ("训练中" if (r.get("train") != "否" or _rt_train)
                           else ("推理中" if (r.get("infer") or _rt_infer) else "空闲"))
        return out

    def _render(self):
        rows = self._rows()
        inv = self._inv or {}
        gpu = (inv.get("gpu") or {})
        busy = sum(1 for r in rows if r["train"] != "否")
        self.lb_head.setText("🧠 模型引擎 · L2~L5　GPU %s%% · 显存 %s/%sMB · %s°C　训练中 %d　(占空=设备算力占用比)" % (
            gpu.get("util", "—"), gpu.get("mem_used", "—"), gpu.get("mem_total", "—"),
            gpu.get("temp", "—"), busy))
        self._rows_cache = rows
        self._sig = [(r["layer"], r["name"], r["ver"], r.get("where"), r.get("weights"), r.get("conv"),
                      r["n"], r.get("statxt"), r["train"], r["last"], r["path"]) for r in rows]
        if self.tb.rowCount() != len(rows):          # 候选行会让总行数 > 4 ⇒ 先扩表再写
            self.tb.setRowCount(len(rows))
        _nc = sum(1 for r in rows if r.get("cand"))
        _ne = sum(1 for r in rows if r.get("ext"))
        if _ne:
            self.lb_head.setText(self.lb_head.text() + "　✅ 在役扩展 %d 条" % _ne)
        if _nc:
            self.lb_head.setText(self.lb_head.text() + "　🔎 候选 %d 行 (灰 = 未切在役)" % _nc)
        for i, r in enumerate(rows):
            cand = bool(r.get("cand"))
            col = C_YELLOW if cand else (C_GREEN if r["active"] else C_RED)
            vals = ("🔎 " + r["layer"] if cand else r["layer"], r["name"], r["ver"],
                    (r.get("where") or "—"), (r.get("weights") or "—"), (r.get("conv") or "—"),
                    str(r["n"]), (r.get("statxt") or ("推理中" if r["infer"] else "空闲")),
                    r["train"], _short_ts(r["last"]), _short_path(r["path"]))
            for j, x in enumerate(vals):
                it = self.tb.item(i, j)
                if it is None:
                    it = QTableWidgetItem()
                    self.tb.setItem(i, j, it)
                it.setText(str(x))
                it.setData(Qt.UserRole, r["path"])          # 完整路径常驻单元格 (双击即复制)
                if j == 0:
                    fg = col
                elif cand:                                   # 候选行整体压暗 ⇒ 一眼看出"没在役"
                    fg = C_WHITE if j == 10 else C_GRAY
                elif j == 7 and r.get("statxt") == "推理中":
                    fg = C_CYAN
                elif j == 7 and r.get("statxt") == "训练中":
                    fg = C_YELLOW
                elif j == 8 and r["train"] != "否":
                    fg = C_YELLOW
                elif j == 4 and not cand:
                    fg = C_CYAN if (r.get("weights") or "").find("?") < 0 and r.get("weights") != "—" else C_WHITE
                else:
                    fg = C_WHITE
                it.setForeground(QColor(fg))
                if r.get("ext"):                             # 在役扩展行: 说清凭什么在役
                    tip = ("✅ 在役扩展 (%s) — %s\n"
                           "在役真源: models/active_models.json#extra_in_service[%s] · 与基座行并列服役\n"
                           "%s\n完整路径 (双击复制):\n%s\n%s"
                           % (r.get("ver") or "在役扩展", r.get("name_full") or r.get("name") or "",
                              r.get("layer_key"), (r.get("ext_role") or ""),
                              r.get("path") or "", ("生效起 %s" % r["since"]) if r.get("since") else ""))
                elif cand:
                    tip = ("🔎 候选 (未切在役) — %s\n候选清单: %s\n候选权重完整路径 (双击复制):\n%s\n"
                           "候选产物 %d 个 · 最近训练 %s\n"
                           "(本行与配置中心「模型配置」/ 主界面「配置通道」同源现算)"
                           % (r.get("note") or "无判据", " · ".join(r.get("names_all") or []) or r["name"],
                              r["path"], r["n"], r["last"]))
                else:
                    tip = ("层 %s · 在役模型 (真名): %s\n"
                           "名字真源: 8796 /status/all 在役模型名 → models/active_models.json (与配置通道同一规则)\n"
                           "运行位置: %s\n运行权重: %s\n转换工具: %s\n"
                           "在役权重完整路径 (双击复制):\n%s\n最近训练 %s\n本层产物 %d 个\n训练进程: %s%s"
                           % (r["layer"], r.get("name_full") or r["name"], r.get("where") or "—",
                              r.get("weights") or "—", r.get("conv") or "—", r["path"], r["last"], r["n"],
                              r.get("train_raw", "无训练进程"),
                              ("\n⚠ 本层磁盘在役产物是**另一个模型**: %s\n   (引擎报名来自 8796; 磁盘产物来自 "
                               "models/active_models.json / ckpt config.json — 两者不是同一个东西)"
                               % r["name_disk"]) if r.get("name_disk") else ""))
                it.setToolTip(tip)
        self._fit_table_height()
        if not self.tb.selectedItems():
            self.tb.selectRow(0)
        self._sync_btns()

    def _fit_table_height(self):
        """表格刚好放得下 4 行 + 表头 (不出现竖向滚动条, 也不留空行区)。"""
        try:
            hh = self.tb.horizontalHeader().height() or 30
            rows = sum(self.tb.rowHeight(i) for i in range(self.tb.rowCount())) or (4 * 32)
            self.tb.setFixedHeight(int(hh + rows + (self.tb.frameWidth() * 2) + 4))
        except Exception:                                                              # noqa: BLE001
            pass

    def _selected_layer(self):
        """选中行 → 层 (**候选行映射回它的基层**, 如 "L2 · 候选" → L2) —— 训练/日志按钮不受候选行影响。"""
        r = self.tb.currentRow()
        rows = getattr(self, "_rows_cache", None) or []
        if 0 <= r < len(rows):
            return rows[r].get("layer_key") or LAYERS[0]
        return LAYERS[r] if 0 <= r < len(LAYERS) else LAYERS[0]

    def _sync_btns(self):
        running = self._proc is not None and self._proc.poll() is None
        self.btn_train.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        ly = self._selected_layer()
        ent = _train_entries().get(ly, "(配置中心未接线)")
        self.btn_train.setText("▶ 训练本层" if not running else "▶ 训练中(%s)…" % self._proc_layer)
        self.btn_train.setToolTip("将执行:\n  %s" % ent)

    # ─────────────────────────── 控制 ───────────────────────────
    def _spawn(self, cmd, tag):
        if self._proc is not None and self._proc.poll() is None:
            self._log_line("⛔ 已有进程在跑 (%s) — 同刻只允许一个训练/执行进程" % self._proc_layer)
            return None
        self._log_line("$ %s" % cmd)
        try:
            # ⚠️ 2026-10-14 实测修: 原来这里写 HF_HOME=~/zmax_data/hf_cache (展开 = /home/ubuntu/zmax_data/hf_cache,
            #   少 /zmax/ 一段, 目录不存在) ⇒ 点 ▶ 训练 L3 会因加载 SmolVLM2 基座去连网而 rc=1。
            #   统一从 tools/zmax_hf_env.py 取 (与 drill / joint_train_all 同一真源), 不再各写一份。
            try:
                sys.path.insert(0, os.path.join(ROOT, "tools"))
                from zmax_hf_env import hf_env                                       # noqa: PLC0415
                _env = hf_env()
            except Exception:                                                        # noqa: BLE001
                _env = dict(os.environ)
            _env["PYTHONUNBUFFERED"] = "1"
            p = subprocess.Popen(cmd, shell=True, cwd=ROOT, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1,
                                 preexec_fn=os.setsid, env=_env)
        except Exception as e:                                                            # noqa: BLE001
            self._log_line("⛔ 起不来: %r" % (e,))
            return None
        self._proc, self._proc_layer = p, tag

        def _reader():
            try:
                for ln in p.stdout:
                    self._log_q.put(ln.rstrip("\n"))
            finally:
                self._log_q.put("── 进程结束 rc=%s ──" % p.poll())
        threading.Thread(target=_reader, daemon=True).start()
        self._sync_btns()
        return p

    def _on_train(self):
        ly = self._selected_layer()
        cmd = _train_entries().get(ly)
        if not cmd:
            self._log_line("⛔ 该层训练入口未接线 (配置中心「模型配置」→ model.train_entry)")
            return
        if cmd.startswith("tools/"):
            cmd = "%s %s" % (PY, cmd)
        self._spawn(cmd, ly)

    def _on_stop(self):
        p = self._proc
        if p is None or p.poll() is not None:
            self._log_line("没有正在跑的进程")
            return
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            self._log_line("■ 已发 SIGTERM → 进程组 %s" % p.pid)
        except Exception as e:                                                            # noqa: BLE001
            self._log_line("⛔ 停止失败: %r" % (e,))
        t0 = time.time()
        while time.time() - t0 < 8 and p.poll() is None:
            time.sleep(0.2)
        if p.poll() is None:                                                              # 真没停就明说 + 强杀
            self._log_line("⚠ 8s 未退出 → SIGKILL")
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except Exception:                                                             # noqa: BLE001
                pass
        self._log_line("　回读: poll()=%s (None 表示仍在跑)" % p.poll())
        self._sync_btns()

    def _on_log(self):
        ly = self._selected_layer()
        cands = sorted([d for d in os.listdir(self._logdir) if d.startswith("joint_train_")], reverse=True)
        for d in cands:
            lp = os.path.join(self._logdir, d, "%s.log" % ly)
            if os.path.exists(lp):
                self._log_line("📄 %s" % os.path.relpath(lp, ROOT))
                try:
                    tail = open(lp, encoding="utf-8", errors="replace").read().splitlines()[-60:]
                    for x in tail:
                        self._log_line("   " + x)
                except Exception as e:                                                    # noqa: BLE001
                    self._log_line("   读不到: %r" % (e,))
                return
        self._log_line("📄 还没找到 %s 的训练日志 (跑一次「▶ 训练本层」后会落到 reports/joint_train_*/%s.log)"
                       % (ly, ly))

    def _on_dir(self):
        r = [x for x in self._rows() if x["layer"] == self._selected_layer()][0]
        p = r["path"]
        self._log_line("📂 %s%s" % (p, "" if os.path.exists(p) else "  ⛔ (路径不存在)"))
        self._log_line("　(在文件管理器里打开: 复制上面的绝对路径)")

    def _on_task(self):
        tid = _active_task()
        cmd = "%s tools/zmax_open.py step2 --activate%s" % (PY, (" --task %s" % tid) if tid else "")
        self._spawn(cmd, "TASK-ENGINEERING")

    def _on_copy(self):
        rows = self._rows()
        L = ["Z-MAX 模型引擎 · L2~L5　%s" % time.strftime("%F %T"), ""]
        for r in rows:
            L.append("%s | 在役 %s | 版本 %s | 本层产物 %d | %s | 训练中 %s | 最近训练 %s" % (
                r["layer"], r["name"], r["ver"], r["n"], "推理中" if r["infer"] else "空闲", r["train"], r["last"]))
            L.append("     权重: %s" % r["path"])
        L += ["", "训练入口(真源 model.train_entry):"]
        for k, v in _train_entries().items():
            L.append("   %s → %s" % (k, v))
        txt = "\n".join(L)
        try:
            QApplication.clipboard().setText(txt)
            self._log_line("📋 已复制 %d 行到剪贴板" % len(L))
        except Exception:                                                                 # noqa: BLE001
            pass
        self._last_copy = txt

    def _copy_cell(self, item):
        """双击单元格 → 复制**完整**文本 (路径列复制完整路径) — 老倪: 显示内容要可复制可导出。"""
        try:
            t = item.data(Qt.UserRole) or item.text()
            QApplication.clipboard().setText(str(t))
            self._log_line("📋 已复制: %s" % t)
        except Exception:                                                          # noqa: BLE001
            pass

    def _log_line(self, s):
        self.log.appendPlainText(s)

    def _drain_log(self):
        n = 0
        while not self._log_q.empty() and n < 400:
            self.log.appendPlainText(self._log_q.get())
            n += 1
        if n:
            self._sync_btns()

    def showEvent(self, e):                                                               # noqa: N802
        """页面里内嵌时, 真实行高要等控件显示过才有值 ⇒ 显示后再按真实行高校一次表高
        (否则页面里会只显示得下 2 行, 2026-10-14 读屏实测)。"""
        super().showEvent(e)
        self._fit_table_height()

    def closeEvent(self, e):                                                              # noqa: N802
        try:
            self._t.stop()
            self._lt.stop()
            self._fetcher.stop()
        except Exception:                                                                 # noqa: BLE001
            pass
        super().closeEvent(e)


# ─────────────────────────── 自检 ───────────────────────────
class ModelEngineWindow(QDialog):
    """独立窗口 = 薄壳: 内容就是同一个 `ModelEnginePanel` (弹出来看/放第二个屏)。"""

    def __init__(self, parent=None, poll=True, interval=5.0):
        super().__init__(parent)
        self.setWindowTitle("🧠 模型引擎 · L2~L5 训练与推理状态")
        self.setObjectName("modelEngineWindow")
        # 🖥 2026-10-14 老倪: 「窗口无法调宽度, 横向都出单个屏幕了, 无法最大化」⇒
        #   去掉固定尺寸 + 显式给最大化按钮; 默认宽 = min(设计宽 1900, 屏幕可用宽−80) —— 单屏也放得下。
        # ⚠ 「无法最大化」实测三层根因 (逐条验过):
        #   ① setFixedWidth(1900) 钉死宽度 → 拖不动 (已改: 设计宽只当默认宽 + _refit 随宽重算)
        #   ② QDialog 带 parent ⇒ WM_TRANSIENT_FOR 被设上, GNOME 的 _NET_WM_ALLOWED_ACTIONS 里
        #      **没有 MAXIMIZE_*** ⇒ 最大化点了不动 (已改: 调用方一律不传 parent)
        #   ③ 仍是 QDialog **类型** ⇒ GNOME 按弹窗对待, 照样剥夺最大化 ⇒ 这里去掉 Qt.Dialog 位,
        #      只留普通顶层窗口 + 最小/最大化/系统菜单按钮 (实测 allowed_actions 才出现 MAXIMIZE)
        self.setWindowFlags((self.windowFlags() | Qt.Window | Qt.WindowMinMaxButtonsHint
                             | Qt.WindowMaximizeButtonHint | Qt.WindowSystemMenuHint) & ~Qt.Dialog)
        _scr = QApplication.primaryScreen()
        _av = _scr.availableGeometry() if _scr else None
        self._def_w = ModelEnginePanel.default_w()          # 与功能区页面同一个默认宽
        self.resize(self._def_w, 660)
        _v = QVBoxLayout(self)
        _v.setContentsMargins(0, 0, 0, 0)
        self.panel = ModelEnginePanel(self, poll=poll, interval=interval)
        _v.addWidget(self.panel)
        # 2026-10-14 老倪「两处界面要一致」: 高度按**内容**定 —— 窗口比面板高时, 多出的高度会把按钮行
        #   拉开/居中, 与功能区页面里的排布对不上 (实测 660 高: 抓图逐像素差 20%, 差异全在 y240-520)。
        self.adjustSize()
        _h = max(460, self.panel.sizeHint().height())
        # ⚠ adjustSize() 会把宽度收到 minimumWidth(980) ⇒ 这里必须显式把**默认宽**摆回来
        #   (实测: 少了这一步, 窗口出来是 980 宽, 路径列被挤 ⇒ 又变成"看到的不是设计好的样子")
        self.resize(getattr(self, "_def_w", 1900), min(_h, (_av.height() - 90) if _av else _h))
        self.panel._refit(self.width())

    def __getattr__(self, name):          # 老代码 (演练/自检/studio) 按老名字访问也能用
        p = self.__dict__.get("panel")
        if p is not None:
            return getattr(p, name)
        raise AttributeError(name)

    def closeEvent(self, e):                                                              # noqa: N802
        self.panel.closeEvent(e)
        super().closeEvent(e)


def _selftest(shot=None):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ok, res = True, []

    def chk(name, cond, extra=""):
        nonlocal ok
        ok = ok and bool(cond)
        res.append("%s %s%s" % ("✓" if cond else "✗", name, (" :: " + str(extra)) if extra else ""))

    inv = json.loads(subprocess.run(INV_CMD, cwd=ROOT, capture_output=True, text=True, timeout=180).stdout)
    w = ModelEngineWindow(poll=False)
    # 🖥 2026-10-14: 窗口现在**可拖宽/可最大化**, 默认宽随屏幕 ⇒ 自检必须钉在**设计宽**(1900) 上验
    #   "字不截断 / 路径放得下" (这两条是设计宽下的要求, 与用户拖窄后的横滚不矛盾)。
    w.panel._refit(1900)
    w.resize(1900, max(460, w.panel.sizeHint().height()))
    w.feed(inv, {})
    rows = w._rows()
    _ins = [r for r in rows if r.get("active") and not r.get("ext")]      # 基座在役行
    _ext = [r for r in rows if r.get("ext")]                             # 在役扩展行 (适配层/原语/技能包)
    _cnd = [r for r in rows if r.get("cand")]
    chk("四层基座行都在役 (L2/L3/L4/L5)", [r["layer_key"] for r in _ins] == list(LAYERS), [r["layer"] for r in _ins])
    chk("每层都有在役扩展行 (SAM3 / L3 LoRA / L4 LoRA / L5 技能包)",
        sorted({r["layer_key"] for r in _ext}) == list(LAYERS) and len(_ext) >= 4, [r["name"] for r in _ext])
    chk("每层在役权重/产物是真路径且存在 (基座+扩展)", all(os.path.exists(r["path"]) for r in _ins + _ext),
        [(r["layer_key"], r.get("ext"), os.path.exists(r["path"])) for r in _ins + _ext])
    chk("表格行数 = 4 基座 + 扩展 + 候选行数", w.tb.rowCount() == 4 + len(_ext) + len(_cnd),
        "%d 行 (基座 4 + 扩展 %d + 候选 %d)" % (w.tb.rowCount(), len(_ext), len(_cnd)))
    # 🧩 老倪 2026-10-14: 「在模型引擎里要增加 SAM3, 位置 L2」⇒ L2 候选行必须含 SAM3 + 判据 + 路径
    _l2s = next((r for r in _ext if r["layer_key"] == "L2"), None)         # SAM3 现在是**在役原语**
    chk("L2 在役行含 SAM3 (感知原语 · 与配置通道/模型配置同源)",
        bool(_l2s) and "SAM3" in str(_l2s.get("name")), (_l2s or {}).get("name"))
    _l2c = next((r for r in _cnd if str(r["layer"]).startswith("L2")), None)
    chk("L2 仍有真候选行 (未证明提升的产物不许混进在役)", bool(_l2c), (_l2c or {}).get("name"))
    chk("候选行带未切在役判据 + 候选权重真路径",
        bool(_l2c) and bool(_l2c.get("note")) and os.path.exists(_l2c.get("path") or ""),
        "%s | %s" % ((_l2c or {}).get("note"), (_l2c or {}).get("path", "")[-46:]))
    chk("表格列名齐 (8 列)", w.tb.columnCount() == 8
        and w.tb.horizontalHeaderItem(0).text() == "层"
        and "权重" in w.tb.horizontalHeaderItem(7).text())
    ent = _train_entries()
    chk("训练入口取自配置中心真源 (model.train_entry)", set(ent) == set(LAYERS), list(ent))
    chk("入口命令都指向真实存在的脚本",
        all(os.path.exists(os.path.join(ROOT, v.split()[0])) for v in ent.values()), list(ent.values()))
    chk("未跑任务时 ▶ 可点 / ■ 停 变灰", w.btn_train.isEnabled() and not w.btn_stop.isEnabled())
    # 2026-10-14 老倪「两处界面要一致」: 窗口高度改成**按内容自适应** (按钮行紧贴表格下方,
    #   不留 160px 空档) ⇒ 判据也随之改口径: 宽必须够 1900 (防截断), 高只需放得下内容
    # 🖥 2026-10-14 老倪: 窗口必须可拖宽 + 能最大化 ⇒ 判据改成"没有把尺寸钉死"
    chk("窗口可调宽/可最大化 (无固定宽 · 有最大化按钮 · 有最小宽兜底)",
        w.maximumWidth() > 4000 and w.minimumWidth() < 1200 and w.width() >= 900 and w.height() >= 460
        and bool(w.windowFlags() & Qt.WindowMaximizeButtonHint),
        "%dx%d · minW=%d maxW=%d · 最大化按钮=%s"
        % (w.width(), w.height(), w.minimumWidth(), w.maximumWidth(),
           bool(w.windowFlags() & Qt.WindowMaximizeButtonHint)))
    img = w.grab().toImage()
    chk("渲染不空 (有内容像素)", sum(1 for y in range(0, img.height(), 4) for x in range(0, img.width(), 4)
                                 if img.pixelColor(x, y).red() > 0x20) > 500)

    # 2026-10-14: 老倪「界面极简, 字不截断」⇒ 关键列必须放得下完整文字 (出现省略号 = 失败)
    fm = w.tb.fontMetrics()
    bad = []
    slack = min((w.tb.columnWidth(c) - fm.horizontalAdvance((w.tb.item(r, c).text() if w.tb.item(r, c) else "")))
                 for r in range(w.tb.rowCount()) for c in (0, 1, 2, 3, 6))   # 2026-10-14: 层列(0) 也纳入 (候选行"🔎 L2 · 候选")
    for r in range(w.tb.rowCount()):
        for c in (1, 2, 3, 5, 6):   # 6 列显示 MM-DD HH:MM, 完整时间戳在 tooltip                       # 在役模型/版本/产物/训练中/最近训练 = Fixed 列
            it = w.tb.item(r, c)
            t = it.text() if it else ""
            if fm.horizontalAdvance(t) + 20 > w.tb.columnWidth(c):
                bad.append("r%d c%d %r" % (r, c, t[:28]))
    chk("Fixed 列文字不被省略号截断 (且版本列余量≥24px 防 ElideNone 硬切)", not bad and slack >= 24, "余量 %dpx" % slack)
    # 2026-10-14: 真源 training[] 实测有脏数据 (同层多行 / "JOINT(L2)" 包裹 / 只有 pid 没进度)
    #   ⇒ 必须收口到"有进度的那行", 且进度取自 progress 子字典 (不是顶层 pct)
    fake = dict(inv)
    _me = os.getpid()                                                                     # 拿一个确定活着的 pid
    fake["training"] = [
        {"layer": "L3", "pid": 999999},                                                   # 已死 + 无进度 ⇒ 丢弃
        {"layer": "JOINT(L2)", "pid": _me, "progress": {"found": True, "step": 8, "total": 20}},
        {"layer": "L3", "pid": _me, "progress": {"found": True, "step": 5, "total": 20}},
        {"layer": "LLM", "pid": _me, "progress": {"found": True, "step": 1, "total": 2}},  # 非 L2~L5 ⇒ 忽略
        {"layer": "L4", "pid": _me, "elapsed_s": 72, "progress": {"found": False}},        # 活+无进度但有耗时 ⇒ "已 72s"
        {"layer": "L5", "pid": 999999, "progress": {"found": True, "step": 3, "total": 20}},  # 已死(哪怕有进度) ⇒ 不算
    ]
    w.feed(fake, {})
    t_l2, t_l3 = w.tb.item(0, 5).text(), w.tb.item(1, 5).text()
    chk("JOINT(L2) 归一到 L2 并取到进度", "8/20" in t_l2 and t_l2.startswith("▶"), t_l2)
    chk("同层多行取\"有进度\"那行 (不被只有 pid 的行盖掉)", "5/20" in t_l3, t_l3)
    _nc = sum(1 for r in w._rows() if r.get("cand"))
    _ne = sum(1 for r in w._rows() if r.get("ext"))
    chk("非 L2~L5 的训练行不凭空造行/造列", w.tb.rowCount() == 4 + _ne + _nc,
        "%d 行 (基座 4 + 在役扩展 %d + 候选 %d)" % (w.tb.rowCount(), _ne, _nc))
    chk("活进程·无进度 ⇒ 写'已跑Ns'或'进度未报' (绝不编百分比)",
        w.tb.item(2, 5).text().startswith("训练中") and "%" not in w.tb.item(2, 5).text(),
        w.tb.item(2, 5).text())
    chk("陈旧训练行(pid 已死)不算训练中, 哪怕它有进度", w.tb.item(3, 5).text() == "否", w.tb.item(3, 5).text())
    w.feed(inv, {})

    need = max((fm.horizontalAdvance((w.tb.item(r, 7).text() if w.tb.item(r, 7) else ""))
                for r in range(w.tb.rowCount())), default=0)
    fixed = sum(w.tb.columnWidth(i) for i in range(7))
    chk("权重路径列放得下最长显示路径 (窗口够宽)", fixed + need + 40 <= w.width(),
        "需 %d, 有 %d" % (fixed + need + 40, w.width()))
    full_ok = all((w.tb.item(r, 7).data(Qt.UserRole) or "").endswith(w.tb.item(r, 7).text().lstrip("…")[-24:])
                  and (w.tb.item(r, 7).data(Qt.UserRole) in (w.tb.item(r, 7).toolTip() or ""))
                  for r in range(w.tb.rowCount()))
    chk("完整路径在 tooltip/双击可复制 (省略号不丢信息)", full_ok)
    # 2026-10-14 读屏实测: 表格写死高度 ⇒ 页面里只显示得下 2 行 (L4/L5 被挤到滚动区外) ⇒ 必须"四行全在视口内"
    chk("四行全在视口内 (竖向滚动条不需要)", w.tb.verticalScrollBar().maximum() == 0,
        "scroll_max=%d 表高=%d 行高合计=%d" % (w.tb.verticalScrollBar().maximum(), w.tb.height(),
                                            sum(w.tb.rowHeight(i) for i in range(w.tb.rowCount()))))
    if shot:
        w.grab().save(shot)
    print("\n".join(res))
    print("SELFTEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--shot", default="")
    ap.add_argument("--live", action="store_true", help="真开窗 (接 8796 与 nvidia-smi 轮询)")
    a = ap.parse_args()
    if a.selftest:
        return _selftest(a.shot or None)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    w = ModelEngineWindow()
    w.show()
    if a.live:
        return app.exec_()
    return 0


if __name__ == "__main__":
    sys.exit(main())
