# 底部硬件状态带放大 / 消失 / 画横杠

状态带 = `tools/gui/status_panel.py`（`StatusPanel`），挂在 `studio.py` 主窗 central 布局最后一行。

## 字号定标: 按物理像素算，别按"看起来差不多"拍

本机面板 eDP-1 3200x2000 / 344mm ≈ **236 DPI**，Xft.dpi≈192 ⇒ **1pt ≈ 2.67 物理 px**。
而 `StatusPanel` 里字体是 `setPixelSize(10/11)`（**px 不随 DPI 放大**）⇒ 字号必须用 SCALE 抬到"物理 px 与 pt 标签同级"：

| SCALE | 面板尺寸 | 10px 字的物理 px | 等效 pt | 现场结论 |
|---|---|---|---|---|
| 1.42 | 1533x56 | 14.2 | ~5.3 | 老倪第一次投诉后仍被第二次投诉「字体太小」 |
| 2.60 | 2808x104 | 26 | ~9.7 | 第三次投诉「字体太大了」; 且 2808 > 屏宽 1920, 右侧一直被父控件裁掉 |
| 1.76 | 1900x70 | 17.6 | ~6.6 | 第四次投诉「还是太大」 ⇒ 再降 |
| **1.45 (现役)** | **1566x58** | **14.5** | **~5.4** | 桌面 1920 宽, 右边余 358px; 白字行带实测 23px→12px |

- **宽度是硬约束**: 面板宽 = `1080 × SCALE`, 且窗口可能被 WM 放到任一显示器 ⇒ `SCALE ≤ 1920/1080 = 1.777`
  (本机 eDP 1920x1200 + HDMI 1920x1080, 两块都是 1920 宽; 换 3200 宽屏才允许更大)。
  ⚠ 超了这个值不会报错, 父控件**静默裁掉右边** ⇒ 屏幕上看像「少了几项」而不是「字号大」。
- 判据(不靠肉眼): 离屏 `--selftest --shot` 量**白字行带高度**与面板尺寸; 上线后再 `xwininfo -id <win>` 拿 `Width`,
  从截图像素量「状态带内容最右列」, 要求 `内容最右列 < 窗口宽`。
- 取证截图别用整屏 scrot 猜: 其它窗口(微信/飞书)会盖住控制台，且控制台常被 WM 放到**副屏**。用 `wmctrl -a '<标题>'` 抬窗后 `scrot -u`(抓焦点窗)，再在窗内自底向上找 `#161b22` 行；`xwininfo -id <win>` 核对 `绝对Y + 高度 == 屏高` 才算"整条在屏内"(窗口底边 = 2160 时正好贴合，多 74px 就是被切)。

## 放大字号：用单一 SCALE，别逐个调 font-size

`StatusPanel` 的 paint 全是写死像素（chip 宽 88、槽宽、灯半径、坐标 11/37/47/60）。
逐处改字号必然错位。做法：

```python
W, H = 1080, 40        # 逻辑画布，paint 坐标一直按这个写
SCALE = 1.42           # 唯一放大系数
setFixedSize(int(W*SCALE), int(H*SCALE))
# _paint:
p.scale(SCALE, SCALE); w, h = self.width()/SCALE, self.height()/SCALE
```

字体 px 一并乘 SCALE，等于 10/11px → 14.5/16px，版式比例不变 ⇒ 不会重叠、不会截断。

## 高度：只改 `H`，别改 y 坐标（所有 y 都挂在中线 `cy = h/2`）

`_paint` 里没有写死的绝对 y：文字行用 `QRectF(x, 0, w, h)` + `AlignVCenter`，灯/环/进度条全部 `cy ± k`。
所以“太高、很空旷”只需改逻辑高度 `H`，内容自动重新居中：

| H (逻辑) | 物理高 @SCALE 1.45 | 现场 |
|---|---|---|
| 40 | 58px | 上下各留 ~15px 空白，老倪：「太高了，很空旷，高度变成当前的一半」 |
| **20 (现役)** | **29px** | 内容 25px 全在带内（上留 1 / 下留 2），无裁切 |

- **下限 = 最高固定元素 18 逻辑 px**（当前档 chip 底 `cy±9`；灯外圈 14、推理环 13、进度条 7 都更矮）⇒ `H ≥ 20`，再矮就切掉 chip 上下边。
- 判据：离屏 `--selftest --shot` 看「行带」+ 像素量内容行相对带顶/带底的留白；上线后 `scrot` 抓窗口，底向上找纯色行得带高，`H×SCALE` 必须对得上。

## 坑 1：缩放后 fillRect/drawLine 走 int 重载 ⇒ 整帧静默不画

`p.fillRect(0,0,w,h,color)` 的 w/h 变成 float 后 PyQt 抛 TypeError，异常在 paintEvent 里被吞掉：
**面板不是空白控件，而是什么都没画，透出父控件底色**（白页上就是一片白，截图看像「状态带没了」）。
改成 `p.fillRect(QRectF(0,0,w,h), QColor(...))`、`p.drawLine(QPointF(0,0), QPointF(w,0))`。

## 坑 1b：改完先离屏 grab 数颜色，别只看 selftest 通过

```python
im = p.grab(); a = np.asarray(im.convert('RGB'))
print(a.mean(axis=(0,1)))      # 深色带 mean 应 ~[27,33,40]；[239,239,239] = 没画
```

selftest 里的「行带高度」判据要跟着 SCALE 改（`_Hp*0.35 ~ _Hp*0.98`），别写死 40px。

## 坑 2：availableGeometry() 本身可能越界 ⇒ 状态带被顶到屏外

这套 GNOME/Mutter 实测 `availableGeometry()` 报 `3068x1862@132,212`，底边 2074 > 主屏 2000；
按它「夹回可用区」= 夹到屏外，最下面那条带整条看不见（抓窗口 framebuffer 能看到，肉眼看没有）。
判据：`_NET_FRAME_EXTENTS` 顶部有 74px，client 绝对 y = frame_y + 74；
窗口夹紧必须用 **屏幕物理几何（xrandr / QScreen.geometry）∩ availableGeometry**。

```python
_g = scr.geometry(); ag = QRect(max(ag.x(),_g.x()), max(ag.y(),_g.y()),
        min(ag.x()+ag.width(), _g.width())-..., min(ag.y()+ag.height(), _g.height())-...)
```

取证别只 `scrot` 猜：在 studio 里加一行启动打印更省事——
`[status_panel] geo=1533x56@0,1750 vis=True | win=3068x1936@132,64 | in_screen=True`。

## 坑 3：槽位画「—」≠ NPU 没跑，是取数超时

状态带 NPU/GPU 槽读 `/status/all.edge.pipeline.devices.*.duty_pct`。
`status_hub.collect_edge()` 原来的 timeout=1.5s，而经 orin 隧道的单请求实测 **2.9~3.6s** ⇒
必然 TimeoutError ⇒ `online=False` ⇒ 界面只能画横杠（intel 上其实 96% 满载）。
修法：后台线程刷 + 缓存（ttl 8s，timeout 8s），请求路径永不阻塞，返回带 `cache_age_s`/`stale`。
判别命令：`curl -s 127.0.0.1:18800/pipeline/stats` 有值 + `/status/all.edge.online=false` ⇒ 就是这个坑。

## 坑 4：多实例互踢，`systemctl restart` 后窗口突然没了

旧实例还在跑时 restart，新实例会自己退出（ExecMainStatus=0，日志只到 AR 页加载），
屏幕上留下的是旧进程（跑的是旧代码）的窗口。

🔴 **按名字找不到实例的坑**：`launch_studio.sh` 是 `cd tools/gui && python studio.py` ⇒ cmdline 是
`/home/ubuntu/zmax/gui-venv311/bin/python studio.py`。用 `pgrep -f "tools/gui/studio\.py"` **命中 0**，
于是你会在"没有实例"的前提下反复 start，而 systemd 每次 43ms 就退出（检测到已有实例）→ 看着像崩溃。
正确写法：`pgrep -f "studio\.py"` 并按 cmdline 过滤（排除 `QtWebEngineProcess` 子进程和本工具自身的 shell），
再 SIGTERM/SIGKILL，最后 `systemctl --user start` 并回读 MainPID。

## 首页不再挂「项目状态 / 硬件资源」两块 (2026-10-23)

老倪两次删减: 「项目状态 Status 那个窗口删掉」「硬件资源 Hardware 这个窗口删掉吧, 与最底部的显示功能重复了」。
`HomeWidget._build()` 里只留 `产品迭代 Roadmap` + `功能模块 Modules` 两节; `_stats_bar()` / `HardwareCard` 类保留但**不实例化**
(离线取证工具 `tools/measure_hw_card_*.py` / `tools/verify_hw_card_sync.py` 仍可自己 new 一个)。

- 硬件数字只在**底部状态带**显示一份 ⇒ 它不能不可见: 窗口夹紧要保证 `client_y + client_h ≤ 屏幕高`
  (实测 xwininfo 的 `Absolute Y + Height == 1200` 刚好贴合才算整条在屏内; 抓图时 y 用客户端 y,
  用 xdotool 的 Y 会多算标题栏 37px, 把底部 28px 状态带裁掉一半而误判成「卡被删了」)。
- 若以后又要在页面上显示硬件, 别另采一份: `HardwareCard._sync_strip(payload)` 已把状态带同一份
  `/status/all` + 同一个 `StatusPanel.modes()` 解析器的槽位原样搬上卡 (名称/比例/文字/颜色逐项相等,
  判据 `tools/verify_hw_card_sync.py`), 两处数字不允许各算一套。

## 坑 5：改完号/改完样式要真重启一次才算生效

控制台进程是用旧源码起的，改文件不会热生效；改完（尤其是版本号）必须**清实例 → 单实例重起**，
再从截图 OCR 回读新号（`tesseract ... | grep -o "5\.50\.7[0-9][0-9]"`），别只信源码 grep。
