# metaworld peg-insert-side-v3 控制契约 (2026-09-04 R0 真实化 12 发探针实测)

来源: tools/probes_real/probe_mw_real*.py (保留为标定工具) + tools/gui/state_space_sim_real.py。
gui-venv311 环境, DISPLAY=:0, MUJOCO_GL=glfw。这些数字都是实测, 不是文档抄的。

## ⚠️ 控制锚: obs[0:3] hand, 不是 endEffector site (最大坑, 空夹根因)
- obs[0:3] hand = 腕部 body = **真实夹爪 claw geom 位置** (z≈0.195 初始)。
- `site("endEffector")` 是腕下 **4cm 虚拟视觉点** (z≈0.155), 非夹持件!
  用 site 当锚降到销身高度时, 真实夹爪还悬空 2-3.5cm → 永远空夹。
- 探针12 实证: hand 引导到 peg 上方 (hand_z ≈ peg_z+0.02, 被销顶住, 指已包住销上部),
  闭合 grp 0.66 接触建立 → 抬升 peg 随动 = 夹住。gen_insert_video 也用 obs hand 当手。
- 判别口诀: 控制/观测用 obs 段位; site 只是视觉/参考标记。接触实验务必查 contact 对里
  的 geom 名 — "peg 接触 4 点" 曾全是 **peg 贴桌面** (桌体 geom 无名 vs peg), 误读成夹持。

## gripper 语义 (与引擎简化世界相反!)
- obs[3] gripper: **1=全开, 0=全闭** (引擎语义是 0=开 1=闭, 别混)。
- 空夹(无物)全闭收敛 ≈0.29; 夹住 3cm 销接触建立 ≈0.66-0.70 (cognition.py 注释 0.70 对);
  深夹可到 0.28。**单看 gripper 分不清夹住/空夹** (都收敛 0.3 附近) → 夹持判定靠
  "抬起时 peg 随动" (夹住: peg 相对夹爪偏移不变; 空夹: peg 不动, 偏移漂移 → 判滑脱回退)。
- 夹爪动作: act[3] = 0.6-1.0 闭合 (gen_insert_video 用 0.6 防夹死), -1.0 张开。
  夹爪一阶收敛慢: 闭合 ~10 步到 0.7, ~20 步到 0.3 — 抓取阶段停留要给足步数。

## 动作映射与时间尺度 (引擎速度指令 → metaworld action)
- metaworld act[:3] = **目标位移增量** (±1 → ~10mm 目标/步), 伺服 ramp 收敛:
  act=1.0 连续 10 步累积 64mm, 稳态 ~9mm/步。≈ 引擎 0.5m/s×0.02s=10mm/步 (巧合对齐)。
- 实测映射: act = clip(u_vec[:3] / K_ACT, -1, 1), K_ACT=0.5 起步 (u 是 m/s 速度指令)。
  比例逼近控制 act = dv/0.03 clip ±1 收敛到 ±0.4mm (探针实测), 比引擎 v_min 逻辑更直接。
- **估计器/动力学 B 增益标定 0.02**: B=0.1 (≈1 env step 物理时长) 预测过冲 5 倍 →
  残差 0.5 级爆发 → contact_p σ(8r) 误判接触 (夹爪离销 20cm 就"接触") → 卡死循环。
  实测每步位移 ≈ 速度指令 × 0.018-0.02s。
- env.step 无渲染 <1ms; render 480×480 = 0.14s; +YOLO 检测+深度 ≈ 0.3-1s (R1 预算)。

## 几何与随机化
- **布局跨进程漂移 >10cm**: 同进程内 freeze 后 seed0 稳定; 不同进程 peg/goal 位置不同
  (探针 3 进程 peg y: 0.58/0.67/0.69/0.52 全不同)。→ 几何**每轮现场采样** (obs 段位 +
  site xpos), 不许写死常量。引擎注释里的 pegGrasp/hole 坐标只是某次快照, 差 3-6cm。
- 任务结构固定: 销沿 x 平躺 24cm (geom size [0.015,0.015,0.12] 局部, 世界=[0.12,0.015,0.015]),
  截面 3×3cm; 孔/终点在 -x 侧; peg 0.1kg free body, 底嵌入桌面 0.3mm (桌面顶 z=0)。
- 夹爪沿 **y 开合** (两指全开 y 距 ~9cm, 全闭 ~3cm = 机械限位), 夹 3cm 宽销刚好过盈。
- 闭合后两指中心漂移 +5mm (结构不对称) → y 目标补偿 -5mm 让闭合中心对准销。
- site 名: goal/hole/pegGrasp/pegHead/pegEnd/endEffector/leftEndEffector/rightEndEffector
  (m.site(name).id + d.site_xpos 可取世界位; pegHead z 比 pegGrasp 低 1cm = 销头)。
- obs 段位 (metaworld 语义, 与 node_obs39 文档一致): [0:3]hand [3]gripper [4:7]peg
  [7:11]peg_quat [11:18]pad [18:21]prev_hand [36:39]goal=site goal ✓ (孔深处, 非孔口;
  hole site = 孔口, 比 goal x 大 ~6-8cm)。

## env API 坑
- **单轮硬上限 max_path_length=500 步**, 到顶 env.step 抛 ValueError("truncate") →
  必须手动 reset; 未完成轮 = 截断 (try/except 捕获结束本轮)。
- 随机化冻结: env.reset(seed=s) 后 env._freeze_rand_vec = True; 同进程二次 reset 一致。
  ⚠️ 8 个不同 seed 跑出全同轨迹 (seed 参数疑似未影响布局) — 多 seed 统计前先验证布局真变了。
- mujoco API 版本差异: model.site_id2name / data.body_xpos / model.geom_xmat **不存在**
  → 用 model.site(name).id / d.site_xpos / d.geom_xpos / m.geom_quat+手写 quat2mat;
  model.geom(i).name 可枚举; 无名 geom 用 m.geom(c.geom1).name or f"g{id}" 兜底。
- 抓取完整序列 (验证可行): 悬停(z=销+8cm)水平对准 → 垂直降 (hand 到销身, 被销顶住) →
  闭合 20-30 步 (grp<0.7) → 抬升 act z 0.4-0.5 (peg 随动 Δz>3cm = 夹住; 不随 → 回退重抓)。
- 接触力合成 (metaworld 无力传感器): 未夹持=夹爪到销上方 gap_z 判据; 夹持=销头-孔口
  距离 <D_CONTACT。合成力只用于残差/接触概率, 夹持真伪靠 peg 随动。

## R0 实现要点 (state_space_sim_real.py)
- 几何每轮 _reset 现场采样存 self.geom; 阶段机每轮新建 ActionModulator
  (grasp_th=0.28 / lift_h=0.08 / max_veto=5; 阈值按 metaworld 实测, 引擎默认值会卡)。
- 夹持: 抓取阶段 grp<0.78 连续 3 步锁存"闭合候选" → 抬起阶段 peg 随动验证 (gf),
  滑脱置 grasped=False → 调度器 advance 夹持丢失回退 (grasp_force<0.05 连续5帧+peg落回)。
- 单轮全流程跑通 (seed 100): 八阶段完成, 真夹持 gf=1。遗留: 多轮 0/8 (布局敏感)。
- 引擎语义 39D 与 metaworld 39D 段位冲突 ([4:7]=v vs peg) — 前馈解析律只吃 [0:3]/[36:39]
  相对量不受影响; 挂训练 MLP 前必须统一语义 (R1 决策点)。

## 物理引擎每步到底吃什么 (闭环 episode 口径)

“MuJoCo 的解算输入是什么? 只是 8 个状态么?” —— 不是。**8 阶段从不进物理引擎**，它只在
上游决定子目标/限速/夹爪时序；进物理的只有 4 维动作。

```
u_exec (4D: 3 轴速度 m/s + 夹爪)
  → action[:3] = clip(u_exec[:3] * a_gain, -1, 1)      a_gain = ctrl_dt / env.action_scale(=0.01 m)
  → action[3]  = +1 if u_exec[3] > 0.5 else -1
  → env.step(action)
```

metaworld 内部 (`sawyer_xyz_env.py::set_xyz_action`): `mocap_pos += action[:3]*action_scale`，
再 clip 到 `[mocap_low, mocap_high]`；夹爪走 `data.ctrl`；然后 `mj_step × frame_skip`
(`ctrl_dt = timestep × frame_skip`，实测 12.5ms)。臂是靠 mocap 约束伺服过去的，**不下发关节力矩**。

- 物理只**输出**、不接收观测: qpos/qvel/site_xpos(`pegGrasp`/`pegHead`/`hand`)/接触力/`dist`。
- 8 阶段的三个真实作用: ① 子目标 `target` (接近 `peg+z(H_APPROACH)`、对位 `H_ALIGN`、下降/抓取
  `H_GRASP_POSE`、抬起 `peg_z0+H_LIFT`、转移 `hole_mouth-head_off+3cm`、插入两段式、完成 `goal-head_off`);
  ② `obs` 第 37~39 维就是这个 target (`visual39 = 当前18 | 上一拍18 | target3`)；③ 每阶段限速 + 夹爪时序。
- 传感器融合后的 `obs43 = visual39 + force6 融合 + tactile4`，喂策略而不是喂物理。
- 回答这类问题先读 episode 生成脚本的控制尾段 (`gen_ss_metaworld_episode.py` 的 action 构造) + 
  metaworld 的 `set_xyz_action`，别从观测维度反推动作契约。

## 四段动作 u_ff → u → u_sat → u_exec: 谁产出 · 有实时字段还是有 DDS 话题

问"这个动作信号在哪 / 有 topic 吗"先查这张表, 别凭工程图回答 (图上有连线 ≠ 有发布者)。

| 段 | 产出代码 | 实时可观测 |
|---|---|---|
| `u_ff` 前馈 | `state_space/parallel.py::FeedforwardAccelerator.forward` | `zmax/ss_state`: `前馈速度_mms`(模长) + `前馈速度_x/_y/_z_mms`; **夹爪通道不发** |
| `u` 调制 | `cognition.py::ActionModulator.decide` | `zmax/ss_engine`: `动作调制_x/_y/_z_mms` + `动作调制_夹爪` |
| `u_sat` 限幅 | `safety.py::saturate` | `zmax/ss_state`: `安全边界_mms` + `安全边界_x/_y/_z_mms` |

⚠️ 速度类键名后缀是 `_mms`, **值已是 mm/s** (生产端写值时 m/s×1000); 显示层不许再按键名后缀乘。
下表的历史键名 (`_mps`) 一律按 `_mms` 读, 契约内部 (DDS `v_cap` 等) 仍 m/s。
| `u_exec` 执行 | `execution.py::execute` | **无实时字段、无 topic**; 只在 episode `npz['u_exec_vec']`(4D) |

`u_ff` 的完整输出面 (问"前馈都输出什么"就按这四层答):
1. 返回值 `[vx,vy,vz,grip]` —— MLP 路径 `u_norm*astd+am` → clip **±0.6**; 解析路径 `Kp=1.2*(target-pos)`
   → clip **±0.5**, 水平距 <3cm 再叠 `+0.03` 最小推力; `grip` 是**规则**(水平距 <3cm→1)不是网络学的。
2. 可追溯计数: `loaded` / `n_calls` / `n_mlp`(域内) / `n_guard`(解析兜底); 域判据 = 3D 距 ≤0.25m
   **且** 归一化逐通道 |x| ≤4σ。
3. `self.probe`: `_seq` · `obs{hand,target,d_h,d_xy,gripper}` · `layers[3]{act_l2,active,dim,top3}` ·
   `out_contrib`(输出归因) · `u_ff` · `act_raw`(3×512) —— 只进 GUI 探针窗口, 不进信号页。
4. 落盘: `npz['u_ff_vec']` 是唯一带夹爪的 4 维记录。

DDS 动作话题 `ss.node.ssff/ssdec/sslimit/ssact.out1` (`zmax::Action*`) **工程图里有、当前无 publisher**:
`matched_pubs=0` + `fields` 空 ⇒ Trace 显 `—`。答这类问题必须给出"图上定义了 / 实际没跑"两句,
并指向真正在流动的字段, 否则用户会去搜一个永远空的话题。

## 能否由速度反推位姿 (`v_ff` → 位姿 → 真机关节) — 实测口径 (785 帧 episode, 80Hz)

问"能不能由 `v_ff` 算出位姿 / 由 plan 节点算出真机位姿"按这五条答, 每条都有硬判据:

1. **位置: 能, 但要用执行后的速度**。`p[k+1] = p[k] + u[k]·dt`, `dt = diff(npz['t'])` (实测 12.5ms / 80Hz),
   与 `npz['x']` 逐帧比 `|p−gt|`:

   | 积分输入 | 平均 | 最大 | 末帧 | 最优缩放 k |
   |---|---|---|---|---|
   | `u_ff_vec` (前馈意图) | 23.4 mm | 36.8 mm | 18.6 mm | 0.912 |
   | `u_limit_vec` (限幅后 = 实际执行) | 5.0 mm | 12.9 mm | 5.0 mm | 0.986 |

   机理: 真值是"执行后的结果", 所以执行量积分天然更准; `u_ff` 只是意图 (中间还过反馈/限速/饱和)。
2. **量纲自证**: 拟合一个全局缩放 k, **k≈1 就证明单位与 dt 都对** —— 不需要隐藏系数。
   k 明显偏离 1 时先怀疑单位或时间步, 别去调增益。
3. **分阶段看漂移往哪走** (`u_limit` 积分, 平均/最大): 接近 9.1/12.9 · 对位 7.9/10.0 · 下降 5.7/8.1 ·
   抬起 6.1/7.4 · 插入 4.1/6.1 · 插入接触 3.5/4.8 · 转移 2.4/6.5 mm。位移越大误差越大。
   插入容差本身 6mm 级 ⇒ **纯积分不够; 必须每帧用实测 TCP 位姿重置锚点**, 否则几十帧就漂过容差。
4. **姿态: 算不出来**。动作 4 维 = vx,vy,vz + 夹爪, 没有角速度; 回放 npz 也只存 `x` 三轴位置
   (无四元数/欧拉角)。6D 位姿的姿态分量只能另取: 实测 TCP 姿态 (`rokae_sdk/tcp_out/latest.json`, 50Hz)
   或规划器给的目标姿态。别用"速度积分出位置 ⇒ 位姿也有了"糊过去。
5. **plan 节点不反推位姿**: `SSPlan` 只是 MoveIt 规划结果 (joints + tcp 目标) 的镜像, 不是"速度→位姿"算子;
   而且要先有数据源 (`~/zmax_moveit_plan` 不存在 / `ss_plan count=0` = MoveIt 容器没起)。
   到真机关节位姿还差一步 IK (MoveIt 或控制器侧), 下发再过 8793 授权 + 速度口径 + idle/automatic 前置闸。

复现: 载入 npz → 按上表积分 → 与 `x` 比 → 打印分阶段表 (约 50 行脚本, 别手算)。

