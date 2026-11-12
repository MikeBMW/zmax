# 节点 ssobs「🧩 SU(2) 统一状态空间」当前输入输出 (2026-11-12 实测)

被问「它输出什么 / 都给谁 / 具体什么数据」时照这个答, 全部有真跑证据。

## 三处代码 (回答"代码在哪"一律给三处)
| 层 | 文件 | 行 |
|---|---|---|
| 契约 (无业务逻辑) | `src/lerobot/middleware/nodes/n_state.py` | 25-42 (全文件 108 行) |
| 实现 (取数→调算法→打标) | `src/lerobot/middleware/nodes/impl/ss_obs.py` | 21 入口 `node_ss_su2`, 到 157 |
| 算法 (纯计算) | `src/lerobot/policies/left_right/state_space/su2.py` | 311 `encode_layer` · 346 `compose_scene` · 351 `peel_layers` · 600 `SU2UnifiedState` |

契约: `PORTS_IN=['in1']` · `PORTS_OUT=['out1','out2','out3']` · `EXEC_MODE='view'` · **`PURE=False`** · `IMPL_KEY='ss_obs'`

## 端口级连线 (画布 JSON `f_port`/`t_port`, 不是只到节点)
- `in1 ← 📡融合定位建图(sssensor).out1`
- `out1 → ⚡前馈加速器(ssff).in1 · 🔍异常推理器(ssreason).in2 · 📊仿真波形(ssvideo).in2 · 🧬元数据MOE门控(ss_moe).in1 · 🧭测地线规划引导(n_geoplan).in1`
- `out2 → 🔮自适应状态估计器(ssest).in1`
- `out3 → 🧮流形引擎(ss_mani_eng).in2`
- 话题 = `ss.node.ssobs.<port>`

## 返回体
- **out1 与 out2 是同一份 43D 观测体** (`ss_obs.py:136-153`): `kind='obs43' · dim=43 · obs/obs43 · obs39 ·
tactile[39:43] · tcp[0:3] · grip[3:4] · peg[4:7] · hole[36:39] · R[24:33] · src · layout`。一包复制两路, 没有第二个信息量。
- **out3 是群读数**(不是数组): `kind='su2' · readout(n̂/θ/|w|/‖r‖) · dominant_layer ·
layer_peel(逐层 theta_before/after/delta/layer_theta) · noncommutativity · layers(四层 describe)`
- 另写内存态 `_SS_STATE[su2_scene/su2_layers/su2_readout/su2_nodes/su2_nodes_src]`,
契约文件 `zmax_data/ss_live/quat_truth_latest.json`。

## 输入实际取的四路 (不读 in1 信封!)
1. `obs43 = _ss_ensure_obs43()` — 有新鲜 YOLO `aligned39` 就用, 否则 metaworld env 真值; 用哪路写 `_SS_STATE['obs43_src']`
2. `frame = _ss_su2_frame()` — 引擎 io_trace 当拍标量: L3 `mani_progress/mani_dperp/mani_rem` · L4 `u_sat/contact_p/mani_eta`
3. `L5_intent` — DeepSeek 3 维意图, 单飞+TTL, 拿不到不写 ⇒ 该层单位元
4. `L2_quat` — quat_truth 记忆真值 ⊕ 感知补偿, 测量过期 w=0

## 坑
1. 🔴 **`PURE=False` ⇒ 常驻循环/画布 `compute()` 只 `out1←in1` 直通, out2/out3=None**, 实现一次没跑。
真算只在「⏭单步 / 右键运行节点 / ▶运行」。判据 = 日志有 `🧩 SU(2) 统一状态空间 ... 状态方向 n̂=`;
**端口有值不算**(端口壳子也有值)。`canvas_loop.json` 的 `fast_only` 里没有 ssobs。
2. 🔴 **L2 走 quat_truth 时 θ 是姿态角本身, 不是误差角**: `q_for_axis(轴, YAW_PREF_DEG)`,
默认 `SS_TRUTH_YAW_DEG=180` ⇒ `z_pos` 轴得 180°/|w|=0; 回落 43D 时才是 tanh 误差指示器。**两种口径不能对比**。
3. 触觉 4 维(`[39:43]`)是 `gen_tactile` 生成, **不是力传感器实测**; `src=env` = 仿真真值不是相机检测。
4. L5 长期落单位元(DeepSeek 实测 60~130s/次) ⇒ `noncommutativity['L2|L5']` 恒 0, **别当"两层解耦"**。
5. `compose_scene` 是**左折叠** `((L2·L3)·L4)·L5` ⇒ 手算矩阵必须写 `M(L2)M(L3)M(L4)M(L5)`;
反序会差 ~1.1, 看着像 bug 其实是自己对账顺序错(实测正序差 2.3e-16)。
6. `commutativity_matrix()` 返回的是 **float**, 不是 dict (别写 `cm[k]['norm']`)。

## 自查命令模板
```python
from lerobot.middleware.nodes.impl.ss_obs import node_ss_su2
out = node_ss_su2({"log": print, "demo_light": True})   # 三端口真值
```
群公理/分解自洽: `U†U−I≈5.6e-17 · det=1 · ‖q‖=1 · 剥离残余 θ=0`;
不可交换实测同拍: L2|L3 45° · L2|L4 104° · L3|L4 118°。

## 为什么这么分 (被问"为什么"时的口径)
- 不是 `fuse_sensors` 拼接(那是传感器融合): 米/概率/标志位混在一个向量里, 分不清谁造成偏差, 也不能运算。
- 分层跟工程层义对齐(L2 几何/L3 规划/L4 安全/L5 大模型), **按"谁负责"分层, 不按传感器分层** —— 剥出哪层偏差大就知道谁去改。
- 用群乘不用相加: 层有先后(先对位→再限幅 ≠ 反序), 不可交换才能表达; 能乘逆元才能逐层剥离。
- tanh 有界: 任意脏数据都落进群、θ<π 不绕圈(否则 θ=π 与 0 混淆 = 假收敛)。
- 代价(诚实): gain 手调(L2=2/L3=3/L4=1/L5=1)未标定 · 分层是人为语义切分 · L5 长期空 · out1/out2 重复。
- 边界: 群元素**不进执行** —— 下发是速度指令(`u_sat*dt`), SU(2) 现在是观察/分解层。
