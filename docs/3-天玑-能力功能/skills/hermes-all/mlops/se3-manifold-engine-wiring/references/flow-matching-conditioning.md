# 五流形状态 → flow matching 条件与噪声 (recipe)

代码: `src/lerobot/manifold/se3_flow_cond.py` (`SE3FlowCond`, `selftest()`)
自检: `cd src/lerobot/manifold && python3 se3_flow_cond.py` → `ok: true`
数据: `zmax_data/se3_flow_cond/selftest.json`（含欧氏 vs 流形对照）
依赖: `se3_layers.SE3Layered` 的帧源与 `geodesic()`、`se3_hopf.hopf/hopf_join/q_normalize`

**现状定位**: 五流形目前只做观测/闸门/看板, 没进任何训练目标。本 recipe 给的是“可接、接法确定、可判据”,
**不是“已经提升”**。

## 1. 条件向量 20 维 (layout 写进常量, 别在调用处散着拼)

```
A  [0:3]   p_mm / 1000                     ℝ³   3
B  [3:6]   n (单位, 工具接近轴 R·e₃)       S²   3
C  [6:10]  q=(x,y,z,w), 统一 w≥0           S³   4
D  [10:12] (cos φ, sin φ)                  S¹   2
E  [12:14] (cos 2πs, sin 2πs)              S¹   2
TQ [14:20] q̇_deg_s / 100 (无量纲)          切空间 6
```

三条口径理由:
- **S¹ 用 (cos,sin)**: 裸角度在 0/2π 处跳变, 线性相减会把 179°→−179° 算成 358°。
- **四元数双覆盖**: q 与 −q 同一姿态 ⇒ 编码前把 w 统一到 ≥0, 否则同一个位姿有两个条件向量,
  网络学到的是符号噪声。
- **位置除以 1000**: 与其余量级对齐(mm 量级进网络会压掉其它分量)。

## 2. 噪声 (x0) 在各自流形上采, 不从 N(0,I) 直接加

```
A:  p + σp·N(0,I3)                         σp = 20 mm
B:  v⊥n 切平面, θ=‖v‖ ⇒ n' = cosθ·n + sinθ·v̂   σ = 8°
C:  q ⊗ exp(½σω), ω~N(0,I3)  (右乘, 保单位)   σ = 12°
D:  φ + σN, wrap 到 [0,2π)                  σ = 10°
E:  s + σN, wrap 到 [0,1)                   σ = 0.02
TQ: v·(1 + N(0,σ))                          σ = 0.10
```

实测对照 (2000 样本, 40 帧真机姿态):

| | 欧氏直接加噪 | 流形上采 |
|---|---|---|
| B 出球面比例 | 100% | 0% |
| B 范数平均误差 | 0.111 | 1.1e-16 |

| | 欧氏直线插值中点 | 测地线中点 |
|---|---|---|
| C 范数 均值 / 最小 | 0.772 / **0.0175** | 误差 1.1e-16 |

结论: 欧氏插值/加噪的中段会跑到流形外(S³ 上范数 0.0175 = 姿态信息全丢), 去噪网络得先学“回到流形”,
那部分容量本该用来学动作。

## 3. FM 插值路径走测地线 (与引擎同一份 `SE3Layered.geodesic`)

```
x_t = {A: geodesic(A0,A1,t), B: geodesic(B0,B1,t), C: geodesic(C0,C1,t),
       D: 环上最短角插值并 wrap, E: 同上(Δs 取 (−0.5,0.5] 的那个方向), TQ: 线性}
```
- E 的 Δs 必须取环上最短方向: `ds = (s1-s0+0.5) % 1.0 - 0.5`。
- 🔴 **`geodesic("B")` 的 slerp 分支要先归一输入**: 轨迹 json 的 n 只有 6 位小数(‖n‖=1±1e-7),
  不归一时中点范数偏 1.7e-7(会被误判成插值实现错)。归一后 0。

## 4. 注入点 (仓里已有 flow matching, 不新造头)

```
multi_task_dit  src/lerobot/policies/multi_task_dit/modeling_multi_task_dit.py:135
                conditioning_vec = observation_encoder.encode(batch)   ← 拼 20 维, conditioning_dim += 20
                :196 compute_loss(...) / :136 conditional_sample(...) 不用改
smolvla         src/lerobot/policies/smolvla/modeling_smolvla.py:812 sample_actions(noise=...) ← 吃流形噪声
L3 节点         src/lerobot/engineering/nodes/flow_matching_impl.py   走上面两个模型, 不用改
```
速度场输入形状 `[x_t(20), t(1), cond(20)] = 41` 维(`vector_field_input`); 条件段必须逐位不被噪声污染
(自检 `cond_tail_identical=true`)。

## 5. 自检判据 (跑一次就要全绿, 否则别往里接)

```
编码      40 帧全部 20 维, w≥0, 无 NaN
噪声      40 样本: B/C 范数偏差 0, D/E 值域 0 越界
插值      t=0 误差 0.0 mm, t=1 误差 0.0 mm, 中点出流形 0 次
网络输入   41 维, 条件段逐位一致
耗时      0.21 ms/条件 (10 Hz 预算 100 ms 的 0.2%)
```

## 6. 分步落地 + 门槛

```
S1  只加条件向量, 噪声仍在欧氏          ┐
S2  换流形感知噪声                       ├ 每步单独同口径对照(同数据/同折/同评估函数)
S3  换成测地线插值路径                  ┘
```
有提升才进默认档; 仅“不回退”只能留影子。报数要给动作误差与成功率两项, 只说 loss 下降不算。

## 7. 回答“能不能做成条件编码噪声注入 flow matching”时的口径

先人话后数据, 三句话说完:
1. 能接, 注入点就在 `observation_encoder.encode` 与 `sample_actions(noise=)`, 不新造模型头。
2. 已经跑出自检(20 维条件 / 流形噪声 0 出界 / 插值端点误差 0 / 0.21 ms)。
3. **还没训练, 所以没有“有提升”的证据** —— 不许把“能接”说成“已经提升”。
