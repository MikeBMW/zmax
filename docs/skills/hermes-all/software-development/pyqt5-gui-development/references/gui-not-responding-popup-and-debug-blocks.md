# GUI 调试时的两类「假故障」— 无响应弹窗 + 断点阻塞 (2026-09-15 实测, 原生 Ubuntu 24.04 + GNOME 46 X11)

## 1) `studio.py is not responding` 弹窗 (Mutter 存活探测)
症状: 调试中反复弹「未响应 / 等待 / 强制退出」对话框, GUI 本身没崩 (进程活着)。

根因: 应用 X11 窗口在 `org.gnome.mutter check-alive-timeout` (默认 **5000 ms**) 内没有回应
Mutter 的 `_NET_WM_PING`。触发场景:
- **停在断点** (VSCode debugpy `--configure-qt none` 拉起, 主线程停在 bp) → Qt 事件循环完全停止;
- 主线程被同步长调用阻塞 (网络/训练/大文件 IO 写在主线程)。

一键关掉探测 (X11, 立即生效):
```bash
echo $XDG_SESSION_TYPE                       # 本次 = x11
gsettings range org.gnome.mutter check-alive-timeout   # type u (uint32)
gsettings set org.gnome.mutter check-alive-timeout 0   # 0 = 关闭存活检测
gsettings get org.gnome.mutter check-alive-timeout     # 确认 uint32 0
gsettings reset org.gnome.mutter check-alive-timeout   # 调试完还原 (默认 5000)
```
注意:
- 这只让弹窗闭嘴, **不解决卡顿**。若没停断点也卡 → 真主线程阻塞, 按 SKILL.md §5
  (worker + pyqtSignal 回主线程 / QTimer 队列 flush) 修, 别用关探测掩盖。
- 屏上已存在的弹窗不会自动消失 (点"等待"即可)。
- 该键是 per-user dconf, 不需要 sudo, 不影响其它机器。

## 2) 判「是断点阻塞还是真卡死」
- `pgrep -af studio.py` 能看到 debugpy 两个进程 (launcher + adapter/`--connect`) = **跑在调试器下**,
  此时"阻塞"多半是断点/单步, 不是代码 bug;
- 想确认是否真的死在主线程: 在调试器里看主线程栈是否停在 `app.exec_()`, 或在代码里
  `faulthandler.dump_traceback_later(20)` 落盘 (见 references/qt-mutter-native-gnome.md)。

## 3) 附带: Windows 侧死锁类问题的处理顺序 (本次实际顺序)
1. 先确认进程/会话类型 (`$XDG_SESSION_TYPE`, `pgrep -af`) — 别先改代码;
2. 先用 WM 层开关消除噪音 (上面 gsettings), 让调试能继续;
3. 调试完再按根因修主线程阻塞; 最后 `gsettings reset` 还原。

## 4) 断点根本不进 (三成因, 按命中率排)
先分清"编辑器里的断点只是画着"还是"代码真跑过了"。判据是**代码内的周期证据行**, 不是调试器状态:
在目标函数里每 N 次打一行 `print(f"真身执行 #{n}")` —— 这行不出, 就是路径根本没走。

1. **整块方法被实例属性替换** (最常见, 也最隐蔽): 装配期 `self.obj.forward = self.obj.analytic_forward`, 而开关在环境变量里
   (`if os.environ.get("SS_USE_MLP") == "1": ... else: <替换>`)。于是 `FeedforwardAccelerator.forward` 该方法体一行都不执行,
   断点设在里面永远不会停。查法: 读活进程环境 `tr '\0' '\n' < /proc/<pid>/environ | grep SS_`, 缺开关即命中。
2. **跑在另一个进程里**: 常驻引擎/采集 loop 是独立进程 (没有 pydevd), 编辑器里调试的是 GUI 进程 ⇒ 断点对它无效。
   查法: `pgrep -af "<entry>.py"` 看两条进程; 要调就 attach 到引擎 pid, 或让引擎在 GUI 进程内跑。
3. **按路径装载的模块没进 `sys.modules`**: `spec_from_file_location` + `exec_module` ⇒ debugpy 解析不到, 断点不绑定。
   改成 `exec(compile(src, abspath, "exec"), m.__dict__)` + `sys.modules[mod_name] = m`, 判据是 `mod_name in sys.modules`
   且目标方法 `__code__.co_filename == realpath(文件)`。

保底手段: 代码里放一个 `if os.environ.get("X_BREAK") == "1": debugpy.breakpoint()` 的硬停开关 —— 不依赖断点绑定。
但注意它在 10~100Hz 的循环里会**每次命中都停**, 表现成"栈不停变化"(见下一条)。

## 5) 断点已经停住, Call Stack 还在不断变化
- 机制: 只冻结命中那个线程; 面板显示"当前选中线程"。别的线程再命中断点, 或线程里异常没接住, 都会发 stopped 事件把焦点抢走。
- 量化: `ls /proc/<pid>/task | wc -l`; `cat /proc/<pid>/task/*/comm` 看是谁 (Qt 事件队列/DBus/缓存/每个 2s 轮询器)。
- 应用侧修法(实测 24 线程 → 16 线程): ① `debugpy.is_client_connected()` 或 `sys.gettrace() is not None` 判定调试中,
  此时**不 start** 后台轮询 QThread (各打一行 `🐞 调试模式: ... 未启动` 让效果可验证), 另留环境变量强制开; 
  ② `threading.excepthook` 改为落日志, 不抛回解释器。
- 用户侧保障: 断点 → Edit Breakpoint → Hit Count=1 / 条件 (`self.n_calls == 1`), 只停你关心的那一拍。
- 别用 `SS_FF_BREAK` 这类"每 N 次硬停"去确认路径 —— 在 Qt 多线程下它正好制造"栈乱跳"的观感。

