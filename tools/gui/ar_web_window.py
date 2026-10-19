"""🥽 AR 页面内嵌浏览器窗口 —— 控制台内的 QWebEngineView。

为什么要有它 (老倪 2026-10-19「点击 AR 按钮，还是没反应，得等好长时间」「3D场景，就是立刻打开的」
「要走这条」):
    外部 chromium 出窗实测 0.4~0.9s, 而且命令只是"转发给已在跑的实例" —— 那个实例一忙,
    窗口根本不出来(实测 studio 子进程 execve 成功、线程起来、30s 无窗)。
    内嵌视图实测: create 0.05s · show 0.09s · 页面 load 0.29s ⇒ 和 3D 场景一样"点了就有"。

缩放 (老倪 2026-10-19「打开 AR 页面整体上很小，每次都得按住 Ctrl 用滚轮放大」「记住上次的状态么」):
    · 这台机器 eDP-1 **3200x2000、DPR=1.0、物理 236 DPI** ⇒ 页面里 12px 就只有 12 个物理像素,
      落在这块屏上约 3.6pt, 肉眼就是"小得看不见"。所以默认**按 DPI 自动定标**: dpi/96*0.85
      (236 DPI ⇒ 2.1 倍); 换一台 96 DPI 的机器自动回到 1.0, 不写死。
    · 缩放值**存盘**(zmax_data/ar_zoom.json): 下次开控制台/下次点 AR 就是你上次那一档 —— 不用每次 Ctrl+滚轮。
    · 三种调法都能记住: 工具栏 🔍－/🔍＋(0.2/下)、Ctrl+滚轮(0.1/格)、Ctrl+= / Ctrl+- / Ctrl+0(回 100%)。

红线:
· PyQt5 的 QtWebEngineWidgets **必须在 QApplication 之前 import**, 否则 PyQt 直接抛
  ImportError("QtWebEngineWidgets must be imported before a QCoreApplication instance is created")。
  已由 studio.py 顶部那句 guarded import 保证; 本模块 import 时若已晚, 会被调用方 except 住并回退外部窗口。
· 只能在 GUI 线程调用(show/raise 都是 Qt 操作)。
· 窗口关掉**不销毁**(保留对象), 下次点 AR 直接 show 回来 —— 页面状态和缩放都还在, 真正"立刻"。
"""
from __future__ import annotations

import json
import os
import sys
import time

from PyQt5.QtCore import QEvent, QUrl, Qt
from PyQt5.QtWidgets import (QAction, QApplication, QLabel, QMainWindow,
                             QToolBar, QVBoxLayout, QWidget)

AR_URL = os.environ.get("ZMAX_AR_URL") or "http://127.0.0.1:8797/ar"

# 仓库根 = tools/gui/../.. ⇒ zmax_data (与 ss_dreamview 的日志/独立 profile 同一个数据盘)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA = os.environ.get("ZMAX_DATA") or os.path.join(_ROOT, "zmax_data")
ZOOM_FILE = os.path.join(_DATA, "ar_zoom.json")
ZOOM_MIN, ZOOM_MAX = 0.6, 3.0
ZOOM_STEP_BTN, ZOOM_STEP_WHEEL = 0.2, 0.1

_WIN = None          # 单例: 整个控制台只开一个 AR 窗口
_T0 = None


def default_zoom() -> float:
    """按屏幕 DPI 定默认缩放 —— 12px 的字在高 DPI 小尺寸屏上不能按 1.0 显示。

    236 DPI(老倪这台 eDP-1 3200x2000, DPR=1.0) ⇒ 236/96*0.85 ≈ 2.1;
    96 DPI 的普通屏 ⇒ 0.85 ⇒ 夹到 1.0(不会莫名放大)。
    """
    _env = os.environ.get("ZMAX_AR_ZOOM")
    if _env:
        try:
            return max(ZOOM_MIN, min(ZOOM_MAX, float(_env)))
        except Exception:                                                   # noqa: BLE001
            pass
    try:
        _dpi = float(QApplication.primaryScreen().physicalDotsPerInch() or 96.0)
    except Exception:                                                       # noqa: BLE001
        _dpi = 96.0
    return round(max(1.0, min(2.6, _dpi / 96.0 * 0.85)), 1)


def load_zoom() -> float:
    """读上次的缩放; 没有/坏了就按 DPI 定。"""
    try:
        with open(ZOOM_FILE, "r", encoding="utf-8") as _f:
            _z = float(json.load(_f).get("zoom"))
        return max(ZOOM_MIN, min(ZOOM_MAX, _z))
    except Exception:                                                       # noqa: BLE001
        return default_zoom()


def save_zoom(z: float) -> None:
    try:
        os.makedirs(_DATA, exist_ok=True)
        _tmp = ZOOM_FILE + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as _f:
            json.dump({"zoom": round(float(z), 2), "ts": time.time()}, _f)
        os.replace(_tmp, ZOOM_FILE)          # 原子写: 半截文件不会把下次启动读崩
    except Exception:                                                       # noqa: BLE001
        pass


def available() -> bool:
    """内嵌浏览器能不能用(装没装 PyQtWebEngine)。"""
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401
        return True
    except Exception:                                                       # noqa: BLE001
        return False


class ARWebWindow(QMainWindow):
    """AR 页面窗口: 工具栏(刷新/缩放/地址) + 一个 QWebEngineView。"""

    def __init__(self, url: str = AR_URL, parent=None):
        super().__init__(parent)
        from PyQt5.QtWebEngineWidgets import QWebEngineView          # 延迟到实例化
        self._url = url
        self._loaded = False
        self._zoom = load_zoom()
        self.setWindowTitle("🥽 AR · 状态空间工程视频源")
        # 窗口尺寸按屏幕算: 布局要求 CSS 视口 ≥ ~1060px 才把 "左=相机+VR / 右=控制面板" 并排显示
        # (main: flex-wrap, leftcol flex-basis 640 + aside 380 + 间距)。缩放到 2.1 时窗口要 ~2400px 才够。
        _w, _h = 2400, 1500
        try:
            _av = QApplication.primaryScreen().availableGeometry()
            _w = min(_w, int(_av.width() * 0.92))
            _h = min(_h, int(_av.height() * 0.92))
        except Exception:                                                   # noqa: BLE001
            pass
        self.resize(_w, _h)
        self.setStyleSheet("QMainWindow{background:#0d1117;}"
                           "QToolBar{background:#161b22;border:0;spacing:6px;padding:4px;}"
                           "QToolBar QLabel{color:#8b949e;font-size:13px;}")

        _central = QWidget(self)
        _lay = QVBoxLayout(_central)
        _lay.setContentsMargins(0, 0, 0, 0)
        _lay.setSpacing(0)

        _tb = QToolBar("AR", self)
        _tb.setMovable(False)
        _act_reload = QAction("↻ 刷新", self)
        _act_reload.setToolTip("重新加载 AR 页面(8797)")
        _act_reload.triggered.connect(self.reload)
        _tb.addAction(_act_reload)

        _act_out = QAction("🔍－", self)
        _act_out.setToolTip("缩小 (Ctrl+-)")
        _act_out.triggered.connect(lambda: self.zoom_by(-ZOOM_STEP_BTN))
        _tb.addAction(_act_out)

        self._lb_zoom = QLabel("  210%  ", self)
        self._lb_zoom.setToolTip("点这里回到 100%")
        self._lb_zoom.setStyleSheet("color:#e6edf3;font-size:13px;font-weight:600;")
        self._lb_zoom.mousePressEvent = lambda _e: self.set_zoom(1.0)    # noqa: E731
        _tb.addWidget(self._lb_zoom)

        _act_in = QAction("🔍＋", self)
        _act_in.setToolTip("放大 (Ctrl+=)")
        _act_in.triggered.connect(lambda: self.zoom_by(ZOOM_STEP_BTN))
        _tb.addAction(_act_in)

        self._lb = QLabel("  %s" % url, self)
        self._lb.setStyleSheet("color:#8b949e;font-size:12px;")
        _tb.addWidget(self._lb)
        _lay.addWidget(_tb)

        self.view = QWebEngineView(self)
        # 🔴 2026-10-19 老倪「AR 打开后, 怎么是白屏呢? 好长时间才显示」:
        #   QWebEngineView 在**画出第一帧之前**的默认底色是白的 (页面 body 再深也轮不到它) ⇒
        #   窗口先是一片白, 等渲染进程起来 + 页面首帧才变深, 看着就是"白屏好久"。
        #   把页面底色钉成 AR 页同一深色 (#0b0f14, 见 tools/web/tcp-ar.html body) ⇒
        #   从点开到出画面的整段都是深色 + 工具栏"⏳ 加载 xx%", 结构上不再有白屏。
        try:
            from PyQt5.QtGui import QColor                          # 延迟 import: 无 WebEngine 时不影响模块加载
            self.view.page().setBackgroundColor(QColor("#0b0f14"))
        except Exception:                                                   # noqa: BLE001
            pass
        try:
            self.view.settings().setAttribute(self.view.settings().JavascriptEnabled, True)
        except Exception:                                                   # noqa: BLE001
            pass
        # 🕒 加载进度上屏: 老倪要"点了就有" —— 没有进度时白色/深色一片, 人以为没反应。
        #    loadStarted → "⏳ 正在加载…" · loadProgress → "⏳ 42%" · loadFinished → "✅ 0.87s".
        try:
            self.view.loadStarted.connect(self._on_load_start)
            self.view.loadProgress.connect(self._on_load_progress)
            self.view.loadFinished.connect(self._on_load_done)
        except Exception:                                                   # noqa: BLE001
            pass
        _lay.addWidget(self.view, 1)
        self.setCentralWidget(_central)
        self._tb = _tb

        self._apply_zoom(self._zoom, save=False)
        # 🔴 实测(2026-10-19): QWebEngineView 的滚轮事件落在它内部渲染控件上(focusProxy 在构造时
        #    还是 None, 事后才建), 局部过滤器收不到 ⇒ Ctrl+滚轮不生效。
        #    改在 QApplication 上挂一层, 只处理"落在这个窗口里"的 Ctrl+滚轮。
        #    ⚠️ 不要再给 self/view 单独装过滤器: 同一个事件会经过多层 ⇒ 一次滚轮放大好几档(实测直接冲到 300%)。
        try:
            _app = QApplication.instance()
            if _app is not None:
                _app.installEventFilter(self)
        except Exception:                                                   # noqa: BLE001
            pass

    # ── 加载状态 (白屏期给可读反馈) ────────────────────────────────
    def _on_load_start(self):
        self._t_load0 = time.time()
        self._lb.setText("  ⏳ 正在加载 AR 页面…")

    def _on_load_progress(self, p: int):
        try:
            self._lb.setText("  ⏳ 加载 %d%%" % int(p))
        except Exception:                                                   # noqa: BLE001
            pass

    def _on_load_done(self, ok: bool):
        _dt = time.time() - (self._t_load0 or time.time())
        self._lb.setText("  %s %.2fs · %s" % ("✅ 页面已加载" if ok else "⚠ 加载失败", _dt, self._url))
        # 落一行到 stderr(控制台日志), 现场可直接对"点了到出画面多少秒"取数, 不靠感觉
        try:
            print("[AR] 页面加载%s 用时 %.2fs · %s" % ("完成" if ok else "失败", _dt, self._url),
                  file=sys.stderr, flush=True)
        except Exception:                                                   # noqa: BLE001
            pass

    # ── 缩放 ────────────────────────────────────────────────────
    def _apply_zoom(self, z: float, save: bool = True):
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, round(float(z), 2)))
        try:
            self.view.setZoomFactor(self._zoom)
        except Exception:                                                   # noqa: BLE001
            return
        try:
            self._lb_zoom.setText("  %d%%  " % round(self._zoom * 100))
        except Exception:                                                   # noqa: BLE001
            pass
        if save:
            save_zoom(self._zoom)

    def set_zoom(self, z: float):
        self._apply_zoom(z)

    def zoom_by(self, dz: float):
        self._apply_zoom(self._zoom + dz)

    def eventFilter(self, obj, ev):
        """Ctrl+滚轮 ⇒ 缩放(并记下来)。不带 Ctrl 的滚轮照常交给页面滚。

        这一层挂在 QApplication 上(见 __init__ 注释), 所以要先判断事件是不是落在本窗口里。

        🔴 一次物理滚轮会被**投递多路**: 实测一次 click 依次到 QWindow → QWidget → QWebEngineView
        → QWidget → ARWebWindow(5 次), 每路都进这个 filter ⇒ 不防抖的话一格滚轮放大 0.5(冲到 300%)。
        其中 **QWindow 那一路每次物理滚轮只出现一次**, 所以:
          · 认 QWindow 那一路 —— 一格算一格, 快速连滚也不会被吞;
          · 其余几路只在"30ms 内没见过 QWindow 那一路"时兜底(某些平台上 QWindow 路可能不出现)。
        """
        try:
            if (ev.type() == QEvent.Wheel and (ev.modifiers() & Qt.ControlModifier)
                    and self.isVisible()):
                _dy = ev.angleDelta().y()
                _now = time.time()
                _wh = None
                try:
                    _wh = self.windowHandle()
                except Exception:                                           # noqa: BLE001
                    _wh = None
                _is_top = (_wh is not None and obj is _wh)
                _w = obj if isinstance(obj, QWidget) else None
                _is_mine = _is_top or (_w is not None and (
                    _w is self or _w is self.view or self.isAncestorOf(_w)))
                if _is_mine:
                    if _is_top:
                        self._last_wheel = _now
                    elif _now - getattr(self, "_last_wheel", 0.0) < 0.03:
                        return True                     # 同一次滚轮的其它投递: 吞掉, 不重复缩放
                    else:
                        self._last_wheel = _now
                    if _dy:
                        self.zoom_by(ZOOM_STEP_WHEEL if _dy > 0 else -ZOOM_STEP_WHEEL)
                    return True
        except Exception:                                                   # noqa: BLE001
            pass
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, ev):
        try:
            # 🔄 2026-10-19: 页面热更新/自救 —— 服务端 tcp-ar.html 改了 mtime 热读, 但内嵌窗口
            #    加载过就不再取 ⇒ 以前只能重启控制台。给 Ctrl+R / F5 = 重载一次(泵也能借这个复活)。
            if ev.key() == Qt.Key_F5 or (
                    ev.key() == Qt.Key_R and (ev.modifiers() & Qt.ControlModifier)):
                self.reload()
                return None
            if ev.modifiers() & Qt.ControlModifier:
                _k = ev.key()
                if _k in (Qt.Key_Plus, Qt.Key_Equal):
                    self.zoom_by(ZOOM_STEP_BTN)
                    return None
                if _k == Qt.Key_Minus:
                    self.zoom_by(-ZOOM_STEP_BTN)
                    return None
                if _k == Qt.Key_0:
                    self.set_zoom(1.0)
                    return None
        except Exception:                                                   # noqa: BLE001
            pass
        return super().keyPressEvent(ev)

    # ── 打开 / 抬前 ──────────────────────────────────────────────
    def ensure_loaded(self):
        if not self._loaded:
            self.view.load(QUrl(self._url))
            self._loaded = True
            self._t_load0 = time.time()

    def reload(self):
        self._loaded = False
        self.ensure_loaded()

    def show_ar(self) -> None:
        """显示并抬到最前 —— 已开着就只抬前(实测 <10ms)。"""
        self.ensure_loaded()
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        try:
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        except Exception:                                                   # noqa: BLE001
            pass


def _make(url: str = AR_URL) -> ARWebWindow:
    global _WIN, _T0
    if _WIN is None:
        _T0 = time.time()
        _WIN = ARWebWindow(url=url)
    return _WIN


def prewarm(url: str = AR_URL) -> bool:
    """控制台启动后预建窗口(**不 show**) + **预载页面**。

    老倪 2026-10-19「AR 打开后, 怎么是白屏呢? 好长时间才显示」:
      只预热窗口、不 load 时, 第一次点开仍要现场跑一遍"WebEngine 起渲染进程 + 拉 90KB 页面 +
      解析内联 JS", 期间就是一片空(旧版还是白底)。现在页面在**隐藏窗口**里先加载完:
        · 点开 = show + raise (实测 <0.1s), 页面骨架/控件已经在 ⇒ 不再白屏;
        · 页面自己在 document.hidden 时不取帧、不轮询 (见 tcp-ar.html pumpTick/refresh),
          被 show 出来时由 visibilitychange 立刻补一帧 ⇒ 后台不占 8797 的请求。
    内嵌不可用(异常)时返回 False, 调用方回退外部窗口。
    """
    try:
        w = _make(url)
        w.ensure_loaded()
        return True
    except Exception:                                                       # noqa: BLE001
        return False


def open_ar(url: str = AR_URL) -> bool:
    """点 AR 的入口: 有窗口就抬前, 没有就建+显示并加载。返回 False = 内嵌不可用(调用方回退外部窗口)。"""
    try:
        w = _make(url)
        w.show_ar()
        return True
    except Exception:                                                       # noqa: BLE001
        return False


def window() -> "ARWebWindow | None":
    return _WIN
