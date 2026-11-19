---
name: se3-manifold-engine-wiring
description: "Use when 流形引擎要真出 SE(3) 或让 L5 语义引导引擎. 五个静默假通的坑+判据。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [manifold, se3, engine, l5, vlm, canvas, zmax]
    related_skills: [su2-unified-state-space, state-space-canvas-engineering, manifold-engine-math-verify]
---

# 流形引擎 SE(3) 真出 + L5 语义引导 (接线坑)

## When to Use

- 要把流形引擎从 SU(2)/S³ 切到真 SE(3) 输出，或排查“分支有代码但不生效”
- 要让 L5/VLM 场景理解引导引擎（阶段→目标、置信→势场权重）
- 接 H-JEPA 语义（hjepa）/ 几何（hjepa_mr）双通道 provider
- 画布上某条边看着连着、引擎却没反应（端口空转）
- 判据变红但怀疑是判据本身选错（欧拉角等价解那类）

目标链: L5 语义 → T_goal/k → 引擎 SE(3) 螺旋 → decoder → cond[15] → action_head。
下面每条都是**看着对、实测错**的，必须按判据验。

## 1. `Navigator.step` 的 se3 分支默认不是螺旋
原实现是 `slerp(R) + lerp(t)`（注册表却写“螺旋运动”）。ρ 与 φ 不平行、角度 1.2rad 时
与真 SE(3) 指数差 **163mm / 10.1°**；ρ∥φ 或小角度则恰好一致 ⇒ 小样本测不出来。
修：`T2 = T @ se3_exp([ρ;φ]*dt)`（平移经 V(φ) 耦合）。判据：三种情形 max|Δ|=0。

## 2. `ManifoldEngine.project()` 会把位姿洗成 I + 零平移
`project(state)` 内部先 `encoder.encode(state)` 做 PCA 再投影 ⇒ 传 12 维位姿进去，
输出是 `R=I, t=[0,0,0]`（实测），后面螺旋从原点出发，距离反涨。
修：SE(3) 模式**直连** `eng.projector.project(p12)`（SVD 正交化，residual≈1e-16, drift=0）。

## 3. ξ 的方向 + 分量序，两处都要对
- 方向：navigator 是**体坐标右乘** `T @ exp(ξ·dt)` ⇒ ξ 必须是 `log(T⁻¹·Tg)`。
  用 `log(Tg⁻¹T)` 会不进反退（实测 18.130→18.169mm）。
- 序：`se3_chain` 的 ξ = `[ρ(平移); φ(旋转)]`，而 `Navigator.step` 的 v = `[φ; ρ]`
  （源码里 `w=v[:3]`, `v[3:6]` 才是平移）。不重排 ⇒ 平移当旋转、5 步涨到 20.04mm。
判据：连续 8 步距离单调下降 + det(R)=1。

## 4. 静默降级一律改成报错
`p.size < 12` 时老代码 `return p + v*dt`（欧氏直线）——看着像 SE3，实际不是。
改成 `ValueError`，否则调试时永远看不到“分支没走”。

## 5. 语义通道必须用 `HJEPAStateProvider`，不是 `HJEPALiveProvider`
`HJEPALiveProvider.__call__` 返回**裸 ndarray**；引擎 `_hjepa_read` 要 `dict{z1,z2,z3,energy}`
⇒ `manifold_engine.py` 的 `if not out:` 直接 `ValueError: truth value of an array is ambiguous`。
这会被误诊为“引擎没接”，实际是 provider 选错。
- 语义：`hjepa_state.HJEPAStateProvider(root, state_fn, frame_path)` → z_dim=640 (256+256+128)
- 几何：`hjepa_manifold_provider.HJEPAManifoldProvider(state_fn=..., mode="weak")` → ξ(6)/v_n(3)/d_se3/d_normal
- 两通道 **并存不替代**（引擎注释原话：姿态误差与语义纹理揉在单一欧氏 latent 会互相污染）
- `w_phi` 默认 0 = 只观测不动动作，别默认打开

## 6. state7 口径与分量来源要分开标
`state7 = [x,y,z(m), rx,ry,rz(rad), grip]`（与 `_rpy_to_T` 的 Rz@Ry@Rx 严格互逆）。
43D obs 里**只有位置没有姿态**：
```
[0:3]手位置 [3]夹爪 [4:7]光模块位置 [7:11]四元数 [11:18]pad7 [18:36]上帧 [36:39]孔位 [39:43]触觉
```
⇒ 位置/夹爪取 in1 的 43D，姿态必须取 TCP 真值，输出里逐分量标 src，别整体报“来自真值”。

## 7. 画布边不许空转：每条入边写 used/why
`ss_mani_eng` 七个入边（in1 有两条上游）。SE3 改造后只有 in1（43D+L5语义）、in5（阶段先验）
真被消费，其余 in2/in3/in4/in6 在 SE3 模式下不用 —— **必须在输出里写 why**，
否则就是“看着有线其实没人读”。别删边：`SS_MANI_TYPE=su2` 回退时它们还要用。

## 8. L5 引导: **自主标定优先**, 回放点只作参考 (目标来源决定是不是真自主)

分层职责(这条决定架构对不对, 不是实现细节):
```
215 点回放表  = 只读安全基准, L2~L5 只能从它学, 不能改它, 也不能拿它的点当自主目标
L5            = 自主标定: 相机看工件 → 手眼 T_cam2tool → T_tool_base(endInRef) → base_link 3D 目标
L4            = 流形引擎: 用 L5 的视觉目标算 ξ/φ 势场 + 度量
L3            = 模仿学习: obs + cond(L4) → 7 维 action chunk
L2            = 原子技能/标准动作: 从真实轨迹 feed/end_episode 固化标杆
```

**“阶段 → 215 点表区间出口 = T_goal”不是自主标定** — 那是把回放点当目标, 用户明确否掉。
`L5Guide` 的正确优先级:
```
visual_goal()   P_cam→T_cam2tool→T_tool_base→P_base   成立即 return, goal_src="L5_visual"
stage 区间      仅当视觉算不出时退回, goal_src="215点表(参考)" + range_src="均分假设(未标定)"
```
- `visual_goal(port_data)`: 从端口挖相机系 3D 点(`det_xyz_cam`/`xyz_cam`/`peg_xyz_m`/裸 3 元组),
  挖不到就返回 `None` **不编**; 幅值 >5 判为毫米自动 /1000。目标姿态沿用当前工具姿态(位置自主, 姿态暂不猜)。
- 手眼外参读 `models/handeye_state.json` 的 `T_cam2tool`, 加载时验 `det(R)≈1`。
- 置信门控照旧: `conf<0.40 ⇒ k_l5=0`; 视觉目标算出但置信不足 ⇒ 仍返回 T_goal 但 `k_l5=K_MIN` 并标注。
- 取不到语义也取不到视觉 ⇒ `ok=False` + why, 引擎退回 `traj_default` 并如实标。

## 8b. 回放轨迹只读锁: 内容一变就 raise, 不静默继续
`tools/web/real_traj_joints.json` 是 L2~L5 的**唯一安全基准**, 任何层写它就是错:
```python
TRAJ_MD5 = "15e4a986d06eb40f25701fed1270712f"; TRAJ_N = 215
def assert_traj_untouched(path):
    md5 = hashlib.md5(open(path,'rb').read()).hexdigest()
    if md5 != TRAJ_MD5: raise RuntimeError("回放轨迹被修改 …只允许读")
```
在 `_frames()` 加载前调 — 校验点在**每次读**而不是写侧, 因为改它的人可能是别的进程/别的层。
要换代必须经用户确认后**显式更新 TRAJ_MD5**, 那是一次口径变更, 不允许顺手改完继续跑。
验证: 拷一份改一个字节(`0.663`→`0.664`) ⇒ 必须当场抓到 md5 不符。

## 9. 判据要选物理量，别选数值等价物
`R_to_rpy` 验证：用**旋转矩阵往返**（R→rpy→R，500 组 worst=1e-14）；
用“欧拉角数值相等”会因 ry 超出 ±π/2 的等价角假红 88/200 —— 那是多解不是 bug。

## 10. Qwen 权重路径
权重在 `zmax_data/hf_cache/hub/models--Qwen--Qwen2.5-VL-3B-Instruct`（7.1G, 完整），
`hf_home` 是空目录（只有 CACHEDIR.TAG）。`scene_vlm.py` 只找 hf_home ⇒ `_LOCAL_DEF=None`
⇒ 回退联网名 ⇒ 离线必失败 ⇒ `l5_scene_vec.json` 永远 `vec=null, conf=0`。
已改成三根探测（hf_cache → hf_home → ~/.cache/huggingface）。
3B fp16 要约 6-7G 显存，训练占着时起不来。

## 11. A~E 五流形接法 (位置/轴/四元数/滚转/相位) — 五个口径坑

`src/lerobot/manifold/se3_layers.py` 用 **5 个真 ManifoldEngine 实例**承载 A ℝ³(`euclidean`) /
B S²(`sphere`) / C S³(`su2`) / D S¹(`torus`) / E S¹(`torus`), C⇄(B,D) 用 Hopf 耦合;
`MANIFOLD_REGISTRY["se3_layers"]=ready` + `ManifoldEngine.se3_layers()` 惰性构造(不用不建 ⇒ 零回归)。
`ss_engine_loop` 里 `ZMAX_SE3_LAYERS=1` 才每拍算, 写 `rec["se3"]` + `/dev/shm/se3_layers.json`。

1. **C 不许用引擎的 su2 投影器**: 那条分支是 `SU2Element.from_rotvec(bounded_rotvec(v, gain=2.0))`,
   是**有界控制器映射**(转角被 gain 压掉), 当投影用会把四元数改掉。C 的投影=S³ 恒等归一;
   引擎 su2 的**度量**(`e8ds`) 照用 —— 度量链仍是引擎的。
2. **S¹ 用 T² 的退化切片** `[θ, 0]`: 引擎只有 `torus`, 第二角恒 0 时 T² 距离恰等于圆上环绕距离,
   不是近似。D=`[φ,0]`, E=`[2πs,0]`。
3. **`n = R·e₃`, 不是 `R·e₁`**: `tools/se3_hopf.py` 头注释写 `R·e₁` 是笔误, 代码算的是第三列
   (工具接近轴)。判据: 与 R 第 3 列夹角 1.5e-06°, 与第 1 列 90°。别按注释去"修".
4. **Hopf 右逆的纤维生成元是体 z 轴**: `q = s(n)·quat_z(φ−φ_s)`, 截面 `s(n)` 把 **e₃** 转到 n。
   写 `quat_x` 会得 179° 误差(整条轨迹)。叉积顺序也必须是 `e₃×n=(−ny,nx,0)`, 反了转成 −n(误差≈180−0.3°)。
   叉积退化(‖n×e₃‖≈0)时不能直接返回单位四元数 —— 还要按 `acos(c)` 转。
   判据: 215 帧往返 max `2.4e-06°`。
5. **对账别用 arccos 角度**: `traj_hopf.json` 的 n 只存 6 位小数, `dot→1` 时 1e-6 舍入被放大成 0.06°
   的假红。判据看**分量最大差**(实测 5.0e-07), 角度只作参考。测地线判据同理: 只测 `0.5°<d<150°`
   的帧对(近对跖/近重合的中点不唯一, 会把 1e-8 放大成 1e-4)。

实测开销 `0.29 ms/拍`(100 拍 29.3 ms, 预算 100 ms); 真值帧龄 0.14 s 时 A/B/C/D/E 与真值逐项一致。

## 12. 五流形上引擎常驻 + 远端看板 (两个必踩的坑)

- **开启方式**: `systemctl edit` drop-in `Environment=ZMAX_SE3_LAYERS=1` → restart `zmax-ss-engine-loop`。
  `layer_calls.jsonl` 每 10 个引擎周期(1 Hz)多一条 `rec["se3"]`, `/dev/shm/se3_layers.json` 同步。
- 🔴 **E（相位）会钉在末帧 `s=0.9995`**: `snapshot(i=None)` 默认取最后一帧索引。接了实时位姿时必须用
  **TCP 投影到轨迹的最近帧**算 i (`nearest_i()`, 相位连续窗口), 否则 A/B/C/D 在动而 E 不动。
  实测改前整轮 E_s 恒 0.9995, 改后 0.3058→0.3190 随真机推进。
- 🔴 **另一台机看实时信号: 它没有珞石 SDK**。做法 = 在引擎侧的 8797 `GET /api/tcp` 上加
  `Environment=ZMAX_SE3_TRUTH_URL=http://<engine-host>:8797/api/tcp`, 本地 `latest.json` 帧龄>2s 才拉远端;
  远端回包归一成 `{x,y,z(m), qx..qw, joints(rad), ts}`。注意 `/api/tcp` 的 `quat` 已经是 `[qx,qy,qz,qw]`。
- 🔴 **最近点连续性窗口会让停回起点的臂报错帧**: 窗口赢过 2.3mm 的全局最近点时(自交 22 处),
  看板报 `#69 偏轨 2.3mm` 而真实是 `#214`。加一条前置规则: `min(d)≤3mm` 就直接取全局最近, 不走窗口。

## 13. 五流形 → flow matching: 条件编码 + 流形感知噪声 (接法已定, 提升未证)

状态向量的用途从"观测/闸门/看板"扩到"策略条件"时, 照这四条做 (`src/lerobot/manifold/se3_flow_cond.py`):

1. **条件向量 20 维** = A(p/1000,3) + B(n,3) + C(q,4, 统一 w≥0) + D(cosφ,sinφ,2) + E(cos2πs,sin2πs,2) + TQ(q̇/100,6)。
   S¹ 一律 (cos,sin): 裸角度在 0/2π 处跳变。四元数双覆盖必须把 w 统一到 ≥0, 否则同一个姿态两个编码。
2. **噪声不许是 N(0,I)**: 从当前状态出发在各自流形上采 —— B 切平面高斯再走测地线, C 右乘 exp(½σω),
   D/E 环上相加并 wrap, A 欧氏。实测欧氏直接加噪 B **100% 出球面**(范数均差 0.111), 流形采 0%(1e-16)。
   同理 FM 插值路径要在流形上做: C 的欧氏直线中点范数可低到 **0.0175**(姿态信息全丢), 测地线 1e-16。
3. **注入点用现成的头, 不新造**: `multi_task_dit:135 conditioning_vec = observation_encoder.encode(batch)`
   拼 20 维并把 `conditioning_dim += 20`; `smolvla:812 sample_actions(noise=...)` 直接吃流形噪声;
   L3 节点 `engineering/nodes/flow_matching_impl.py` 走的就是这两个头, 不用改。
4. **分开报账**: 只加条件向量 / 加流形噪声 / 换测地线插值路径 三步单独做同口径对照,
   有提升才进默认档(仅不回退只能留影子)。

🔴 **引擎 `geodesic("B")` 的 slerp 分支要先归一输入**: 轨迹 json 的 n 只有 6 位小数(`‖n‖=1±1e-7`),
不归一的中点范数偏 1.7e-7 —— 会被误判成插值实现错。

细节(维度表/σ 取值/实测对照/自检判据/门槛)见 `references/flow-matching-conditioning.md`。

## 改动画布时
六断言 + `_archive` 备份 + 剔除新增后逐条比对，见 `state-space-canvas-engineering`。
本链做到“零画布改动”是因为 `n_vlm_llm → ss_mani_eng in1` 这条线本来就有，只是代码不读它。
