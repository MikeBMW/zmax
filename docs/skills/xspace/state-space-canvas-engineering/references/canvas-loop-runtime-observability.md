# 常驻画布循环的运行观测与性能 ("卡住 / 太慢 / 空转" 类投诉)

适用: `tools/ss_canvas_loop.py` 起的状态空间常驻循环，用户报「怎么一直在这里循环过不去 / 还是太慢 / 还是循环 / 反复执行」。
核心原则: **先证明它在不在推进，再谈优化**。用户看到的是终端，终端不输出 = 他判定卡住，无论进程是否活着。

## 0. 一分钟判别它在不在跑 (不要靠终端有没有新行)

```bash
cd /home/ubuntu/zmax && ./gui-venv311/bin/python -c "
import json,time; d=json.load(open('zmax_data/ss_live/canvas_loop.json'))
print('tick',d['tick'],'cost',d['cost_ms'],'budget',d['budget_ms'],'帧龄 %.1fs'%(time.time()-d['t']))"
```

- `tick` 在涨 = 在跑；`帧龄 < 2s` = 活的。此时用户说"卡住" ⇒ 问题在**可见性**，不在引擎。
- `tick` 不涨再往下查 (py-spy 主线程栈 / 是否被 debugpy 挂起 / 被 `pkill` 杀掉)。
- ⚠️ **`tick` 的增量只有在"只有一个循环进程"时才有意义**：两个进程写同一个 state 文件会让 tick 计数翻倍，算出 65Hz 这种不可能的数。测速前先 `ps -eo pid,cmd | grep "[t]ools/ss_canvas_loop.py"` 确认只有一个。

## 1. 终端要自证"循环在推进"，但**只在状态变化时出声** (最重要的一条)

心跳 (5s) + 证据行，两条都要：既要一眼看到在跑，又**不能刷屏**。每秒一行 `检测 3 点` 会被读成「还在反复检测 / 没完没了地检测」，体感与没有输出一样糟 —— 用户不会因为数字在变就安心，只会觉得机器在空转刷日志。

```
[06:12:02] 💓 tick=3750 · 42ms/100ms · 10 节点
[06:13:09] ✅ 段21 夹爪闭合 · t=7.82s · 件1 · 检测 3 点 · u=[-0.06,-0.02,-0.09,0.07]
```

- 心跳 ~5s (`ZMAX_LOOP_BEAT_S`)；证据行 **只在"件号"变化时**打 (约 11s 一件) —— 段号每 0.2s 就换一次，按段打等于每拍打。`ZMAX_LOOP_EVIDENCE=0` 全关（只留心跳）。
- 🔴 去重状态用**同类型容器**：`_last_ev = [None]` 就必须写 `if _key != _last_ev[0]`。写成 `!= _last_ev`（tuple 跟 list 比）恒为真 ⇒ 去重形同虚设、每拍照打，用户体感仍是刷屏，而你读代码会觉得"我明明加了去重"。
- 🔴 **不要为了"检测慢"把 `ZMAX_L2_PERIOD_S` 从 0.5 降到 0.1**：单次检测稳态只有 28ms（reset 6 + render 8 + detect_3d 10 + 2D 框 4），"慢"来自冷启（首帧 609ms · aligner 2.18s · L3 5.6s，全是一次性）与 0.5s 节流本身。提到 10Hz 后用户的描述会从"检测慢"直接变成"还在反复检测、没完没了"。
- 超节拍时心跳**直接点名**最贵的两个节点：`⚠️ 超节拍 ← ssyolo 56.1ms · ss_mani_eng 38.0ms`，省掉一轮"谁超的"排查。
- 证据行字段取自 traces 的 `out1`：`ssyolo.out1.points` (检测点数/`frame`) · `ssplan.out1.seq/label/elapsed_s/mod` · `ssact.out1.u_sat`。
- **段号/件号/elapsed 一定要露出来**：规划是**时间驱动**的 (`plan_long_impl` 按 `elapsed_s` 选段)，看到 `段21 → 段28 → 件2 段1` 就知道它在推进；只露 `u` 时用户会认定"在原地反复"。

## 2. "加载画布"反复打印 = 画布被每拍重写（自激重载环）

症状: 日志每 ~4s 一条 `加载画布: 80 节点 / 80 连线`，且状态文件/归档目录持续增长。
机制: 有节点每拍 `import_config_files(verbose=True)` + `write_into_node()`，`cfg_loaded_at` 这类**时间戳字段每拍都变** ⇒ 判定"内容变了" ⇒ 整份画布 `save_canvas()` + 备份 ⇒ mtime 变 ⇒ 循环 `load_project()` 重挂工程 + 重载模型。

修法 (幂等两件):
1. 比对时**剔除时间戳**只看内容：`cfg_loaded_at`、嵌套 `loaded_at` 一律不参与"是否变化"判定；内容没变就**不写盘不备份**。
2. 全量配置块**只在文件签名变化时打印** (`_imp_sig` = 各真源 `mtime/size` 元组)，其余拍静默；否则 10Hz × 9 行 = 每秒 90 行重复块，用户看到的就是"卡在同一段"。
3. 签名里**不要放会被别的进程频繁写的文件 mtime** (如工程库 `.db`)，改放 size + 查询结果 5s TTL 缓存；否则 GUI/工单写一次库就整轮重扫 (~80ms 尖峰)。

副作用清理: 这类 bug 会攒下成千上万个 `*.bak_cfgimport_*`。用 `ls -t | tail -n +21 | xargs -r rm -f` 保留最近 20 个 (别一次性删当前正在读的)。

## 3. 节拍达不到 HZ: 结算口径错了

`dt = 1/HZ - cost` 里的 `cost` 若只算 `prj.step()`，就漏掉本拍杂项 (keepalive、心跳、写状态，实测 ~7ms) ⇒ 目标 10Hz 实测 9.3Hz。
修法: 进循环第一句记 `t_iter = time.monotonic()`，`dt = 1/HZ - (time.monotonic() - t_iter)`。判据: 单进程 25s 窗口 `tick 增量 / 秒` ≈ 目标值 (实测 9.97Hz)。

## 4. 超节拍: 找"这一拍贵在哪"，别调低 HZ 掩盖

实测稳态基线 (10 节点白名单): 均值 21~43ms / p95 30~70ms / 预算 100ms。尖峰来源与处置:

| 来源 | 实测 | 处置 |
|---|---|---|
| YOLO 真推理撞进节拍 | 40~200ms (GPU 被 sam3/引擎抢) | 推理挪**后台单线程**，主线程 render+obs 后立刻返回**上一帧结果** (`cached_ago_s`)，冷启同步算一次 |
| 慢节点每拍重算 | 22~38ms | 节点内节流 (`ZMAX_MANI_PERIOD_S` 0.25s) + 回放上次结果 |
| 配置/工程库重扫 | 80ms | 见 §2 的签名 + TTL |

- 后台线程只放**无状态推理** (detect_3d_meta / predict)；**env.reset/render 留在主线程** —— MuJoCo/EGL 在非主线程渲染有崩溃风险。
- 后台线程绝不把异常抛给主循环：写进 `_BG['err']` 并在节点日志报一次。
- GPU 侧先看谁在占: `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader`；8G 卡上 sam3 (~2.3G) + 每个循环 (~2.3G) 很容易把预算吃光。

## 5. 循环跑着但 `u` 恒 0 = 白名单少了一个节点，不是执行器坏了

`u_sat` 全机器只有 🛡 安全执行边界 (`safety_limit_impl.py`, 画布 id `sslimit`) 在写；执行器 `robot_actuator_impl.py` 读不到就回落 `np.zeros(4)`。
⇒ **`ZMAX_CANVAS_ONLY` 白名单必须含 `sslimit`**，否则 YOLO 在检测、plan 在出段、actuator 每拍 `execute(0,0,0,0)`，现象正是"一直在循环但什么都不动"。
- 判据: 证据行 `u=` 从 `[0.00,0.00,0.00,0.00]` 变成每秒都在变的小量。
- 白名单改动要**同时**写 `tools/gui/simulink_module.py::_vscode_launch_cfg` 模板 (右键打开 VSCode 会整份重写 `.vscode/launch.json`)。

## 6. 模型加载失败是**熔断**不是重试: GPU 一满就永久罢工

症状: `[模型] L3 SmolVLA+LEW ... 未加载/失败 → RuntimeError: CUDA error: out of memory`，之后每拍 `已熔断: ...`，u 永远 0。
修法: 熔断加**冷却重试** (`SS_L3_RETRY_S`, 默认 60s)，记录 `failed_t`；不要只留 `SS_L3_FORCE_RETRY` 手动开关。
防复发: 同一台机器**只跑一个画布循环**；起第二个之前先看 `nvidia-smi` 剩余显存。

## 7. 其他实测小坑

- `torch.from_numpy(np.asarray(PIL.Image...))` 报 `non-writable tensor` ⇒ `np.array(..., copy=True)`；PIL 的缓冲是只读的。
- 杀循环进程**按 pid**，绝不要 `pkill -f <模式>`：模式既会匹配到自己这条 shell（命令输出戛然而止、后续验证全没跑），也会顺手杀掉用户在 VSCode 里 F5 起的同一脚本会话（他那边表现为"又卡住了 / 怎么退出了"）。可靠的挑法（跳过自己的 bash 包装）：
  ```bash
  ps -eo pid,args | awk '$2 ~ /python$/ && $3 ~ /ss_canvas_loop/ {print $1}' | while read p; do kill $p; done
  ```
- **常驻循环必须自带"停"的入口**：`ZMAX_LOOP_MAX_TICKS=N` 跑够即正常结束（用户被"没完没了地检测"惹烦时会直接问"干循环有啥用"）。退出写 `sys.stdout.flush(); os._exit(0)` —— 裸 `return` 会让解释器去析构 MuJoCo/EGL 与后台推理线程，实测报 `FATAL: exception not rethrown` 并 dumped core，现场看着像崩了。
- 用户在 F5 会话里跑的是启动时那份代码：改完 `library.py` / `ss_canvas_loop.py` 后**必须让他重启一次**，否则他看到的还是旧行为。
- 汇报口径: 给 tick 数、cost/budget、哪一拍超、ulp 级的具体数值 (u 的四个分量)，不要只说"已修好"。
