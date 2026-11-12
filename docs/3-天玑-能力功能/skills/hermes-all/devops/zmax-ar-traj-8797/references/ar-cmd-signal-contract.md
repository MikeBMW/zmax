# AR 指令流契约 (`ar_cmd_chain.json` / `ar_cmd.json` / `ar_exec.json`)

供回答「AR 场景给机器人输出的是什么 / 发的是什么信号 / 走了几成是什么 / 执行器到底接没接进 AR」这类问题时用。
先看本文再答，别现场翻字段。

## 0. 先把这条流的权限判清楚：它不驱动真机

判一条输出流是否下发真机，**去功能注册表读 `real_cmd` / `real_auth`，不要用"它写了坐标"推断**。
Z-MAX 的注册表把这个写死了：

```python
grep -n 'real_cmd\|真机零指令\|real_auth' tools/ar300_config.py \
    src/lerobot/engineering/nodes/plan_long_impl.py
# ar300_config.py  →  {"scene": "AR 仿真双臂", "real_cmd": False}
#                 →  「只写渲染指令 ar_cmd.json, 真机零指令」
# plan_long_impl  →  副作用注释: 「AR 渲染指令, 真机零指令」
```

消费方只有三个，全是"看"：`tcp_ar_server.py`(`GET /api/ar/cmd`) · `ar_mujoco_scene.py` · 备份脚本。
**没有任何一条进 `bridge` / `zmax-l2-daemon` / Orin 39061 / 珞石控制器。**

真机指令走的是另一条链，吃的是 L2 收口的 `u`（4 维速度+夹爪）：
```
L2 收口闸 → zmax-l2-daemon(4060) → 39071 → Orin 39061 → 珞石控制器
```

⇒ 报节拍时必须写成「**计划节拍**」，不能写「产线出了 N 件」。两件事在 KPI 上是分开的。

## 1. 三条流 / 三个文件（按「谁写 → 谁读 → 能不能拿来判接入」排）

| 文件 | 写者 | 接口 | 现在算什么 |
|---|---|---|---|
| `zmax_data/ss_live/ar_cmd_chain.json`（**单文件双分区**：`plan` / `exec` / `annot`）| `plan` 分区← 运动规划 `n_moveit`；`exec` 分区← 机器人执行器 `ssact`（`ar_bridge.update("exec",…,src="ssact")`）；`annot`← L2 全节点联通器 | `GET /api/ar/cmd`（**优先读它**，回 `chain:true`、`src:"chain:n_moveit+ssact"`、`drive:"exec:ssact"`、`exec_u…`）| **唯一可用来判「执行器接进 AR 没有」的通道** |
| `zmax_data/ss_live/ar_cmd.json` | `ss_plan_long` / `uph_tact`（`ZMAX_UPH_AR_PUB=1`，`ZMAX_AR_OWNER` 定唯一写者）| 同一 `/api/ar/cmd`（chain 过期/空时**回落**它）| 老推进器，仍是回退路径 |
| `zmax_data/ss_live/ar_exec.json` | 执行器旧写口 | `GET /api/ar/exec` | **旧残影**：可能几天不更新，回 `fresh:false`。别拿它判「没接」 |

- 双分区同文件、文件锁串行：两个节点各写自己的分区，**不会互相盖掉**（`src/lerobot/engineering/exec/ar_bridge.py` 文件头说明）。
- 页面 10Hz 轮询，`AR_CMD_FRESH_S = 3.0` 超时静默回落——**不报错**。要判它还在不在跟，
  看顶部横幅驱动源与 `age_s`/`fresh`，别以为没动就是坏了。
- 🔴 **判「接没接」只认 `/api/ar/cmd` 的 `chain` / `drive` / `exec_u`**；
  用 `/api/ar/exec` 的 `age_s` 下结论会得到相反的答案（实测该接口 `age_s≈3.7 天 / fresh:false`，而同一时刻
  `/api/ar/cmd` 是 `age_s=0.07 / chain=true / drive=exec:ssact`）。旧端点要不要清理先问人，别顺手删。
- 🔴 **画布 port 上看不见这条边**：`ssact.out1` 只连「🌍 物理世界」，AR 出口是**文件出口**（节点写
  `ar_bridge` → `ar_cmd_chain.json`）。所以「拓扑里没有线」不等于「没接」，回答时把这两层分开说。

## 1b. 🤖 机器人执行器的两个开关：AR 场景 / 真机（语义别搞反）

真源：画布节点 `params.ar_scene` / `params.real_auth` → 控制台写 `zmax_data/ss_live/exec_switches.json`
（`{t,t_str,node,ar_scene,real_auth,src}`）。**只有这一个写口**，页面/脚本都读它。

| 开关 | 真实作用 | 代码位置 | 不是什么 |
|---|---|---|---|
| AR 场景开关 `ar_scene` | **真机否决闸**：`ar_scene=true` 且文件新鲜（≤`AR_SW_FRESH_S`=1800 s）⇒ 每条运动下发被拒，拒因写「AR 场景开关=开 ⇒ 真机不动」。停机/复位类在闸之前放行（白名单 `robot_stop` / `rokae_recover_estop` / `estop` / `recover`）| `src/lerobot/engineering/exec/daemon.py::_ar_scene_gate()` / `_auth_guard()` | **不是通道路由器**：关掉它不会「把信号切到真机」，只是把否决撤掉 |
| 真机开关 `real_auth` | **真授权**：`ctl_auth.grant/revoke`（与 8793 工位总览同一写口），`real_auth=false` ⇒ `_auth_guard` 回「真动授权未开(现场安全)」| `tools/gui/simulink_module.py::on_toggle_real` → `tools/ctl_auth.py` | 不是「另一个显示位」——它真改授权窗 |

判「开关是不是真起作用」的**只读**实测法（不点开关、不改文件）：
```bash
cd ~/zmax && ./gui-venv311/bin/python - <<'EOF'
import sys; sys.path.insert(0,'src'); sys.path.insert(0,'tools')
from lerobot.engineering.exec import daemon as D
print('AR 闸 :', D._ar_scene_gate())
print('运动  :', D._auth_guard('move_joint','运动'))
print('急停  :', D._auth_guard('estop','运动'))
_g = D._ar_scene_gate; D._ar_scene_gate = lambda: None   # 只在内存里摘掉 AR 闸
print('AR=关 :', D._auth_guard('move_joint','运动'))      # 看真机开关/授权是否仍挡
D._ar_scene_gate = _g
EOF
```
实测口径：AR=开 ⇒ 运动被拒、理由含「AR 场景开关=开」；摘掉 AR 闸后仍被 `ctl_auth` 拒 ⇒ 两开关串联。

边界（必须主动告诉用户，否则他会以为「关了 AR 就全停了」）：
- **fail-open**：`exec_switches.json` 超过 1800 s 没更新 ⇒ 闸自己松开（防止画布失联把现场锁死）。
  `tools/ss_canvas_loop.py::keepalive_switch()` 只续 `ar_scene`、**永不自动续 `real_auth`**（安全红线）。
- **没有真正的通道互斥**：`exec` 分区照写（`ar_bridge.enabled()` 只看 `ZMAX_AR_CHAIN`，不看 `ar_scene`），
  所以「AR 开关=关」时 AR 数据仍在跑，只是页面 `/api/ar/mode` 拿 `ar_scene=false` 不进 AR 模式。
  要严格互斥就在 `ar_bridge.update()` 入口加 `if not ar_scene: return`（只影响渲染，不碰真机）。
- 报这两个开关的状态时，**读 `exec_switches.json` 的 `t_str` 与刷新龄并一起给出**，别只报「开/关」——
  它可能是几小时前的值（画布循环停了就不续期）。

## 2. 字段契约：只有三个数是动作

| 字段 | 含义 |
|---|---|
| `a` | 段起点，笛卡尔 mm |
| `b` | 段终点，笛卡尔 mm |
| `u` | 段内进度，**0~1 比例**（见 §3，曾长期是秒）|
| `kind` / `label` | 段类型 / 人话描述（`move` / `down` / `up` …）|
| `seq` / `mod` / `batch` | 第几段 / 第几件 / 第几批（轮次）|
| `mt_id` / `mt_name` / `mt_i` / `mt_n` | 元任务归属与进度 |
| `t_seg` / `t_left` / `elapsed_s` | 本段时长 / 本段剩余 / 整体已用（秒）|
| `vision.src_kind` | 视觉点来源，`sim` = 仿真算的，不是实拍 |

`exec` 分区另有：`u` / `u_sat`（4 维执行指令，已饱和）/ `check.valid` / `check.over_rate` /
`src_file="execution.py:RobotExecutor.execute"`。**它是节点真算出来的指令，不是透传**；但仍 `real_send=false`。

前端 `arCmdSolve()` 三步：`tm = a + (b−a)·u` → `ikTool1(tm/1000, q)` 逆解 6 关节角 → Three.js 摆臂。
**关节角不是下发来的，是浏览器每帧自己 IK 解的。**

## 3. 🔴 `u` 的单位坑：曾把「秒」当「几成」发出去

`plan_long_impl._pub_ar(o1, u, seg_t, el)` 的调用点是 `_pub_ar(o1, el - seg_t0, seg_t, el)`，
即传进去的是**本段已过秒数**；函数内只有 `min(1.0, max(0.0, u))` 砍边界，**没有除以 `seg_t`**。
段时长中位数 0.3s ⇒ 页面把 0.15 当 15% 画，实际已走 50%，**虚拟臂每段只走约 30% 就跳到下一段起点**，
看上去一顿一顿。

判别式（一条就够，不需要读代码）：**`u + t_left ≈ t_seg` ⇒ `u` 是秒；`u ≈ (t_seg − t_left)/t_seg` ⇒ `u` 是比例。**
实测对照：`u=0.0823, t_left=0.418, t_seg=0.5`（0.0823+0.418=0.5 ⇒ 秒）；修后 `u=0.7929`
与 `(0.3−0.062)/0.3=0.793` 误差 0.000。

修复形态（`t_in_seg / seg_t`，`seg_t` 为 0 时取 1.0）：
```python
_pub_ar(o1, el - seg_t0, seg_t, el)
# def _pub_ar(o1, u, seg_t, el):
#     u = (u / seg_t) if seg_t > 1e-9 else 1.0      # ← 这一步原本缺
#     ... "u": round(min(1.0, max(0.0, u)), 4)
```

🔴 **同一文件名/函数名的两份实现要互相对账**：`uph_tact_impl._pub_ar` 早已归一化，
`plan_long_impl._pub_ar` 没有 —— 两个都在写同一个 `ar_cmd.json`，只有当前生效的那个才暴露问题。
改/读任一份前先 `grep -rn '_pub_ar(' src/lerobot/engineering/nodes/` 两份一起看，否则会以为"代码是对的"。

改完这类循环服务重启一次 `zmax-ss-canvas-loop` 即生效，然后**回读 `u` 与 `(t_seg−t_left)/t_seg` 的差**才算验完。

## 4. 已知空槽 / 隐式约定（答问题时不要当成有值）

- **`q` / `q_l` 恒为 `null`**：payload 留了关节角槽位，但全仓库没有任何节点写它，`tcp_ar_server` 只透传。
  现在纯靠前端 IK。别在回答里把它说成"下发了关节角"。
- **指令里没有臂别字段**：臂别只能从 `mt_name` 前缀解析（`右臂 ·` / `左臂 ·` / `双手 ·`）。
  改动 mt_name 文案会让臂别解析静默失效——这是隐患，不是设计。
- **起停靠人点**：代码明确禁止页面自己 `plantStart()`，必须手动点「🏭 全流程 UPH」。

## 5. 怎么答这类问题（用户明确要求过「说人话」）

被问「发的是什么 / 走了几成是什么 / 给机器人输出的是什么」时：

1. **先一句人话结论**，再决定要不要给字段表。例：
   > 服务器每 0.1 秒告诉页面三个数：从哪走到哪、现在走了几成。就这三样。
2. **不要一上来甩 JSON / 字段表 / IK / 笛卡尔这些词**。用户为此打断过：
   「你到底发的是啥啊, 说人话」。字段表放在他追问细节之后。
3. **该说的实话必须留**：不驱动真机、`q` 是 null、视觉是 `sim`。这些是结论的一部分，
   不是"技术细节可以省略"。省略了就是在暗示真机在动。
4. 讲进度这类量，**给一个可复算的等式**（`u + t_left = t_seg`）比给形容词有效。
5. 问「开关是不是真的在切换通道」时，**分两侧答**：真机侧 = 真否决闸（给 `_auth_guard` 的拒因原文）；
   AR 侧 = 只是页面模式（写链不停）。一句「真的在切换」会把 fail-open 与不互斥这两件事藏起来。
6. 🔴 **被第二次要求「说人话」= 连「字段表 + 人话总结」并存都不许**：第二次就是载体错了。
   形态只有一段散文 + 一个生活比喻 + 一个具体数字，例如
   「它不指挥机械臂，只画路线：先抬到安全高度、再横着挪、再落下去，一共 5 小步。执行器拿这张清单才真动手，
   而且每步走完要停下看真值确认，所以计划 313 件/小时、现场只有 203 件/小时」——
   文件路径 / 字段名 / 代码行号一律留到最后一句「要核的时候看这里」。
   常见翻车：一句话人话之后又接了三种出口 / 两套时间基 / 四条链路，等于没改载体。

## 6. 🔴 段表只带位置，姿态不在表里（被问「只有位置，能保证姿态么」时照此答）

段表是**几何路线**，不是位姿轨迹。三条链上的段表都只有位置：

| 段表 | 字段 | 有没有姿态 |
|---|---|---|
| `sim_insert.json`（AR/UPH 那张，392 段/4 件）| `a` `b` `kind` `label` `k` `mod` `seq` `t` `carry_*` | **没有** quat/欧拉角 |
| `n_moveit` 输出（`plan_impl.run`，out1→`n_exec.in1`）| `i` `kind` `a` `b` `abs_mm` `len_mm`（moveit 后端才带 `t`）| **没有** |
| `ar_cmd_chain.json` 的 `plan` 分区（喂 AR）| `a` `b` `u` `seg_i` `seg_kind` `label` `total_mm` `pose_src` | **没有** |

真机姿态是**开环保持**，来源只有三条（`exec/daemon.py` 里挑目标姿态那段）：
① 段/命令里显式带 `quat`（路径复现）② 技能标 `quat:"taught"` ⇒ 用点位库示教姿态（`data/skills/l2_atomic/taught_points.json`，
实测 69 点 69/69 带 quat）③ 其余情况**现读当前 TCP 四元数**＝「姿态保持不变」，读不到就拒发（不吃陈旧缓存）。
插入方向也不是解算出来的：`local_mm` 沿**示教姿态自己的局部轴**进退（沿模块轴向）。

🔴 没有任何姿态判据：
- `wait_arrive(target, tol_mm=2.0)` 的误差式 `max(|p[i]-target[i]|)*1000` 只用位置，函数里从没比较四元数 ⇒ 姿态走歪照样报到位。
- 板坐标系定位只解模块在板平面的 x/y（射线∩板平面，~1mm），**不解孔轴朝向/偏航**；工件在治具里转个角，段表与判据都看不出来。
- 插入兜底是力（≤40N）+ 位移，不是姿态闭环；SE(3) 的 `u=[F;M]` 力矩在势场/阻抗层算得出来，但没进段表、没驱动姿态自由度。
- AR 画面里光模块的朝向是**写死的常量**（`module_calib_ref.json` 的 quat，注释写明实测反算带 3.5° 残差才改死值）——
  所以 AR「看着是平行的」不能当姿态证据，它连真机都不反映。

⇒ 标准答法：**位置能保证（有真值 + 2mm 到位判据）；姿态只能保证「和示教一致/保持不变」，且没有判据**，
前提是治具与孔朝向固定、示教正确。要真闭环得补四件：段表加 quat 并逐段带 → `wait_arrive` 加四元数夹角判据（≤0.5°，连续两次）
→ 板坐标系解出孔轴 yaw 回写目标姿态 → AR 渲染改吃段表姿态、删掉死值。

### 6b. `MAX_SEGS=40` 会静默截断，目标不可达仍报 ok
`plan_impl._segments()` 末尾 `segs[:MAX_SEGS]`（默认 40）+ 单步 ≤50mm / 向下 ≤20mm ⇒ 远距离目标必被砍。
实测从 AR 虚拟末端 `(401,-435,555)` 去槽1 `(490,499,118)`：40 段只走到 `z=215.4`，**差 97.4mm 没到**，
而节点照样回 `ok=true`、`goal=(490,499,118)`、`n=40`。判据：末段 `b` 与 `goal` 逐轴差 >0.5mm 即截断。
消费方（daemon / AR 页）拿到的是一份「到不了终点」的段表且没有任何告警 —— 报修口径按「静默截断」讲，别读成规划失败。
