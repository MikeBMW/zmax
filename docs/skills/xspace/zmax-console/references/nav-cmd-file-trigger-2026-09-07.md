# 外部命令文件触发 (nav-cmd-file-trigger) — 2026-09-07

老倪远程指挥时: "别瞎点了" → "增加技能, 直接打开simulink模式"。
盲点像素被明确纠正; 正解 = GUI 内确定性命令通道。

## studio.py 内置代码段 (v5.0.0+, 主窗口 __init__ 尾部; 丢了可重贴)

```python
# 📡 外部命令文件触发: 监控 /tmp/zmax_nav_cmd — 写入一行命令即执行
self._nav_cmd_timer = QTimer(self)
self._nav_cmd_timer.timeout.connect(self._poll_nav_cmd)
self._nav_cmd_timer.start(300)
self._nav_cmd_seen = set()

def _poll_nav_cmd(self):
    try:
        p = "/tmp/zmax_nav_cmd"
        if not os.path.isfile(p):
            return
        with open(p) as f:
            lines = [l.strip() for l in f if l.strip()]
        os.remove(p)  # 先删防重复
        for line in lines:
            if line in self._nav_cmd_seen:
                continue
            self._nav_cmd_seen.add(line)
            try:
                if line == "simulink":
                    self._on_nav("simulink")
                elif line == "ss_canvas":
                    _oneshot(self, 600, self._open_ss_canvas_cmd)
                elif line == "ss_3d":
                    _oneshot(self, 1200, self._open_ss_3d_cmd)
                elif line in self.modules:
                    self._on_nav(line)
                else:
                    self.statusBar().showMessage(f"📡 未知命令: {line}", 2500)
            except Exception as _e:
                self.statusBar().showMessage(f"📡 命令失败 {line}: {_e}", 3000)
    except Exception:
        pass

def _open_ss_canvas_cmd(self):
    """（注：早期版会加载画布真源）"""

def _open_ss_3d_cmd(self):
    self.simulink.open_ss_3d(on_top=False)
```

注意: studio.py 顶部已有 `from PyQt5.QtCore import ... QTimer ...` (178 行附近),
不需要另起别名。类内方法缩进对齐。

## 用法

```bash
echo simulink > /tmp/zmax_nav_cmd     # 切 Simulink 页 (QStackedWidget idx 10)
echo ss_canvas > /tmp/zmax_nav_cmd    # 开状态空间画布 (=加载状态空间工程)
echo ss_3d > /tmp/zmax_nav_cmd        # 开 3D 视图
echo ss_run > /tmp/zmax_nav_cmd       # ▶ 跑状态空间仿真
echo monitor > /tmp/zmax_nav_cmd      # 开独立窗口「📈 实时监控 · 信号分析」
echo training > /tmp/zmax_nav_cmd     # 任意 modules key: home/dataset/training/...
echo l5_status / l5_interact / l5_diag > /tmp/zmax_nav_cmd
```
写后 `ls /tmp/zmax_nav_cmd` 消失 = 已消费 (轮询 300ms; 画布/3D 另有 600/1200ms 延迟补偿)。

## 🔴 命令通道实测锤出来的三条 (2026-10-12「信号分析动起来」)

1. **`ss_run` 前必须画布已加载** —— 新起/重启后的进程里 `simulink.nodes` 是**空**的,
   直接 `start_sim()` 只会写一行 `⚠️ 画布为空 — 点击「参考应用」…` 就返回(**静默失败**,
   看台面就是"我点了运行但没反应"). 正确顺序: `ss_canvas` → 等几秒 → `ss_run`.
   已在 `studio._run_ss_cmd` 内置兜底(空画布先 `open_state_space()` 再跑; 下次重启生效)。
2. **`ss_run` 失败的原因去 `/tmp/simulink_log.txt` 找, 不要猜** —— `SimulinkModule._log` 把
   每一行都落这个文件(带 `[HH:MM:SS]`), 运行/失败/相态全在里面(比截图 OCR 快且准)。
3. **"信号分析会不会动"看 `zmax_data/ss_live/trace_live.json` 的帧龄**(≤2s 才算实况):
   它的**唯一写入者**是 3D 面板渲染帧时的 `ss_dreamview.publish_trace_live` ⇒ 3D 窗口
   必须在 `_ss_3d_windows` 里才喂得到帧。判据 `tools/verify_ss3d_trace_publish.py`(11 项)。
   屏幕侧复核: 实况期对信号分析窗口连拍, 相邻两张平均像素差 >2 = 真在动(实测 8.0/7.7/8.0;
   停后 0.01) —— 像素差比 OCR 可靠, 也不用看字。

## 为什么不用 xdotool 盲点
- 像素找按钮 (PIL 色块聚类/猜卡片坐标) 多轮失败: 深色主题无浅色大块可锚、
  青色点缀遍布全屏非卡片色、窗口双实例 (一个 desktop=-1 幽灵) 位置混淆。
- 盲点成本: 每轮截图→分析→猜坐标→点→再截图验证, 且点错污染界面状态。
- 确定性替代优先级: ① 命令文件 (运行中直达, 不重启) ② env 钩子 ZMAX_AUTO_SS* /
  ZMAX_AUTO_RUN / ZMAX_AUTO_TEST (需重启 GUI) ③ 键盘导航 ④ 像素点击 (最后手段)。

## 窗口归属判定 (xdotool 多实例混淆)
- `xdotool search --name "XSpace Studio"` 返回多个 → 同名窗口可能是幽灵/装饰。
- `xdotool get_desktop_for_window <wid>`: desktop=-1 = 隐藏幽灵; 可见 = desktop=0。
- `xdotool getactivewindow getwindowname` 确认前台; 操作前 `windowactivate <wid>`。
- GUI 中央大片黑 = Mutter map/渲染问题或窗口根本没在截图区域 — 先确认
  `getwindowgeometry Position` 落在截图范围内, 别把黑屏当界面状态分析。
- `xdotool search --onlyvisible --name XSpace` 会额外返回一个 `mutter-x11-frames`
  (=GNOME 窗框代理, 它镜像窗口标题) —— 不是第二个控制台, 按 `_NET_WM_PID` 认归属。
- `scrot` 抓的是**最上层**那张 ⇒ 截任何独立窗口前先 `wmctrl -i -a <win>` 再等 1~3s。

## 相关
- zmax-console SKILL.md § 外部命令文件触发
- simulink_module.py SimulinkModule.open_state_space / open_ss_3d / start_sim / _real_finish / _ss_tick
- 重启 GUI: 精确 PID / `pkill -f "[s]tudio.py"` 方括号技巧 (见 SKILL.md 陷阱)
