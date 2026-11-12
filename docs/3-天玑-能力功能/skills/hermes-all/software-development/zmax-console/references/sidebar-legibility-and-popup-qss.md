# 侧栏可读性 / 下拉弹层配色 / 字号口径

用户在 studio 侧栏里报「字太小」「下拉背景白、字也白，看不到选项」时的定式。

## 1. 弹层白底白字 = 弹层控件没写样式（不是配色偏好）

只写 `QComboBox{...}` 只管**本体**；弹出列表是独立的 `QAbstractItemView`，没写就走系统浅色底，
而本体给的是浅色字 ⇒ 白底白字。任何新加的下拉都要同时写本体 + 弹层，并补 palette：

```python
combo.setStyleSheet(
    "QComboBox{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:4px;"
    "padding:2px 6px;font-size:13px;min-height:26px;}"
    "QComboBox::drop-down{width:18px;border:none;}"
    "QComboBox QAbstractItemView{background:#161b22;color:#e6edf3;border:1px solid #30363d;"
    "outline:0;font-size:13px;selection-background-color:#1f6feb;selection-color:#ffffff;}"
    "QComboBox QAbstractItemView::item{min-height:28px;padding:3px 8px;}")
# 兜底: 有的平台/主题下弹层不吃 QSS, 用 palette 再压一层 (Base/Text/Highlight/HighlightedText)
```

**同时在 `studio._build_global_qss()` 里给全局规则**: 一个页面漏写就复发，全局兜住才是根治
(`QComboBox QAbstractItemView { background:#161b22; color:#e6edf3; font-size:13px; ... }` +
`::item{min-height:26px}`)。全局规则用 f-string 时记住双大括号 `{{ }}`。

## 2. 字号口径（用户嫌小时按这个档调，不要逐处临时加）

| 位置 | 口径 |
|---|---|
| 侧栏页基准 | 12 → 13pt（页级 `setFont(+1pt)` 只影响本页，不动其它页面） |
| 页内正文/说明 | 最小 12px（原 11px 的一律提上去） |
| 下拉本体 + 弹层 | 13px，本体 `min-height:26~28px`，弹层 `::item{min-height:26~28px}` |
| 弹层宽度 | 长选项 ≥300px 最小宽，保证「🧊 … / 🪐 … / 🎯 …」一屏看得全不省略 |

调完必须做**截断体检**: 扫页内 `QLabel/QPushButton/QComboBox`，`sizeHint().width() > width()+2` 的条数必须为 0 ——
字号放大最容易把窄栏里的文字挤没了，而这个用户是看画面当结果的。

## 3. 「字到底多大 / 看不看得清」怎么取证

- **不要读字体 API 下结论**: QSS 里的 `font-size:13px` 不反映在 `QFont.pointSize()`（读出来常是 -1 或旧值）。
- 正确做法: 渲染后量**文字墨迹带高度** —— 逐行扫亮像素，连续的行段就是一行文字，段高 ≈ 字形像素高。
- 可读性量化: `QPalette.Base` vs `QPalette.Text` 的 WCAG 对比度，≥4.5:1 才算看得清（深底浅字实测 14.6:1）。
- 离屏(`QT_QPA_PLATFORM=offscreen`)拿 `combo.view()` 的 palette 与 `grab()` 就够，不必抬真窗口。

## 4. 与「可完全隐藏」联动

侧栏里可隐藏的视图页，摘掉下拉项后要验：下拉项数 −1、控件 `isVisible()==False`、刷新 QTimer 停、`QSettings` 落 0；
再用预置 `QSettings=0` 新建页面验重启态（详见 pyqt-gui-auto-verification 的「可完全隐藏」窗口判据）。
归还入口放工具条上的小可勾选按钮，不占窗口面积。
