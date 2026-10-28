# GUI 无响应 / 关不掉 —— 分层诊断与修法

用户报「用鼠标关不掉了」时，先分清是**窗口层没收到**，还是**事件循环不处理**。这两类症状一样、根因完全不同，
修错了会重启十次也没用。

## 1. 先看主线程栈，不看 CPU%

```bash
py-spy dump --pid <gui_pid> | head -20
```

| 栈的样子 | 含义 | 对应病因 |
|---|---|---|
| `MainThread (idle)` 停在 `<module>`/`main` 的 `app.exec_()` | 事件循环在正常空转 | 事件没送到：窗口 id 错 / 窗口未映射 / 覆盖层吃事件 |
| `MainThread (active+gil)` 停在 `paintEvent` / `setData` / `setPen` / 自定义绘制 | 主线程被绘制占死 | 这一帧算不完，WM_DELETE、Ctrl+Q、SIGTERM **全都不处理**，只有 SIGKILL 能收 |

判据铁律：**CPU 100% + 主线程 `idle` 是最经典的误判组合** —— 高 CPU 可能来自子进程/渲染进程，
栈才是唯一证据。反过来，界面还画得出来也不算“活着”：绘制本身可能就是凶手。

## 2. 别对僵尸窗口 id 发关闭

GUI 被杀掉后，旧 window id 仍可能出现在 `wmctrl -l` 与通配搜索里，对它发 WM_DELETE 会**永远“没反应”**，
让人误判成“Qt 不处理关闭”。

```bash
xdotool search --pid <新pid> --onlyvisible      # 每次按当前 pid 重新解析 id
xwininfo -root -tree | grep -i <窗口名>          # 看真正的父子结构, 别信缓存住的 id
```

一次会话里同时存在两个 studio 进程时，“旧 id 还在列表里”是常态 —— 换 id 之前不要下任何结论。

## 3. 窗口建了但没显示：`IsUnMapped`

```bash
xwininfo -id <id> | grep -E "Map State|Absolute upper-left|Width"
```

`Map State: IsUnMapped` = Qt 已创建窗口但还没 `show()`（启动流程卡在初始化、或被 `hide()` 掉）。
顶出来：`xdotool windowmap <id>` 再 `windowactivate <id>`。
注意这**不是**“窗口丢了”—— 进程与事件循环都在跑，只是没映射到屏幕上。

## 4. 修法：两处，缺一处就还是关不掉

1. `closeEvent` **第一行** `ev.accept()` —— 清理链再长（停定时器、保存工程、收子进程）也不能留下
   “拒绝关闭”的路径；否则某次清理抛错会把窗口永久钉住。
2. `main()` 里接住退出信号转成正常退出：

```python
for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(s, lambda *a: app.quit())
```

不接信号的后果：外部想关只能 `kill -9`，工程状态与未落盘的编辑必丢。

## 5. 根治占死事件循环的绘制热点

- 定时器里**每帧全量 `setData`** 的多曲线图：开 `setDownsampling(auto=True, mode="peak")` +
  `setClipToView(True)`，只画视窗内的点 + 自动降采样，单帧数据量能降一到两个数量级。
- 自定义 `paintEvent` 里做**文字布局/避让/包围盒计算**（标签 `_labels → _block` 这类）：结果必须缓存，
  只在数据/尺寸变化时重算。每帧重算几何是另一条同样致命的热点。
- 顺序固定：**先量**（py-spy 抓 2~3 次，确认每次都停在同一路径，排除偶发）→ 改 → 再量与复测栈。

## 6. 重启纪律

- **用户正在编辑界面时不要重启**：先确认再动手。界面里的临时选择会丢，但已经写进真源文件的配置
  （产品档位、工程档）重启后会读回 —— 汇报时把这两件事分开讲，别让人以为全部白干。
- 守护脚本/启动脚本会把被杀掉的 GUI **自动拉起来**，所以“杀掉就没事了”是错的：根因不修，新进程会卡在同一处
  （同一个绘制热点、同一个 `UnMapped`）。
- 启动用受管后台会话，不要自己套 `nohup`/`setsid`：托管进程结束能收到通知，套壳的进程失联后你连它有没有起来都不知道。
