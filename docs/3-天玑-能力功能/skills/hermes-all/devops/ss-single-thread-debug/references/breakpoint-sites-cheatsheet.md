# 断点落点语义速查（状态空间 / 真机轨迹）

用户问「停在这是啥意思」时，先按落点说清「这是哪一环、该看什么」，再谈修复。

## 每拍主链（跑在用户 F5 的进程里 ⇒ 红点可打）

| 落点 | 位置 | 此刻意味着 | 变量面板看什么 |
|---|---|---|---|
| 周期锚 | `scheduler_fsm.py:181 self.n_cycle += 1` | 每拍必过，唯一稳定的周期锚 | `self.state` `self.n_trans` |
| 提前返回 | `scheduler_fsm.py:247 return self.state` | 证据不足（`target is None`）掉头，252 永远到不了 | `meta` 里 dist_h/d_xy/depth/force 是否全 None |
| 正常出口 | `scheduler_fsm.py:252 return self.state` | 确认迁移后才到 | 迁移前后 state |
| 夹持丢失 | `scheduler_fsm.py:209 return self.state` | 回退分支 | gripper / 力 |
| 调制器推进 | `cognition.py` decide 入口的 `advance(...)` 块 | 本拍把几何/力证据推进 FSM | 传参 meta |
| 最终动作 | `cognition.py` `return u, f"阶段 {st}{tag}"` | 状态空间出口：本拍融合+限幅后的速度 | `u` / `st` / tag 里的削因 |
| 技能收口 | `atomic_skills.py` `return self.corridor_finish(_out)` | 本拍技能算完，正把速度投影进本技能圆柱通道 | `self.code`(SK01~SK08) `_out`(u/why/stage) 返回的 `corridor` 字段 |
| 执行器取指令 | `robot_actuator_impl.py:81 u_sat = _SS_STATE.get("u_sat")` → `:96 u_vec = _ex.execute(u_sat)` | `in1`(sslimit 的 out1) 已到手，正在「校验+量纲归一」 | `u_sat` `u_vec` `_ex.last_check` |
| 执行器校验 | `state_space/execution.py:134 a = np.asarray(u).ravel()` / `:169 return a` | 收到指令第一句 / 校验完要输出最后一句 | `u` `a` `self.max_rate` `self.last_check` |
| 派单 | `real_traj_flow.py` 的 `_post("/api/arm/step_traj", body)` | 把下一段丢给 8797（臂即将动） | `n` `start` `speed` `total` |

`corridor_finish` 的语义（用户最常停这里）：轴向 `v ≤ min(v_cap, L/tact)`（节拍参与限速）；横向偏出半径时**切掉往外跑的分量并补一个回中速度**，不是等比缩小；单拍位移 `‖v‖·dt ≤ s_tick`。返回的 `corridor` 里 `n/a` = 夹爪开合这类零位移段，`error` = 缺该段通道真源。

## 「状态空间工程的输出」怎么答

输出只有一个东西：**`sslimit` 节点 out1 里的 `u`（4 维：3 速度 m/s + 1 夹爪）**。

```
生成  cognition.py  return u, f"阶段 {st}{tag}"           （decide 出口）
打包  safety_limit_impl.py:277  return {"out1": {"kind": "modulator", "u": [...]}, "out2": {...}}
消费  ssact = n_actuator.py:23 → impl/ss_act.py(17 行, node_ss_exec) → robot_actuator_impl.py:96
落盘  zmax_data/ss_live/exec_state.json（exec/daemon.py 5Hz 原子写）
```

`RobotExecutor`（`state_space/execution.py:89`）**不是执行器下发口**：`execute()` 只做 NaN/Inf 拦截、通道范围 `_LIMIT`、变化率 `max_rate` 三项校验并记 `last_check`，数值原样返回。

停在这里看到 `a = array([-0.11578, 0.011491, -0.029385, 0])` 时，标准答法：
- `a[0:3]` = 末端速度，单位 **m/s**（≈116/11/−29 mm/s），已被 `sslimit` 按阶段限速（接触 0.061 / 精段 0.087 / 自由 0.320 m/s）；`a[3]` = 夹爪，0 = 本拍不动。
- `np.asarray(u).ravel()` 只是把列表转成一维 float 数组，**不触发任何执行**。
- 「真的执行了么」= 没有：状态空间的 `u` 只算不记录下发（`robot_actuator_impl.py:9` 铁律），臂的动作来自 215 点轨迹表；这就是「断点里 u 在变、臂却按轨迹走」的原因。
- 要让 u 真驱臂，得接到 `exec/daemon.py:868` 的 `/move_pose`（现在只有绝对位姿/J6 自转走那条），属闭环直驱改造，要先问用户。

## 容器内（红点绑不上）

`tools/rokae/arm_step_traj.py` 的 `MoveAbsJCommand` 跑在 docker 容器里 = **真发臂那句**。VSCode 断点对它无效，只能用旗标文件断点：

```
主机 zmax_data/rokae_sdk/stop_at_cmd   容器 /sdk/stop_at_cmd
```

旗标放哪由挂载决定：`rokae_sdk_run.sh` 里 `$SDK_DIR:/sdk`（可写）与 `$REPO_TOOLS:/repo:ro`（只读）——旗标必须落在可写挂载里；`/repo/...` 写不进去。语义：存在即停（停在**发指令前**，臂一动不动），删掉即走，最长停 1 小时。

## 三条铁律

1. **停住 ≠ 故障，也不会让 VSCode 变红**：容器断点停的是「机器人」，不是「代码」，调试器毫无反应是预期行为。
2. **下断点先打招呼**：静默 touch 旗标会让臂突然不动，用户会当成故障追问；动旗标前一句话说清「这会让臂停住、删掉即走」。
3. **证据必须出现在用户屏幕上**：VSCode 终端每段一行打印、调试器暂停、AR 页横幅都算；文件日志、mtime、「我 curl 到的数字」都不算——会被直接判定为「你的证据没有用」。给派单路径加 `print(..., flush=True)`（n/start/speed/轮次/游标）比任何日志都有效。

## 自停锚（不改代码就能停）

- `/tmp/zmax_stop_at_dispatch` → 停在派单前（用户进程内，可看变量）。
- `zmax_data/rokae_sdk/stop_at_cmd` → 停在容器发指令前。
- 两者都是「文件在即停、删即继续」，不依赖调试器，适合用户不在电脑前时布防。
