# 🎯 SU(2) 轨迹球窗口 (画布右侧栏「🧮 主参数 M」页)

需求口径: 四元数把三维旋转映成 S³ 上的一段滑动轨迹, 要在右侧栏主参数里**看见**这段轨迹;
并且这个窗口**必须能完全隐藏**。落地 = `tools/gui/su2_traj_ball.py::SU2TrajBall` +
`tools/gui/model_tree.py::MasterParamMView` 的 `viz_stack` 第 3 页。

## 1. 页面结构 (照既有视图的插法, 别另起窗口)

`MasterParamMView` 里已有一条 `viz_stack`(QStackedWidget) 装「🧊 流形几何四面板」与「🪐 球心引力架构」。
新视图 = **同一个 stack 的第 3 页** + 下拉第 3 项, 不新开 QDialog/QDock:

```python
self.viz_stack.addWidget(self.su2_ball)          # index 2
self.cmb_viz_view.addItems(["🧊 流形几何 · 四面板", "🪐 球心引力架构 · 太阳系", "🎯 SU(2) 轨迹球 · S³"])
```

- `viz_stack` 统一 `setMinimumHeight(150)` / `setMaximumHeight(620)`: 页面不滚, 高度差由这块吸收;
  单独给子控件设 470 的最小高会把太阳系/表格压扁 (历史上踩过)。
- `MasterParamMView(module=None)` 可在离屏直接实例化 (`self._root` 由 `__file__` 上溯推出来), 便于验收。
- 切页回调 `_switch_viz_view(idx)` 要给 `idx==2` 加 reload 分支, 否则切过去还是旧轨迹。

## 2. 画 S³ 而不是 S² (语义不能混)

- **S³ 才是那把尺子**: 单位四元数活在四维单位球上, 含「转多少」; Bloch **S²** 只承载方向 v/|v|, 丢掉转量。
  默认 S³, 留一个 `S³/S²` 切换按钮给需要「绕哪根轴」的人。
- 四维画到屏幕用**立体投影**, 极点必须放在球外一点:

  `p = (x,y,z) / (1.05 − w)`

  从 w=+1.05 投影 ⇒ 单位元 (w→1) 时 p→0 收敛到球心, 分母恒 ≥ 0.05, 不会像从 w=−1 投影那样在
  单位元附近炸到无穷。投影一一对应 ⇒ 屏上弧长可按同比例换回真实旋转角 (图上标注 `≈°`)。
- 轨迹点用 **slerp 补点** (相邻两次观测之间补 12 点), 画出来才是「滑动」的弧; 直接把观测连成折线
  看着像跳变, 用户会以为卡顿。
- 两端符号先商掉 (`canonical`: w<0 取反), 否则 ±q 会在球上画出「瞬移」的假段。
- 元素: 轨迹(按时间渐变) · 🟢 q_fused 当前点 · 🟡 q_truth 记忆基准(空心圈) · ⚪ 起点;
  读数 `θ / |w| / S³ 弧长(rad 与 °) / 采样点数` + `补偿误差 / 势 V / 测量权重 / 轴向`。
- **不要开第二个 GL 上下文** (主窗口已占 GL): 用 QPainter 2.5D 手绘球体/网格/坐标轴, 拖动旋转 + 滚轮缩放。

## 3. 数据源: 只认真源, 空态不画假点

`zmax_data/ss_live/quat_truth_calls.jsonl` (每次 observe 的 q_truth/q_fused) → 退 `quat_truth_latest.json`;
都没有就画「空态: 等 quat_truth 观测」并停笔。定时器 1.5s 刷新。

## 4. 「完全隐藏」的正确做法 (四个动作缺一不可)

1. `setVisible(False)` —— 窗口整个消失;
2. **停刷新 QTimer** —— 隐藏后不再空转读文件;
3. **从下拉里摘掉这一项** (`removeItem`) —— 否则菜单里还留一条, 用户认为「没隐藏干净」;
4. `QSettings` 落盘 (`mparam/su2_ball` 0/1, 写完立刻 `sync()`) —— 重启保持隐藏。

还原口: 视图行最左边一个 🎯 小开关 (checkable), 按下=显示/弹起=隐藏 —— 隐藏态**不能没有还原入口**,
但还原入口不能占窗口面积 (它只是工具条上的 26px 按钮)。

隐藏时若正看着球页 ⇒ 先退回上次看的视图 (`mparam/su2_prev`), 否则 stack 停在一个被摘掉的页上会空屏。
组件用 `hiddenChanged(bool)` 信号通知宿主, 宿主统一做摘项/落盘 —— 组件自己不碰 QSettings。

## 5. 离屏验收 (不碰相机/共享内存)

`QT_QPA_PLATFORM=offscreen` 建 QApplication → 实例化控件 → `reload()` → `widget.grab().toImage()`;
**用关键颜色的采样像素数当证据**, 而不是「我看图觉得对」:

| 断言 | 判据 |
|---|---|
| 真画出来了 | 轨迹蓝 / 当前点绿 / 记忆黄 三类像素都 > 0 (实测 74/26/36 @每 2px 采样) |
| 轨迹是补点后的弧 | `len(traj)` 明显大于观测条数 (8 条观测 → 85 点) |
| 模式切换 | 切 S² 后重绘仍有轨迹像素 |
| 完全隐藏 | `isVisible()==False` 且 `timer.isActive()==False` 且信号收到 True |
| 恢复 | `set_hidden(False)` 后 `isVisible()`/timer 都回来, 轨迹点不丢 |
| 宿主摘项 | 下拉项 3 → 2, `_su2_shown=False`, QSettings=0; 再切回 3 项 / 1 |
| 重启态 | 预置 QSettings=0 新建页面 ⇒ 下拉 2 项、球不可见、timer 停; =1 ⇒ 3 项、可见、timer 转 |

坑: 隐藏后再 `grab()` 仍会返回**上一次的画面内容**, 拿它证明「变黑了」是假证据 —— 隐藏态一律用
`isVisible()`/`timer.isActive()`/下拉项数判。

脚本落在仓库 `tools/verify_su2_ball_ui.py`, 产物截图在 `zmax_data/ss_live/ui_su2_ball_{shown,s2,hidden}.png`
与整页 `ui_mparam_with_ball.png` (数据目录, 不入库)。
