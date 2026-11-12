# 字号/DPI 口径 + 支持文件索引 (2026-09-26)

## 1. 老倪字号口径 (连纠两次: "字体太小, 看不清" → "比刚才好点, 但还是太小, 再放大")

- 高分屏 (实测工位机 192 DPI) 上 QSS `font-size: Npx` 的**视觉观感约为设计值的一半** →
  12px 的数值行用户直接判"看不清"。宽屏大字号不是"美化", 是**可读性底线**。
- **一次给到位, 别小步试探**: 第一次只把 12px 提到 15px → 被判"比刚才好点, 但还是太小"。
  正解 = 直接上 **~2.3×**(12px → **28px**), 同批配 标题 **34px** / 列表 **24px** / 按钮 **20px**
  (padding 9×18), 卡内 `setContentsMargins(24,20,24,20)` + `setSpacing(14)`。
- **改完必须给客观数字**(用户按数字验收, 不接受"我觉得大了"): 写
  `tools/measure_<组件>_fonts.py` → offscreen 真实例化该组件 → 逐行打印
  `font().pixelSize()` / `fontMetrics().height()`。本次实测: 主数值 28px/行高 39 ·
  标题 34px/行高 47 · 时间戳 18px/行高 26 · 卡片 sizeHint 570→734px。
- 卡片变高前确认父容器**可滚动**(首页在 QScrollArea + `setWidgetResizable(True)` → 安全;
  固定行高的面板会截断底部行)。
- 先量后改再量: 报"原来 X px → 现在 Y px, 行高 Z"。没量之前别反复调(会白跑轮次)。
- 重启才生效: 改完 studio.py 要杀旧实例再起(否则用户看到的还是旧字号, 会再报"没变")。

## 2. 本技能支持文件索引 (新会话优先看这几个)

| 文件 | 何时看 |
|---|---|
| `references/periodic-timer-blocking-io-worker-thread-2026-09-26.md` | **GUI 卡顿根因家族**: 定时器槽在主线程做阻塞 I/O (HTTP / 子进程 / `time.sleep`) → 主线程被冻; 含定量方法(逐调用耗时 + 心跳最大间隙)与"采集搬 QThread + 代理收 setText"的修法。改任何刷新/轮询逻辑前必读 |
| `scripts/ui_jitter_probe.py` | 主线程 10ms 心跳测"最大间隙"(= 用户感知的"卡一下"), 直接可跑 |
| `references/main-thread-io-and-button-evidence-2026-09-16.md` | 主线程 I/O + 按钮取证(同类问题的更早一例) |
| `references/gui-patch-safety-and-side-effects-2026-09-19.md` | 大 GUI 单文件改动的安全流程 |
| `references/display-refresh-honesty-and-window-stubs-2026-09-17.md` | 刷新/显示的"看着变了其实没变"类坑 |

## 1b. 下拉弹层「白底白字」+ 弹层字号（属同一类可读性投诉）

症状: 用户说「背景还是白色，字体也是白色，都看不到要选择的文字了」。
**根因永远是漏写弹层，不是配色偏好**: `QComboBox{...}` 只样式化本体；弹出列表是独立的
`QAbstractItemView`，没写就走系统浅底，而本体给的是浅色字 ⇒ 白底白字。

```python
combo.setStyleSheet(
    "QComboBox{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:4px;"
    "padding:2px 6px;font-size:13px;min-height:26px;}"
    "QComboBox::drop-down{width:18px;border:none;}"
    "QComboBox QAbstractItemView{background:#161b22;color:#e6edf3;border:1px solid #30363d;"
    "outline:0;font-size:13px;selection-background-color:#1f6feb;selection-color:#ffffff;}"
    "QComboBox QAbstractItemView::item{min-height:28px;padding:3px 8px;}")
# 再兜一层 palette (有的平台/主题弹层不吃 QSS): view().palette() 的 Base/AlternateBase/Text/
# WindowText/Highlight/HighlightedText 逐个 setColor; view().setMinimumWidth(300) 给长选项
# (如「🧊 … / 🪐 … / 🎯 …」三项) 留够宽, 否则一进弹层就省略号。
```

**再加一条全局兜底**: 在 app 级 `_build_global_qss()` 里写同样的 `QComboBox QAbstractItemView`
规则。单页面写只能修那一处，别的页面照样复发；全局兜住才是根治（f-string 里用双大括号 `{{ }}`）。

字号口径（嫌小时按这档，别逐处临时加）: 侧栏页基准 12→13pt（页级 `setFont(+1pt)`，不动其它页）·
页内正文最小 12px（原 11px 一律提上去）· 下拉本体与弹层都 13px、本体 `min-height:26~28px`、
弹层 `::item{min-height:26~28px}` · 弹层最小宽 ≥300px。

### 怎么量（别读字体 API）
- QSS 写的 `font-size:13px` **不反映在 `QFont.pointSize()`**（读出来常是 -1 或旧值）⇒ 用字体 API 判"字号改没改"会假绿。
- 正确判据: 渲染后逐行扫亮像素，连续行段 = 一行文字，**段高 ≈ 字形像素高**（实测改前 11px、改后每行 14px）。
- 可读性量化: `QPalette.Base` vs `QPalette.Text` 的 WCAG 对比度，≥4.5:1 才算看得清（深底浅字实测 14.6:1）。
- **截断体检**: 扫页内 `QLabel/QPushButton/QComboBox`，`sizeHint().width() > width()+2` 的条数必须为 0 ——
  字号一放大最容易把窄栏文字挤没，而这类用户就是看画面当结果的。
- 全部可离屏做: `QT_QPA_PLATFORM=offscreen` + `combo.view().grab()`，不必抬真窗口。

## 3. 一句话铁律(与 §1 同源)

主线程只做**渲染**; 取数(HTTP/子进程/sleep/重算)一律进工作线程;
**字号这类用户主观项, 用客观测量 + 一次给足, 别小步试探**。
