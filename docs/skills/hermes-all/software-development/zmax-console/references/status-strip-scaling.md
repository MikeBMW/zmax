# 底部硬件状态带放大 / 消失 / 画横杠

状态带 = `tools/gui/status_panel.py`（`StatusPanel`），挂在 `studio.py` 主窗 central 布局最后一行。

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

字体 px 一并乘 SCALE，等于 10/11px → 14.2/15.6px，版式比例不变 ⇒ 不会重叠、不会截断。

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

## 坑 5：改完号/改完样式要真重启一次才算生效

控制台进程是用旧源码起的，改文件不会热生效；改完（尤其是版本号）必须**清实例 → 单实例重起**，
再从截图 OCR 回读新号（`tesseract ... | grep -o "5\.50\.7[0-9][0-9]"`），别只信源码 grep。
