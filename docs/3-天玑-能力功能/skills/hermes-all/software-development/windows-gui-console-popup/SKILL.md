---
name: windows-gui-console-popup
description: Use when a Windows GUI app flashes console windows
version: 1.0.0
author: 小红
license: MIT
metadata:
  hermes:
    tags: [windows, gui, subprocess, popup, ifeo]
    related_skills: [windows-app-deployment, windows-system-maintenance]
---

# Windows GUI 程序反复弹黑窗（控制台窗口）

## When to Use

- 某个 GUI 程序（Qt / .NET / Electron / PyInstaller 打包的 exe）运行时，屏幕上反复闪黑窗
- 已经试过在 PATH 里放静默包装但没用
- 需要判断“某个控制台命令是不是被某个进程在 spawn”
- 用户说“启动时弹好多窗口又自己关掉”，而窗口标题其实是**程序自己的名字**

## 症状
两种完全不同的东西都被用户叫“弹窗”，先分清再修，否则会照着错误分支修半天：

- **子进程控制台窗**：黑底命令行窗口，标题是被调用的工具名或 `C:\Windows\System32\xxx.exe`，按固定秒数周期闪现。见「修复 A」。
- **程序自己的窗口**：标题等于 exe 名（如 `Z-MAX_Console`），启动那几秒成百个挤着闪、一闪一关，单个只有十几毫秒，用户多半是**从任务栏 / Alt+Tab 的抖动**感知到的。见「修复 B」——别在外部瞎藏，先诊断再决定。

## 根因
GUI 子系统进程（IMAGE_SUBSYSTEM_WINDOWS_GUI）没有控制台，且 Windows 不让 GUI 子进程继承父控制台。于是它每次 `subprocess` 调一个**控制台程序**（nvidia-smi、ps、sysctl、tasklist…），系统就为其新建一个控制台；默认终端是 Windows Terminal 时表现为一个窗口闪现。

注意：`shell=True` 时中间还有 cmd.exe，那本身也是控制台程序。

## 诊断（别猜，抓证据）

0. **先数窗口归属**（决定走 A 还是 B）。WinEvent 记 30-90 秒 SHOW 事件，按 `hwnd` 去重、按 `pid` 分组：
   - 全部 hwnd 来自**一个** pid、class 是 `Qt*QWindowIcon` ⇒ 程序自己的窗口 → 修复 B。
   - pid 落在 conhost/各工具进程、class 是 `ConsoleWindowClass` / `CASCADIA*` / `PseudoConsoleWindow` ⇒ 子进程控制台窗 → 修复 A。

   只看事件总数会误判：同样 500 条事件，可能是 500 个不同 hwnd（真·500 个窗口），也可能是同一个窗口反复 show。计数片段见 `references/diagnose.md` §5。
1. **抓父进程**：WMI `Win32_ProcessStartTrace` 事件里记录 ProcessName + ParentProcessID，立刻 Get-CimInstance 反查父进程名。能确认是哪个进程在 spawn。见 `references/diagnose.md`。
2. **抓窗口**：直接跑 `scripts/winhook.py [秒数] [精确标题]`（SetWinEventHook 0x8000/0x8002 + PeekMessage 泵，记 hwnd/class/pid/rect，末尾按 title 出 summary）。自己写的话**不要用 powershell 写这个 hook** —— 回调委托被 GC 会 c000041d 崩溃，弹出新的「PowerShell 已停止工作」。
3. **确认是不是真程序**：控制台程序会带 `conhost.exe` 子进程；winexe 包装不会。这是最硬的判据。
4. **PATH 包装为什么没生效**：给包装 exe 加命中日志，重启目标程序看日志是否为空。空 = 程序走的是绝对路径或裸命令名，PATH 顺序救不了。
5. **先排除你自己**：你每跑一条 bash / powershell 诊断命令，在 Windows Terminal 下都可能新开一个**可见的**伪控制台窗口（`git.exe` / `ssh.exe` 的 `PseudoConsoleWindow` 伴一个 WT 顶层窗）。用户说“还在弹”而你正在连着敲命令时，先按 owner pid 把这些窗口剔除（你的 shell 后代）再判断是不是程序弹的，否则会把自家噪音当成没修好、反复回炉。

## 修复：IFEO 静默转发

对每个高频控制台工具注册 Image File Execution Options，重定向到自己的 winexe 转发器：

```
HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\nvidia-smi.exe
    Debugger = D:\<app>\_stubs\ife_wrap.exe
```

系统会调用 `ife_wrap.exe "<原 exe 全路径或原命令名>" <原参数...>`，转发器用 `ProcessStartInfo{UseShellExecute=false, CreateNoWindow=true}` 跑真实程序，stdout/stderr/退出码原样转发。**根本不再产生控制台**，不是隐藏窗口。

### 三个必踩的坑

1. **无限递归**：转发器若再启动同名 exe，IFEO 再次劫持 → 死循环 + 卡死。必须先把真实 exe 复制到 `_stubs\real\<name>-real.exe` 再从副本启动。
2. **args[0] 没有扩展名**：IFEO 传进来的可能是裸命令名 `ps` 或 `nvidia-smi`（无路径无 .exe）。`Path.GetExtension` 为空时要补 `.exe`，否则找不到副本，调用静默失败。
3. **打包程序的源码改了没用**：PyInstaller onedir 的模块在 PYZ 里，磁盘上的 `.py` 不参与加载。改源码加 `CREATE_NO_WINDOW` 是白工。
   验证只需一轮：在源码里插一句写文件的探针、重启、看文件是否出现（文件不出现 = frozen 版）。
   frozen 版两条路：① 外部手段（IFEO/包装）治标；② 真的重新打包——配方和坑见 `references/pyinstaller-rebuild.md`。

转发器源码见 `scripts/ife_wrap.cs`（csc 编译，`/target:winexe`）。

## 修复 B：程序自己的窗口（先诊断，别急着藏）

标题等于 exe 名、启动几秒内成百个一闪一关的窗口，多半是程序建页时把**无 parent 的 QWidget 短暂当成了顶层窗口**（Qt 里 addWidget / reparent 之前，它就带着默认标题露了一下）。frozen 包里改不了代码，但**第一反应不能是隐藏**：实测给这类窗口套 `SW_HIDE`，启动反而更慢甚至卡死，还会在任务栏堆一串同名项，最后只能整体回滚。

按这个顺序做：

1. **量清楚**：hook 按 `title=` 字段过滤数 show 事件（别 grep 整行，进程名每行都有），再看采样到的窗口矩形。这批窗口的共性是：尺寸一致、位置固定、寿命十几毫秒、`WS_CAPTION` 但没有 `WS_EX_TOOLWINDOW` ⇒ 每个都往任务栏注册一个按钮又立刻消失。
2. **报告，不擅自动手**：把数量、尺寸、位置、寿命、任务栏副作用讲清，并说明真修在 spawn 侧（QWidget 创建时带 parent、批量建控件前 `setUpdatesEnabled(False)`、或用不入任务栏的窗口类型），需要重新打包。
3. **只有用户明确点头才做外部干预**，并且干预必须可回滚：把轮询隐藏器、计划任务、启动脚本三处改动逐条列出来；回滚 = 杀进程 + `schtasks /delete` + 还原启动脚本。真要写，用轮询式 C# winexe（每 25ms `EnumWindows`）而不是 WinEvent hook —— hook 版在 `-WindowStyle Hidden` 环境下启动即秒退，无日志无退出码。要常驻就用 `schtasks /sc onlogon /rl highest` 起，别塞进启动脚本：wscript 的 `sh.Run` 拉起的子进程在测试里会立刻消失，同一环境换 `Start-Process` 却正常。
4. **干预的验收不许用“峰值窗口数”自证**：那个数字只反映采样那一刻，用户看的是启动全过程。必须同时看 ①启动到主窗口的时间 ②主进程 `Responding` ③窗口/任务栏是否还在堆 ④**让用户在屏幕前确认**。少这一条就会演出“我报已修好、用户说更卡了”。

**若拿到了重新打包的机会**，全局守卫要包全**五条显示路径**，只包 `show()` 实测只干掉 505 个中的 115 个，剩下 390 个走的是 `setVisible`：

```python
for _n in ("show", "setVisible", "showNormal", "showMaximized", "showFullScreen"):
    _orig = getattr(QWidget, _n, None)
    if _orig is None:
        continue
    def _guarded(self, *a, _o=_orig, **kw):
        if self.parent() is None and not (self.windowTitle() or "").strip():
            self.setAttribute(Qt.WA_DontShowOnScreen, True)
        return _o(self, *a, **kw)
    setattr(QWidget, _n, _guarded)
```

判据只匹配「无 parent + 标题为空或等于进程名」，带标题的主窗口不受影响；包个 `ZMAX_NO_FLASH=1` 回滚开关。改完必须重新打包才生效，流程见 `references/pyinstaller-rebuild.md`。

这是**看不见**而不是不创建：向用户说清“源码在打包 exe 里，防不住”，并把真修（改 spawn 侧代码 + 重新打包）指给打包方。

## 验证

- 30 秒 WinEvent hook 监控，期望 `events=0` 或只剩无关的隐藏 OLE 窗口。修复前同长度应有几十个。
- **计数一律按 `title='<精确标题>'` 匹配**。grep 整行会把每行都带的进程名算进去，实测把 505 条虚报成“506 个窗口”。
- 程序自身窗口类（修复 B）**不能只靠窗口计数验收**：同时记录启动到主窗口的时间、主进程 `Responding`，并让用户看着屏幕确认；只报“峰值 1 已解决”必然翻车。
- 转发日志确认命中且路径指向副本（不是原 exe）。
- 目标程序的业务数据仍正常（读到了 GPU/进程数据）。

## 回滚与风险

- 回滚：删掉对应 IFEO 注册表键即可（改动只在那两个键）。
- `_stubs\real\*` 副本被删会导致**全系统**该命令失效（不只目标程序）。别乱删。
- 转发器日志要限流（>512KB 清空），否则每 5 秒几条会撑爆磁盘。

## 别用这些方案

- **用 hook 去隐藏子进程的控制台窗**：治标——窗口照样创建、只是藏起来，而且 PowerShell 版 hook 自己会崩；控制台窗要用 IFEO 从源头消掉（修复 A）。
- **拿 `SW_HIDE` 去糊程序自己的启动窗**：实测让启动变慢甚至卡住，隐藏但没销毁的窗口还在任务栏 / Alt+Tab 堆一串同名项，体验比原来更差。真要做也得先量清、先跟用户对过、留好回滚（见修复 B）。
- **用 `wscript -e:vbscript -c "<内联代码>"` 跑一次性脚本**：wscript 不认 cscript 风格的选项，会弹「Windows Script Host / 指定了未知的选项」，而且这个错误框**会一直挂在屏幕上**，用户会当成又一个弹窗。只写 `.vbs` 文件再 `wscript file.vbs`；要内联用 `cscript //E:vbscript //nologo`。
- **把默认终端改回 conhost**：窗口照样闪，只是换成 conhost 画。
- **PATH 里放同名包装 exe**：只对走 PATH 的调用有效；用绝对路径或 shutil.which 缓存的调用会绕过。
