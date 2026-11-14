---
name: vscode-breakpoint-inspection
description: Use when 要在 VSCode 停断点并看变量值。
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [debugging, vscode, debugpy, breakpoint, numpy]
    related_skills: [zmax-console, su2-unified-state-space]
---

# 在 VSCode 里把断点真停住, 并让值可读

pdb / debugpy 的基础用法见已装的 `python-debugpy`; 本文只补两件它不管的事: **替用户在 GUI 里起会话并自证停住**, **把没有语义的数组改成带物理量的名字**。

## 何时用
- 「用 vscode 定义一个断点, 停在 X 的输出/return, 我看看实际的输出」
- 「在 vscode 里看不到这个变量的物理含义」—— 大数组/结构体在 Locals 里只有下标
- 需要在用户屏幕上留一个**已经停住**的会话, 而不是给他一串操作步骤

## 铁律
1. **交付物是"已停住的会话"**。他说"你给我运行"= 你去点、去按、去起, 不许让他自己 F5。
2. **断点必须门控, 且用 `debugpy.breakpoint()` 而不是内置 `breakpoint()`**: 共享库里裸 `breakpoint()` 会把常驻服务挂死。
   ```python
   def _debug_stop() -> None:
       if os.environ.get("ZMAX_DEBUG_<TAG>") != "1":
           return
       try:
           import debugpy                       # 调试会话里 debugpy 一定可 import(扩展自带)
           debugpy.breakpoint()                # ← 停成编辑器里的 Paused(有调用栈/变量)
           return
       except Exception:
           pass
       breakpoint()                            # 兜底: 无 debugpy 时落终端 Pdb
   ```
   内置 `breakpoint()` 在 VSCode 调试会话里会落到**终端 Pdb**(编辑器不显示 Paused、Locals 空白),
   用户会以为"断点没停"; `debugpy.breakpoint()` 等价于"在这里下一行断点", 才是他要的形态。
   门控变量只出现在调试 launch 配置的 `env` 里; 常驻服务环境没这个变量 ⇒ 生产路径逐位不变。
   ⚠️ 停止后调试器报的行号通常比 `debugpy.breakpoint()` 那行**大 1**(它在下一行挂起), 报位置按实测栈说。
3. **先让变量有名有单位, 再让他看** —— 见第三节。
4. **自证停住**: py-spy 抓到 `_do_wait_suspend (pydevd)` + 你的函数帧, 才算停住。进程状态 `S` 分不出"停住"和"在跑"。
5. 不许把 `patch` 当探针: 写进去的 `"X"`、删掉的一行就是真代码。改完用 `py_compile` + AST 裸 name 扫描 + 真跑验。

## 一、配置与启动
- 单文件夹窗口读 `.vscode/launch.json`; 用户若开的是 `.code-workspace`, **同一份配置还要写进该文件顶层 `"launch": {"configurations": [...]}`**, 否则选择器里根本没有它。两份都要 JSON 校验。
- 必填: `"type": "python"`, `"request": "launch"`, `"program": <绝对路径>`, `"justMyCode": false`, `"console": "integratedTerminal"`, `env` 带门控变量; 配置名加个显眼前缀(如 `🧪 断点 · …`)方便唯一匹配。
- 起会话(**别用裸 F5**: 它复用上次用过的配置, 可能是个又重又无关的 GUI 配置):
  ```bash
  DISPLAY=:0 wmctrl -a "Visual Studio Code"; sleep 1
  DISPLAY=:0 xdotool key --clearmodifiers ctrl+shift+p; sleep 1.5
  DISPLAY=:0 xdotool type --delay 25 "Debug: Select and Start Debugging"; sleep 1.5
  DISPLAY=:0 xdotool key Return; sleep 2
  DISPLAY=:0 xdotool type --delay 25 "<配置名里的唯一词>"; sleep 1.5
  DISPLAY=:0 xdotool key Return
  ```
- 重来: `shift+F5` 停掉旧会话再按上面重起 —— 暂停中的旧会话指着旧代码, 改了文件不重起等于没改。

### 要"F5 必中指定配置": 先改**他正在用的那个窗口**的配置, 别新开窗口
老窗口的"上次用过哪条配置"是**内存里的状态, 不在任何文件里**: 你在 `.vscode/launch.json` 里把它排到第一,
或在 `.code-workspace` 的 `launch` 里再写一份, F5 仍可能起动的是**同文件夹里上次选中的那条**(实测起成了无关的 `debug_55d_output.py`)。
他若已经在看着一个窗口, **绝不新开**: 当场会被否「你不用自己再打开 vscode, 就在我已经打开的这个 vscode 设置断点」。
定式 = 把该窗口对应的 `launch.json` **备份后整体覆盖成只有一条配置**(代码块见下), F5 就无歧义必中;
会话起来后是否恢复原文件随意(已在跑的会话用内存里的配置, 不受影响)。
🔴 **两个来源都收敛到同一条**: 单文件夹窗口读 `.vscode/launch.json`, 而他开的是 `.code-workspace` 时其顶层
`"launch": {"configurations": [...]}` 也会出现在选择器里 —— 一边留 3 条一边留 1 条, 他看到的就是"那么多配置",
会要求「别搞那么多配置, 就一个」。改完两处 JSON 都要 `json.load` 校验并回读配置名给他看。

### 要"前端 GUI / 后端工程分开调试"时: 就两条, 不许多
用户口径会变: 先是「别搞那么多配置, 就一个」, 后来又会说「工程逻辑代码和控制台 GUI 的代码可以分开…
VSCode 的 debug 也要分成前端 GUI 和后端工程 两个」。**按最新口径写, 不是按条数写**:
默认一条; 他明确要分开 ⇒ 正好两条, 不多不少(别自己再加 attach/compound, 那又变成"那么多配置")。
- 前端 GUI 一条: `program` = 控制台入口(`tools/gui/studio.py` 这类), env **只给界面需要的**
  (`ZMAX_ROOT`/`PYTHONUNBUFFERED`), **绝不带 `ZMAX_DEBUG_*`** —— 否则调界面时会卡在感知/算法节点上。
- 后端工程一条: `program` = 常驻循环入口(`tools/ss_canvas_loop.py`, 与部署到端侧同一份),
  env 带门控 `ZMAX_DEBUG_<TAG>` + `ZMAX_DISPATCH_INPROC=0` + 本节提到的调度开关。
- 两条本质是**两个进程**, 断点因此天然不串; 在回复里把"哪个 program / 带哪些 env / 彼此独立"一次写清。
- 交付前先验"能起", 不要只说写好了:
  ```bash
  pgrep -af 'tools/gui/studio.py'        # 生产 GUI 已在跑 ⇒ 别再 F5 一个, 先问一句或只验编译
  ZMAX_FSM=1 ZMAX_DISPATCH_INPROC=0 timeout 12 <venv>/python tools/ss_canvas_loop.py
  sudo <venv>/bin/py-spy dump -p <pid> | grep -E 'ss_canvas_loop|main'   # 看见 main(<入口>.py:NN) = 真起来了
  ```
  GUI 那条无法安全双开时, 至少 `py_compile` + `import PyQt5` + 确认无同名进程在跑, 并如实说"未实开, 因生产实例在跑"。
🔴 **别在他正开着那个文件时硬覆盖**: 覆盖瞬间编辑器重载、光标被抢, 轻则把他弹走, 重则他判定"你把 launch.json 写乱了"。
覆盖前 `cp -a <file> <file>.bak_<tag>`, 覆盖后回读新内容报一遍。
```bash
D=/home/<user>/.hermes/cache/scratch/mfdbg        # 只要一个文件夹 + 一条配置, 不放代码
mkdir -p $D/.vscode && cat > $D/.vscode/launch.json <<'JSON'
{"version":"0.2.0","configurations":[{"name":"🧪 断点 · <名字>","type":"python","request":"launch",
 "program":"/abs/path/tools/debug_node_x.py","python":"/abs/venv/bin/python",
 "cwd":"/abs/repo","console":"integratedTerminal","justMyCode":false,
 "env":{"ZMAX_DEBUG_<TAG>":"1","PYTHONUNBUFFERED":"1","PYDEVD_DISABLE_FILE_VALIDATION":"1"}}]}
JSON
code -n $D                                     # 新窗口, F5 无选择器 ⇒ 必中这条
xdotool windowactivate $(wmctrl -l | awk '/mfdbg/{print $1}') && sleep 2 && xdotool key --clearmodifiers F5
```
- 上述临时窗口**只在他还没有窗口 / 明确允许新开时**用(好处: 不动仓库配置 · 无选择器 · 关窗即净);
  他已有窗口 ⇒ 按上面定式改他那一个, 不要多留窗口(他会要求「关掉没用的」, 而断点会话所在窗口不能关)。
- 窗口标题带文件夹名(`Welcome - mfdbg - Visual Studio Code`), 用 `wmctrl -l | grep <名>` 取窗口 id 再 `xdotool windowactivate <id>`,
  别用 `xdotool search --class code | head -1`(会拿到别的窗口, 报 `XGetWindowProperty[_NET_WM_DESKTOP] failed`)。
- 停下来之后把入口文件摆到眼前: `code -r --goto /abs/path/nodes/library.py:<行>`(调试器已跳到该文件时这步只为对齐光标)。

### 调试一个**画布/常驻节点**: 默认跑真实常驻循环 (他否过小 runner)
🔴 **默认 = 跑真实循环, 不要自造小 runner**: 老倪原话「不要这个单独 debug的py文件，要正常状态空间运行，我要看到全貌，不要断章取义」。
他要在**全体工程的正常运行逻辑**里看断点: `program` 指常驻入口(本项目 `tools/ss_canvas_loop.py`, 与部署到 550C 的是同一份),
栈就是 `main(ss_canvas_loop) → project.step → node.compute → <节点实现> → <算法函数>`, 才有说服力。
小 runner 只在**他明确说"就看这一个节点"**时用; 用完 `rm` 掉, 别留在 `tools/` 里(他会看到并要求删)。
- 跑真循环要**关掉副作用**: 加 `"ZMAX_DISPATCH_INPROC": "0"` 进 launch env, 否则停在断点上时下游可能真派发技能/发指令;
  回复里主动交代这一条("技能派发已关, 停着看时不会真下发")。
- 真循环一拍照完可能几十秒(全量 pass), 命中前 py-spy 会抓到 `node.step`/网络 `connect` —— 那不是没停, **轮询等**它到锚点。
- 小 runner 只在**他明确说"就看这一个节点"**时才有位置: 写 `tools/debug_node_<名>.py`(import 节点模块 → 造最小 ctx `{"log": print}` → 调一次), launch 的 `program` 指它; 用完 `rm` 掉。**默认绝不走这条** —— 他要的是"全貌", 小 runner 会被当场判"断章取义"。
- 🔴 **program 不许指 GUI**(`studio.py` / 带 GUI 的 `state_space_sim*.py` 入口): 他明确「不用跟 GUI 一起调试，就是状态空间工程，跟部署到 550C 的工程一样」。GUI 的 ▶运行 是 demo 播放(`execute_node_logic(demo=True)` 不执行节点真函数), 断点永不命中; 只有引擎/画布循环入口才真调节点。
- 🔴 **「同一个工程」要按算法文件核, 不按路径核**: 本机与 550C 的节点壳位置常不一致(实测本机 `middleware/nodes/impl/ss_sensor.py` 调 `perception.fuse_sensors`, 550C 仍是 `engineering/nodes/library.py`), 只比节点文件路径会得出"代码不一样"的错结论。核法: 各机 `grep -rl 'def node_<fn>' src` 找真实壳, 再对**算法文件**(`policies/left_right/state_space/*.py`)逐个 md5 对照; 算法文件一致即同源, 壳位置不同只是布局差异, 要在回复里点明。
- 🔴 **断点锚点放"算法实现"的第一行, 不放画布/派发层的节点函数**。派发层节点(如 `engineering/nodes/library.py::node_xx`)
  只做 ensure/日志/转手, 停在那里等于让他看壳 —— 他会当场质疑「节点是这个文件么? 应该是**算法**里」。
  定式: 算法侧 `state_space/<算法>.py` 的入口函数第一行放门控 `_debug_stop()`, 派发层删掉门控、只留一行注释指向它
  (`# 断点不在这里, 在 <算法>.py 的 <函数>()`)。锚点放入口第一行(还没做任何事), 他看到的变量就是原始入参。
- 🔴 **门控要内联在目标行, 不要抽成 `_debug_stop()` helper**: 抽成 helper 后暂停帧落在 helper 里
  (`_debug_stop (x.py:422)` ← 真正的算法函数), 栈顶不是他要看的函数; 他会把目标函数整段贴过来要求
  「在这里设置断点, 别瞎跳」, 所以**他贴哪几行就停哪几行**, 内联成
  `if os.environ.get("ZMAX_DEBUG_<TAG>") == "1": import debugpy; debugpy.breakpoint()` 直插函数体第一条语句,
  栈顶才是 `fuse_sensors (perception.py:47)` 这种"函数名 + 本行"。同时 `import os` 要真在该文件里(算法文件常只 import numpy)。
- **多级门控**: `ZMAX_DEBUG_<TAG>=1` 只停入口, `=2` 再停"真正下发(训练/执行)"那层; 用一个 env 值分档,
  比多开几条 launch 配置好维护, 也让他能自己要求"再往下钻一层"。改完把派发层与算法层一起 py_compile。
- 🔴 **只拷/只改节点文件会挂在兄弟模块上**: 包的 `__init__.py` 常 `from . import library`, 而 `library.py` import 同目录几十个 `*_impl` ⇒ 缺一个就报
  `ImportError: cannot import name 'X' from partially initialized module 'pkg.nodes' (most likely due to a circular import)` —— 看着像循环 import, 实为**缺文件**。
  先把整目录 `.py` 补齐(`rsync -a --include='*.py' --exclude='*' <源>/nodes/ <目标>/nodes/`), 再谈代码问题。
- **无 GUI 也能证明门控断点真停**: `printf 'c\n' | ZMAX_DEBUG_<TAG>=1 <venv>/python tools/debug_node_x.py`, 输出里出现 `> /path/file.py(NN)func()` 即已停在锚点(Pdb 报的行号常比 `breakpoint()` 那行大 1, 报行号按实际输出说)。

## 二、自证停住(唯一可信证据)
```bash
pgrep -f '<script 名>'                 # debugpy 起的是孙进程: adapter → launcher → <hash> script.py, 取最后一个
sudo py-spy dump --pid <pid>           # 期望: _do_wait_suspend (pydevd) → do_wait_suspend → <你的函数>
sudo py-spy dump --pid <pid> --locals  # locals 内容; numpy 显示成 <ndarray at 0x…>
```
- py-spy 跨 uid / ptrace 范围需要 sudo。
- 每次报"停在哪个文件第几行": 改代码后行号会变, 上一轮的行号不能复用。
- 无 GUI 兜底(先跑它确认门控真的生效): `ZMAX_DEBUG_<TAG>=1 python -m pdb driver.py` → `c` → `p x.shape`。

## 三、让向量"有物理含义"(最常被提的要求)
他看到的不该是"55 个数", 而是 `tcp_p` / `peg_xyz` / `hole_xyz` … 各自带单位。

```python
named = {seg.name: vec[seg.start - base:seg.stop - base] for seg in SEGMENTS}
x = np.concatenate([named[s.name] for s in SEGMENTS])   # 顺序只由段表决定
self.named, self.named_units = named, {s.name: s.unit for s in SEGMENTS}
```
- 段表(`SLICE` / `layout_table()`)是唯一口径, 调用点禁止自己数下标。
- 再给 `describe(x) -> [{name, unit, idx, value, meaning}]`: 调试控制台一句 `us.describe(x)` 出带单位的表, 比让他在 Locals 里逐项点开快得多。
- **零回归是硬门槛**: `np.array_equal(新x, 旧concat)` 多组随机输入全 True 才敢说"只是可读了"。少一个/错一位下标形状不变, 下游全部数字静默错。
- **dtype 保持原样**: float64 转 float32 会引入 ~1e-8 差, "与旧口径逐位相同"就不成立。
- 段名手打必错(`grip_scalar` 不是 `gripper_scalar`): 名字从段表取。

## 四、收尾怎么说
- 三句话给全: 停在哪个文件哪行 · Locals 展开哪个键看到什么 · 调试控制台敲哪几条命令。
- 他还要往下走就预告: F5 会依次再停在哪几处, 每处哪几段非零、为什么是 0(如"无示教几何 ⇒ peg/hole=0, 几何误差 e=0")。
- 提交前 `git grep -n 'breakpoint()'` 确认剩下的都是门控版本。

## 常见坑
- **断点停在派发层**(`library.py` / `nodes.py` 这类壳) ⇒ 他一句话就否: 「怎么还在这个文件, 应该是算法里」。
  挪进算法层入口(见第一节), 派发层只留注释; 改完**重起会话**, 暂停中的旧会话还指着旧代码。
- 🔴 **反复停在无关文件 = 编辑器里残留的旧断点, 不是你设的**: 实测每次 F5 先撞 `execution.py:168`、`atomic_skills.py:1609`,
  无论怎么继续都到不了目标行 —— 那几处源码里并没有门控 breakpoint, 是**存在窗口状态里的红点**。
  诊断 = py-spy 栈顶一直是别的函数; 清法 = `ctrl+shift+p` → 输 `Remove All Breakpoints` → Return,
  然后重新 F5/继续, 栈顶应立刻变成目标函数。清完要告诉他"你自己再点回来即可"(那是他的断点, 别默默删掉不吭声)。
- **「编辑器怎么又跳回 X.py 了」不一定是跑位**, 两种都正常: ①他在**调用栈面板点了上一层帧**(点回最上面那条即回到算法);
  ②入口函数 `return` 完成后调试器**必然**回到调用点。唯一判据是 `py-spy dump` 的**栈顶帧**: 栈顶仍是算法帧
  (`_do_wait_suspend → do_wait_suspend → <算法函数>`) 就说明没跑位, 直接把栈贴给他, 别顺着"是不是跳回去了"去改代码。
- **一次开太多 VSCode 窗口** ⇒ 他会要求「关掉没用的」。用 `wmctrl -ic <id>` 关多余的, 但**绝不关断点会话所在的那个窗口**(关窗=杀会话),
  并在回复里点明"哪个窗口是断点所在、为什么必须留"。
- **`xdotool key --window <id> F5` 在 Electron 窗口上不生效**: X SendEvent 被忽略/报 `BadWindow`, 键盘当没按过。
  用 `xdotool windowactivate --sync <id>` 然后 **`xdotool key --clearmodifiers F5`(不带 `--window`)**。
  窗口被关掉/重建后旧 id 全失效(报 `There are no windows in the stack` / `Invalid window`) ⇒ 每次操作前重读 `wmctrl -l` 取 id。
- **F5 之后马上 py-spy 会抓到 import 阶段**(`torchgen/model.py`、`email/feedparser.py` 之类) —— 那不是"没停", 是还没跑到锚点。
  轮询找 debuggee 再 dump: `for i in $(seq 1 24); do D=$(pgrep -P $(pgrep -f 'launcher .*<prog>' | head -1) | head -1); [ -n "$D" ] && break; sleep 3; done`。
  `Failed to get process executable name / No such file or directory` = 这个 pid 已失效(会话已结束或拿到旧 pid), **重找 pid**, 别当成"py-spy 坏了"。
- **重起会话前先杀干净**: `pkill -f 'launcher.*<prog>'`; 暂停中的旧会话不杀, 新一次 F5 会和它抢窗口/端口, 观察到的饼也是旧的。
- **裸 F5 选错配置** ⇒ 起的是别的程序, 用户以为断点没生效。`ps -eo cmd | grep debugpy/launcher` 看它到底跑了哪个 `.py`, 别靠猜。
- **改了 `.code-workspace` 的 `launch` 就以为 F5 会用** ⇒ 老窗口仍会起动它记住的那条(folder 级 `launch.json` 的选中项)。要确定性就用上面那条"单配置临时窗口"。
- **用内置 `breakpoint()`** ⇒ 停在终端 Pdb, 编辑器没变成 Paused, 用户说"没停"。换 `debugpy.breakpoint()`。
- **只有 `.vscode/launch.json` 而用户开的是 workspace 文件** ⇒ 选择器里找不到配置, F5 静默用了别的。
- **断点在不执行的分支上**(某个输入下根本走不到) ⇒ 现象是"跑完没停"; 先确认该行在本轮输入下会执行, 或挪到公共出口。
- **靠编辑器行断点** ⇒ 格式化/加注释就漂; 用门控 `breakpoint()`, 行号变了也还在。
- **只说"已停住"没有帧栈证据** ⇒ 用户按 F5 发现程序早结束了。
