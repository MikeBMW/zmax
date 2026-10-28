# 配置中心左栏「拖不动 + 字被截」= 被右侧最小宽度顶死 (2026-10-12)

> 老倪原话: 「你看现在的配置中心，左侧栏，无法更改宽度，字体都挡住了。改适配宽度」
> 交付: v5.49.2 · `tools/gui/veh6_config_page.py` · 判据 `tools/verify_config_tree_width.py` 10/10 × 两套 DPI · 文档 `docs/CONFIG_CENTER_TREE_WIDTH_20261012.md`

## 🔴 两个症状一个根因, 别先动左栏

诊断三步, 全部量化(不要目测/猜):

1. **左栏文本需求** = `fontMetrics().horizontalAdvance(最长条目) + 缩进×层级`
   (真机 192DPI 实测 `   perf.anomaly_recovery` = 337px ⇒ 加箭头22/边框4/滚动条18/余量12 = **393px**)
2. **右栏最小宽** = `tabs.minimumSizeHint().width()` (实测 **2653px**)
3. **对比**: 整页最小宽 = 393 + 2653 = **3046px**; 窗口可用宽 = 窗口 3068 − 主侧栏 240 = **2828px**

⇒ 整页最小 > 可用 ⇒ **分割条零余量** ⇒ 既**拖不动**, 又把左栏挤到最小值(337px 的字挤进 230px) = **字被截**。

## 顶宽真凶: 单行 QLabel

QLabel 默认按全文撑宽 ⇒ 一条长说明行能把**整页**最小宽度顶起来, 而这种行看着完全无害。

实测链: 页1「⚙️ 工程配置」一条 **2621px** 说明行(`任务 TASK-07-AOI…唯一依据 reports/aoi_points…`)
→ `页1.minimumSizeHint().width() = 2649` → `tabs = 2653` → 整页 3046。
同类: 页0 `状态空间工程(主工程): …` = 2078px(把页0 顶到 2090)。

**定位法**(秒级, 不用猜): 实例化页面后遍历页内 QWidget 打 `minimumSizeHint().width()`, 谁大是谁:

```python
for w in page.findChildren(QWidget):
    if w.minimumSizeHint().width() > 520:
        print(type(w).__name__, w.minimumSizeHint().width(), getattr(w, "text", lambda: "")()[:100])
```

## 修法三条一起下

1. **左栏按 fontMetrics 实测定宽**(`_tree_need_width()`): 遍历树(含子项)取 `缩进×层级 + 文本宽` 最大值
   + 箭头/边框/滚动条/余量 ⇒ 当**初始宽**同时当**最小宽**(挤不没)。用 fontMetrics ⇒ DPI 自动适配:
   96DPI→230 · 真机192DPI→393。预先固定像素必然在某天被截。
2. **真能拖 + 记得住**: `setHandleWidth(8)`(原来 4px 不好抓) · `setChildrenCollapsible(False)`(禁拖成 0 宽) ·
   拖动结果写 `QSettings("ZMAX","Console").setValue("config_center/tree_width", w)`;
   下次开页面恢复时**只在 ≥ 需求宽度时**用, 且不超过页面 50%(防把右栏挤没)。
3. **超宽说明行自动换行(治本)**: 右侧任何 `minimumSizeHint().width() > 520` 的 QLabel → `setWordWrap(True)`。
   **全文一字不删**(换行显示, 照旧可复制 —— 老倪要可复制), 但右侧最小宽回落到表格本身:
   **tabs 2653→1924, 整页 3046→2325 < 可用 2828 ⇒ 分割条真有 ~500px 余量可拖**。
   构造时扫一遍 + `showEvent` 再扫(有的页内容是后填的), 幂等。

## 🔴 判据必须跑两套 DPI

* 离屏是 **96 DPI**, 真机 (X 3200x2000, Qt `logicalDotsPerInch = 192`) 文本 px **差 2×** ⇒
  只跑离屏会把"真机才截"的 bug 判绿。跑法: `QT_FONT_DPI=192 python tools/verify_config_tree_width.py`。
* **别预先固定像素**(如"拖到 320"): 高 DPI 下 320 < 需求 393 ⇒ 假红。用「需求宽度+60」这类相对口径;
  页面也要放到「最小尺寸 + 300」而不是预先固定 2200(否则高 DPI 下最小尺寸顶死, 拖拽测不出来 = 假红)。
* 10 项判据: 需求按内容实测 · 初始=需求 · 初始不截字 · **强压 `setSizes([1,50])` 后仍 ≥ 需求** ·
  拖宽生效 · 宽度落盘 · **拖到比内容窄被拒** · 新开页面沿用 · 右栏仍 ≥400px · 拖后仍不截字。

## 真机外观复核(不动现场)

`DISPLAY=:0` + `pg.setAttribute(Qt.WA_DontShowOnScreen, True)` + `show()` → `pg.grab().save(png)`:
走真 X + 真 192DPI 渲染, 但**不往老倪桌面弹窗**。再裁左栏 + `tesseract -l chi_sim+eng` 读回条目名核无省略:
实测读到 `模型配置 1/6 · 工程配置 6/9 · 功能配置 1/3 · 性能配置 51/64 · 文档配置 0/3 · TASK-01-FW … TASK-07-AOI`。

## 生效

GUI 改动要重启才生效: `env -u QT_QPA_PLATFORM bash tools/studio_ctl.sh restart --force`
(restart 脚本自己会等, 别用 `timeout` 卡它 —— 实测 180s 被切断时重启实际已在正常进行);
完事核**窗口标题里的版本号** + 窗口归属: `DISPLAY=:0 xdotool search --onlyvisible --name "XSpace Studio" getwindowname %@`
与 `xprop -id <win> _NET_WM_PID` 是不是新 pid —— 只看 `pgrep` 会漏"起的是旧版本"。
