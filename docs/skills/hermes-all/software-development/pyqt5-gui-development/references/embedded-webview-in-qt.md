# 在 PyQt5 应用里内嵌网页 (QWebEngineView) 代替外部浏览器

适用: 控制台/工具里"点一个按钮打开某个本地 http 页面(监控面板/AR 页面/调试台)", 要求点了就出来。
外部浏览器(含 chromium --new-window)在这类场景是有害的: 慢、可能不出窗、抢焦点、跟用户日常标签页混在一起。

## 实测对比 (同一台机, 同一个 http://127.0.0.1:PORT/ 页面)

| 路径 | 出窗/可见耗时 | 备注 |
|---|---|---|
| 外部 chromium (共享实例) | 0.38~0.50s | 命令只是转发给已在跑的实例; 实例忙时**窗口永不出现**(子进程 execve 成功、线程在跑、30s 无窗) |
| 外部 chromium (独立 `--user-data-dir`) | 0.73~0.86s | 窗口一定由自己建, 稳但更慢 |
| 内嵌 QWebEngineView (预热后) | **0.03~0.08s** | 与打开原生 Qt 窗口同档 |
| 内嵌, 窗口关掉后再点 | **0.001s** | 对象不销毁, 只 show/raise |
| 页面 loadFinished | 0.29s | 与出窗解耦, 先出窗再加载 |

## 依赖

```bash
# 先看现有版本线, PyQtWebEngine-Qt5 必须与 PyQt5-Qt5 同版本(都装进 PyQt5/Qt5/lib, 装错会覆盖核心 Qt 库)
python -m pip freeze | grep -iE "pyqt|sip"
# 生产 venv 动手前留底, 并先在一次性 venv 里跑通
python -m pip freeze > /tmp/venv_before.txt
python -m venv /tmp/webtest && /tmp/webtest/bin/pip install PyQt5==<同版本> PyQtWebEngine
```

装完必须验: `python -c "import PyQt5.QtCore as c; print(c.QT_VERSION_STR)"` + `from PyQt5.QtWebEngineWidgets import QWebEngineView`
都能过, 且 `PyQt5-sip` 没被顶掉(sip 变了就再跑一次主程序冒烟)。

## 骨架: 模块级单例窗口 (可直接抄)

```python
"""ar_web_window.py —— 内嵌页面窗口: 关窗不销毁, 再点只 show。"""
import time
from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtWidgets import QAction, QLabel, QMainWindow, QToolBar, QVBoxLayout, QWidget

URL = "http://127.0.0.1:8797/ar"
_WIN = None

class WebWindow(QMainWindow):
    def __init__(self, url=URL, parent=None):
        super().__init__(parent)
        from PyQt5.QtWebEngineWidgets import QWebEngineView   # 实例化时再取, 但模块必须先被 import 过
        self._url, self._loaded = url, False
        self.resize(1500, 950)
        box = QWidget(self); lay = QVBoxLayout(box); lay.setContentsMargins(0, 0, 0, 0)
        tb = QToolBar(self); tb.setMovable(False)
        act = QAction("↻ 刷新", self); act.triggered.connect(self.reload); tb.addAction(act)
        tb.addWidget(QLabel("  " + url, self))
        lay.addWidget(tb)
        self.view = QWebEngineView(self); lay.addWidget(self.view, 1)
        self.setCentralWidget(box)

    def ensure_loaded(self):
        if not self._loaded:
            self.view.load(QUrl(self._url)); self._loaded = True

    def reload(self):
        self._loaded = False; self.ensure_loaded()

    def show_ar(self):
        self.ensure_loaded()
        self.showNormal() if self.isMinimized() else self.show()
        self.raise_(); self.activateWindow()

def _make(url=URL):
    global _WIN
    if _WIN is None:
        _WIN = WebWindow(url=url)
    return _WIN

def prewarm(url=URL):            # 启动 3s 后 QTimer.singleShot 调: 建窗口不 show/不 load
    try:
        _make(url); return True
    except Exception:
        return False

def open_ar(url=URL):            # 按钮入口; 返回 False = 内嵌不可用, 调用方回退外部浏览器
    try:
        _make(url).show_ar(); return True
    except Exception:
        return False
```

主程序里两处接线 (缺一不可):

```python
# ① 模块级顶部, 早于 main() 里的 QApplication(sys.argv)
try:
    import PyQt5.QtWebEngineWidgets  # noqa: F401  顺序敏感
    _WEB_OK = True
except Exception:
    _WEB_OK = False

# ② QApplication 之后 3s 预热
def _prewarm():
    try:
        import web_window as w; w.prewarm()
    except Exception:
        pass
QTimer.singleShot(3000, _prewarm)
```

## 缩放与可读性 (高 DPI 屏 + 记住上次)

**症状**: 用户说"网页整体很小, 每次都得按住 Ctrl 滚轮放大"。不是页面写小了 —— 3200x2000 的屏上
`devicePixelRatio()` 仍可能是 1.0, CSS 12px 就是 12 个物理像素, 236 DPI 下约 3.6pt。

**默认值按屏算**, 不写死 1.0:

```python
ZOOM_MIN, ZOOM_MAX, STEP_BTN, STEP_WHEEL = 0.6, 3.0, 0.2, 0.1
ZOOM_FILE = os.path.join(DATA_DIR, "ar_zoom.json")

def default_zoom() -> float:
    dpi = float(QApplication.primaryScreen().physicalDotsPerInch() or 96.0)
    return round(max(1.0, min(2.6, dpi / 96.0 * 0.85)), 1)   # 236 DPI ⇒ 2.1; 96 DPI ⇒ 1.0

def load_zoom() -> float:        # 上次那一档优先, 没有/坏了才按屏算
def save_zoom(z):                # 原子写: .tmp + os.replace, 半截文件不会把下次启动读崩
```

**窗口尺寸按缩放反算 CSS 视口**: 页面常是 `main{display:flex;flex-wrap:wrap}` + `#leftcol{flex:1 1 640px}` +
`aside{flex:0 1 380px}` ⇒ 并排至少 ~1060 CSS px。缩放 2.1 时窗口要 ~2400px 才够, 否则卡片全堆成一列
(用户会当成"排版坏了")。窗口取 `availableGeometry()*0.92` 封顶; 探针里断言卡片 x 坐标确实分两列。

**缩放三入口 + 存盘**:

```python
    def _apply_zoom(self, z, save=True):
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, round(float(z), 2)))
        self.view.setZoomFactor(self._zoom)
        self._lb_zoom.setText("  %d%%  " % round(self._zoom * 100))
        if save:
            save_zoom(self._zoom)

    def keyPressEvent(self, ev):              # Ctrl+= / Ctrl+- / Ctrl+0
        if ev.modifiers() & Qt.ControlModifier:
            if ev.key() in (Qt.Key_Plus, Qt.Key_Equal): self.zoom_by(STEP_BTN); return
            if ev.key() == Qt.Key_Minus:                self.zoom_by(-STEP_BTN); return
            if ev.key() == Qt.Key_0:                    self._apply_zoom(1.0); return
        return super().keyPressEvent(ev)
```

**Ctrl+滚轮**: 必须挂在 QApplication 上 —— 滚轮落在 QWebEngineView 内部的渲染控件, 构造时
`focusProxy()` 还是 None, 局部 `installEventFilter` 收不到。而一次物理滚轮会被投递 5 路
(QWindow → QWidget → QWebEngineView → QWidget → 本窗口), 每路都进同一个 filter ⇒ 不防抖会一格放大 0.5, 直接冲到 300%。

```python
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)          # 只装这一层, 别再给 view/self 各装一层(会成倍计数)

    def eventFilter(self, obj, ev):
        if (ev.type() == QEvent.Wheel and (ev.modifiers() & Qt.ControlModifier)
                and self.isVisible()):
            wh = self.windowHandle()
            is_top = wh is not None and obj is wh                   # 每个物理滚轮恰好一次
            w = obj if isinstance(obj, QWidget) else None
            if is_top or (w is not None and (w is self or w is self.view or self.isAncestorOf(w))):
                now = time.time()
                if is_top:
                    self._last_wheel = now
                elif now - getattr(self, "_last_wheel", 0.0) < 0.03:
                    return True                                     # 同一滚轮的其它投递: 吞掉
                else:
                    self._last_wheel = now
                dy = ev.angleDelta().y()
                if dy:
                    self.zoom_by(STEP_WHEEL if dy > 0 else -STEP_WHEEL)
                return True
        return super().eventFilter(obj, ev)
```

**验证口径**(xdotool 真发 Ctrl+滚轮):

```bash
xdotool mousemove <窗口中心> keydown ctrl click 4 keyup ctrl      # 1 格
```

- 别在 xdotool 返回后立刻读 `view.zoomFactor()`: 事件是异步处理的, 读到旧值 ⇒ `QTimer.singleShot(600, …)` 再读。
- 判据三条: 连滚 3 格正好 +0.3(不是 +1.5) · 点击工具栏 ± 各一次正好 ±0.2 · **新起一个进程**读回同一档(证明存盘生效)。

## 探针 (证明"点了就有"且页面真活着)

```python
import sys, time
sys.path.insert(0, "<gui 目录>")
import PyQt5.QtWebEngineWidgets  # noqa: 必须早于 QApplication
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)      # 探针里 close() 唯一窗口会让事件循环直接退出(像崩溃)
import web_window as w
t = time.time(); w.open_ar(); print("show %.3fs" % (time.time() - t))
def probe():
    w.window().view.page().runJavaScript(
        "JSON.stringify({n:performance.getEntriesByType('resource').filter(e=>e.name.includes('/snap/')).length,"
        "title:document.title})", lambda r: (print("页面:", r), app.quit()))
QTimer.singleShot(2500, probe)
QTimer.singleShot(15000, app.quit)
app.exec_()
```

判据: `n` > 0 (页面自己的轮询在跑) + `title` 对 = 页面真的在渲染; 再 `window().grab().save(png)` 量灰度均值
(深色页 ~26, 纯白/空白 ~255) 排除"窗口在但白屏"。

## 回退与可观测

- 回退链: 内嵌 → 外部浏览器(共享实例, 快) → 独立 `--user-data-dir`(稳) → `xdg-open`。
- 每一步一行时间线日志 (`spawn pid=… isolated=…` / `窗口出现 0x… +0.53s`), 出问题直接读日志定位到环, 不用复现。
- 打开流程里的 busy/去重标志**在 spawn 返回后立刻释放**, 不要把后处理(等窗口/切场景/读接口)排在释放之前 ——
  否则用户连点几次全是静默 no-op。
