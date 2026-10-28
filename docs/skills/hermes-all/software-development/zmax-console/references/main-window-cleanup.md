# 主界面收整 (2026-10-21 老倪三条)

1. 「最下面的 训练 Z-MAX三层结构架构 Sys 这行字 删掉」
2. 「删掉 simulink 画布 跟随单步 核心居中 两个按钮; 整体按钮向左移动, 左侧对齐」
3. 「日志区怎么无法用鼠标向上拖动调高了? 现在只剩一行」

## 1. 底部状态栏: 不能只 hide

显示那行的代码在 `_goto_page()`:
`statusBar().showMessage(f"● {names[idx]}  |  Z-MAX 三层解耦架构  |  Sys-0 + Sys-11 + Sys-12 + Sys-2")`

**坑**: 全工程 55 处 `showMessage()`, 而 Qt 的 `showMessage()` 会**把状态栏重新显示出来** ⇒
只调一次 `hide()` / 只删那一行字符串, 下次切页又回来。

**解**: 换一个吞掉调用的子类 (studio.py `_QuietStatusBar`):

```python
class _QuietStatusBar(QStatusBar):
    def __init__(self, parent=None):
        super().__init__(parent); self.setSizeGripEnabled(False); self.hide()
    def showMessage(self, *a, **k): self.hide()
    def addWidget(self, *a, **k): return None
    def addPermanentWidget(self, *a, **k): return None
...
self.setStatusBar(_QuietStatusBar(self))
```

调用方一行不改, 行为确定 (也不会再有「右下角读数」这类控件悄悄挂上去)。
验证靠 OCR: 截窗 → 裁底部 90px → `tesseract` 里不该再出现「Z-MAX 三层解耦架构 | Sys-0」。

## 2. 删画布两个勾选框: 能力靠 getattr 保障

`chk_follow_step` / `chk_core_center` 在 `simulink_module._build()` 里建 + `tl.addWidget()`。
删对象前先确认**所有引用都是 `getattr(self, "chk_...", None)` 且 `is None` 走默认开** —— 现在三处
(5630 保障居中 / 6748 加载后居中 / 10879 跟随判定) 全是这个写法, 所以直接删对象 = 行为不变 (默认开)。

删完工具栏自然左对齐 (FlowBar 本来就是从左 10px 起排; 之前是两个勾选框占住最左两格把按钮推右)。
离屏取证: `FlowBar.flow()` 第 1 项 `x=10 ▶ 运行` (改前 x≈290)。

## 3. 日志区拖不动: max==min 的死钉

`_log_panel.setMaximumHeight(46)` + `setMinimumHeight(46)` —— 46/46 ⇒ splitter 手柄物理拖不动,
只剩一行。这是 2026-10-16 为了给右栏 M 页腾高度钉的, 副作用没人跟。

改回: `min 28` / `max 16777215` / `setSizes([1100, 160])`, 竖向 splitter
`setHandleWidth(8)` + `setChildrenCollapsible(False)` + `QSplitter::handle:vertical` 上色 (默认手柄只有 ~4px 且与背景同色,
所以既拖不动也看不见)。

离屏判据: `_v_split.setSizes([500,460])` 后 `_log_panel.height()` 从 160 → 460 (>46 成立)。

## 验收口径 (别靠肉眼)

- 勾选框: `'chk_follow_step' in vars(win)` == False
- 工具栏: FlowBar 首项 geometry.x ≈ 10
- 日志: `_log_panel.maximumHeight() > 10**6` 且 `handleWidth() >= 8` 且 setSizes 后高度跟着变
- 状态栏: 截窗 + OCR 底部 90px 无「三层解耦架构」
