---
name: geometric-latent-branch
description: "Use when 给世界模型加 SE(3)/S² 几何分支、接引擎、L2~L5 部署。"
version: 1.2.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [se3, manifold, jepa, world-model, latent, geodesic, zmax]
    related_skills: [manifold-sphere-geometry, manifold-engine-energy, intact-jepa-integration, su2-unified-state-space]
---

# 给世界模型/潜空间加 SE(3)·S² 几何分支

原生 JEPA 类世界模型的潜空间是**单一欧氏向量**: 姿态误差和纹理语义揉在一起, 预测出的 latent 没有刚体约束,
也直接吐不出可控制量。定式改造 = **共享底层编码器, 上层拆两条互不干扰的分支**:

- **语义分支** (原样不动): 纹理 / 遮挡 / 接触视觉
- **几何分支** (新增): ξ∈se(3) 相对位姿 twist + v_n∈T_nS² 接触法向

目标场景是精细装配的相对位姿 / 接触法向。

## When to Use (何时用)
- 用户给出一份「欧氏语义 + 黎曼几何混合表征」类方案文档, 要落成真代码与判据。
- 要预测相对位姿 / 接触面法向, 而现有模型只输出无几何含义的 latent。
- 要往流形引擎/状态空间里加一条几何通道, 且**不能动在役主干**。
- 现象侧信号: 模型“插斜了但位置对”却完全无反应, 或 PSNR/损失怎么调都不动而几何量从未进过 rec。

## 1. 先查仓里已有的算子, 绝不另造

| 需要 | 现成函数 | 位置 |
|---|---|---|
| SE(3) exp/log/hat | `se3_exp` `se3_log` `so3_exp` `so3_log` `_hat` | `src/lerobot/manifold/lie_intent.py` |
| 接触误差 twist | `contact_twist(T_peg, T_hole)` = `log(T_hole⁻¹T_peg)` | 同上 |
| S² 距离/切映射/测地线/黎曼梯度/三种 loss | `distance` `log_map` `exp_map` `geodesic_slerp` `tangent_project` `sphere_distance_loss` | `src/lerobot/manifold/sphere.py` |
| 法向/切向分解 + 摩擦锥 | `ContactConstraint` | `src/lerobot/manifold/manifold_chain.py` |
| 性能耦合代价 + 帕累托闸 | `PerformanceConstraint` | 同上 |

真正缺的只是「从视觉特征接出的 head + 损失项 + 可拔插开关」。先 `grep -n "def se3_\|def so3_" src/lerobot/manifold/lie_intent.py` 确认,
再决定写什么 —— 造第二份公式必然与既有实现漂移。

## 2. 接入点选共享特征, 不选主干内部

现有 world model 的编码器常是 `Conv + AdaptiveAvgPool(1) + Flatten` —— 空间信息已经压掉了,
所谓"共享 patch token"落地就是那个 256 维向量。几何分支从它接出 ⇒ **主干一层不动**,
原权重 strict load 不破 (新分支用 `strict=False` 单独加载)。

几何分支体量: geo_enc + SE3Head + SphereHead + 方差头 ≈ **10 万参数**,
让它明显小于主分支同等模块 (三层 z_enc ≈100 万) —— 方案要求"轻量"。

引擎侧照现有通道同一模式加三处, 不要发明新接口:
`__init__` 里 `xxx_provider / xxx_note / xxx_w` (env 开关, **默认 0**) · `set_xxx_provider(provider, note)` ·
`_xxx_read()`; `step()` 里 `rec["xxx"]` 与原有通道**并存**。

## 3. 判据 (五组全过才算接进)

1. **未接 provider ⇒ rec 里没有该键** (零回归)
2. **结构完整**: ξ 6 维 / v_n 3 维 / 还原后的 n 是单位向量 / 诊断量齐全, 权重项 `w=0`(只观测不进势)
3. **与原通道并存且不污染**: 原语义通道维数逐位不变
4. **几何算子单调**: 接触流形 `d_SE3` 严格单调且**精确等于平移量** (0→0.001→0.005→0.02→0.05)
5. **开关 = 0 ⇒ 动作逐位相同**: `p_next` `max|Δ| = 0.000e+00`, Φ 逐位相同

## 4. 坑

### 🔴 单调性判据绝不能穿过未训练的网络 (同一个错犯过两次)
几何算子 (`se3_distance` / `decompose_se3`) 的单调性可以直接喂输入测。
但 provider 层的 `d_SE3` 是**「预测 vs 实际」**, 而 ξ 来自**随机初始化的网络** (量级 ~0.109)
⇒ 输入偏移 0→0.05 撼不动这个常数, 测出来反而递减。
定式: **单调性归几何算子, provider 只判「对输入有响应」(跨度 >0)**。
写判据前先问一句 "这个量里有没有未训练的随机项"。

### 🔴 相对位姿的基准必须首步锁定, 不能用单位阵
`T_pred = g_rel0·exp(ξ)` 而 `T_cur` 是**绝对**位姿。把 `g_rel0` 设成 `I` ⇒ 两者坐标系不同
⇒ `d_SE3` 恒带一个固定偏移 (实测 0.109m), 误差怎么变都不收敛。
定式: provider 首次调用时 `self._baseline_T = T_cur.copy()`; 之后 `T_rel = inv(baseline)@T_cur`,
**比较对象用 `T_rel` 而不是 `T_cur`**, 并在 rec 里记 `baseline_locked` 供审计。

### 🔴 欧氏版对纯姿态误差完全失明 —— 这是改造的全部价值, 要钉成判据
纯姿态偏 1°: 黎曼版 `V_p = ½ξᵀW₆ξ = 1.523e-07`, 欧氏版只看 3 维位置差 ⇒ **正好 = 0**。
"插斜了但位置对"在旧实现里不可见。任何声称"黎曼改造有用"的汇报都必须带这一条数字对照,
否则就是没有证据的主观说辞。

### API 口径 (不先看一眼就白跑一轮)
- `sphere.normalize(x)` 返回 **`(array, meta_dict)` 元组**, 不是数组 ⇒ 取 `[0]`。
  同族的 `tangent_project` / `exp_map` 也可能带 meta, 接之前先 `type()` 看一眼。
- `ManifoldEngine.step(state, potential_fn=None, dt=...)` —— **第二个位置参数是 `potential_fn`**, 不是速度。
  传 ndarray 会报 `'ndarray' object is not callable`。
- `PerformanceManifold.evaluate(peg_head)` 的欧氏对照必须喂 `p.hole_pos`, **不能喂原点** ——
  `HOLE_POS` 不是 0, 喂原点会得到一个假的不为零的 `V_p`, 让人误判"欧氏版也看得见姿态误差"。
- 测 `ManifoldEngine` 用 `homeostasis=False`: 否则每步原子写 `zmax_data/ss_live/manifold_homeostasis.json`,
  与常驻引擎回路抢同一文件, `os.replace` 偶发 `FileNotFoundError` (tmp 被对方删掉)。
  这不是引擎 bug, 是测试隔离没做。
- **法线必须开 antipodal 消歧**: `d(a,b)=arccos(aᵀb)` 在 `a=−b` 时给 π, 但接触面法线"反了"与
  "错 90°"不是一回事 ⇒ 用 `sphere.distance(..., antipodal=True)`, 实测法线反向时 risk=0。
- 方差头用**对角 Σ**: 输出 log-std 再 `exp` ⇒ SPD 必然成立, 不需要 Cholesky 约束。
  切空间高斯 NLL 写成 `0.5·Σ[(ξ−μ)²/σ² + 2logσ + log2π]`, 自检要能手算对平。
- **NLL 训练时必须夹 σ 下限** (`clamp(log_sigma, min=log(5mm))`)。不加时 σ 一路压到 0,
  NLL 靠"声称自己绝对准"刷到 -26 再反弹, 而回归项早已收敛到 1e-4 —— 曲线看着在降,
  实际是方差塌缩。插装配 5mm 已是"对不准"的量级, 再小无物理意义。训练日志要把
  `sigma_mean` 打出来盯着, 否则塌缩在 loss 曲线上看不出来。
- `hjepa_manifold.tangent_gaussian_nll` 是 **numpy** 实现: 塞进 torch 训练循环会返回 float
  而不是 tensor, backward 直接断链。训练循环里内联等价式 (返回 `sum(dim=-1)` 的 tensor),
  别复用 numpy 版。

## 5. 损失与训练节奏

```
L_g = ‖log(g⁻¹·g*)‖²          # 用 lie_intent.se3_log
L_n = arccos(nᵀn*)²           # 小角度可退 ‖n−n*‖²
L_total = L_jepa + λ_g·L_g + λ_n·L_n
```

- **网络永远只输出切空间向量 (欧氏)**, 不输出流形元素 —— 这是避开黎曼层/黎曼 BN 不稳定性的关键,
  也匹配精细操作的"小扰动"假设。
- `λ` 从 `1e-2 ~ 1e-4` 起步 (JEPA loss 量级远大于几何 loss)。
- **分三阶段预热**, 不然几何分支被语义 loss 主导: ①只训主干 (冻结几何分支) ②冻结主干+语义分支,
  只训几何 (先法线后 SE3) ③全放开联合微调。
- 动量 target (EMA, 冻结梯度) 与 JEPA 理念一致: 目标来自动量编码器而非人工标签,
  适配无标注时序视频; 有真值姿态时可切监督版。
- 时序 rollout: `ξ_{t+τ} = f_dyn(c_t, h_g_t, a_t)` → `g_{t+τ} = g_t·exp(ξ̂_{t+τ})`。

## 6. 汇报纪律

仓里现成的 JEPA 权重可能**对画面几乎不敏感** (实测 8 张真帧输出余弦 1.00000、对 state ±0.3 扰动余弦 0.995)
⇒ 那是"欠训练的世界模型通道", 不是看图编码器。几何分支同样只对 state 有响应。
**必须写清"这是结构接通, 不是能力达标"**, 不能暗示模型在学画面。
同理: 用合成数据跑的 e2e (PSNR 5.6) 只证明通路, 不代表质量, 汇报时要标出。

## 7. 几何量进 L2~L5: 是**约束**, 不是新的"力"

`tools/layer_forces.py` 是分层力的唯一表, 里头的"力"全是 **3 维速度矢量**
(L2=`chunk_latest.ff[0]` 前馈 · L3=`chunk[0]` 动作头 · L4=`M̂·u_ff` 度量 · L5=场景矢量)。
几何量 (6 维 twist / 3 维切向量 / 测地线距离) **不能塞进这个表当第五路力** —— 量纲和语义都不对。

正确落法: 几何量只出"放行 / 限幅多少 / 权重多少", **不产生动作**, 符合
「上层给意图和条件 → 可行域逐层收窄 → 执行由 L2 收口」:

| 层 | 几何量用途 | 出口 |
|---|---|---|
| L2 执行收口 | `d_normal` / `d_se3` → 横向限幅系数 + veto | 法线 ≥5° 或位姿 ≥20mm ⇒ veto, 禁止推进 |
| L3 阶段条件 | `d_se3 ≤2mm` AND `d_normal ≤1.5°` AND `σ_max ≤0.2` 三条同时满足才放行 | 只给 allow/why, 不推进 |
| L4 度量调制 | ξ 方向 + `log_sigma` 置信 → `M` 各向异性倍数 | 只改 base_M, 不动动作 |
| L5 规划条件 | 动力学 rollout 未来 n 步位姿序列 | 无动力学模型时**如实标"匀速外推"**, 不许当预测卖 |

阈值写成模块级常量 (2mm / 1.5° / 5° / 20mm / σ0.2), 现场按标定覆盖, 不预先固定进逻辑分支。
自检要覆盖: 限幅随偏离**单调降**、三种阶段条件**各自单独触发拒绝**、`ξ=0` 时退化为各向同性、
无动力学时 why 里必须带"匀速外推"字样。

几何分支只负责**看** (预测 ξ / v_n / 测地线距离)。要把它变成**推** (体坐标力扭 / 关节力矩)
是另一件事, 归 `se3-impedance-control`: 那里有 Adjoint 分块、`[ρ;ω]` 分量顺序、
误差 twist 符号、被动性硬闸与 `J_b` 映射的完整流程。两条通道可以同时接, 不冲突。

## 8. 三档部署与自主进化 (550C → 550B → 550A)

`550C=Intel 端侧` 跑进化 · `550B=4060` 回传落盘 · `550A=4060` 拿回传超参训练。一条编排脚本
三个子命令 (`--c-evolve / --b-pull / --a-train / --all`), 但**子脚本各自独立文件** ——
把源码塞进 `'''...'''` 字符串再 ssh 推过去, 内层 `"""` 与拼接残留会把文件边界搞乱
(报 `unterminated triple-quoted string`, 或删错行把子脚本内容泄漏进主文件)。

- Intel 上**系统 `python3` 没有 torch**; 有 XPU torch 的是 `~/train_venv/bin/python`。
  service 的 `ExecStart` 与 ad-hoc ssh 命令都要指它, 否则 `ModuleNotFoundError: torch`。
- 推代码走 `tar czf -` 管道时 **`subprocess` 不能用 `text=True`** —— gzip 是二进制,
  会 `UnicodeDecodeError: 0x8b`。用 `capture_output=True` 拿 bytes 再 `input=`。
- 端侧是**扁平 .py**, 本地是包结构 ⇒ import 写成 `try: from lerobot.manifold.x import ...`
  `except: from x import ...` 双兼容, `sys.path` 同时插 `src/` 和目录本身。
- 常驻: 进化器"跑 N 代就退出 + 台账跨轮续", 外面套 `while true; sleep 180` 即可,
  不必改进化器主循环。`ExecStartPre` 断言 `torch.xpu.is_available()`。
- 550C 在没有真机位姿时只能用**合成轨迹**, 550A 必须用**真机位姿**
  (从 `gs_train_service/jobs/*/ds/cameras.json` 的 `T_cam2world` 读, 先打帧间位移
  min/med/max 判断数据是否可信 —— med <0.1mm 说明这批位姿几乎同一个点, 学不到运动)。
  汇报时两者数据来源必须分开标。

### 🔴 无标注时的适应度必须防三种假提升

没有逐帧 6D 标注时, 几何分支的适应度只能靠**自洽性** (SE(3) 时序平滑 + 法线平滑 + 切空间 NLL)。
这容易自欺, 三条都必须做:

1. **适应度权重固定, 绝不许参与变异**。实测让 `w_nll` 一起变异时, 分数 6.17→11.89 全靠
   `w_nll` 0.30→0.98, 模型本身一点没变好 —— 典型平凡基线式假提升。只变异模型超参
   (lr / steps / 隐宽 / 层数 / 正则项), 权重预先固定。
2. **各分量先归一化再加权**。`f_se3` 是 `-1e-4` 量级、`f_nll` 是 `-12` 量级, 原样加权 ⇒ NLL 完全主导,
   另外两项白测。各自除一个参考尺度 (如 `1e-2 / 1e-2 / 12`) 再乘固定权重。
3. **台账里同时记原始分量和归一化分量**, 汇报时能一眼看出分数是哪个分量贡献的。
4. 🔴 **安全/物理约束必须是硬闸, 不能做成加权项**。被动性 (`V̇≤0`)、力矩限幅、碰撞禁区这类
   一旦违反就必须「整代判废」; 写成加权项会被收敛类的满分掩盖过去。
   加权是**性能**判据的形状, 硬闸是**安全**判据的形状, 两者不能混。
   同理, 硬件保护参数 (如 `u_max`) 不进搜索空间 —— 进化不许把限幅抬大来换分。

### 🔴 适应度"收敛不动"要如实报

合成轨迹上跑到 `0.5951~0.5995` 连续多代全回滚, 就是**已经触顶**, 说明这批数据没有可学的东西
(几何平滑量本来就 ≈0, `raw se3` 到 `-1e-6`)。正确说法是"链路通、数据不足以支撑进化",
不能包装成"自主进化成功"。

## 9. 方案3: 双向跨模态 (两模态平等) 与塌缩硬闸

方案1 (`GeometricBranch`) 是**单向**: `z_vis ─条件─▶ 几何头 ─▶ ξ`。方案3
(`hjepa_m3.build_m3_jepa`) 把两个模态摆平, 再加一条**反向**预测, 两侧在联合嵌入空间对齐:

```
z_vis ─▶ e_vis ─▶ ξ_pred        # 图像预测几何
ξ     ─▶ e_geo ─▶ z_vis_pred    # 几何预测图像   ← 方案1 没有这条
```

价值: 视觉表征被刚体运动学**反向塑形**(方案1 的几何只能读视觉, 不能反过来影响它)。
代价: **跨模态塌缩** —— 这是方案3 唯一真正的风险, 也是它出名的"训练不稳定"。三条定式:

1. **对齐项必须是 InfoNCE, 不能是 `(1−cos).mean()`**。后者最省力的解是把所有样本挤到球面上
   同一点: 余弦立刻 =1, loss 看着极漂亮而嵌入零信息(实测 loss 2.70→0.62, 但 `std` 只有
   0.07/0.09、`cos=0.98`)。InfoNCE 拿 batch 内其他样本当负样本, 塌缩时 CE 涨到 `log B`,
   天然反塌缩。
2. **防塌缩正则要和 CE 同量级**。CE ≈ `log B` ≈ 3.4, 方差/协方差权重给 1.0 会被完全压过;
   用 3.0。权重不动, 调的是正则项的倍数。
3. **塌缩判据用有效秩, 不用"每维 std ≥ γ"**。VICReg 的 `γ=1.0 ⇒ 判据 0.25` 是给 **2096 维**
   嵌入定的; 16 维的 `std` 稳态就在 0.22, 而且 120 步与 350 步几乎一样(0.2166→0.2263)
   ⇒ 那是**稳态不是训练不足**, 拿 0.25 去卡只会误判成失败。公式与阈值见
   `references/cross-modal-collapse.md`。

**进化里塌缩是硬闸, 不是加权项**: 塌缩时对比 loss 极低、`img2geo` / 对角优势看着都不差,
加权一定被骗。与被动性硬闸(§8.4)同一种形状但理由不同 —— 那条是**安全**, 这条是**统计退化**;
两者都不许进搜索空间当可调项。

实现位置: `src/lerobot/manifold/hjepa_m3.py`(`build_m3_jepa` / `collapse_score` /
`effective_rank`), 进化器 `tools/hjepa_m3_evolver_intel.py`。两方案**并存**, `HJEPA_M3` 默认未接
⇒ 方案1 通道逐位不变。
