# 工厂调度状态机作为工程入口（Z-MAX 实测）

## 分层（不要再把“纯 tick 循环”当入口）
- 入口：`src/lerobot/engineering/start.py` —— 打状态集合/策略表、装每拍钩子、启动引擎。
- 状态机：`state_space/scheduler_fsm.py::DispatchFSM` —— 13 状态 + 每状态策略（层配比/限速/力否决）+ 证据守卫。
- 执行腿：`tools/ss_canvas_loop.py` —— 10Hz 逐节点；它只提供 `TICK_HOOK`，不自己做调度。

## 两个必须先修的坑（不修则“状态机看着有、实际不动”）
1. **调制器每拍新建**：`safety_limit_impl.py` 里是 `mod = cog.ActionModulator()`，每拍一个。
   状态若跟着调制器 `new`，`stage_idx` 每拍回 0、`history` 每拍清空 ⇒ 状态机永远停在「接近」。
   修法：状态机做**进程级单例**（`get_fsm()`）。
2. **同一文件被加载两次**：端侧用 `importlib.spec_from_file_location` 按路径加载 `cognition`，
   包导入与文件加载会得到**两个模块对象**，各自模块级全局互不相通 ⇒ 入口拿到 A 实例、引擎推进 B 实例，
   现象是“引擎日志已经把状态推到抬起，入口一行切换都不打”。
   修法：单例注册表挂在 `builtins` 上（`builtins._ZMAX_FSM_REG`），而不是模块全局。

## 验证（tools/verify_scheduler_fsm.py，27 项）
- 闸1 等价性：FSM on/off 在同一观测串下阶段序列**逐拍相同**（insert/tray/full × 3 seed）。
- 闸2 策略表：权重和=1、接触段 L3≤0.10 且 L4≥0.55、限速 接触<精<自由。
- 闸3 守卫：confirm_n 连续、夹持丢失回退、转移→插入悬高容差、插入达标→完成。
- 闸4 集成：仲裁器读到状态机策略；力超阈否决 L3。
- 闸5 单例：两种加载方式 `get_fsm()` 返回同一实例，且 A 推进 B 可见。
- 每个用例前要 `_registry().clear()`，否则单例会串味（测试自带隔离）。

## 入口是**正式**的, 不是调试脚本(判据四条)
```
① 生产 unit 的 ExecStart 直接指向它(不是 tools/*.py 节拍器)
② 文件里没有任何 ZMAX_DEBUG_* / 硬编码路径 / 手工桩 / 断点标记
③ VSCode 走 debugpy 附加, 行为一致; 关掉编辑器服务照跑
④ 调试开关只在引擎侧(如 ZMAX_DEBUG_MAPFUSION / ZMAX_DEBUG_FUSE), 入口不掺和
```
用户强调"这是真正的工程正式入口, 切记"时, 意思是**别把它当临时 runner 改来改去**, 也不要为了调试往入口塞开关。

## 入口 vs 装载点(回答"这是总入口对吧"的口径)
- 入口: `start.py` —— 状态机 + 策略表 + 钩子 + 锁 + 停机。
- 装载点: 引擎 `main()` 里的 `load_project()` —— 那一刻才把节点图(94 节点/222 连线 JSON)装进来;
  之后 `prj.step(only=...)` 每拍按拓扑序跑节点 → `middleware/node.py step/compute` → 节点实现 →
  `sssched` → `cognition.decide` → `scheduler_fsm.step`。
按两层回答, 用户才能对上"我停在这一行是什么意思"。

## 单实例锁 + 优雅停机(缺了会"一会儿动一会儿不动")
```python
fh = open("/tmp/<proj>_start.lock", "a+")
try:  fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:  # 读文件里的 pid, 打印"已有入口在运行 pid=…", return 2
fh.seek(0); fh.truncate(); fh.write("%d\n" % os.getpid()); fh.flush()   # 持有到进程退出
```
- 机制: 两个入口进程 = 两个状态机单例 ⇒ **双写** `ss_live/*.json`; 派发宿主 `dispatch_inproc.owner()` 只认一个,
  第二个被拒 ⇒ 现场表现是"有时动有时不动", 极难查。
- 锁用 `flock` 而不是 pid 文件判活: 进程退出内核自动释放, 不留脏锁(文件留在原地无害)。
- 信号: `SIGTERM`/`SIGINT` → 打一行 `🛑 收到信号 N ⇒ 停止工程` 再 `raise KeyboardInterrupt`, 由 `__main__` 兜住;
  退出码给 0=正常 / 2=被锁拒 / 130=Ctrl+C, systemd 与 CI 都能判。
- 取证(交付必跑): 起第一个 → `cat 锁` 有 pid; 起第二个 → 打出"拒绝重复启动"并返回 2; `kill -TERM` → 看到停止行。

## VSCode 里 F5 能不能直接跑(否则 ModuleNotFoundError)
`launch.json` 的 `env` 必须给 `PYTHONPATH=<repo>/src:<repo>/tools`。入口自己注入 `sys.path` 只保护"入口被直接执行",
debugpy/其它 runner 可能先 import 别的东西 —— 两层都做。配置名按职责分两条: 前端 GUI / 后端工程(入口)。

## 入口可观测性
- 引擎装 `loop_quiet` 会把 `print` 收进 `/tmp/ss_canvas_loop.log` ⇒ 入口自己的话必须写 `sys.__stdout__`，
  否则 F5 后终端一片空白，看着像没启动。
- 状态机每次切换落 `zmax_data/ss_live/ss_fsm.json`（state/策略/切换原因/history）。

## systemd 换入口（不改主 unit，用 drop-in）
```
[Service]
ExecStart=
ExecStart=/home/intel/gsxpu-venv/bin/python /home/intel/zmax_550c/src/lerobot/engineering/start.py
Environment=ZMAX_CANVAS_HZ=10
Environment=ZMAX_FSM=1
Environment=ZMAX_ORCH=1
```
`ExecStart=` 空一行是必须的，否则旧命令行会继续生效。
