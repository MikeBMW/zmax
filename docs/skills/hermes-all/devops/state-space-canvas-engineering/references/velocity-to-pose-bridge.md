# 仿真速度 v_ff → 位置位姿：哪些量是算的、能算到多准、缺什么

用于回答「v_ff 能算出位姿吗」「插拔场景里哪些量是计算出来的」「桥接到真机怎么限速」。

## 1. 四层速度里只有 v_ff 是模型/解析输出

| 层 | 来源 | 性质 |
|---|---|---|
| `v_ff` 前馈 | 非插入段 `accel.forward(obs)`（蒸馏 MLP）；插入段 `accel.analytic_forward(obs)` | **唯一模型/解析计算输出** |
| `u_fb` 反馈 | `clip(0.5 × 残差EMA, ±0.5)` | 纯公式（状态校正器） |
| `u` 调制 | `u = u_ff + k_fb·u_fb` + 阶段限速（原子技能 SK01–08 + 物理约束闸） | 纯公式 |
| `u_limit` 安全边界 | `saturate(u, ±0.6)`，插入段另有回退置位 | 纯公式 |

- 场景里**看着在动**的位姿/夹持/接触概率/帧号来自回放的仿真真值 npz（metaworld peg-insert-side，785 帧），不是算的。
- 控制台进程**没有** `SS_INTACT` / `SS_L4_INTACT` ⇒ 3D 场景里的 `v_ff` 是**前馈加速器**，不是 INTACT；
  INTACT 跑在另一个常驻进程（`ss_engine_loop`，L4 = vote[unified, intact]）。要让场景 v_ff 来自 L4 模型，得给控制台进程加 `SS_INTACT=1` 再重启。
- episode 的 `meta.l45` 会自述本集各层实现（例：「L4 = 解析安全闸 saturate + 平滑，真 L4 模型未接入这两条 episode 链」）—— 引用它比自己推断可靠。

## 2. 速度积分成位置：实测精度（785 帧 · 80Hz · dt=12.5ms）

| 用哪个速度积分 | 平均误差 | 最大误差 | 末帧误差 | 最优单一缩放 k |
|---|---|---|---|---|
| `u_ff_vec`（前馈） | 23.4 mm | 36.8 mm | 18.6 mm | 0.912 |
| `u_limit_vec`（执行后） | **5.0 mm** | 12.9 mm | 5.0 mm | **0.986** |

- k≈1 ⇒ 单位就是 m/s、dt 就是 12.5ms，**没有隐藏系数**；差的是"意图 vs 执行"。真值是执行后的结果，所以用 `u_limit` 积分必然更准。
- 分阶段（u_limit 积分 / 真值位移）：接近 9.1/82.8 · 对位 7.9/58.4 · 下降 5.7/61.6 · 插入 4.1/72.9 ·
  插入·接触 3.5/17.0 · 转移 2.4/180.6 · 抬起 6.1/88.0（mm）。
- ⇒ **纯积分不能当位姿真值**：插入容差本身 6mm 级，积分误差同量级甚至会翻倍。必须**每帧用实测 TCP 位姿重置锚点**（或闭环校正），否则误差单调累积。

## 3. 姿态拿不到（链路限制，不是实现没做）
- 动作向量 4 维 = `vx, vy, vz` + 夹爪，**没有角速度**；episode 的 `x/peg/peg_head` 只有 3 维位置，无 quat。
- 光模块/末端"没有旋转俯仰"是**真值本身**：`meta.qpos` 16 维 = 7 关节 + 2 夹爪 + 3 光模块位置 + **4 四元数**（本集恒为单位四元数）。
- 要 6D 位姿，姿态只能另行取：实测 TCP 姿态（`tcp_out/latest.json`，50Hz 真值）或规划器给的目标姿态；关节角要 MoveIt IK（MoveIt 容器未起时 `ss_plan` 是黑的）。

## 4. 桥接到真机的规矩（用户硬要求，见 SKILL.md 同名段）
- 只跟方向：`v_cmd = normalize(v_ff) · min(|v_ff|, cap)`；cap **代码常量硬上限 10 mm/s**，配置写更大按 10 执行并打日志；死区 3 mm/s。
- 位姿 `p += v_cmd·dt` 只积分位置；旋转字段写 `null` 并标"未建模"。
- 桥接打开后**只是位姿流**（`ss_plan` / 画布 / 3D），不等于驱动真机；真机仍要 8793 授权 + IK 出关节角。交付时必须说清这条边界。

## 5. 接到真机 target: 三个断点 + 坐标系口径 (真机联调必查)

桥把位姿写进 `ss_plan` **不等于**真机 target 会动。实测"开关已开 / 已授权 / plan 已联通"但 target 不变，是三处独立断点：

1. **没有消费端**: `ss_plan` 只有显示用途 (画布 / 3D / 数据空间 / 校验脚本)。`grep -rln ss_plan` 数一遍消费者，
   没有一个写 target ⇒ 数据在动、目标不动。这是"发布成功"与"链路接通"的区别，交付时必须分开说。
2. **target 写端被独占**: 真机 target 的唯一写入文件是 `zmax_data/runtime/moveit_plan/plan_req.json`
   (容器内 `moveit_plan_live.py` 读 `/ws/plans/plan_req.json`)。它常被
   `moveit_plan_req.py --auto --to <点位> --watch` **每秒重写成固定示教点** ⇒ 新目标来源必须先停掉它或另走一段，
   否则你写进去的下一毫秒就被覆盖。判据: 隔 3s 看 `ls -l --time-style=+%H:%M:%S plan_req.json` 的 mtime 是否在跳 +
   `pgrep -af moveit_plan_req`。
3. **规划器/容器没在跑**: `sudo docker ps -a` 看 `zmax-moveit` 状态；`live_plan_latest.json` 的 mtime 就是最后一次规划时刻。
   容器 `Exited (137)` (137 = SIGKILL；`OOMKilled=false` 多为整机/会话关机带走) 时，写 req 也不会出新 plan ⇒ target 依旧不动。
   把容器退出时刻与整机重启/事故时刻对齐核实，别把"我写了 req"当成"会有新规划"。

**跨坐标系口径 (不解决会出事故)**: 桥输出的是**仿真基座系**绝对位姿 (≈ `(0.02, 0.61, 0.19)`)，真机 TCP 真值在**真机基座系**
(≈ `(0.658, -0.047, 0.362)`)，两者差 ~0.7 m。直接把仿真位姿当 target ⇒ 目标点瞬间跳半米多。
正确接法: `target = 真机当前 TCP + normalize(v_ff)·min(|v_ff|, cap)·dt`，只叠**方向增量**；
姿态用真机当前 quat (`tcp_out/latest.json` 或 `/pose`，桥没有姿态)；每步 ≤10 mm/s。
接之前先 dry-run (只写目标不执行)，看 target 连续小步移动再谈执行。

只读核查三连 (不动臂): `curl -s localhost:8793/ctl/status` 看 `motion_armed` 是否已撤 ·
`curl -s localhost:8793/pose` 取真机当前 TCP/quat (8793 没有 `/api/health`，走 `/ctl/status` `/pose` `/station/status`) ·
`sudo docker inspect zmax-moveit --format '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}} {{.State.FinishedAt}}'`。

## 6. 复核命令
```bash
# episode 结构 (t / x / u_ff_vec / u_limit_vec / stage / meta.qpos)
gui-venv311/bin/python -c "import numpy as np; d=np.load('reports/ss_episode_latest.npz',allow_pickle=True); print(d.files); print(d['meta'][0]['qpos'])"
```
积分对比脚本：按 `p[0]=gt[0]` 起，`p[i+1]=p[i]+u[i]*dt`（`dt=np.diff(t)`），再对真值逐帧取欧氏误差；
注意 `dt` 长度比 `u` 少 1，切片用 `u[:-1] * dt[:,None]`（写错就是 `operands could not be broadcast`）。
