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

## 改动画布时
六断言 + `_archive` 备份 + 剔除新增后逐条比对，见 `state-space-canvas-engineering`。
本链做到“零画布改动”是因为 `n_vlm_llm → ss_mani_eng in1` 这条线本来就有，只是代码不读它。
