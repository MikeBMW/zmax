#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📊 左下角常驻状态面板 (Z-MAX 控制台 · 2026-10-01 老倪)

老倪原话: 「将硬件 GPU CPU 内存 磁盘大小等状态、状态空间的在役模型版本号、模型是否在推理、
训练中的模型版本号、模型是否在训练的状态、数据生成的场景 3DGS 数据资产版本号, 这些信息都
推到 8796 服务, 放在窗口左下角, 注意要用红绿灯、状态条、进度条等控件显示, 不要占用太大面积,
不要用很多文字, 我要看状态」⇒ 本控件: **极小面积 + 极少文字**, 文字只留 3~4 字符数字与
极短版本号, 其余全靠 红绿灯 / 状态条 / 进度条 表达, 详细内容放 tooltip(悬停才看)。

数据源 (冻结契约, 由 8796 服务端提供):
  { "ts": float,
    "hw": {"gpu": {"util","mem_used_mb","mem_total_mb","temp_c","name"},
           "cpu": {"util","cores","load1"},
           "mem": {"used_gb","total_gb"},
           "disk": {"used_gb","total_gb","pct"}},
    "models":  [{"layer","name","version","state":"in_service|candidate|untrained","inferring":bool}],
    "training":{"active","layer","name","version","step","total","pct","eta_s","speed_s_per_step"},
    "assets":  [{"kind":"3DGS","name","version","path"}] }

形态 (**一行**, 总 1080x40 px · 2026-10-14 老倪「下面的硬件显示排成一行; 现在两行, 占地方」):
  单行从左到右: GPU/CPU/内存/磁盘 (Ø8 灯 + 名称 + 迷你状态条 26x7 + 数值)
                → 训练进度条(40x7)+% (或空载灰灯)
                → 每层一个 chip (Ø8 灯 + 层标 + 短模型名 ≤9字 + 极短版本 + 同层计数 +N)
                → 右端 3DGS v<版本>  → 最右 Ø8 通信灯
  推理中=青环 · 训练中=黄弧;   颜色语义: 绿=在役&健康 · 黄=候选或忙 · 红=异常/未训练 · 灰=未知
  老倪口径: 「不要占太大面积, 不要用很多文字, 我要看状态」⇒ 一行换掉两行, 高度 68→40,
  宽度加给内容(4 硬件 + 4 模型层 + 训练 + 资产全在一行内, 不折叠不截断)。

运行/自检:
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/gui/status_panel.py --selftest
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/gui/status_panel.py --live-shot /tmp/p.png --seconds 3
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.request

from PyQt5.QtCore import Qt, QPointF, QRectF, QThread, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QApplication, QWidget, QMenu

# ---- 配色 (与 tools/gui/hw_widgets.py 同一套口径) ----
C_BG2, C_BORDER = "#161b22", "#30363d"
C_WHITE, C_GRAY, C_DIM = "#e6edf3", "#8b949e", "#6e7681"
C_GREEN, C_YELLOW, C_RED, C_CYAN = "#3fb950", "#d29922", "#f85149", "#39d0d8"
TRACK = "#2b3340"

UI, MONO = "Noto Sans CJK SC", "Consolas"

# 状态 → 灯色
STATE_COLOR = {"in_service": C_GREEN, "candidate": C_YELLOW, "untrained": C_RED}
LAYER_ORDER = ("L2", "L3", "L4", "L5")

DEFAULT_URL = os.environ.get("ZMAX_STATUS_URL", "http://127.0.0.1:8796/status/all")


def tone(v, lo=70.0, hi=90.0):
    """利用率 → 颜色。缺测(None) = 灰 (不画 0 冒充)。"""
    try:
        if v is None:
            return C_DIM
        f = float(v)
    except Exception:
        return C_DIM
    return C_GREEN if f < lo else (C_YELLOW if f < hi else C_RED)


def _num(v):
    try:
        return int(round(float(v)))
    except Exception:
        return None


def _txt(v, suffix="%"):
    n = _num(v)
    if n is None:
        return "—"
    s = str(max(0, min(999, n)))
    return s + suffix


_DATE_PRE = re.compile(r"^v?\d{8}-")


def short_ver(v):
    """极短版本号: 去掉所有模型共有的日期前缀(v20261001-), 优先留最能区分的尾巴。

    'v20261001-annot' -> 'annot' · 'v20261001-r6' -> 'r6' ·
    'smolvla_lew_v10_1h/004000' -> '004000' · 'v1001-r6' -> 'r6' · 'unknown' -> 'unknown'
    """
    v = str(v or "").strip()
    if not v:
        return "—"
    v = _DATE_PRE.sub("", v)
    if "/" in v:
        v = v.split("/")[-1]
    parts = v.split("-")
    if (len(parts) > 1 and 1 <= len(parts[-1]) <= 8 and len(parts[0]) >= 4
            and any(c.isdigit() for c in parts[0])):
        v = parts[-1]            # 头像版本号(v1001 / v20261001)才换成尾巴; 'deepseek-vl' 这类保持原名
    if len(v) > 9:              # 太长: 下划线目录名只留末段 (intact_l4_current -> current)
        seg = [x for x in v.split("_") if x]
        if len(seg) > 1:
            v = seg[-1]
    return v or "—"


# ---- 短模型名 (2026-10-01 老倪: 「L2 L3 L4 的模型名字要显示出来, 现在的 v1001 也不知道是哪个模型」) ----
# 只从 name 字段**真实提取/缩写**, 不编造。≤9 字符。同层多个模型必须能互相区分。
_NAME_ALIAS = {                 # 长型号的固定缩写 (都是 name 里真实出现的词)
    "taskplanner": "TaskPlan",
    "flow-matching": "FlowMatch",
    "smolvla+lew": "SmolVLA",
    "intact-jepa": "INTACT",
    "deepseek": "DeepSeek",
}
_NAME_MOD = (                   # 名里的限定词 → 后缀 (同层区分: INTACT vs INTACT-WM)
    (re.compile(r"世界模型|\bWM\b", re.I), "-WM"),
    (re.compile(r"lora", re.I), "-L"),
)


def short_name(name):
    """name 字段 → ≤9 字短名。规则(一致、可读、可复算):
      ① 去括号说明  ② 去 "L3 " 层前缀  ③ 取第一个 ASCII 型号词(遇 '+' 截断)
      ④ 长词查 _NAME_ALIAS; 仍超 9 字按 9 字截断
      ⑤ 名带 LoRA / 世界模型 等限定词 → 加 -L / -WM 后缀(同层可区分)
      ⑥ 全中文名 → 取前 4 个汉字
    """
    s = str(name or "").strip()
    if not s:
        return "?"
    s = re.sub(r"[(（].*$", "", s).strip()                       # ① 去括号
    s = re.sub(r"^L\d+\s+", "", s).strip()                       # ② 去层前缀
    m = re.search(r"[A-Za-z][A-Za-z0-9._+\-]{1,}", s)            # ③ 第一个 ASCII 词
    if m:
        base = m.group(0).split("+")[0].rstrip("._-")            # SmolVLA+LEW -> SmolVLA
        base = _NAME_ALIAS.get(base.lower(), base)
        for rx, suf in _NAME_MOD:                                # ⑤ 限定词后缀
            if rx.search(s) and (len(base) + len(suf)) <= 9:
                base += suf
                break
        return base[:9]
    c = re.search(r"[\u4e00-\u9fff]{2,}", s)                     # ⑥ 全中文
    return (c.group(0)[:4] if c else (s[:9] or "?"))



# ============================================================
# 取数线程: 只往队列里放, 绝不碰任何 Qt 控件
# ============================================================
class _Fetcher(QThread):
    def __init__(self, url, out, interval=1.0, timeout=0.9, parent=None):
        super().__init__(parent)
        self.url = url
        self.out = out                      # list, 主线程消费
        self.interval = float(interval)
        self.timeout = float(timeout)
        self._stop = threading.Event()
        self.setObjectName("status_panel_fetch")

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            t0 = time.time()
            try:
                req = urllib.request.Request(self.url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = r.read(262144)
                obj = json.loads(body.decode("utf-8", "replace"))
                if isinstance(obj, dict):
                    self.out.append((True, obj, time.time()))
                else:
                    self.out.append((False, "not-a-dict", time.time()))
            except Exception as e:                                  # 读失败静默降级
                self.out.append((False, "%s: %s" % (type(e).__name__, e), time.time()))
            # 只留最近 2 条, 防无界增长
            del self.out[:-2]
            self._stop.wait(max(0.05, self.interval - (time.time() - t0)))


# ============================================================
# 面板
# ============================================================
class StatusPanel(QWidget):
    W, H = 1080, 40                 # 2026-10-14: 两行→一行 (560x68 → 1080x40), 占地方改小
    POLL_MS = 1000
    MAX_CHIPS = 4

    def __init__(self, parent=None, url=None, poll=True):
        super().__init__(parent)
        self.url = url or DEFAULT_URL
        self.setFixedSize(self.W, self.H)
        self.setToolTip("状态面板: 等待 8796 /status/all …")
        self._obj = None                    # 最近一次成功载荷
        self._err = "未连接"                # 最近一次失败原因 (不显示在界面上, 只进 tooltip)
        self._age = None                    # 最近一次成功取数的时刻
        self._sig = None                    # 值变化才重绘
        self._queue = []
        self._worker = None
        if poll:
            self._worker = _Fetcher(self.url, self._queue, interval=self.POLL_MS / 1000.0, parent=self)
            self._worker.start()
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(self.POLL_MS)
            app = QApplication.instance()
            if app is not None:
                try:
                    app.aboutToQuit.connect(self.shutdown)
                except Exception:
                    pass

    # ---------- 生命周期 ----------
    def shutdown(self):
        try:
            self._timer.stop()
        except Exception:
            pass
        w = self._worker
        if w is not None and w.isRunning():
            w.stop()
            w.wait(2000)

    def closeEvent(self, e):                                            # noqa: N802
        self.shutdown()
        super().closeEvent(e)

    # ---------- 取数消费 (主线程) ----------
    def _tick(self):
        try:
            if self._queue:
                ok, payload, ts = self._queue[-1]
                del self._queue[:]
                if ok:
                    self._obj, self._age, self._err = payload, ts, None
                else:
                    self._obj, self._err = None, str(payload)
                self._apply()
        except Exception:
            pass                                                        # 轮询绝不炸 UI

    def _apply(self):
        sig = self._signature()
        if sig == self._sig:                                            # 值没变不重绘(省 GPU)
            return
        self._sig = sig
        if not getattr(self, "_boot", ""):                              # 启动档: 用于标「已切档待重启 ⟳」
            try:
                self._boot = str(self._profile().get("key") or "")
            except Exception:
                self._boot = ""
        self._refresh_tooltip()
        self.update()

    def _signature(self):
        try:
            return self._signature_inner()
        except Exception as e:                                          # 畸形载荷: 退化成"每次重绘"
            return ("bad", repr(e))

    def _signature_inner(self):
        d = self._obj
        if not isinstance(d, dict):
            return ("err", self._err)
        hw = d.get("hw") or {}
        g = (hw.get("gpu") or {})
        c = (hw.get("cpu") or {})
        m = (hw.get("mem") or {})
        k = (hw.get("disk") or {})
        mods = tuple((str(x.get("layer", "")), str(x.get("version", "")), str(x.get("state", "")),
                      bool(x.get("inferring"))) for x in (d.get("models") or []) if isinstance(x, dict))
        tr = d.get("training") or {}
        trs = (bool(tr.get("active")), str(tr.get("layer", "")), str(tr.get("version", "")),
               _num(tr.get("pct")), _num(tr.get("step")))
        asst = tuple((str(x.get("kind", "")), str(x.get("version", "")))
                     for x in (d.get("assets") or []) if isinstance(x, dict))
        return (_num(g.get("util")), _num(g.get("temp_c")), _num(c.get("util")),
                _num((float(m.get("used_gb") or 0) / float(m.get("total_gb") or 1)) * 100) if m.get("total_gb") else None,
                _num(k.get("pct")), mods, trs, asst)

    # ---------- 供自检/手动喂数 ----------
    def feed(self, obj):
        self._obj, self._age, self._err = obj, time.time(), None
        self._apply()

    def feed_error(self, msg="unavailable"):
        self._obj, self._err, self._age = None, msg, None
        self._apply()

    # ---------- 数据派生 (全部防御式, 缺字段=缺测, 绝不抛) ----------
    def _rows(self):
        d = self._obj if isinstance(self._obj, dict) else {}
        hw = d.get("hw") if isinstance(d.get("hw"), dict) else {}
        gpu = hw.get("gpu") if isinstance(hw.get("gpu"), dict) else {}
        cpu = hw.get("cpu") if isinstance(hw.get("cpu"), dict) else {}
        mem = hw.get("mem") if isinstance(hw.get("mem"), dict) else {}
        dsk = hw.get("disk") if isinstance(hw.get("disk"), dict) else {}
        g_u, c_u = _num(gpu.get("util")), _num(cpu.get("util"))
        m_u = None
        try:
            if mem.get("total_gb"):
                m_u = _num(float(mem.get("used_gb") or 0) / float(mem["total_gb"]) * 100.0)
        except Exception:
            m_u = None
        d_u = _num(dsk.get("pct"))
        if d_u is None and dsk.get("total_gb"):
            try:
                d_u = _num(float(dsk.get("used_gb") or 0) / float(dsk["total_gb"]) * 100.0)
            except Exception:
                d_u = None
        row1 = [("GPU", g_u), ("CPU", c_u), ("内存", m_u), ("磁盘", d_u)]
        return row1, gpu, cpu, mem, dsk

    def _models(self):
        d = self._obj if isinstance(self._obj, dict) else {}
        ms = [x for x in (d.get("models") or []) if isinstance(x, dict)]

        def _key(x):
            ly = str(x.get("layer", ""))
            return (LAYER_ORDER.index(ly) if ly in LAYER_ORDER else 9, ly)
        return sorted(ms, key=_key)

    def _training(self):
        d = self._obj if isinstance(self._obj, dict) else {}
        t = d.get("training")
        return t if isinstance(t, dict) else {}

    def _edge(self):
        """Intel 端侧 (550C): {online, device, busy, last_ms, hw{...}} —— 契约没有就返回 {} (旧服务端兼容)."""
        d = self._obj if isinstance(self._obj, dict) else {}
        e = d.get("edge")
        return e if isinstance(e, dict) else {}

    def _orin(self):
        """Orin AGX: {online, cpu_temp_c, mem_*, load1, robot_stack} —— 只读遥测."""
        d = self._obj if isinstance(self._obj, dict) else {}
        o = d.get("orin")
        return o if isinstance(o, dict) else {}

    def _profile(self):
        """当前产品档 (真源 active_product): {key:'550B', hardware:'calib', hw_label:'标定', mode, caps, summary}."""
        d = self._obj if isinstance(self._obj, dict) else {}
        p = d.get("profile")
        return p if isinstance(p, dict) else {}

    def _cams(self):
        d = self._obj if isinstance(self._obj, dict) else {}
        c = d.get("cams")
        return c if isinstance(c, dict) else {}

    # ---------- 三档 = 三种算力用法 (550A/4060 · 550B/4060桥接 · 550C/Intel) ----------
    def _hw_of(self, key, fallback):
        """该档要求的算力载体 (真源 products[<档>].hardware 优先; 读不到退回静态兜底)。"""
        try:
            from lerobot.engineering import status_hub as _hub
            h = _hub.profile_hardware(key) or {}
            return str(h.get("label") or h.get("key") or fallback)
        except Exception:                                            # noqa: BLE001
            return fallback

    def modes(self):
        """三档各自的「灯 + 4 个指标槽」。当前档用完整槽位; 另外两档给菜单用的一行摘要。

        槽 = (名称, 填充比例或None, 右侧文字或None)。
        · 缺数据画「—」, 不编数;   · 550B 的槽 = 观察全硬件: 相机/机械臂/端侧/栈。
        """
        d = self._obj if isinstance(self._obj, dict) else {}
        hw = d.get("hw") if isinstance(d.get("hw"), dict) else {}
        gpu = hw.get("gpu") if isinstance(hw.get("gpu"), dict) else {}
        cpu = hw.get("cpu") if isinstance(hw.get("cpu"), dict) else {}
        mem = hw.get("mem") if isinstance(hw.get("mem"), dict) else {}
        dsk = hw.get("disk") if isinstance(hw.get("disk"), dict) else {}
        e, o, cm = self._edge(), self._orin(), self._cams()
        hwe = e.get("hw") if isinstance(e.get("hw"), dict) else {}

        def _pct(a, b):
            try:
                return _num(float(a) / float(b) * 100.0)
            except Exception:
                return None

        mem_l = _pct(mem.get("used_gb"), mem.get("total_gb"))
        if mem_l is None:
            mem_l = _num(mem.get("pct"))

        # —— 550A: 4060 上开发训练
        a_mod = {"key": "550A", "hw": self._hw_of("550A", "4060"), "mode": "开发训练", "dot": "green", "online": True,
                 "fact": "GPU %s%% · 训练 %s" % (_txt(_num(gpu.get("util"))), "中" if (d.get("training") or {}).get("active") else "无"),
                 "slots": [("GPU", _num(gpu.get("util")), None),
                           ("CPU", _num(cpu.get("util")), None),
                           ("内存", mem_l, None),
                           ("磁盘", _num(dsk.get("pct")), None)]}

        # —— 550B: VSCode 标定 / 观察所有硬件
        c_on, c_n, c_tot = bool(cm.get("online")), int(cm.get("n_fresh") or 0), int(cm.get("n_total") or 0)
        rob = o.get("robot") or {}
        rs = o.get("robot_stack") or {}
        arm_ok = (str(rob.get("power_state") or "") == "on") and not rob.get("has_error")
        arm_txt = ("通" if arm_ok else ("错" if rob.get("has_error") else ("电" if rob else "—"))) if o.get("online") else "—"
        e_on = bool(e.get("online"))
        o_on = bool(o.get("online"))
        eps_n, eps_tot = int(e_on) + int(o_on), 2
        rs_n, rs_tot = sum(1 for v in rs.values() if v), len(rs)
        b_mod = {"key": "550B", "hw": self._hw_of("550B", "4060"), "mode": "桥接 · 状态空间工程/全 tool · 观察全硬件",
                 "dot": "green" if (c_on and c_n > 0) else ("dim" if not c_on else "yellow"),
                 "online": bool(c_on),
                 "fact": "相机 %d/%d · 端侧 %d/%d · 栈 %s" % (c_n, c_tot, eps_n, eps_tot,
                                                          ("%d/%d" % (rs_n, rs_tot)) if rs else "—"),
                 # 槽 = (名称, 填充比例, 右侧文字, 语义色)。★ 计数类「满额 = 好」必须显式给 ok,
                 #   否则 tone(100%) 按"负载过高"上红色 —— 实测被子代理抓到: 端侧 2/2、栈 2/2 显示红点红满条。
                 "slots": [("相机", (100.0 * c_n / c_tot) if c_tot else None,
                            ("%d/%d" % (c_n, c_tot)) if c_tot else "—",
                            "ok" if (c_tot and c_n >= c_tot) else "warn"),
                           ("机械臂", 100.0 if arm_ok else (0.0 if arm_txt == "错" else None), arm_txt,
                            "ok" if arm_ok else ("bad" if arm_txt == "错" else "idle")),
                           ("端侧", 100.0 * eps_n / eps_tot, "%d/%d" % (eps_n, eps_tot),
                            "ok" if eps_n >= eps_tot else "warn"),
                           ("栈", (100.0 * rs_n / rs_tot) if rs_tot else None,
                            ("%d/%d" % (rs_n, rs_tot)) if rs_tot else "—",
                            "ok" if (rs_tot and rs_n >= rs_tot) else "warn")]}

        # —— 550C: 部署到 Intel 端侧 (五槽: NPU/GPU/CPU/内存/磁盘 —— 老倪要「所有硬件·算力·磁盘都显示」)
        e_busy, e_ms = bool(e.get("busy")), e.get("last_ms")
        e_model = str(e.get("model") or "—").split("/")[-1].replace(".xml", "")
        acc = hwe.get("accel") if isinstance(hwe.get("accel"), dict) else {}
        a_npu = acc.get("npu") if isinstance(acc.get("npu"), dict) else {}
        a_gpu = acc.get("gpu") if isinstance(acc.get("gpu"), dict) else {}
        a_cpu = acc.get("cpu") if isinstance(acc.get("cpu"), dict) else {}
        npu_txt = ("%.0fms" % e_ms) if (e_on and e_ms is not None) else ("忙" if (e_on and e_busy) else "—")
        npu_tops = a_npu.get("tops_int8")
        gpu_tops = a_gpu.get("tops_int8")
        gpu_txt = ("%sT" % ("%.0f" % gpu_tops if gpu_tops else "—")) if e_on else "—"   # 算力标识 (INT8 TOPS)
        disk_free = hwe.get("disk_free_gb")
        disk_txt = ("%.0fG" % disk_free) if isinstance(disk_free, (int, float)) else "—"  # 余量, 大写 G 省宽度
        c_mod = {"key": "550C", "hw": self._hw_of("550C", "Intel"), "mode": "端侧部署",
                 "dot": "cyan" if (e_on and e_busy) else ("green" if e_on else "dim"), "online": e_on,
                 "fact": "NPU %s / %sTOPS · iGPU %sTOPS · 盘余 %sGB" % (
                     npu_txt, ("%.0f" % npu_tops) if npu_tops else "—",
                     ("%.0f" % gpu_tops) if gpu_tops else "—", disk_free if disk_free is not None else "—"),
                 "slots": [("NPU", None, npu_txt, "ok" if e_on else "idle"),
                           ("GPU", None, gpu_txt, "ok" if e_on else "idle"),
                           ("CPU", _num(hwe.get("cpu_pct")), None),
                           ("内存", _num(hwe.get("mem_pct")), None),
                           ("磁盘", _num(hwe.get("disk_pct")), disk_txt)]}
        out = [a_mod, b_mod, c_mod]
        # 档位与硬件不符 (例: 4060 上挂着 550C) ⇒ 当前档的灯转黄 + fact 前缀, 不许静默
        pr = self._profile()
        if pr and pr.get("hw_ok") is False:
            for m in out:
                if m["key"] == pr.get("key"):
                    m["dot"] = "yellow"
                    m["fact"] = "⚠ 档位≠本机硬件 · " + str(m.get("fact") or "")
                    m["hw_warn"] = str(pr.get("hw_warn") or "")
        return out

    def current(self):
        """当前档 (真源 active_product); 真源没给就用 550B (调试档兜底, 与 zmax_profile 同口径)."""
        key = str(self._profile().get("key") or "550B")
        for m in self.modes():
            if m["key"] == key:
                return m
        return self.modes()[1]

    def set_boot_product(self, key):
        """控制台**启动时**读到的档 (它的界面/话题就是按这个建的)。

        与真源现读不同 ⇒ 右侧画 ⟳, 表示「真源已换, 重启控制台才全生效」; 不假装已经生效。
        """
        k = str(key or "").strip().upper()
        if k:
            self._boot = k
            self._sig = None
            self.update()

    def switch_profile(self, key):
        """写真源 active_product (留 .bak + 日志)。界面立刻显示新档, 但**运行时能力要重启控制台才全身生效**. """
        try:
            from lerobot.engineering import status_hub as _hub
            r = _hub.set_profile(key)
        except Exception as ex:                                        # noqa: BLE001
            r = {"ok": False, "err": "%s: %s" % (type(ex).__name__, str(ex)[:90]), "key": key}
        if r.get("ok"):
            self._sig = None
            self.update()
        return r

    def _popup_profile_menu(self, gpos):
        cur = self.current()
        m = QMenu(self)
        m.setStyleSheet("QMenu{background:#1f2733;color:#e6edf3;border:1px solid #30363d;font-size:10px;}"
                        "QMenu::item{padding:3px 18px 3px 10px;}QMenu::item:selected{background:#2d3b4d;}"
                        "QMenu::separator{height:1px;background:#30363d;margin:3px 6px;}")
        for t in self.modes():
            mark = {"cyan": "◉", "green": "●", "yellow": "◐", "dim": "○"}.get(t["dot"], "○")
            act = m.addAction("%s %s  %s · %s · %s" % (mark, t["key"], t["hw"], t["mode"], t["fact"]))
            act.setCheckable(True)
            act.setChecked(t["key"] == cur["key"])
            act.triggered.connect(lambda _c=False, k=t["key"]: self._on_pick(k))
        m.addSeparator()
        m.addAction("切换写真源 active_product … 重启控制台后能力全生效").setEnabled(False)
        m.exec_(gpos)

    def _on_pick(self, key):
        r = self.switch_profile(key)
        if not r.get("ok"):
            self.setToolTip("切换失败: %s" % r.get("err"))
        self._sig = None
        self.update()

    def mousePressEvent(self, ev):                                      # noqa: N802
        try:
            if ev.button() == Qt.LeftButton and ev.pos().x() <= 96:
                self._popup_profile_menu(ev.globalPos())
                return
        except Exception:
            pass
        super().mousePressEvent(ev)

    def _chips(self):
        """按层聚合 (型号可能一层多个): 每层一个 chip —— 优先展示**在役**那一个的版本号,
        灯色取该层最好状态 (在役>候选>未训练), 推理标记 = 该层任一在推理。
        ⇒ 一排就看得出「哪层在役/哪层只是候选/哪层没训过」。最多 MAX_CHIPS 层, 其余聚合成 ×N。
        """
        groups = {}
        order = []
        for m in self._models():
            ly = str(m.get("layer") or "?")
            if ly not in groups:
                groups[ly] = []
                order.append(ly)
            groups[ly].append(m)
        chips = []
        for ly in order:
            ms = groups[ly]
            prim = None
            for st in ("in_service", "candidate", "untrained"):
                for x in ms:
                    if str(x.get("state")) == st:
                        prim = x
                        break
                if prim is not None:
                    break
            prim = prim or ms[0]
            chips.append({"layer": ly, "state": str(prim.get("state") or ""),
                          "version": prim.get("version"), "inferring": any(bool(x.get("inferring")) for x in ms),
                          "n": len(ms), "in_service": any(str(x.get("state")) == "in_service" for x in ms),
                          "name": short_name(prim.get("name")), "full": str(prim.get("name") or "")})
        if not chips:
            # 读不到/服务不可达 ⇒ 占位灰灯 (行形状不变, 一眼看出"没数据"而不是"没这一层")
            chips = [{"layer": ly, "state": "", "version": "", "inferring": False,
                      "n": 0, "in_service": False, "placeholder": True, "name": "", "full": ""}
                     for ly in LAYER_ORDER]
        return chips

    def _assets(self):
        d = self._obj if isinstance(self._obj, dict) else {}
        return [x for x in (d.get("assets") or []) if isinstance(x, dict)]

    def _refresh_tooltip(self):
        try:
            self._refresh_tooltip_inner()
        except Exception:
            self.setToolTip("状态面板 · %s" % self.url)

    def _refresh_tooltip_inner(self):
        d = self._obj
        if not isinstance(d, dict):
            self.setToolTip("状态面板 · 8796 /status/all 不可达\n%s\n%s" % (self.url, self._err or ""))
            return
        _, gpu, cpu, mem, dsk = self._rows()
        gpu = gpu or {}
        cpu = cpu or {}
        mem = mem or {}
        dsk = dsk or {}
        L = ["状态面板 · %s" % self.url]
        L.append("GPU %s · util %s%% · 显存 %s/%s MB · %s°C" % (
            gpu.get("name", "—"), _num(gpu.get("util")), gpu.get("mem_used_mb", "—"),
            gpu.get("mem_total_mb", "—"), gpu.get("temp_c", "—")))
        L.append("CPU %s 核 · util %s%% · load1 %s" % (
            cpu.get("cores", "—"), _num(cpu.get("util")), cpu.get("load1", "—")))
        L.append("内存 %s/%s GB · 磁盘 %s/%s GB (%s%%)" % (
            mem.get("used_gb", "—"), mem.get("total_gb", "—"),
            dsk.get("used_gb", "—"), dsk.get("total_gb", "—"), dsk.get("pct", "—")))
        pr = self._profile()
        if pr:
            caps = pr.get("caps") or {}
            L.append("产品档 %s · %s · 算力=%s (%s)" % (pr.get("key", "—"), pr.get("role", "—"),
                                                     pr.get("hw_label", "—"), pr.get("mode", "—")))
            L.append("  档位能力: topics=%s comm=%s 信号分析=%s 3D场景=%s VSCode=%s 远程旁路=%s 算法=%s"
                     % (caps.get("topics", "—"), caps.get("comm", "—"),
                        caps.get("signal_analysis", "—"), caps.get("scene_3d", "—"),
                        caps.get("vscode", "—"), caps.get("remote_bypass", "—"), caps.get("algo", "—")))
            L.append("  真源 %s" % (pr.get("source") or "—"))
            L.append("  硬件要求 %s · 本机 %s %s" % (
                "%s(%s)" % (pr.get("hw_label", "—"), pr.get("hardware", "—")),
                pr.get("host_hardware", "—"), "✓ 相符" if pr.get("hw_ok", True) else "⚠ 不符"))
            if pr.get("hw_warn"):
                L.append("  ⚠ %s" % pr.get("hw_warn"))
            boot = getattr(self, "_boot", "") or pr.get("key")
            if boot and boot != pr.get("key"):
                L.append("  ⚠ 已从 %s 切到 %s: 真源已写, **重启控制台**后界面/话题/算法准入才全生效" % (boot, pr.get("key")))
            L.append("  点最左侧 chip 可换档: 550A·4060 开发训练 / 550B·4060 桥接(状态空间工程·全tool) / 550C·Intel 端侧部署")
            L.append("  硬件绑定以真源 products[<档>].hardware 为准; 档位与本机不符时 chip 灯转黄")
        cm = self._cams()
        if cm:
            if cm.get("online"):
                items = cm.get("items") or []
                L.append("相机 %d/%d 有帧 (帧龄≤3s): %s" % (
                    cm.get("n_fresh", 0), cm.get("n_total", 0),
                    " · ".join("%s %s" % (str(i.get("label") or i.get("key"))[:14],
                                          ("%.1fs" % i["age_s"]) if isinstance(i.get("age_s"), (int, float)) and i["age_s"] >= 0 else "无")
                               for i in items)))
            else:
                L.append("相机: 8791 /stats 不可达 (%s)" % (cm.get("err") or "—"))
        o = self._orin()
        if o:
            if o.get("online"):
                rob = o.get("robot") or {}
                L.append("Orin · %s · 内存 %s/%s MB · load %s · %s°C · 机器人 %s/%s · 生产栈 %s"
                         % (o.get("host", "—"), o.get("mem_used_mb", "—"), o.get("mem_total_mb", "—"),
                            o.get("load1", "—"), o.get("cpu_temp_c", "—"),
                            rob.get("power_state", "—"), rob.get("operation_state", "—"),
                            ",".join(k for k, v in (o.get("robot_stack") or {}).items() if v) or "无"))
            else:
                L.append("Orin: 不可达 (%s)" % (o.get("tried") or "—"))
        e = self._edge()
        if e:
            hwe = e.get("hw") or {}
            L.append("Intel 端侧 · %s · %s · 模型 %s (sha %s)" % (
                "在线" if e.get("online") else "不通",
                ("推理中 %sms" % e.get("last_ms")) if e.get("busy") else "空闲",
                str(e.get("model") or "—").split("/")[-1], e.get("sha16") or "—"))
            acc = hwe.get("accel") if isinstance(hwe.get("accel"), dict) else {}
            a_cpu = acc.get("cpu") if isinstance(acc.get("cpu"), dict) else {}
            a_gpu = acc.get("gpu") if isinstance(acc.get("gpu"), dict) else {}
            a_npu = acc.get("npu") if isinstance(acc.get("npu"), dict) else {}
            L.append("  Intel CPU: %s · %s 线程 · %s→%s MHz · 占用 %s%% · load %s" % (
                hwe.get("cpu_model") or a_cpu.get("name") or "—", hwe.get("cpu_n") or "—",
                hwe.get("cpu_mhz_now") or "—", hwe.get("cpu_mhz_max") or a_cpu.get("cap") or "—",
                hwe.get("cpu_pct") if hwe.get("cpu_pct") is not None else "—", hwe.get("load1", "—")))
            L.append("  Intel iGPU: %s · %s · 算力 %s TOPS(INT8) · 驱动 %s · 当前%s" % (
                a_gpu.get("name") or "—", a_gpu.get("arch") or "—",
                ("%.1f" % a_gpu["tops_int8"]) if isinstance(a_gpu.get("tops_int8"), (int, float)) else "—",
                a_gpu.get("driver") or "—", "在用" if a_gpu.get("in_use") else "空闲"))
            L.append("  Intel NPU: %s · %s · 算力 %s TOPS(INT8) · %s · %s · 当前%s" % (
                a_npu.get("name") or "—", a_npu.get("arch") or "—",
                ("%.1f" % a_npu["tops_int8"]) if isinstance(a_npu.get("tops_int8"), (int, float)) else "—",
                a_npu.get("driver") or "—", a_npu.get("dev") or "—",
                "在用" if a_npu.get("in_use") else ("空闲" if a_npu.get("present") else "不在")))
            L.append("  Intel 内存: %s/%s MB (%s%%) · 温度 %s°C · n_req %s · 最近10s %s 次/s" % (
                hwe.get("mem_used_mb", "—"), hwe.get("mem_total_mb", "—"), hwe.get("mem_pct", "—"),
                hwe.get("temp_c", "—"), e.get("n_req", "—"), e.get("rate_10s", "—")))
            pl = e.get("pipeline") or {}
            if pl.get("on"):
                for dev, st in (pl.get("devices") or {}).items():
                    L.append("  并行调度 %s: %.1f fps · 均值 %s ms · 占空 %s%% · 已跑 %s 次%s" % (
                        dev, st.get("fps") or 0, st.get("avg_ms"), st.get("duty_pct"), st.get("n"),
                        (" · " + st["err"]) if st.get("err") else ""))
                L.append("  合计 %.1f fps (NPU+GPU 同时吃满)" % (pl.get("total_fps") or 0))
            for dsk in (hwe.get("disks") or [])[:3]:
                L.append("  Intel 磁盘 %s: 总 %s GB · 已用 %s GB · 余 %s GB (%s%%)" % (
                    dsk.get("mount", "—"), dsk.get("total_gb", "—"), dsk.get("used_gb", "—"),
                    dsk.get("free_gb", "—"), dsk.get("pct", "—")))
            if e.get("tried"):
                L.append("  试过: %s" % ", ".join(e["tried"]))
        L.append("模型 (%d):  (短名 ≤9 字, 缩自 name 真值)" % len(self._models()))
        for m in self._models():
            L.append("  [%s] %-9s · %s · %s（%s）%s" % (
                m.get("layer", "?"), short_name(m.get("name")), m.get("version", "?"),
                m.get("name", "?"), m.get("state", "?"),
                " · 推理中" if m.get("inferring") else ""))
        t = self._training()
        if t.get("active"):
            L.append("训练中: [%s] %s · %s · %s/%s (%s%%) · eta %ss · %s s/step" % (
                t.get("layer", "?"), t.get("name", "?"), t.get("version", "?"),
                t.get("step", "?"), t.get("total", "?"), t.get("pct", "?"),
                t.get("eta_s", "?"), t.get("speed_s_per_step", "?")))
        else:
            L.append("训练中: 无")
        for a in self._assets():
            L.append("资产: %s %s · %s · %s" % (a.get("kind", ""), a.get("version", ""),
                                                a.get("name", ""), a.get("path", "")))
        self.setToolTip("\n".join(L))

    # ---------- 绘制 ----------
    def paintEvent(self, _e):                                           # noqa: N802
        try:
            self._paint()
        except Exception:                                               # paint 内异常会 abort 全进程
            pass

    def _paint(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(C_BG2))
        p.setPen(QPen(QColor(C_BORDER), 1))
        p.drawLine(0, 0, w, 0)

        # 字体一律用 setPixelSize (本机 Qt 字体 DPI≈192, pt 会放大 ~1.5 倍 ⇒ 撑破小框)
        f_lb = QFont(UI)
        f_lb.setPixelSize(10)
        f_sm = QFont(MONO)
        f_sm.setPixelSize(11)
        f_name = QFont(UI)                  # 短模型名 (2026-10-01 加: 层标和版本号都看不出是哪个模型)
        f_name.setPixelSize(10)
        f_ver = QFont(MONO)
        f_ver.setPixelSize(10)
        f_num = QFont(MONO)
        f_num.setPixelSize(11)
        f_num.setBold(True)
        f_sb = QFont(MONO)
        f_sb.setPixelSize(11)
        f_sb.setBold(True)

        # ── 算力目标 chip (2026-10-21 老倪: 最左侧要显示 550A/4060 · 550B/标定 · 550C/Intel) ──────
        #    灯: 青=端侧推理中 · 绿=在线/可观察 · 黄=部分掉线 · 灰=不通;  ⟳ = 已切档但待重启生效
        cur = self.current()
        cy = h / 2.0
        gw = 88.0
        SEL_W = 96.0
        boot = getattr(self, "_boot", "") or cur["key"]
        pending = bool(boot) and boot != cur["key"]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1f2733"))
        p.drawRoundedRect(QRectF(4.0, cy - 9.0, SEL_W - 14.0, 18.0), 9.0, 9.0)
        self._lamp(p, 12.0, cy, QColor({"cyan": C_CYAN, "green": C_GREEN, "yellow": C_YELLOW,
                                        "dim": C_DIM}.get(cur["dot"], C_GREEN)), bool(cur["online"]))
        p.setPen(QColor(C_WHITE if cur["online"] else C_DIM))
        p.setFont(f_lb)
        p.drawText(QRectF(19.0, 0, 58.0, h), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(f_lb).elidedText("%s·%s" % (cur["key"], cur["hw"]), Qt.ElideRight, 58))
        p.setPen(QColor(C_YELLOW if pending else C_GRAY))
        p.drawText(QRectF(SEL_W - 22.0, 0, 10.0, h), Qt.AlignVCenter | Qt.AlignRight,
                   "⟳" if pending else "▾")

        _slots = list(cur["slots"])[:5]
        _SEM = {"ok": C_GREEN, "warn": C_YELLOW, "bad": C_RED, "idle": C_DIM, "busy": C_CYAN}
        for i, _sl in enumerate(_slots):
            cap, frac, txt = _sl[0], _sl[1], _sl[2]
            sem = _sl[3] if len(_sl) > 3 else None
            x0 = SEL_W + i * gw
            has = (frac is not None) or (txt not in (None, "", "—"))
            if sem:
                col = QColor(_SEM.get(sem, C_GREEN))
            else:
                col = QColor(tone(frac)) if frac is not None else QColor(C_GRAY)
            self._lamp(p, x0 + 5, cy, col, has)
            p.setPen(QColor(C_GRAY))
            p.setFont(f_lb)
            _lw = 25.0 if frac is not None else 34.0      # 纯文字槽 (机械臂/栈/NPU/GPU) 标签区给宽, 三字不截
            p.drawText(QRectF(x0 + 11, 0, _lw, h), Qt.AlignVCenter | Qt.AlignLeft,
                       QFontMetrics(f_lb).elidedText(cap, Qt.ElideRight, int(_lw)))
            bx, bw, bh = (x0 + 37 if frac is not None else x0 + 47), (26 if frac is not None else 16), 7
            by = cy - bh / 2.0
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(TRACK))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 3.5, 3.5)
            if frac is not None:
                p.setBrush(col)          # 2px 底 (原 3px): 6% 的条看起来别像 11%
                p.drawRoundedRect(QRectF(bx, by, max(2.0, bw * min(1.0, max(0.0, frac / 100.0))), bh), 3.5, 3.5)
            right = str(txt) if txt not in (None, "") else _txt(frac)
            p.setPen(QColor(C_WHITE if has else C_DIM))
            p.setFont(f_num)
            p.drawText(QRectF(x0 + 60, 0, 26, h), Qt.AlignVCenter | Qt.AlignRight, right)

        # ---- 模型层 chips (同一行: 画在训练条之后 / 3DGS 之前的空档里, 见本函数末尾) ----
        # (老倪 2026-10-01: 「L2 L3 L4 的模型名字要显示出来, 现在的 v1001 也不知道是哪个模型」)
        vs = self._chips()
        fm_sm, fm_nm, fm_ver = QFontMetrics(f_sm), QFontMetrics(f_name), QFontMetrics(f_ver)

        def _chip_w(m, with_cnt):
            ly = str(m.get("layer", "?"))[:3]
            nm = str(m.get("name") or "")
            vr = short_ver(m.get("version")) if m.get("version") else "—"
            w_ly, w_nm, w_vr = fm_sm.width(ly), fm_nm.width(nm), fm_ver.width(vr)
            cnt = fm_ver.width("+%d" % max(0, int(m.get("n") or 1) - 1)) + 4 if (with_cnt and int(m.get("n") or 1) > 1) else 0
            return 12 + w_ly + 4 + (w_nm + 4 if w_nm else 0) + w_vr + cnt, w_ly, w_nm, w_vr

        # 通信灯 (绿=最近取数成功; 灰=服务不可达/读失败) —— 一行布局: 落在这条中线的右端
        fresh = self._age is not None and (time.time() - self._age) < max(3.0, self.POLL_MS / 1000.0 * 3)
        self._lamp(p, w - 9, cy, QColor(C_GREEN if fresh else C_DIM), fresh)

        # ---- 训练进度条 + % · 模型层 chips · 3DGS 资产 —— 全部落在**这一条中线**上 (一行布局) ----
        tx = SEL_W + len(_slots) * gw + 6.0   # 算力 chip + 该档的指标槽 (4~5 个) 之后
        bar_w = 40.0
        pct_x = tx + bar_w + 3.0
        pct_w = 26.0
        t = self._training()
        pct_end = tx + 14.0
        if t.get("active"):
            pct = _num(t.get("pct"))
            if pct is None:
                try:
                    pct = _num(float(t.get("step") or 0) / float(t.get("total") or 1) * 100.0)
                except Exception:
                    pct = None
            bw, bh = bar_w, 7
            by = cy - bh / 2.0
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(TRACK))
            p.drawRoundedRect(QRectF(tx, by, bw, bh), 3.5, 3.5)
            if pct is not None:
                p.setBrush(QColor(C_CYAN))
                p.drawRoundedRect(QRectF(tx, by, max(3.0, bw * min(1.0, max(0.0, pct / 100.0))), bh), 3.5, 3.5)
            p.setPen(QColor(C_WHITE if pct is not None else C_DIM))
            p.setFont(f_num)
            p.drawText(QRectF(pct_x, 0, pct_w, h), Qt.AlignVCenter | Qt.AlignRight, _txt(pct))
            pct_end = pct_x + pct_w
        else:
            self._lamp(p, tx + 5, cy, QColor(C_DIM), False)

        # 3DGS 资产 (同一条中线的最右, 通信灯左侧) —— 先算它要占多宽, 剩下的才给模型层
        assets = [a for a in self._assets() if str(a.get("kind", "")).upper() == "3DGS"]
        ver = short_ver(assets[-1].get("version")) if assets else "—"
        label = "3DGS %s" % ver
        if len(assets) > 1:
            label = "3DGS ×%d %s" % (len(assets), ver)
        p.setFont(f_ver)
        xr = w - 22.0                            # 右端给通信灯(w-9)留位
        room = max(24.0, xr - (pct_end + 8.0))
        label = QFontMetrics(f_ver).elidedText(label, Qt.ElideRight, int(room))
        tw = QFontMetrics(f_ver).width(label)
        x_assets = xr - tw

        # ---- 模型层 chips: 塞在「训练条之后、3DGS 之前」的空档里 (一行) ----
        chips_x0 = pct_end + 12.0
        chips_limit = max(chips_x0, x_assets - 10.0)
        with_cnt = chips_x0 + sum(_chip_w(m, True)[0] + 8 for m in vs) <= chips_limit
        x = chips_x0
        for m in vs:
            cw, w_ly, w_nm, w_vr = _chip_w(m, with_cnt)
            if x + cw > chips_limit:                 # 真源 4 层一定放得下; 这是不许画出框的兜底
                break
            st = str(m.get("state", ""))
            col = QColor(STATE_COLOR.get(st, C_DIM))
            self._lamp(p, x + 6, cy, col, st in STATE_COLOR)
            # 推理/训练标记 = 灯的外圈 (青环=推理中 · 黄弧=训练中), 不占额外宽度
            if self._is_training_layer(m.get("layer")):
                p.setPen(QPen(QColor(C_YELLOW), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawArc(QRectF(x - 0.5, cy - 6.5, 13, 13), 40 * 16, 280 * 16)
            elif m.get("inferring"):
                p.setPen(QPen(QColor(C_CYAN), 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QRectF(x - 0.5, cy - 6.5, 13, 13))
            p.setPen(QColor(C_WHITE))
            p.setFont(f_sm)
            p.drawText(QRectF(x + 13, 0, w_ly, h), Qt.AlignVCenter | Qt.AlignLeft,
                       str(m.get("layer", "?"))[:3] or "?")
            cx = x + 13 + w_ly + 4
            if w_nm:                            # 短模型名 (最要紧的一格)
                p.setPen(QColor(C_GRAY))
                p.setFont(f_name)
                p.drawText(QRectF(cx, 0, w_nm, h), Qt.AlignVCenter | Qt.AlignLeft, str(m.get("name") or ""))
                cx += w_nm + 4
            p.setPen(QColor(C_DIM))
            p.setFont(f_ver)
            p.drawText(QRectF(cx, 0, w_vr, h), Qt.AlignVCenter | Qt.AlignLeft,
                       short_ver(m.get("version")) if m.get("version") else "—")
            cx += w_vr
            if with_cnt and int(m.get("n") or 1) > 1:       # 其余同层模型: 计数聚合
                p.setPen(QColor(C_DIM))
                p.setFont(f_ver)
                p.drawText(QRectF(cx + 4, 0, 26, h), Qt.AlignVCenter | Qt.AlignLeft,
                           "+%d" % (int(m.get("n") or 1) - 1))
            x += cw + 8

        p.setPen(QColor(C_BLUE_A if assets else C_DIM))
        p.drawText(QRectF(x_assets, 0, tw, h), Qt.AlignVCenter | Qt.AlignRight, label)

    def _is_training_layer(self, layer):
        t = self._training()
        return bool(t.get("active")) and str(t.get("layer", "")) == str(layer)

    @staticmethod
    def _lamp(p, cx, cy, col, on=True):
        """Ø8 红绿灯圆点 (亮=有状态, 灰=未知)"""
        col = QColor(col)
        if on and col.name() != C_DIM:
            glow = QColor(col)
            glow.setAlpha(60)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(cx - 7, cy - 7, 14, 14))
        p.setBrush(col)
        p.setPen(QPen(QColor("#000000"), 1))
        p.drawEllipse(QRectF(cx - 4, cy - 4, 8, 8))


C_BLUE_A = "#58a6ff"        # 资产标签色 (模块级常量, 与 studio 的 C_BLUE 同值)


# ============================================================
# 自检 / 单机截图
# ============================================================
DEMO = {
    "ts": 1759000000.0,
    "hw": {"gpu": {"util": 97, "mem_used_mb": 21003, "mem_total_mb": 24564, "temp_c": 71,
                   "name": "NVIDIA GeForce RTX 4090"},
           "cpu": {"util": 41, "cores": 16, "load1": 6.52},
           "mem": {"used_gb": 21.4, "total_gb": 31.2},
           "disk": {"used_gb": 812, "total_gb": 1024, "pct": 79}},
    "models": [{"layer": "L2", "name": "YOLO+解析链", "version": "v1001-r6", "state": "in_service", "inferring": True},
               {"layer": "L3", "name": "SmolVLA+LEW", "version": "v1001-r6", "state": "in_service", "inferring": False},
               {"layer": "L4", "name": "INTACT", "version": "r3", "state": "candidate", "inferring": False},
               {"layer": "L5", "name": "planner", "version": "v2", "state": "untrained", "inferring": False}],
    "training": {"active": True, "layer": "L5", "name": "planner", "version": "v7", "step": 12400,
                 "total": 20000, "pct": 62, "eta_s": 1830, "speed_s_per_step": 0.42},
    "assets": [{"kind": "3DGS", "name": "station_scan", "version": "v12", "path": "/home/ubuntu/zmax/zmax_data/3dgs/station"}],
}



# 8796 /status/all 真实响应快照 (2026-10-01 抓取, 13 个模型; 模型名截断到 24 字符以省空间)
REAL = {"ts": 0.0, "hw": {"gpu": {"util": 0, "mem_used_mb": 660, "mem_total_mb": 8188, "temp_c": 55, "name": "NVIDIA GeForce RTX 4060 Laptop GPU"}, "cpu": {"util": 9, "cores": 32, "load1": 2.98}, "mem": {"used_gb": 7.7, "total_gb": 31.0}, "disk": {"used_gb": 353, "total_gb": 425, "pct": 83}}, "models": [{"layer": "L2", "name": "YOLO 检测 + 2D→3D 解算 (真机域在", "version": "v20261001-annot", "state": "in_service", "inferring": True}, {"layer": "L2", "name": "SAM3 开放词汇分割 (官方权重 09-29 ", "version": "v20261001-annot_v1", "state": "candidate", "inferring": False}, {"layer": "L2", "name": "状态空间小模型组 (前馈/估计/预测/校正)", "version": "unknown", "state": "in_service", "inferring": True}, {"layer": "L2", "name": "光学质量检测 AOI (金手指/端面)", "version": "unknown", "state": "in_service", "inferring": False}, {"layer": "L3", "name": "SmolVLA+LEW 长程规划 (在役运行时 ", "version": "smolvla_lew_v10_1h/004000", "state": "in_service", "inferring": True}, {"layer": "L3", "name": "SmolVLA+LEW 长程规划 LoRA (7", "version": "v20261001-r6", "state": "candidate", "inferring": False}, {"layer": "L3", "name": "L3 长程序列规划器 TaskPlanner", "version": "unknown", "state": "in_service", "inferring": False}, {"layer": "L3", "name": "Flow-Matching Action Hea", "version": "unknown", "state": "in_service", "inferring": False}, {"layer": "L4", "name": "INTACT-JEPA 意图-动作 (在役稳定指", "version": "intact_l4_current", "state": "in_service", "inferring": True}, {"layer": "L4", "name": "INTACT 世界模型 光模块插入 v6+LoR", "version": "v20261001-r200", "state": "candidate", "inferring": False}, {"layer": "L4", "name": "流形专家预测器 (JEPA: 潜空间→流形→动作", "version": "unknown", "state": "in_service", "inferring": False}, {"layer": "L4", "name": "阶段专家 MOE · 7 专家 + 先验门控路由", "version": "unknown", "state": "in_service", "inferring": False}, {"layer": "L5", "name": "DeepSeek 视觉规划 (L5 大模型主路)", "version": "deepseek-vl", "state": "in_service", "inferring": True}], "training": {"active": False, "layer": "", "name": "", "version": "", "step": 0, "total": 0, "pct": 0, "eta_s": 0, "speed_s_per_step": 0.0, "note": "无 >1500MiB 的计算进程 ⇒ 未在训练"}, "assets": [{"kind": "3DGS", "name": "scene_20261001_run3 · 81612 高斯", "version": "v20261001-574772c8", "path": "/home/ubuntu/zmax/zmax_data/gs_assets/scene_20261001_run3/gs.splat"}]}


def _selftest(shot=None):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ok = True
    res = []

    def chk(name, cond, extra=""):
        nonlocal ok
        ok = ok and bool(cond)
        res.append("%s %s%s" % ("✓" if cond else "✗", name, (" :: " + str(extra)) if extra else ""))

    # 1) 面积红线 (2026-10-14: 老倪「排成一行; 现在两行占地方」⇒ 560x68 两行 → 1080x40 一行)
    pn = StatusPanel(poll=False)
    chk("面积 ≤ 1080x56 px (一行)", pn.width() <= 1080 and pn.height() <= 56, "%dx%d" % (pn.width(), pn.height()))

    # 1b) 真·一行判据: 渲染后按像素扫描内容行带, 必须只有**一条**带 (背景外的像素行连续成带)
    pn.feed(REAL)
    img = pn.grab().toImage()
    bands, cur = [], None
    for y in range(3, img.height()):                    # 跳过 y=0 的 1px 边框线
        n = 0
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            if abs(c.red() - 0x16) > 12 or abs(c.green() - 0x1b) > 12 or abs(c.blue() - 0x21) > 12:
                n += 1
        if n > 0:
            cur = (cur[0], y) if cur else (y, y)
        elif cur:
            bands.append(cur)
            cur = None
    if cur:
        bands.append(cur)
    chk("渲染内容只有 1 条行带 (一行)", len(bands) == 1, "行带 %s" % (bands,))
    if bands:
        y0, y1 = bands[0]
        chk("行带高度 ≤ 40px 且占满中部", (y1 - y0) <= 40, "%d..%d (%dpx)" % (y0, y1, y1 - y0 + 1))
    # 1c) 一行里必须同时看得见 4 个硬件项 + 4 个模型层 + 3DGS (都没有被折到别处)
    xs = [x for x in range(0, img.width(), 2)
          if any(abs(img.pixelColor(x, y).red() - 0x16) > 12 or abs(img.pixelColor(x, y).green() - 0x1b) > 12
                 for y in range(max(3, bands[0][0]), min(img.height(), bands[0][1] + 1))) ] if bands else []
    chk("单行内容横跨 ≥600px (装得下 4 硬件+4 层+资产)", bool(xs) and (max(xs) - min(xs)) >= 600,
        "x %s..%s" % (min(xs) if xs else "-", max(xs) if xs else "-"))

    # 2) 颜色阈值
    chk("阈值 69→绿", tone(69) == C_GREEN)
    chk("阈值 70→黄", tone(70) == C_YELLOW)
    chk("阈值 90→红", tone(90) == C_RED)
    chk("缺测→灰", tone(None) == C_DIM)

    # 2b) 极短版本号规则 (8796 真实载荷里的写法)
    chk("short_ver 去日期前缀", short_ver("v20261001-annot") == "annot", short_ver("v20261001-annot"))
    chk("short_ver 留尾巴", short_ver("v20261001-r6") == "r6", short_ver("v20261001-r6"))
    chk("short_ver ckpt 目录", short_ver("smolvla_lew_v10_1h/004000") == "004000", short_ver("smolvla_lew_v10_1h/004000"))
    chk("short_ver 兜底", short_ver("unknown") == "unknown" and short_ver(None) == "—")

    # 2c) 同层多模型 → 聚合成一个 chip 且优先在役
    pn.feed(REAL)
    ch = pn._chips()
    chk("13 模型聚合成 4 层 chip", [c["layer"] for c in ch] == ["L2", "L3", "L4", "L5"], [c["layer"] for c in ch])
    l2 = ch[0]
    chk("L2 chip 取在役模型版本", short_ver(l2["version"]) == "annot" and l2["state"] == "in_service", l2)
    chk("L2 chip 标记推理中", l2["inferring"] is True)

    # 2d) 短模型名 (老倪 2026-10-01: 「L2 L3 L4 的模型名字要显示出来, 现在的 v1001 也不知道是哪个模型」)
    chk("短名 ≤9 字", all(1 <= len(c["name"]) <= 9 for c in ch), [c["name"] for c in ch])
    chk("短名可读: L2 YOLO/SAM3", short_name(REAL["models"][0]["name"]) == "YOLO"
        and short_name(REAL["models"][1]["name"]) == "SAM3",
        [short_name(REAL["models"][0]["name"]), short_name(REAL["models"][1]["name"])])
    chk("短名: SmolVLA / INTACT / DeepSeek",
        [short_name(REAL["models"][4]["name"]), short_name(REAL["models"][8]["name"]),
         short_name(REAL["models"][12]["name"])] == ["SmolVLA", "INTACT", "DeepSeek"])
    chk("全中文名 → 汉字短名", short_name("流形专家预测器 (JEPA: 潜空间→流形→动作)") == "流形专家"
        and short_name("状态空间小模型组 (前馈/估计/预测/校正)") == "状态空间")
    chk("层标前缀被去掉", short_name("L3 长程序列规划器 TaskPlanner") == "TaskPlan")
    chk("同层两个 INTACT 能区分",
        short_name("INTACT-JEPA 意图-动作 (在役稳定指针)") == "INTACT"
        and short_name("INTACT 世界模型 光模块插入 v6+LoRA") == "INTACT-WM",
        [short_name("INTACT-JEPA 意图-动作 (在役稳定指针)"),
         short_name("INTACT 世界模型 光模块插入 v6+LoRA")])
    chk("两个 SmolVLA 能区分",
        short_name("SmolVLA+LEW 长程规划 (在役运行时 ckpt)") == "SmolVLA"
        and short_name("SmolVLA+LEW 长程规划 LoRA (7帧窗口)") == "SmolVLA-L")
    chk("chip 带短名(非空)", all(c["name"] and c["name"] != "?" for c in ch), [c["name"] for c in ch])

    # 3) 正常载荷: 渲染不崩 + 有内容
    pn.feed(DEMO)
    img = pn.grab().toImage()
    nonbg = sum(1 for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
                if abs(img.pixelColor(x, y).red() - 0x16) > 12 or abs(img.pixelColor(x, y).green() - 0x1b) > 12)
    chk("正常载荷渲染有内容(非背景像素)", nonbg > 200, nonbg)
    if shot:
        pn.grab().save(shot)
    chk("tooltip 含全部模型与训练", all(k in pn.toolTip() for k in ("L2", "L3", "L4", "L5", "训练中", "3DGS")),
        pn.toolTip().splitlines()[0])

    # 4) 服务不可用 → 灰点, 不崩
    pn.feed_error("ConnectionRefusedError")
    im2 = pn.grab().toImage()
    chk("降级不崩且能重绘", im2.width() == pn.width() and im2.height() == pn.height())
    if shot:
        pn.grab().save(shot.replace(".png", "_degraded.png"))
    chk("降级 tooltip 明写不可达", "不可达" in pn.toolTip())

    # 4b) 多模型(6 个) → 聚合位渲染不崩, 仍 ≤560 宽
    many = json.loads(json.dumps(DEMO))
    many["models"] = many["models"] + [{"layer": "L6", "name": "x2", "version": "v9", "state": "in_service", "inferring": True},
                                       {"layer": "L7", "name": "x3", "version": "v8", "state": "candidate", "inferring": False}]
    pn.feed(many)
    pn.grab()
    chk("6 模型走聚合位不崩", pn.width() == 1080)
    if shot:
        pn.grab().save(shot.replace(".png", "_many.png"))

    # 5) 畸形载荷防御
    bad = [None, {}, {"hw": None}, {"hw": {"gpu": {"util": "x"}}, "models": "nope", "training": [], "assets": {}},
           {"hw": {"mem": {"used_gb": None, "total_gb": 0}}, "disk": {"pct": "abc"}},
           {"models": [{"layer": "L4"}], "training": {"active": True, "pct": None, "step": 3, "total": 0}}]
    for i, b in enumerate(bad):
        try:
            pn.feed(b)
            pn.grab()
            chk("畸形载荷 #%d 不崩" % i, True)
        except Exception as e:
            chk("畸形载荷 #%d 不崩" % i, False, repr(e))

    # 6) 无服务真实构造 (3s 轮询尝试) → 灰, 不崩
    pn2 = StatusPanel(poll=True, url="http://127.0.0.1:59999/status/all")
    pn2._worker.interval = 0.3
    t0 = time.time()
    while time.time() - t0 < 1.6:
        app.processEvents()
        time.sleep(0.05)
    pn2.grab()
    chk("连不上时仍为灰灯", pn2._obj is None and pn2._err is not None, pn2._err)
    pn2.shutdown()

    print("\n".join(res))
    print("SELFTEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def _live_shot(path, url, seconds, scale=1):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    pn = StatusPanel(url=url)
    pn.show()
    t0 = time.time()
    while time.time() - t0 < float(seconds):
        app.processEvents()
        time.sleep(0.05)
    img = pn.grab().toImage()
    if int(scale) > 1:                      # 放大截图取证 (老倪要 4x 看清层+短名+版本)
        img = img.scaled(img.width() * int(scale), img.height() * int(scale),
                         Qt.IgnoreAspectRatio, Qt.FastTransformation)
    img.save(path)
    print("shot=%s scale=%sx size=%dx%d url=%s data=%s err=%s" % (
        path, scale, img.width(), img.height(), url,
        "ok" if isinstance(pn._obj, dict) else "none", pn._err))
    print("title/短名: %s" % " | ".join("%s %s %s" % (c["layer"], c["name"], short_ver(c["version"]))
                                        for c in pn._chips()))
    print("tooltip=%s" % pn.toolTip().replace("\n", " | "))
    pn.shutdown()
    return 0 if isinstance(pn._obj, dict) else 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--shot", default="")
    ap.add_argument("--live-shot", default="")
    ap.add_argument("--scale", type=int, default=1, help="截图放大倍数 (4 = 4x 取证)")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--seconds", type=float, default=3.0)
    a = ap.parse_args()
    if a.selftest:
        return _selftest(a.shot or None)
    if a.live_shot:
        return _live_shot(a.live_shot, a.url, a.seconds, a.scale)
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
