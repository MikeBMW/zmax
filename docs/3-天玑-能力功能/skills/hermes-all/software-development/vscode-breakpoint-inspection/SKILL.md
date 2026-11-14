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
1. **交付物是"已停住的会话"**, 但**绝不抢他的光标/终端**(老倪逐字: 「以后不许抢夺我的光标控制权」):
   - 不许在他正编辑/调试时用 `windowactivate`/`xdotool key` 抢焦点 —— 他的光标会跳走、缓冲区被搅乱;
   - 不许在**他的终端里前台跑工程入口**: 常驻入口多有单实例 flock, 你跑一次就把他下一次 F5 挡成 `exit 2`, 他的终端还被你的输出淹没;
   - 起会话用独立窗口(见第一节), 或者**让他按 F5、我只做只读取证**(py-spy / 日志 / HTTP / 文件回读)。
   他要的"停住"是**他屏幕上那个会话停在锚点**, 不是你在自己 shell 里 pdb 停一下表演给他看 —— 后者他会直接问「vscode 显示啊?」。
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
   🔴 **`debugpy.breakpoint()` 在没有客户端连接时是 no-op**: 它只打一条提示就继续, 于是"自停锚"在非调试进程里静默不停,
   用户看到的是「怎么还不停住」。两条路径都要真停必须显式判连接再回退:
   ```python
   _stopped = False
   try:
       import debugpy
       if getattr(debugpy, "is_client_connected", lambda: False)():
           debugpy.breakpoint(); _stopped = True
   except Exception:
       pass
   if not _stopped:
       import pdb; pdb.set_trace()        # 裸跑 / 无调试器时停在终端
   ```
3. **先让变量有名有单位, 再让他看** —— 见第三节。
4. **自证停住**: py-spy 抓到 `_do_wait_suspend (pydevd)` + 你的函数帧, 才算停住。进程状态 `S` 分不出"停住"和"在跑"。
5. 不许把 `patch` 当探针: 写进去的 `"X"`、删掉的一行就是真代码。改完用 `py_compile` + AST 裸 name 扫描 + 真跑验。

## 一、配置与启动
- 单文件夹窗口读 `.vscode/launch.json`; 用户若开的是 `.code-workspace`, **同一份配置还要写进该文件顶层 `"launch": {"configurations": [...]}`**, 否则选择器里根本没有它。两份都要 JSON 校验。
- 🔴 **改 launch 里的 env 要定位到“那一条配置块”, 不能用全局字符串替换**: 多条配置都有 `"ZMAX_SINGLE_THREAD": "1"`
  这类的共用键, 按“第一次出现”插新键会插进**另一条配置**(实测把 `ZMAX_LLM_OFF` 误加到了前端 GUI 那条),
  看着改成功、跑的却是另一条。定式: 用**只在该块出现的锚**(如 `"ZMAX_ORCH": "1",`、`"program": "…/start.py"`),
  改完把每条配置的 `name + 关键 env` 逐个打印出来核(JSON `json.load` 后遍历), 而不是 `grep -c` 数量。
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
- 🔴 **配置名按角色取, 不许叫"断点"**: 老倪原话「这是前端GUI, 不是断点」。
前端 = `🖥 前端 GUI · 控制台可视化 (studio.py)`, 后端 = `🧠 后端工程 · 调度状态机 (start.py)`;
只有真·临时定点观察的配置才配 `🧪 断点 · …`。改名要同步**三处**, 否则名又变回去:
`.vscode/launch.json` + `.code-workspace` 的 `launch` 段 + GUI 模板 `simulink_module.py::_vscode_launch_cfg`。
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
🔴 **launch.json 会被工程自己的 GUI/工具重写**: 交付前若配置"莫名少了一条", 先比对备份而不是怀疑自己没写:
```bash
md5sum .vscode/launch.json .vscode/launch*.json*    # 与某个 backup 完全一致 ⇒ 被整体回灌了
./<venv>/bin/python -c "import json;print([c['name'] for c in json.load(open('.vscode/launch.json'))['configurations']])"
```
典型来源是 GUI 右键"打开 VSCode"按**内置模板**重写(本项目 `tools/gui/simulink_module.py::_vscode_launch_cfg`);
只手改 launch.json 会被下一次点击抹掉 ⇒ 要让配置长期存在, 必须同时改模板生成器, 并在回复里点明这条红线。
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

## 一·五、"每个周期都要进入"的断点锚(热循环 / 调度器)

他要「在这里加一个断点, 每个周期都能进」时, **不要让他自己去点 F9** —— 在代码里放锚 + 开关:

- **锚行 = 函数体第一条可执行语句, 不是收口 `return`**。带否决/异常早退的函数里, 收口 return 不是每拍都到。
  实测 `ActionModulator.decide`: 正常周期执行 89 行并命中收口行 1 次; 残差否决周期只执行 8 行就在 `return _zero` 早退,
  收口行命中 **0** 次。顺带加一个真有用的计数(`self.n_cycle += 1`)并写进快照 —— 断住时能在监视窗口看"第几周期",
  而不是加一行纯装饰的 `pass`(那种改动经不起"这行有什么意义"的追问)。
- **开关用 env + 文件双触发**: env 便于 launch 里固定, 文件(`/tmp/zmax_stop_at_<tag>`)便于当场开/关不重启。
  跑长流程前**先删触发器文件**, 否则每拍都停, 现场看起来就是"卡死"。
- **用 `sys.settrace` 自证锚行真的会执行**(比读代码可靠, 也顺手能证明"收口 return 会不会被跳到"):
  ```python
  hits = {}
  def tr(f, ev, a):
      if ev == 'line' and f.f_code.co_filename == TARGET:
          hits[f.f_lineno] = hits.get(f.f_lineno, 0) + 1
      return tr
  sys.settrace(tr); obj.method(...); sys.settrace(None); print(hits)
  ```
  注意 trace 开始前函数入口行已执行 ⇒ 入口行计数为 0 是正常的, 结论按"入口之后的行"判。
- 🔴 **进程不会热加载改过的代码**。「加了断点怎么还不停」先分四种病因, 不要让他反复按 F5 试:
  ① 他的调试会话在你改文件**之前**就起了(必须重起会话); ② 没有触发器/门控变量; ③ 上一轮"证明了会停"是在**你的终端**用 pdb, 他的 VSCode 根本看不到;
  ④ **他打开的那份文件不是被加载的那份**(同函数在仓库里有多份副本);
  ⑤ **真正在 tick 的不是他那个调试进程**(见下一条, 最常见也最像"灵异");
  ⑥ **目标函数一次都没被调用** —— 上游节点在调用它之前就"缺输入直通"返回了。实测 `sssched` 日志刷了 1520 条
     `缺前馈 (in6/in9 都没有数值) ⇒ 直通, 调制器未生效`, 而 `ssff` 明明打出 `u_ff=[-0.364,-0.022,-0.079,0]`;
     根因是端口载荷**本身就是业务字典**(`{"kind":"u_ff","u_ff":[...]}`), 而读端口的地方写的是
     `v = pv.get("value") if isinstance(pv, dict) else pv` —— 没有 `value` 键就得到 `None`, 后面的字段扫描整段跳过。
     修法 `pv.get("value", pv)`。诊断动作固定两步: ①`grep -c '<直通/未生效/未调用 的字样>' <引擎日志>`;
     ②真调一次该节点 `run(ctx)` 看返回是 `kind=<正常>` 还是 `*_skipped` —— 少走这两步会一直怀疑 VSCode。
  ⑦ **单线程档把"后台线程"改成当场内联 ⇒ 主线程卡在网络调用, 目标函数永远轮不到**。
     单线程调试档里异步辅助函数通常走 `spawn_or_inline()` 的 inline 分支(`thread_policy.py`),
     于是 VLM/LLM/HTTP 节点的"后台不阻塞"变成**同步阻塞**: 一次请求按 `SS_VLM_TIMEOUT` 默认 60s 等,
     整拍卡在 `urlopen → connect`, 下游 `decide()` 一拍都执行不到 ⇒ 那条链上任何断点都不进,
     而且 env、行号、进程归属全是对的 —— 只有栈能看出来。
     判据(唯一可信): `sudo py-spy dump --pid <debuggee>` 主线程栈里出现
     `create_connection/urlopen → <api>.py → spawn_or_inline → node_xxx → project.step → main`,
     说明 tick 没走完, 不是断点问题。
     修法: 给该节点加短路闸 `if os.environ.get("ZMAX_LLM_OFF") == "1": return True`(打一行"已短路"),
     并在**调试配置**里同时设 `ZMAX_LLM_OFF=1` + 把远端超时压到 8s 级; 生产/多线程档不设这两个 env。
  ⑧ **还有第二个进程在写同一批状态文件** ⇒ 你看到的是别人的输出。`zmax_data/ss_live/*.json` 与
     `skill_calls.log` 里常带 `pid` 字段: 它不等于调试进程 pid 就说明另有一个常驻引擎
     (如 `zmax-ss-engine-loop.service`) 在写。先 `systemctl stop` 那个 unit 再取样, 否则
     `n_cycle`/`state` 永远停在别人的值上, 你会误判"断点没进"。
  如实说清是哪一条, 并给出下一步(重起 / 删触发器 / 由他按 F5)。
- 🔴 **断点"永远不进"先查: 是不是另一个进程在替你跑同一个循环?** 常驻工程常被 GUI 看门狗/服务管理器托管 ——
  他的 F5 会话只是个空壳, 10Hz 循环跑在**别的 pid** 里(实测 `ss_canvas_loop.py` PPID=1, kill 掉 12s 内自动重生一个新的)。
  断点绑的是调试会话里的模块, 计算在另一个进程 ⇒ 一行都不会停。取证与修法:
  ```bash
  pgrep -af '<引擎入口>'            # 有 PPID=1 的独立实例 = 就是它在 tick
  kill -TERM <pid>; sleep 12; pgrep -af '<引擎入口>'   # 又活了 ⇒ 有看门狗在托管
  ```
  根治 = **两个入口共用同一把 flock**, 但**只有入口(start.py)持锁, 从属引擎只探测不持锁** ——
  反过来让引擎持锁会死在另一个坑里: 看门狗拉起的引擎抢先把 pid 写进锁, 用户按 F5 的入口被自己的引擎挡成
  `⛔ 已有工程入口在运行` (实测 14:47 起每一轮都这样), 他只会看到「怎么自己断了」。
  ```python
  # 引擎 main(): 只探测"入口是否已接管", 拿到锁立刻 LOCK_UN 放掉; 探测失败 ⇒ 本引擎让位
  def _entry_running():
      try:
          fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
          fcntl.flock(fh.fileno(), fcntl.LOCK_UN)      # 探测完立刻放, 绝不常驻持有
          return False
      except OSError:
          return True
  ```
  - ⚠️ fcntl 模块别挂在文件对象上 (`_io.TextIOWrapper` 不许自定义属性 ⇒ 每拍抛异常被外层 except 吞掉,
    表现就是"让位闸装了却从不让位"); 用独立变量存。
  - ⚠️ **只写在主循环里会迟一整拍**: 画布载入/慢节点一拍可 8~30s, 那期间两个引擎同时在写状态。
    用 daemon 线程 0.5s 一拍查, 命中即 `os._exit(0)`; 主循环里那处保留也无害。
  - ⚠️ **判"锁在谁手里"不要用 `fuser`**: 它列的是"打开该文件的进程", 探测式引擎每拍都会打开它 ⇒
    你会对着一个不持锁的 pid 说"锁被它占了"。判据只有一条: 自己 `flock(LOCK_EX|LOCK_NB)` 试一次。
  顺序必须是**他先 F5 拿到锁 → 你再 kill 老引擎**; 反过来 kill 完看门狗立刻重生一个, 而锁还空着 ⇒ 又变成它在跑。
  ⚠️ `if __name__ == "__main__": main()` 会丢弃返回值 ⇒ 闸拒绝时退出码仍是 0、看不出被挡; 写成 `sys.exit(main())`
  (或 `_rc = main(); if _rc: sys.exit(_rc)`)让退出码可见, 否则你自己验闸时会误判"没生效"。
- 🔴 **先查"同一个函数有几份副本", 再谈断点没进**: 老工程里 `policies/.../cognition.py` 常有 3 份
  (`src/` 最新 / `zmax_data/staging_<repo>/src/` 与 `external/<fork>/src/` 是旧快照), 画布节点 json 又常常
  **没有 `file` 字段**(实体只有 `{id, name, type}`), 加载器按节点 id 解析实现 ⇒ 编辑器里断点绑的副本可能根本不在执行链上。
  ```bash
  find . -name '<module>.py' -not -path './.git/*' -exec md5sum {} \; | sort      # 几份/各是什么时间
  grep -n "<id>" <工程 json>                                                       # 节点有没有 file 字段
  ```
  判据: 只有 `src/` 下那份是活的; `zmax_data/staging_*`、`external/*` 一律视为历史快照, 别在那里下断点。
- **别靠猜节点绑到哪个文件, 跑现成的断点审计**: `tools/node_breakpoint_audit.py` / `tools/canvas_node_audit.py`
  会产出 `zmax_data/deliverables/*/reports_archive/node_breakpoints.json`, 每行带 `open_file`(编辑器打开的那份)、
  `real_file`/`real_line`(真正执行的)、`open_bindable`、`verdict` —— 直接告诉他"断点该下在哪个文件第几行"。
  `tools/dap_probe_breakpoint.py` 只在 `debugpy --listen 127.0.0.1:5678` 的会话上可用(**端口写死**);
  他是从 VSCode F5 起的会话, DAP 端口是私有的 ⇒ 那条路只能由他按 F5 验, 你改用审计 json + `sys.settrace` 取证。

## 一·六、验收口径: 只认"链路末端在动", 不认"配置生效"

改完配置/代码说"可以了"之前, 必须拿到**目标链路执行过的计数证据**, 否则下一次就是他一句
「你不是说可以了么?」。配置生效(`env` 进了进程、`enforce()` 打出 `torch=1`)只证明前半段。
- 硬指标: 计数快照两次采样递增(`n_cycle` / 调用计数 / 该函数写入的 json mtime 前移)。
  报"还在 0"比报"已生效"强, 他至少知道下一步该查哪。
- env 到没到进程要直接读 `/proc/<pid>/environ`(不是读 launch 文件推断):
  `tr '\0' '\n' < /proc/<pid>/environ | grep -E 'ZMAX_SINGLE_THREAD|ZMAX_LLM_OFF'`。
- 插入锚点/改代码后**行号整体偏移**: 报行号前重新 `grep -n '<目标语句>' <file>`, 不许复用上一轮行号
  (实测同一句 `return u, f"阶段 {st}{tag}"` 在插入 14 行锚点后从 573 变成 587, 他按 573 点红点自然不进)。

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
