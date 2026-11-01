---
name: qt-gl-rendering-pitfalls
title: "Qt/pyqtgraph GL 渲染坑与 QPainter 2.5D 替代"
description: "Use when pyqtgraph 渲染坑: GL 空白/GLError/曲线 RecursionError/曲面."
trigger: "pyqtgraph GLViewWidget 渲染失败、'Error while drawing item'、glGetAttribLocation、第二/多 GL 窗口、曲面/碗可视化、QPainter 投影自绘、PlotDataItem dataRect/np.min RecursionError、曲线刷新卡死/白屏"
---

# Qt/pyqtgraph GL 渲染坑与 2.5D 替代 (2026-09-07 实测)

一套实测钉死的跨平台 Qt OpenGL 可视化经验, 覆盖 pyqtgraph GL 的上下文
陷阱、GLSurfacePlot 网格绘制、以及"干脆用 QPainter 自绘 2.5D"的替代路线。

## 坑 0 (最狠): paint() 里抛异常 = Qt 直接 abort 整个进程 (2026-09-13 实测)

- 症状: 用户报"一打开某某界面程序就崩"(不是卡死, 是硬崩); 日志尾是
  `Fatal Python error: Aborted` + faulthandler 线程转储, 栈顶落在某个 `paint()`。
- 实例: `simulink_module.py` 背景行 paint → `_wrap_title(name, fm, avail)` →
  `QFontMetrics.elidedText(text, Qt.ElideRight, avail)` 里 **avail 是 float**
  → `TypeError: argument 3 has unexpected type 'float'` → Qt abort 全 GUI。
  (根因: 上游 `avail_w = max(80.0, float(...))`, 旁边虽算了 `_aw = int(avail_w)` 却传错了变量)
- **规则**: 凡是传给 Qt API 的宽度/坐标/尺寸参数一律先 `int()`/`float()` 显式转换;
  `QFontMetrics.elidedText` 的 width **必须 int** (PyQt5 不做隐式转换, 直接 TypeError)。
- **排查姿势**: 崩在 paint 里时 `try/except` 包住没用 (异常已逃到事件循环 → abort);
  正解 = 用 offscreen 复现: 加载场景 → 直接 `item.paint(painter, option, None)`
  或 `scene.render(painter)` → 把异常抓成字符串;
  再加**单元阴性对照** (`fm.elidedText(..., 300.0)` 应抛 / `..., 300` 应正常) 钉死根因。
- 只在特定数据下崩 (如"某个标题刚好需要省略号才崩") = 分支触发型 bug: 修复要放在
  **函数入口做类型归一**, 而不是只改那一个调用点。

## 坑 0b: 2D 曲线的 `RecursionError` 落在 `PlotDataItem.dataRect → np.min` (不是 np.min 递归)

- 症状: 栈尾 `pyqtgraph/graphicsItems/PlotDataItem.py … _getDisplayDataset → dataRect → _getDataBounds → np.min(arr)`
  报 `RecursionError: maximum recursion depth exceeded in comparison`, 界面卡/白。
- 机制: `np.min` 自己不会递归 —— 它只是**栈已经被信号级联压满后倒在哪一行**。
  刷新路径 `item.setData(...)` / `vb.setYRange(...)` / `linkedViewChanged(...)` 三者互相触发,
  每个 ViewBox 收到新量程就立即重绘, 重绘里又要 `dataRect` 扫数组 ⇒ 一帧叠一层栈, ~1000 层就炸在 np.min。
  只设一处范围 (如 "X 范围只设一次") 只能治当年那条路径; 多子图联动 + 每帧按曲线 `setYRange` 的组合会再犯。
- 四道闸 (都在 `tools/gui/canoe_graphic.py` 已落地, 换别的绘图窗照抄):
  1. `item.setData(x, y, skipFiniteCheck=True)` —— 从绘制路径里**彻底去掉** `np.min` 扫描 (报错那行不执行);
     数据在环形缓冲里已保证有限 (NaN/inf 在入口过滤), 可以安全跳过。
  2. 刷新函数加**重入闸** (`_in_refresh` + `_refresh_pending`): 正在刷新就不再进, 级联不会叠栈。
  3. `setYRange` 只在**量程真变**时才调 (缓存上一帧 lo/hi, 容差 1e-9) —— 绝大多数帧量程不变, 根本不发 `sigRangeChanged`。
  4. `except RecursionError:` **不吞错**, 把完整栈追加到 `zmax_data/graphic_logs/gui_recursion.log`
     (带时间/曲线数/模式) 再 raise —— 下次复发直接看栈, 不用重现。
- 验证手法: 把 `sys.setrecursionlimit()` **故意压到 250** 后跑压力路径 (全选缓冲 × 三种布局 × 25 拍)。
  默认 1000 层时小规模跑必过, 压到 250 有一点深层重入就立刻暴露 —— 这是最便宜的回归判据。
- 现象判读: 即使这次不炸, 报错行也说明绘制走了一条很深的**重入**路径; 先切「同轴单图」看是否消失,
  能立刻区分是"联动级联"还是"单图数据量"问题。

## 核心坑 1: pyqtgraph shader 全局缓存绑「第一个」GL 上下文

- pyqtgraph `opengl/shaders.py` 在模块导入/首次绘制时编译一次, ShaderProgram
  句柄绑定创建它的那个 GL 上下文, 全局缓存。
- **再新建一个 GLViewWidget = 新 GL 上下文** → 旧句柄失效 → 该窗口所有 GL item
  绘制报 `GLError ... glGetAttribLocation` (或 stderr "Error while drawing item ..."),
  界面可能整体黑/缺内容, 无弹窗。
- 已知的"窗口复用"修复 (close 不销毁、只复用首窗) 只解决**同一窗口重开**;
  需要**第二个独立 GL 窗口** (如从主 3D 视图开辅助曲面窗) 时 pyqtgraph GL 不可用。
- 判断: 第二窗口所有 item 全报错 = 上下文问题; 首窗口正常。

### 解法 A: 多窗口场景禁用新 GLViewWidget
辅助曲面/仪表窗用非 GL 方案 (见 QPainter 2.5D)。

### 解法 B: 单窗口内的 mesh 绘制注意
- `GLSurfacePlotItem(x=1D数组, y=1D数组, z=2D, shader=None)` 在本机
  (Mesa/兼容上下文) 崩 `glGetAttribLocation` → 改用 `GLMeshItem`:
  自己构造 `gl.MeshData(vertexes=(N*M,3), faces=(2*(N-1)*(M-1),3) uint32)`,
  再 `GLMeshItem(meshdata=md, color=单色RGBA, smooth=False, shader=None,
  drawEdges=True, edgeColor=...)` — 纯色+边线路径与主场景已验证 mesh 一致。
- 同一程序里 GLScatterPlotItem/GLLinePlotItem 不要对第二窗口设
  `setGLOptions("additive")` — additive shader 同样跨上下文崩; 默认渲染即可。

## QPainter 2.5D 正交投影自绘 (零 GL 依赖的曲面方案)

固定视角下画"网格曲面 + 动态点/线"的可靠替代, 无 GL 上下文问题:

1. 正交相机: `eye = dist*(cosEl*sinAz, cosEl*cosAz, sinEl)`; `fwd=-eye/|eye|`;
   `right=norm(cross(fwd, worldUp))`; `upv=cross(right, fwd)`。
   投影点: `d=p-eye` → `x'=dot(d,right)*s+cx`, `y'=cy-dot(d,upv)*s` (s=像素/mm 缩放),
   深度 = `dot(d,fwd)` 用于排序。
2. **静态网格预渲染 QPixmap**: 把曲面四边形网格 (含参考环/十字线) 一次性画进
   QPixmap (远→近排序, 半透明 fill + 边线); resize 时重渲。每帧只投影动态
   点/轨迹/竖线叠上去 → 帧开销极小。
3. paintEvent 每帧: 画缓存 pixmap + 动态元素 (QPainter drawLine/drawEllipse)。
4. 数值实时放 QLabel (widget 布局内), 别塞画面。

## 坑 0c: 每帧新建 QFont/QFontMetrics = 烧掉一整个核 (实测 CPU 214%→155%)

自绘面板每帧给几十块文字各建一次 `QFont(size, bold)` + `QFontMetrics(f)` 再量宽, 看着是"纯计算",
实测**每次量宽 13.7µs**、主线程被文字度量吃满 ⇒ 窗口在可见时 CPU 200%+, 后台时又只有 22%(不重绘)。
- 修法: `_cached_fm(size, bold)` 以 `(size, bold)` 为键缓存 QFont + QFontMetrics; 标题 QFont 复用;
  换行结果再按 `(text, width, size, sep)` 缓存(**必须有界** —— 键里含数值文本时数字每帧变, 无界缓存会自己变成内存泄漏)。
- 实测收益: 量宽 13.7µs → 4.5µs; 同一可见页面 CPU 214% → 155%。
- 定位: `sudo env "PATH=$PATH" py-spy record -o /tmp/spy.txt --format raw --pid <pid> --duration 200`
  (非 root 会 `Permission Denied`; `py-spy top` 若输出为空就改用 record 的 raw 再自己聚合行首函数名),
  热点通常落在 `paintEvent` / `_block` / `_wrap` / `_fmw` 这几个自绘函数上。
- 🔴 **降幅只能在"同一可见页面"前后各采一次**: 后台窗口不重绘, 拿后台 22% 对比前台 120% 是假数。

## 渲染验证 (offscreen/真实 DISPLAY 通用)

- 像素级验证不要走 `QImage.bits()` + np.frombuffer (PyQt5 sip.voidptr 无 size 坑);
  直接 `widget.grab()` / `view.grabFramebuffer().save('/tmp/x.png')` → PIL 读图统计:
  非背景像素数、特定色系像素数 (青网格等) 判断"真画出来了"。
- 注意阈值: 深色背景 (#0d1117 ≈ 13,17,23) 会被 `>10` 全判亮 → 统计用 `>60` 或数色系。
- QWidget 小窗未 resize/未 processEvents 时 grab 尺寸极小 → 先 `resize()`+`show()`+
  `processEvents()` 再抓。
- QPainter/QPen/QPixmap/QPolygonF/QBrush 模块级使用必须显式 import;
  **QPolygonF 在 PyQt5.QtGui, 不在 QtCore** (QPointF 在 QtCore) — 实测 ImportError。
- 测试脚本里 numpy 的 `&` (位与) 会被命令安全检查误判为后台符号 — 用 `*` 或 np.logical_and。

## 常见流程

1. 新 3D 可视化: 单窗口 → GLMeshItem/GL items (首上下文 OK)。
2. 第二窗口 (曲面/辅助图) → QPainter 2.5D (预渲染 pixmap + 动态投影)。
3. 验证: 存 PNG 数像素, 别裸奔上线。
