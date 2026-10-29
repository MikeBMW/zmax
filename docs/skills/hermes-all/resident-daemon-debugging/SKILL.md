---
name: resident-daemon-debugging
description: "Use when 调试常驻 FIFO/daemon 服务, 断点不命中或进程不能停。"
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [debugging, daemon, fifo, vscode, debugpy, zmax]
    related_skills: [real-arm-motion-control, live-service-change-discipline, systematic-debugging]
---

# 调试常驻服务 / FIFO 执行器

## 触发
- 在常驻进程（FIFO 消费者、看门狗、推流服务、信号库守护）里下的断点**不停**。
- 用户问「我怎么 debug X.py，断点放哪里」。
- 需要看执行分支/中间量，但**不能停进程**（在跑生产动作）。

## 铁律

1. **断点只绑定到"加载了同一文件的那个调试进程"**。按 F5 起的往往只是 GUI/主程序，常驻服务是另一个
   plain-python 进程 ⇒ 断点永远不命中。判断方式:

   ```bash
   for p in /proc/[0-9]*; do cmd=$(tr '\0' ' ' < $p/cmdline 2>/dev/null);
     case "$cmd" in *<文件>.py*) echo "${p#/proc/} $(ps -o lstart= -p ${p#/proc/})"; echo "  ${cmd:0:160}";; esac; done
   ss -ltnp | grep -E '5678|5679'      # 无监听 = 没有调试会话
   ```

   命令行含 `debugpy/launcher … -- <file>` 才是被调试的进程。

2. **在常驻进程上停下 = 冻住它**，而下游（机械臂、推流、队列）按上一条指令继续。要下断点只允许两种场合:
   离线台（不读生产输入、不下发）或强制 dry 的分离实例。

3. **分离实例必须分开三样东西**: 输入通道、单实例锁、输出日志。只换输入不换锁 ⇒ 新实例会按
   "新实例赢"的锁策略把线上实例 SIGTERM 掉（这是防多实例抢 FIFO 的设计，不是 bug）。

4. **改完代码必须重启服务，断点才有意义**（运行中的进程是旧代码，行号与逻辑都可能对不上）。

5. **生产实例上只取证，不下断点**: `tail` 日志（含原始日志尾）、服务自己的回执接口、
   `py-spy dump --pid <pid>`（不暂停进程）。

## 断点不命中的完整分诊链（按顺序跑，每步都能独立证伪）

“断点不进”有四层原因，**先证进程，再证代码，最后才改配置**。跳过前两层去改 launch/env，会陷入
“改配置 → 让用户重启 → 还是不进”的死循环（本项目连改五轮 launch/env/加载方式都没解决，真因是第一层）。

### ① 代码跑在哪个进程（最常见）
GUI 显示“未运行 / 没点 ▶ 运行”，而 `ss_live/engine_latest.json` 的 mtime 每 0.1s 在刷 —— 刷新者是
**systemd 常驻服务**，不是用户 F5 起的 GUI。断点打在 GUI 进程里 ⇒ 永不可能命中。

```bash
systemctl is-active <loop 服务名>
python -c "import os,time;print(round(time.time()-os.path.getmtime('zmax_data/ss_live/engine_latest.json'),2))"
tail -3 zmax_data/ss_live/actuator_calls.log     # 节点入口写的「时间 + pid」
```

正向取证: 在节点入口加一行**每次调用 append 时间+pid** 的日志（本仓 `zmax_data/ss_live/actuator_calls.log`）。
判读要带一条限制: 这种埋点只覆盖**走那个入口**的路径。引擎里常见的直连调用
（如 `u_vec = self.execr.execute(u_sat)`）根本不经过节点实现文件 ⇒ **日志为空不等于 execute 没被调**，
只能证明“那个入口没走”。要证“函数真被调过”，用 py-spy 棨或在该函数自己里埋点。

要它跑: 先停常驻服务，再在界面点 ▶ 运行/右键运行节点。不想每次靠人记得点，就在调试模式下
**启动自动跑一次业务代码**（本仓 `ZMAX_DEBUG_MODE=1` 时 GUI 建完窗口后调一次仿真启动函数，
`ZMAX_AUTO_RUN=0` 可关）—— 这是把“断点不进”真正关掉的那一步，只改配置永远到不了。
窗口往往是**异步建好**的，所以用 QTimer 每秒轮询 `app.allWidgets()` 找带目标方法的实例（上限约 60 次），
一次性 `singleShot` 会在窗口存在前就执行并落空。
验收口径: 自动跑后日志里出现 `[brk:<tag>] 到达` 或 py-spy 栈里出现该函数。
调试完把常驻服务 start 回来（`sudo systemctl start <loop 服务名>`），别让生产循环一直停着。

### ② 这个进程此刻在干什么
```bash
sudo py-spy dump --pid <pid>
```
MainThread 栈只有 `paintEvent → _sphere` 这类绘制代码、没有任何 `run/execute/step` ⇒ 进程里没有节点在执行
（同时它 `active+gil` 还在持续算，界面反而显得“有数据在动”，最具误导性）。栈里出现 `pydevd_*` 线程是调试器
自己的，不要误判。

### ③ 断点本身（三个机械陷阱，都与“断点有没有坏”无关）
- **行号漂移**: 反复编辑同一文件会把函数整体后移几十行，用户留在旧行号上的断点落在注释/空行 ⇒
  解释器**根本不会设置它**（pdb 只回 `*** Blank or comment`），界面红点还在、跑起来永不停。
  交付时必须报**当前** `def` 行与第一条可执行语句行，并明说“旧断点已失效”。
- **launch.json 被 GUI 自己整份重写**: 手改 `.vscode/launch.json` 加 env，用户下一次右键「打开源码」就被
  模板函数覆盖回默认（本仓模板在 `simulink_module._vscode_launch_cfg`）。要加 env 只能**改模板再让模板重生成**；
  判据是起进程后读 `/proc/<pid>/environ` 与 `cmdline`，不是看 json 里写了什么。
- **frozen modules**: debugpy 自报 `frozen modules … may make the debugger miss breakpoints`。Python 3.11 起
  必须在 launch 配置里给 `pythonArgs: ["-X","frozen_modules=off"]`（`args` 是给程序的，不生效）+
  env `PYDEVD_DISABLE_FILE_VALIDATION=1`。
- **加载器没注册 `sys.modules`**: pydevd 按**模块名**在 `sys.modules` 里定位文件。用
  `spec_from_file_location` + `module_from_spec` + `exec_module` 但漏了 `sys.modules[name] = m`，
  该文件里**所有断点静默失效**（函数照跑、不报错、界面红点还在）。同一仓库常有的模块注册了、有的漏了 ——
  逐个核，别假设“同一个 repo 的加载方式都一样”。自查:
  `python -c "import sys;sys.path.insert(0,'src');<触发一次节点>;print('<模块名>' in sys.modules)"`。
- **`exec(compile())` 造的模块**: `__spec__`/`__loader__` 都是 None。首次加载能按 `co_filename` 绑上，
  一旦**取消再添加**断点，pydevd 没有 loader 可重新定位 ⇒ 静默不绑。要能反复绑就必须 spec 加载。
- **debugpy 没编译 frame eval**: `find <debugpy>/_vendored/pydevd/_pydevd_frame_eval -name "*.so"` 为空
  ⇒ `PYDEVD_USE_FRAME_EVAL=NO` ⇒ **不能对已加载模块在运行时加/删断点**，只在 compile 那一刻注入。
  对策: 每次运行前清模块缓存（`library._SS_MODS` 与 `sys.modules` 里的 `state_space.*`/`ss_real.*`）
  强制重编译，新断点在编译时被注入；代价几十 ms。两个入口都要清: ▶运行 与 右键运行节点。

### ④ 验证“能不能停”只有两条硬口径
```bash
python -m pdb -c "b /abs/path/file.py:LINE" -c c -c "p 变量" tools/<跑一次节点的脚本>.py
```
- 路径必须**绝对**（相对路径匹配不上 `co_filename`），行号必须落在可执行语句。
- 动态 `exec(compile(src, path, "exec"))` 加载的模块 **pdb 能停、debugpy 的 UI 断点未必** —— 两者要分开证，
  别拿 pdb 停住了就宣布 VSCode 也能停。

兜底断点用**文件开关**而不是 env: `touch <仓库>/zmax_data/ss_live/BREAK` ⇒ 代码里 `os.path.exists()` 无条件
`breakpoint()`。它不依赖 env、不依赖 `debugpy.is_client_connected()`，是唯一能区分“代码没到”与“调试器没接管”的开关。
三个必做:
- **路径层级按该文件实际深度数，不要套别的文件**: `nodes/x.py` 上溯 5 层到仓库根，但
  `policies/left_right/state_space/x.py` 要 **6** 层。套错一层就指到 `src/` 下不存在的目录 ⇒ 开关和记账
  文件全部静默失效。算完立刻打印真实路径核对一次。
- **用完立刻删**: 常驻服务里的同一节点也会被停住，整条循环卡死。
- **写据点的兜底分支不许 `except: pass`**: 路径算错 + 静默吞异常 = 表现成“代码没执行”，排查代价极高。
  至少落一行日志，或让路径算错本身可见。

**默认值必须是“只记录不停”**: GUI 主线程一 `breakpoint()`，Qt 事件循环停转 —— 界面冻结、鼠标点不动，
连新断点都点不了（py-spy 栈顶会显示 `_do_wait_suspend (pydevd.py)`）。代码内置断点只作**显式**通道
（文件开关 / `ZMAX_DEBUG_BREAK`），默认只打印“到达”一行。去重也不能用“一辈子只停一次”的集合 ——
那样第一次停完就永不再停（现场表现为“启动能进、再运行不进”）；要按**运行轮次/时间窗**去重。
要看变量用终端 pdb 通道，GUI 不受影响。

### 交付口径
每次说“改好了”都附**一条可复现命令 + 它的真实输出**。没跑 pdb、没看 py-spy 栈就说“还没验证”，
不说“应该能停”。一个未验证的“已修复”被否一次，用户之后会要求把每个结论重新证明一遍。

命令清单与判据见 `references/breakpoint-not-hitting.md`。

## 三步配方

### ① 离线台（零风险，日常首选）

给服务写一个只调"计算层"的入口: import 模块 → 直接调纯函数（算目标/算分段/算路由），
不打开输入管道、不写下游。断点随便下，改参数重跑秒级。

示例（Z-MAX 执行器）:

```bash
./gui-venv311/bin/python tools/l2_debug_offline.py L2.forward --d_mm 10
./gui-venv311/bin/python tools/l2_debug_offline.py L2.goto_space1 --speed 32 --manual
```

配套写法: 用 `importlib.util.spec_from_file_location` 加载服务模块（确认 import 无副作用: 线程只在
`main()` 里起），从真值文件读当前状态，逐阶段调 `plan_stage()` 打印目标/Δ/call。

### ② 分离 dry 实例（全链路）

服务要提供 env 开关，默认行为不变:

| env | 作用 | 不设的后果 |
|---|---|---|
| `<SVC>_INPUT`（如 `ZMAX_L2_FIFO`） | 换输入管道 | 与线上实例抢同一条管道，命令被分食 |
| `<SVC>_LOCK`（如 `ZMAX_L2_LOCK`） | 换单实例锁 | 新实例接管并 **SIGTERM** 线上实例 |
| `<SVC>_DEBUG_DRY=1`（如 `ZMAX_L2_DEBUG_DRY`） | 收到的任何指令强制 dry | 断点停在动作中，下游继续执行 |

```bash
ZMAX_L2_FIFO=/tmp/l2_dbg.fifo ZMAX_L2_LOCK=/tmp/l2_dbg.lock ZMAX_L2_DEBUG_DRY=1 \
  ./gui-venv311/bin/python -m debugpy --listen 5678 --wait-for-client tools/l2_daemon.py
echo '{"skill":"L2.forward","d_mm":10,"speed":32}' > /tmp/l2_dbg.fifo
```

VSCode `launch.json` 里把这三项写进 `env`，`"justMyCode": false`，`program` 用**绝对**
`${workspaceFolder}/...`（路径不一致断点也不绑）。

### ③ 生产实例: 只读取证

```bash
tail -f <服务日志>
curl -s 'http://127.0.0.1:<port>/<回执端点>'      # 服务自己的原始回执
py-spy dump --pid <pid>                            # 卡住时看栈，不暂停
```

## 断点该下在哪: 先认分支

常驻服务通常按「任务形态」分流，不同按钮走不同函数 —— 断错函数就会以为"命令没到"。以 Z-MAX
执行器为例:

```
steps 非空      → run_stages() → plan_stage()      (空间点/号位/安全点 等多段技能)
ros=pose_rot    → run_rot_chunks()                 (A/B/C 绕工具轴)
ros=j6_rot      → run_j6_rot()                     (J6 自转)
其它(相对/单步)  → build_move()                     (方向键 前进/后退/左右/升降)
```

断点条件用**变量**不用行号: `spec.get("skill")=="L2.forward"`、`i==1`。

取证顺序: ①入口解析 ②`dispatch()` ③算目标（`build_move`/`plan_stage`）④闸门 ⑤最终下发（`_send_via_sdk`
→ `_T.exec_call`）⑥等到位（`wait_arrive`）。

## 🚫 指令被拒 `FIFO 打不开([Errno 6] No such device or address)` = 两个根因, 别只查一个

`Errno 6 / ENXIO` 在 FIFO 写端(`os.open(path, O_WRONLY|O_NONBLOCK)`)只有一个含义: **此刻没有读端**。
FIFO 文件存在、权限对、mtime 正常 —— 全都不代表有人读。实测两处(2026-10-20 老倪「操作机器人的指令被拒」):

1. **守护进程根本没在跑**(最常见)。`ls -l zmax_data/l2_cmd.fifo` 是 09:00 留下的空文件, 照样好看。
   判活别用 `pgrep -f <名字>`(会匹配到自己这条命令, 甚至把自己 kill 掉), 扫 cmdline:
   `for p in /proc/[0-9]*; do c=$( { tr '\0' ' ' < $p/cmdline; } 2>/dev/null ) || continue; case "$c" in *python*[l]2_daemon.py*) echo ${p#/proc/};; esac; done`
2. **在跑也照样被拒**: 主循环写成 `while True: with open(FIFO) as f: for line in f:` = **开-读-关**循环。
   关闭那一瞬到下次打开之间没有读端 ⇒ 恰好此刻点的指令 ENXIO; 更致命的是 **指令执行期间整条 FIFO 是关的**
   (一路 20s 的动作走完才回到 open) ⇒ 动作进行中点的每一条全被拒, 而现场表现是「点了没反应」。

**修法(服务自己持常驻读端)**: 启动时 `_fd = os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)`(O_RDWR 让它自己也是写端
⇒ 别的写端永不 ENXIO), 主循环用 `select.select([_fd], [], [], 0.5)` 等数据, `os.read(_fd, 65536)` 取块,
按 `\n` 切行、**尾段不完整就留到下一轮**(`_buf`)。保留原有逐行处理体: 把 `with open(FIFO) as f:` 换成
`with io.StringIO("\n".join(lines)) as f:` 即可**不用重排缩进**(逐行体里的 `continue` 语义不变)。

**自证顺序**(不动机器人): ①`ls -l /proc/<pid>/fd | grep fifo` 看到那条 FIFO ⇒ 读端锚在;
②投一条**未知技能**探针 `printf '{"skill":"__pipe_probe__"}\n' > fifo` ⇒ 日志出现「拒绝: 未知技能」
且进程存活 ⇒ 管道通且没有下发运动。只在需要验运动时才用真技能。

常驻件都要有 `start|stop|restart|status` 的 ctl 脚本, 且 **status 必须直接报「FIFO reader 有没有」**——
「进程在」不等于「能收命令」, 这两件事在这套系统里已经各自出过一次事故。

## 坑

- **FIFO 没人读, 先查"保活是不是被人关了"**: `crontab -l | grep -i keepalive` 可能看到
  `# [关机暂停 <日期>] */5 * * * * …` —— 关机前手工注释掉、开机后**没人恢复**, 于是执行器从此没人拉起,
  现场表现就是「点了没反应 / 被拒: FIFO 打不开(Errno 6)」。修: 按原样取消注释 `crontab /tmp/ct_after.txt`, 再
  用手册脚本(cron 里那个 keepalive, **不是**简单 start)拉起 —— keepalive 会带上 `ZMAX_VL_INTENT_WAIT_S=600`
  这类裁决等待环境变量, 少了它们慢层重试轮次必然超时 ⇒ 落"未给裁决⇒从严不安全" ⇒ 所有动作被拒。
  起完三个判据一起看: ①`/proc/<pid>/fd` 挂着 FIFO ②`tr '\0' '\n' < /proc/<pid>/environ | grep ZMAX_VL` 有 600Σ
  ③投 `{"skill":"__pipe_probe__"}` ⇒ 日志「拒绝: 未知技能」且进程存活。

- **重启计数一路涨 + 日志只有一句「已有写入器在跑」= pid 文件陈旧 + pid 被系统复用**, 不是"真有实例在跑"。
  单实例锁只判 `os.kill(pid, 0)` 存活是不够的: 进程崩掉后那个 pid 会被内核回收、分给**别的**活进程,
  于是每次启动都判"已有实例"→ 直接退出。实测症状 = `systemctl show -p NRestarts` 六百多次、
  服务 `active` 但产物文件几小时不更新, 而 `journalctl -u` 里**没有 traceback**(只有 `status=1`)。
  诊断: `cat <pid文件>` → `ps -p <pid>` 看不见但 `os.kill(pid,0)` 不抛 ⇒ 读 `/proc/<pid>/cmdline`
  看它其实是谁(实测是另一个常驻件 pull 到了同一个号)。
  修法: 存活检查 + **cmdline 校验**双条件 —— `"<自己的模块名>" not in /proc/<pid>/cmdline` 就当陈旧锁接管并打日志。
  只判存活必然复发。
- **`journalctl -u` 只有 `Main process exited, code=exited, status=1` 时, 真错误在别处**: 看 unit 的
  `StandardOutput/StandardError` 指向的日志文件(如 `/var/log/<svc>.log`), 或前台手动跑一次同一 ExecStart 命令
  —— 锁/路径/依赖类退出在这两条里才有原话。
- **keepalive/看门狗每 N 分钟拉起服务**: 分离 dry 实例在跑时它可能认为"服务已在"从而不拉起线上实例 ⇒
  调试期间线上执行是停的；要恢复就 kill 调试实例，等看门狗拉起。
- 服务启动时会 unlink + 重建自己的输入 FIFO ⇒ 第二个实例会抢走路径，先起的实例读的是**已删除的 inode**
  （看起来活着，收不到命令）。
- 断点停在"等下游回执"的循环里最危险（下游可能已经动了）。要么 dry，要么把断点放在**下发之前**。
- 离线台要读**真实状态文件**（不是内存缓存），否则算出来的目标与线上不一致。
- 用户在 VSCode 里按 F5 调试 GUI 时，断点下在执行器文件上是必然不命中的 —— 先解释进程归属，
  再给配好的 launch 配置，别先让用户去"重启试试"。
- **别只用“日志/端口正常”证明节点在跑**: 界面数据可能来自另一个进程写的文件。要证“我要调的那段代码在这个
  pid 里执行过”，只有两种证据: 该 pid 打出的调用日志，或 py-spy 栈里出现那个函数。
- **“用户说都重启了好几次”= 停止让他重试**: 改成自己去取证（`/proc/<pid>/environ` · `py-spy dump` ·
  `wmctrl -l` + 截图 OCR · 写 pid 到调用日志）。让用户反复重启而不给出新证据，是在消耗信任。
