# 常驻守护调试手册（离线台 + dry 实例 + 断点表）

适用：改一个常驻 FIFO/队列守护（执行器、采集、发布循环）之前，想单步看"它算出了什么、在哪一层被拦"；
或现场报"点了没反应"要先定根因。

## 1. 先画出进程结构（决定断点能放哪）

典型守护都是同一个形状，先把行号钉在结构上再下断点：

```
main()
 └─ while True: reload(配置/注册表)
     └─ with open(FIFO) as f: for line in f:      ← 阻塞等命令
         ├─ spec = json.loads(line)               ★A 看命令原文
         ├─ 调试开关 ⇒ spec["dry"]=True
         └─ dispatch(reg, spec, chan)             ★B 分支入口
              ├─ build_target()   单步: 目标/位移          ★C
              ├─ plan_stage()     多阶段: 单段目标/Δ/守卫   ★D
              ├─ run_stages()     逐段: 计划→闸→下发→等到位
              │    ├─ 上限/天花板闸                      ★E
              │    ├─ dry 分支 (打印后 return)
              │    └─ send() → transport.exec_call(...)  ★F 最终载荷
              ├─ auth_guard()   授权/epoch 闸            ★G
              └─ wait_arrive()  真值等到位                ★H
```

## 2. 三种姿势（按安全度排序）

**① 计划层离线台（日常首选，零风险）**

```bash
cd <repo>
<venv>/bin/python tools/<svc>_debug_offline.py <命令id> --参数 ...
<venv>/bin/python tools/<svc>_debug_offline.py <命令id> --pose x,y,z   # 换个起点复算
<venv>/bin/python tools/<svc>_debug_offline.py <命令id> --json           # 给对比用
```

实现要点：
- `importlib.util.spec_from_file_location` 加载生产模块，**不要复制一份逻辑**（复制的那份迟早和生产不一致）；
- 真值/输入从服务同源文件读（不要另取一路），读不到就让用户 `--pose` 显式给，**不填默认值**；
- 两类分支都要覆盖：单步（相对位移/绝对点/旋转）和多阶段（steps 列表逐段算）。

**② dry 实例（全链路、不下发）**

```bash
mkfifo /tmp/<svc>_dbg.fifo 2>/dev/null
<SVC>_INPUT=/tmp/<svc>_dbg.fifo <SVC>_LOCK=/tmp/<svc>_dbg.lock <SVC>_DEBUG_DRY=1 \
  <venv>/bin/python -m debugpy --listen 5678 tools/<svc>.py
echo '{"cmd":"..."}' > /tmp/<svc>_dbg.fifo
```

三个开关的语义（默认路径与行为必须完全不变）：
| 开关 | 作用 | 不设会怎样 |
|---|---|---|
| `<SVC>_INPUT` | 换一条输入 FIFO/端口 | 两个读者抢同一条管道，命令被吃掉 |
| `<SVC>_LOCK` | 换一把单实例锁 | 新实例把线上实例 SIGTERM 掉 |
| `<SVC>_DEBUG_DRY` | 收到的任何命令强制演练 | 断点停住时设备照旧动 |

**③ 线上实例：只读证据**

```bash
tail -f <服务 stdout 日志>          # 受理 / 下发 / 到位 / 拒发原文
curl -s http://127.0.0.1:<port>/log?n=30
tr '\0' ' ' < /proc/<pid>/cmdline   # 重启前照抄原命令行（带参数的开关）
py-spy dump --pid <pid>             # 卡住看栈，不暂停进程
```

## 3. 断点表模板

| 断点 | 位置 | 条件 | 看什么 |
|---|---|---|---|
| A | `json.loads(line)` 之后 | `'<命令id>' in line` | 原始报文、解析结果 |
| B | `dispatch(...)` 调用行 | `spec.get("cmd")==...` | 是否命中、注册表版本 |
| C | `build_target()` 内 | 进入即停 | 输入真值、偏移/锁点、返回值 |
| D | `plan_stage()` 内 | 段名匹配 | 阶段定义、当前点、返回的 pos/Δ/err |
| E | 上限/天花板闸 | — | 上限值 vs 目标值 |
| F | `transport.exec_call(...)` | `'<关键字段>' in call` | 最终载荷全文 |
| G | `auth_guard()` | `kind=="运动"` | 授权态、epoch、拒绝原因 |
| H | `wait_arrive()` | — | 目标、实测、残差、超时 |

行号会漂 ⇒ 用"函数名 + 函数第一行"定位。

## 4. launch.json 模板

```jsonc
{
  "version": "0.2.0",
  "configurations": [
    { "name": "<svc> · 计划层(离线)", "type": "debugpy", "request": "launch",
      "program": "${workspaceFolder}/tools/<svc>_debug_offline.py",
      "args": ["<命令id>", "--参数", "值"],
      "console": "integratedTerminal", "cwd": "${workspaceFolder}" },
    { "name": "<svc> · dry 实例", "type": "debugpy", "request": "launch",
      "program": "${workspaceFolder}/tools/<svc>.py",
      "console": "integratedTerminal", "cwd": "${workspaceFolder}",
      "env": { "<SVC>_INPUT": "/tmp/<svc>_dbg.fifo", "<SVC>_LOCK": "/tmp/<svc>_dbg.lock",
               "<SVC>_DEBUG_DRY": "1" } }
  ]
}
```

## 5. 坑

- 断点停在"正在执行"的时刻 = 进程冻结、硬件继续走完上一条 ⇒ 只有 dry 时才允许下断点。
- 保活/自愈脚本判"有没有 <svc>.py 在跑" ⇒ 调试实例会顶替生产实例；开工前说清，收尾 kill 掉等保活拉起。
- 重启前读空输入队列，否则旧命令会被真跑一遍。
- 改名/改逻辑时别复用外层循环变量（内层同名 `for x in rows` 会让外层 `x` 指向最后一行，整表渲染成同一行内容）。
- 线上实例没带 debugpy 启动 ⇒ attach 不进去；用 py-spy/log 取证，别反复尝试 attach。
