# 单步全链调试档 (让每个节点等我的操作)

触发: 用户要「单步运行能走过任何节点的任何细节」「所有逻辑节点等我操作, 不允许任何节点自己跑」。
目标不是加断点, 而是**让整条引擎在一拍内把活干完, 且没有任何东西脱离调用栈** —— 否则断点只能停
在调用它的那一行, 而真正干活的线程/子进程照跑。

## 0. 先证明「业务代码本来就在主线程」

```bash
grep -nE 'threading|Thread\(|Timer\(|ThreadPoolExecutor|Popen|multiprocessing|asyncio' \
  tools/<engine>.py src/**/middleware/{project,node}.py | head -30
py-spy dump --pid <pid>   # 线程清单: 只认业务线程名; pydevd.Writer/Reader/CommandThread 是调试器自己的
```
实测形态: 7 个线程 = `MainThread` + 6 个 pydevd ⇒ 业务 100% 主线程, 可以逐层单步(要求 launch 里
`justMyCode=false`, 否则动态 import 的模块不进断点)。

## 1. 三层守卫 (环境变量开, 生产默认关)

写一个 `engineering/step_mode.py`, `ZMAX_STEP_MODE=1` 时才生效, 装三样:

1. **线程内联**: 节点里所有 `thread_policy.spawn_or_inline(name, fn)` 变成当场同步执行。
2. **子进程守卫**: 节点计算里发起的 `.py` 子进程一律拒并打印 `文件:行 + 命令`; **库探针放行**
   (`python -c …`、metaworld/aligner 之类的初始化)。放行清单写错会把正常节点搞崩 —— 宁可多放。
3. **并行压到 1**: 引擎快车道 `FAST_ONLY=[]`、`OMP/MKL/TORCH_NUM_THREADS=1`、`torch.set_num_threads(1)`。
   快车道不开会跳过节点 ⇒ 单步看不到, 这是「单步走过全部逻辑」的前提。

## 2. 🔴 死循环 worker 必须拆成「单轮函数」, 不能原地内联

最易踩: 节点里 `Thread(target=_worker).start()`, 而 `_worker` 是 `while True` + sleep。把线程换成内联
⇒ **整拍卡死在节点里**, 单步表现是「按了继续再也不动」且看不出是谁。

```python
def _worker_once():          # 一轮: 取帧 → 判定 → 写快照, 立即返回
    ...
@contextmanager / spawn_or_inline("ss_aoi", _worker_once)
```

节点每拍最多推进一轮(主线程), 节奏由引擎拍频决定。其它形态: `Thread(...).start()`(如 l5_intent)
直接换 `spawn_or_inline`。

## 3. 验收 (四条都要, 缺一条就是「看着单步、其实有东西在跑」)

```
① 进程线程名只有 MainThread (pydevd 除外)
② 收尾行: 「本进程没有任何节点试图脱离调用栈运行 ✔」
③ 行级 trace 覆盖: node.py / 调制器 impl / cognition / 状态机 都有行数 (>0)
④ 状态机 n_trans 随拍递增 (证明状态真的在被单步推进, 不是冻在首状态)
```

## 4. launch.json 三条配置(前端/连续/单步)互不拉起

```jsonc
{"name": "🖥 前端 GUI",   "program": "tools/gui/studio.py"},                       // 不 import 引擎
{"name": "🧠 后端工程",   "program": "src/lerobot/engineering/start.py",
 "env": {"PYTHONPATH": "<repo>/src:<repo>/tools", "ZMAX_FSM": "1", "ZMAX_ORCH": "1", "ZMAX_DISPATCH_INPROC": "0"}},
{"name": "🐞 单步全链",   "env": {"ZMAX_STEP_MODE": "1", "ZMAX_SINGLE_THREAD": "1",
                                     "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "TORCH_NUM_THREADS": "1"},
 "justMyCode": false}
```

`PYTHONPATH` 必须显式给(`src` + `tools`), 否则 F5 起来第一行就 ImportError; `ZMAX_DISPATCH_INPROC=0`
让单步档只跑状态机不下发技能(臂不动), 想真动才改成 1。

## 5. 单位与节奏口径(回答「多久走完一环」)

- 单步档一拍 = 全节点一趟(实测 94 节点/222 连线工程: 每段 12 个节点、一圈几十秒~数分钟)。
- 引擎把自己的 `print` 重定向进日志文件 ⇒ 入口/守卫的话要写 `sys.__stdout__`, 否则 F5 后终端空白。
- 单步档不要跑全流程驱动线程: 连续档用 1Hz 线程, 单步档用每拍 hook —— 否则你一停断点, 那边还在下发。
