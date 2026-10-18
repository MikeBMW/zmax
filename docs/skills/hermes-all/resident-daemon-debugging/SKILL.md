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

## 坑

- **keepalive/看门狗每 N 分钟拉起服务**: 分离 dry 实例在跑时它可能认为"服务已在"从而不拉起线上实例 ⇒
  调试期间线上执行是停的；要恢复就 kill 调试实例，等看门狗拉起。
- 服务启动时会 unlink + 重建自己的输入 FIFO ⇒ 第二个实例会抢走路径，先起的实例读的是**已删除的 inode**
  （看起来活着，收不到命令）。
- 断点停在"等下游回执"的循环里最危险（下游可能已经动了）。要么 dry，要么把断点放在**下发之前**。
- 离线台要读**真实状态文件**（不是内存缓存），否则算出来的目标与线上不一致。
- 用户在 VSCode 里按 F5 调试 GUI 时，断点下在执行器文件上是必然不命中的 —— 先解释进程归属，
  再给配好的 launch 配置，别先让用户去"重启试试"。
