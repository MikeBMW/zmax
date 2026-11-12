---
name: su2-unified-state-space
description: Use when 统一状态空间/流形引擎按 SU(2) 映射各层, 或接 L4 潜与 INTACT.
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [lie-group, su2, state-space, quaternion, bloch, zmax, canvas]
    related_skills: [zmax-state-space-architecture, simulink-flow-engineering]
---

# 统一状态空间 = 群 (SU(2) 二阶特殊酉群)

## When to Use
- 用户要把"统一状态向量/观测拼接"升级成**统一状态空间(一个群)**: "统一状态空间其实是一个群"。
- 需要把**多层**(执行/规划/自主/大模型 L2/L3/L4/L5)与**多节点**的数据"全面映射"到同一个数学对象里观察/理解。
- 需要天然带"合成/分解/距离/耦合"语义的状态表示(而不是拼接向量)。

## 数学骨架 (先把定义钉死, 再谈映射)
```
SU(2) = { U ∈ C^2×2 : U†U = I, det U = 1 } = { U(ω)=exp(−i ω·σ/2) : ω ∈ R³ }   σ=泡利矩阵
四元数表示  U = w·I − i(x σx + y σy + z σz),  (w,x,y,z) 单位四元数 ⇒ U ≅ S³
群运算      U1·U2 = 哈密顿四元数积 (不可交换);  U⁻¹ = U† = 共轭四元数
李代数      ω = 旋转向量, θ=‖ω‖ 旋转角, n̂=ω/θ 旋转轴
log 主值分支: half = atan2(‖v‖, w), ω = n̂·2·half  (保证 exp(log U)=U 精确; 别用 arccos|w| 近似)
可观测量    Bloch 向量 r = (2(wy−zx), 2(wx+zy), w²+z²−x²−y²),  ‖r‖ ≡ 1 (纯态, 全在球面 S²)
            θ = 2·arccos|w| (偏离角) · |w| = cos(θ/2) (与参考态对齐度/收敛度)
            距离 Fubini–Study arccos|⟨U1,U2⟩| · 不可交换性 ‖[U1,U2]‖₂ (层间耦合强度)
```
语义: **U = I ⇔ 场景收敛(误差为零)**; n̂ = 状态方向; θ = 偏离幅度 ⇒ 轨迹即 θ↓ / |w|↑ 的收敛过程。

## 有界映射律 (任意数据都能进群, 且可视化不会自相矛盾)
```
ω = π·tanh(gain·‖v‖)·v̂        # 任意实向量 v → su(2) 系数 → U = exp(−i ω·σ/2)
```
性质: ① θ 对 ‖v‖ **严格单调**(误差越大越"激活") ② 方向 n̂ 完全保留 ③ **θ<π 恒成立, 永不绕圈**
④ ‖v‖→0 ⇒ U→I。
**别用 `ω = gain·v`**: θ 会超过 π 绕回, 轨迹与读数出现"θ≈π 与 θ≈0 混在一起"的假收敛。

## 表示边界: SU(2) 只装朝向 —— 坐标/位姿要用 SE(3)
用户会提"用 SU(2) 群记录每个 object 的 3D 坐标位姿"。**照字面办会建错数据结构**, 先纠正:
```
SU(2) ≅ S³ ≅ 单位四元数 (w,x,y,z)   ⇒ 只有 3 个旋转自由度, 没有平移
(x,y,z) 是平移                       ⇒ SU(2) 里装不下
位姿 = SE(3) = SO(3) ⋉ ℝ³            ⇒ 存二元组 (U, t): U∈SU(2) 表朝向 ✓  t∈ℝ³ 表位置 ✓
```
1. **朝向用 SU(2) 是对的**(本文其余部分照用); **位置必须显式存 ℝ³**, 两者合成 SE(3) 才是完整位姿。
2. **别拿有界映射律存绝对坐标**: `π·tanh` 在 ‖v‖ 超过饱和点后压平 ⇒ 相距很远的两个物体映射到几乎
   同一个群元素, 位置不可反演。有界映射律的用途是**误差/状态向量 → 群元素**(可视化、收敛判据),
   **不是度量存储** —— 混用会让"地图上两个不同物体"看起来是同一个状态。
3. **单个 object 的结构化记录** = `(U, t)` + 尺寸 + 点云质心 + 协方差(边界不确定度)。
   朝向误差的规范算法: `U_err = U_obj⁻¹·U_target`, `θ_err = 2·arccos|w|`(对齐/收敛判据, 交最下层收口)。
4. 已有**外部位姿真值**(运动学/编码器, 如 50Hz TCP)时, 不要再叠一层 SLAM 去估相机位姿 ——
   那是把两个误差源相加; 直接用"深度反投影 + 已知位姿"做体素融合。SLAM 只在**没有**外部位姿时才是对的答案。

## 「四元数 = 游标卡尺」: 成立条件与判据
用户会说「任意旋转一一映射到 S³ 上的一段轨迹, 所以算轨迹 = 执行动作」。分成两半回答, 两边都要能跑数字:

**尺子那一半 (数学) 可以做到精确**, 但与有界映射律是两个模块, 别混:
- 尺子 = 精确 exp/atan2: `q = [cos(θ/2), sin(θ/2)·n̂]`, 逆映射 `ω = n̂·2·atan2(‖v‖, w)`; **不做 tanh、不裁剪**。
- 有界律 `ω = π·tanh(gain‖v‖)v̂` 只是**误差指示器**: 实测 100mm→35.5°、1000mm→173.5°、5000mm→180°,
  角分辨率从 6.3e-3 掉到 2.8e-5 rad/mm (200×) ⇒ 大误差段多对一, 不可反演, 不能当执行尺子。
- 刻度关系必须写对: **S³ 两点夹角 = 物理转角的一半** (90° 旋转在球面走 45°)。写成 1:1 是量错尺子。
- 双覆盖 q≈−q 必须先商 (归一到 w≥0, w≈0 按首个非零分量定符号), 否则轨迹在符号跳变处出现假长弧/假 π。
- 落地判据 (全机器精度): 随机 2e4 旋转往返 ≤1e-15 · 轨迹逐点单位模长 ≤1e-16 · canonical 幂等 · 90°→45.000000° ·
  0.1°→0.05°。工具: `state_space/pose_caliper.py::selftest()`。

**“算轨迹 = 执行动作”那一半要三个前置**, 缺一个就只能叫“算了一条姿态列表”:
1. **计划里必须有姿态流**: 段表逐段带 `quat` + `quat_src`。校验的是覆盖率而不是“字段存在”——
   实测 AR 段表 392 段 **0 段带 quat**、点位台账也无姿态 ⇒ 姿态弧长 0.000°, 尺子没有可量对象。
   这种情况脚本必须报 **blocked**, 不许 hold/单位姿态冒充姿态轨迹。
2. **段间连续**: 逐段比 `prev.b` 与 `next.a`, 统计 >5mm 的断点数 (实测全表 27 处、最大 905mm)。
   断点不补过渡段 = 执行端“瞬间到位”, 时间口径也白报。
3. **限幅自洽**: 段内若走 5 次最小加加速度 (S 曲线), **峰值 = 1.875×均值** (实测 631mm/s 均值 → 1183mm/s 峰值,
   超 1000mm/s 现场限幅) ⇒ 时间要按峰值重排, 否则节拍虚报。
姿态序列生成器: `tools/se3_pose_path.py` (位置 S 曲线 + 姿态 slerp, 输出逐点 `pos_mm/q/theta_so3_deg/quat_src`)。
同一张 392 段表按四个口径能报出四个 UPH —— 报数必须带阶梯, 不许只报最大那个:
`段表 t 直加 313 → 补段间过渡 292 → 按峰值限幅重排 277 → 台账同 label 实测 216`。
执行端要真按它走, 还需 IK 位姿跟踪 + 姿态到位判据 (位置≤tol AND 姿态≤0.5° 两连判, 缺姿态 fail-closed),
且属真机动作 —— 必须走现场授权, 不在本地“先跑一下”。

## 层合成与反演 (上层只给意图/条件, 执行由最下层收口)
```
U_scene = U_L2 ⊗ U_L3 ⊗ U_L4 ⊗ U_L5      # 群乘, 顺序敏感(右乘=后作用的层)
反演/观察: 逐层左乘逆元 U_Li⁻¹·U_scene → 读残余 θ 变化 = "这一层贡献了多少"
自洽校验: 全部剥离后残余 θ ≈ 0 (回到单位元) — 4 次群乘的浮点残差应 ≤1e-6
层间耦合: ‖[U_i,U_j]‖₂ (值大 = 两层强依赖/顺序敏感; 实测 L2|L4 最强 0.587)
```
各层取"该层真正产生的量": 执行层=几何误差(目标件头 − 孔位); 规划层=流形进度/法向偏离/剩余深度;
自主层=限幅后动作范数/接触概率/(1−性能流形效能); **大模型层=意图向量, 未接入时诚实取单位元**
并在日志写明"该层未接入"(不要编造意图数值)。

## 节点级"全面映射"
给每个画布节点定义"取哪个输出当状态向量"的语义规则表:
`("vec", label子串, k)` / `("slice", label, i, j)` / `("diff", labelA, labelB)` / `("chans", [...])`。
数值可能藏在**字符串**里(`xy=(0.096,0.520) conf --`) → 正则提数; 提不到就**返回空 → 该节点取单位元
并在报告里标注"本帧无数值输出"**(诚实标注, 不编造)。全场景态 = 各节点群元素按链路顺序群合成。
加层/加节点只改这张表, 不动画布。

## 群公理自检 (每次改动后跑; 报数值, 不报"通过")
封闭性(酉性/det=1)、结合律、单位元、逆元、exp∘log 与 log∘exp 互逆、‖r‖=1、|w|=cos(θ/2)、
距离对称/三角不等式、**映射封闭性(大值脏输入 0 个坏元素)**。实测全项 ≤1e-15, 平均不可交换角 ≈1.32 rad
(证明非阿贝尔)。把这份 self-test 做成可直接跑的脚本/节点, 而不是只在头脑里相信。

## 对称性/等变性硬检验 (说「用对称性做泛化」之前必须先跑)
群公理自检只证明「这是群」，**不证明「这套实现在跨位姿时等变」**。要后者，把命题拆成四条当场量:
E1 等距性 / E2 预测等变性 / E3 判据不变性 / E4 零样本换位姿(同段 vs 旋转90° 的一步误差比)。
全过才可对外说「换位姿不需要新数据」。三个必踩的坑: 四元数双覆盖 q≈−q 要**两侧**归一到 w≥0
(否则假误差 π)、量迁移性只能**开环一步**(闭环多步的漂移会把结论反过来)、阈值按 float32 地板定
(1e-12 会把正确实现判死)。完整量法与实测基线见 `references/equivariance-verification.md`。

## 可视化: 一个载荷喂所有视图
`viz_payload(frame, obs43, node_states, history)` 统一返回
`scene / s3 / bloch / layers / nodes / understand / trajectory` → Bloch 球(拖动旋转/滚轮缩放/轨迹)、
S³ 分量、层贡献+反演表、层间不可交换与 FS 距离热力矩阵、节点映射全景、阶段轨迹, 以及"打开其它可视化
工具"的入口。**所有可视化层都从这一份载荷取数** = 契约, 避免各视图口径漂移。

## 两套 SU(2) 生产者: 引擎 p ≠ 统一状态空间 U_scene (报口径前先分清)
同一台机器同时有两个 SU(2) 四元数, 都住 S³, 但输入/算式/落盘都不同 —— 说"球上的轨迹/状态空间输出"前必须指明是哪一个:

| 量 | 谁算 | 输入 | 算式 | 落盘 |
|---|---|---|---|---|
| 引擎导航点 p | `manifold_engine.project`, ss_engine_loop 每拍 | `z_latent[:3]` (L4 潜表示; 编码器接不上=内建 PCA) | `from_rotvec(bounded_rotvec(z[:3], gain=2))` | `/dev/shm/zmax_ss_engine/engine_*.jsonl` · `engine_latest.json` |
| 场景态 U_scene | `compose_scene(encode_layers(...))`, 画布 ssobs 节点 | frame 分层量 + obs43 几何误差(光模块头−孔位) | 四层群乘 U_L2⊗U_L3⊗U_L4⊗U_L5 | 只在内存 `_SS_STATE`; 落盘仅 `quat_truth_latest.json` 的 q_fused |

- **出处判据(必做)**: 取同一拍 `engine_latest.json`, 用 `z_latent[:3]` 重算 p 再对比 —— 实测最大差 3.15e-07
  ⇒ 球上那串点确定是引擎 p。重算不成立 = 代码被改过, 以重算为准, 不许沿用旧结论。
- **`z_source` 必须一起读**: 写着"回退内建 PCA"时 p 的输入是 PCA 投影, 不是 VLM 潜表示 ⇒ 可以画,
  但不能说成"L4 视觉潜空间"。同理 `provider=traj` 说明源是仿真回放帧, 不是现场画面。
- U_scene 代价实测 **0.43 ms/次**(四层合成+剥离+不可交换矩阵, 50 次均值) ⇒ 10Hz 回路(预算 100ms)放得下;
  要球画真输出就让 ssobs 每拍 push 并把 `scene.as_dict()` 追加一条 jsonl, 球改读它 —— 不许拿引擎 p 冒充。
- 一键判定: `scripts/verify_su2_output_provenance.py`(重算 p + 打 z_source + 指明 U_scene 出处)。

## 三个出口: out1 观测体 / out2 分层结构 / out3 参考姿态 (问"输出了没"先分清哪个口)
`ssobs` 节点(`src/lerobot/middleware/nodes/impl/ss_obs.py`)一拍吐三样, 下游按语义取, 不许互相顶替:

| 口 | 内容 | 判据 |
|---|---|---|
| out1 | 43D 观测体 (与 L2 编码**同一拍同一份** obs43) | `out1.kind=obs43 dim=43` 且与 L2 输入逐位同源 |
| out2 | 四层结构体 `kind=su2_layers`: 每层 θ/方向/可见度/权重/贡献 + 场景合成 | `out1 != out2` (历史上 out2 曾是 out1 的副本) |
| out3 | 只读结构体: 主层/层剥离/不可交换/权重/`predict`/`quat_ref` | 出口里**不许有下发字段** |

- 层权重取代手调增益: `w_L = 该层有没有数 × 时效`(L5 半衰 30s, 过期即 0), 加权在**群内**做(slerp/角缩放)而不是向量平均。
  判据: 全权重=1 时必须与旧 compose **逐位相同**(零回归), 且 w 0→1 必须真改场景(Δθ≠0) —— 两条都过才算权重不是摆设。
- 预测先行只外推**观测输入**再编码成群元素去比; 直接外推群元素会被 tanh 非线性污染(平稳段就有 3~8° 假残差, 突变被淹没)。
- 验收: `./gui-venv311/bin/python tools/verify_su2_layers.py` —— A1~A4(出口语义) · B1(零回归) · E1(剥离残余) ·
  C1~C2(权重四态与真实生效) · D1~D3(平稳残差 0 / 突变 4.17° / 出口无下发字段)。

### 参考姿态进执行链 (群元素 → 段表 → 执行器)
链路: `ssobs.out3.quat_ref`(xyzw, 附 `quat_ref_order` / `quat_ref_src`) → 段表同段 `quat:"su2"|"ref"` 或 `quat_ref`
→ `src/lerobot/engineering/exec/daemon.py::_ref_quat` → 既有"位置≤tol **AND** 姿态≤0.5°"双判据。
- **默认零变化**: 段表不写 `quat` / 不给 `quat_ref` 就不进这个分支 ⇒ 改这条链不用回归老任务。
- **fail-closed**: 3 分量 / 非单位 / 非数值 / `quat_ref_order != "xyzw"` 一律拒发, 宁可不发也不发坏姿态。
- 验收: `./gui-venv311/bin/python tools/verify_pose_chain.py` —— P1 节点吐合法 q · P2 六轴对齐 0.000° ·
  P2b 分量顺序转换 · P3 执行器认 `su2:quat_ref` · P4 四类坏输入全拒 · P5 默认段不进入 · P6 容差 0.5°。
- 回答"参考位姿输出了吗"必须分三层, 缺一层就是谎报: ①**代码/节点层**(验收脚本 P1 有数) ②**实时层**
  (常驻回路在跑 `systemctl is-active zmax-ss-canvas-loop`, 且段表真带 quat) ③**下发层**(真机授权)。
  段表 0 段带 quat 时正确说法是"**通道在、未启用**", 不是"输出了"。

## 四元数怎么交给流形引擎: 只给该给的通道 (别塞编码器)
统一状态空间交给引擎的**实际数据 = 统一状态向量**(`ss_engine_loop`: `state = O[idx, :STATE_DIM]` → `eng.step`), 不是四元数;
四元数是引擎自己从 `z→project()` 投出来的 p。**标准口径 55 维**(`STATE_DIM` 默认 55, 由 `ZMAX_STATE_DIM` 覆盖);
老 43 维轨迹由引擎做 43↔55 自适配(尾部补 0, 口径写进 `conform_note`) ⇒ 前 43 维语义一字不动。报"引擎吃了多少维"先看 `state_dim`, 别沿用旧文档的 43。
```
[ 0:39] 视觉与本体  tcp_p3 | grip_scalar1 | peg_xyz3 | peg−tcp3 | grip_xy2 | q_right6 | dq_right6 | tcp_R9 | target3 | hole3
[39:43] 触觉力觉    grasp | contact | dir_x | dir_y
[43:55] 预留 12     finger_pressure4 | temperature1 | acoustic1 | current2 | spare4   (默认全 0 = 沉睡, 按名 extra 才唤醒)
```
分段唯一依据 `src/lerobot/policies/left_right/state_space/unified_state55.py`(`SLICE` / `layout_table()`), 消费端禁止自己数下标。
要把 q 接进去, 只有四条通道, 取舍已逐条实测:

| 通道 | 做法 | 结论 |
|---|---|---|
| 编码器输入 | 47 维 (43+q4) 或塞进现有 43 维 | ✗ 破坏按 43 维标定的潜空间(`manifold_engine.npz`, 标定帧极少); 且 q/−q 同旋转, 线性编码器当成两个输入 |
| 目标群点 | `eng.goal_point = q` | ✗ 先别接: 357 帧系统实测 **不存在刚性对齐** —— 同帧夹角中位 76.4°(p10 61.8 / p90 147.3), 用首帧做固定对齐后残差中位仍 157.8°, 相邻帧转角相关仅 0.284 ⇒ p 空间里的 I 不等于"几何到位"; 要接先训 q→p 映射, 不是改一行 |
| 条件调制 | `ẑ(t+1) = f(z_t, rotvec(q_t))` | ✗ 实测无收益: 留出 108 帧 RMSE 0.6082(纯 z) → 0.6073(+q) = 0.15%, 而零阶保持 0.0959 ⇒ 该数据 z 段内不动, 没有动态可学 |
| 判据/监控(唯一可立即上) | θ_exec / \|w\| / `distance_fs(p,q)` 只读落盘 | ✓ 不进编码、不污染潜表示; 用来判"引擎在潜空间收敛了但物理没到位"的漂移 |
| 状态点注入 | `step(..., p_override=q)` · 回路开关 `ZMAX_SS_P_FROM_UNIFIED=1` | △ 能力已具备、**默认关**: 当解码点动作留出 RMSE 0.0453→0.3947(8.72×) ⇒ 只适合几何用途(phi/导航/判据); 必须同步 `current_manifold_point`, 否则假生效(坑 19) |

规则: **未证明提升的通道不得进默认档**; 每条通道留可复跑脚本(`tools/exp_q_conditioning.py` → `reports/q_conditioning.json`),
等真机/相机链路给出每帧都在变的 z 再重跑同一对照, 不许拿仿真阶梯数据的一次实验当定论(反方向也不行)。
喂之前必备: 先 `canonical` 归一(q 与 −q 同旋转), 判等用 \|⟨q1,q2⟩\| 而不是 canonical 后点乘(见坑 14)。

## 引擎的输入/输出/记忆 (它不积分, 也没有 z→z 世界模型)
`ManifoldEngine.step(state, potential_fn=None, dt=0.01, sensor_residual=None)` 是**一拍**(在役 10Hz), 内部五步:
`project`(state→编码 z→投到 S³ 得 p) → `gradient_flow`(Φ=到 goal 的度规距离, ∇Φ 切空间投影) →
`_evolve`(沿梯度走一步得 p_next) → 解码 action(readout 岭回归) → 可选 `feedback_update`。

| | 内容 |
|---|---|
| 输入 | `state` = **55 维标准口径**(老 43 维自动尾部补 0; 唯一状态输入) · `goal_point`(四元数, 由引擎自己 `project(轨迹末帧)` 得到, 不是外部给的) · 可选 potential_fn / sensor_residual / dt |
| 输出 | rec: `p` / `p_next` · `z`(16)+`z_source` · `phi` / `grad` · `action`(4) · confidence/anomaly/residual · M/momentum · `orbit` · homeostasis · 三段耗时 |
| 跨拍记忆 | 只有 `velocity`(仅 `inertia=True`) · `orbit` 历史 · `_a_prev` · `hom` |

- **`p_next` 不回写**: 引擎没有持久 `p`, 下一拍的 p 又是从新观测 `project` 出来的 ⇒ 语义是"每拍重新估计 + 算下一步", 不是积分推进。要累积演化必须开 `inertia=True` 或由调用方把 `p_next` 回灌成 state。
- **动作由 `z` 解码, 不由 `p`** ⇒ 任何改 p 却不改 z 的接法(覆盖 p、外部塞四元数)都会让输出自相矛盾。
- **潜空间不是模型**, 是 R¹⁶ 坐标; 填它的是编码器。设计链路: SmolVLM2-500M 视觉塔(冻结) → f∈R⁷⁶⁸ → 度规约束 `g_f=(1/M)·diag(σ²)` 归一 det=1 + 广义特征分解 `Cov(f)v=λg_f v` → `z=Vᵀg_f^{-1/2}(f−μ)`(16 = 6 度量主方向 + 10 残差)。
  **维度以 768 为准**(实测视觉塔输出 768 维, 与标定文件 mu 一致; 早期文档写 960 会让复核者对不上口径)。
  抓帧不通时回退内建 PCA, 并在 `z_source` 明写"成功 0/失败 N", 不静默。
- **没有 z→z 的转移模型**: `orbit` 是用最近几步 **p** 的角速度外推; `manifold_layer.predict_manifold` 是接触/性能流形读出。对外不许说"在潜空间里预测下一个四元数"——真要在 z 里预测, 得补转移网络并用真机连续数据训。
- 视觉塔 ~0.8s/帧(4060 实测 792ms/24 帧) ⇒ 只能独立线程 ~1Hz 刷 z, 引擎 10Hz 只读最新值 + 帧龄, 超期即回退并标注。
- **要回答"引擎到底吃到什么"别靠推理**: `tools/debug_55d_output.py` 用三种真实口径(在役 state jsonl 尾行 tcp/quat/jpos/jvel、CAD 几何夹具、满通道)跑 `UnifiedState55D.fuse()` 并打印分段; 配合 `ZMAX_DEBUG_55D=1` 门控断点, VSCode 配置「🧪 断点 · 55D 输出」直接停在 `fuse()` 的 `return x`。
- **55 维在调试器里必须“有名字”**: 用户会直接问"这个 x 的物理含义"。`fuse()` 不裸拼 `[k*v, t, e]`, 而是先按 `SLICE` 切成 `named`(19 个物理量) + `named_units`(单位), 再按 `ALL_SEGMENTS` 顺序拼回 x; 另有 `describe(x)` 吐 `[{name, unit, idx, value, meaning}]`。
  **改拼装方式必须零回归**: `np.array_equal(新x, 旧concat)` 多组随机输入全 True 才能说"只是可读了"; 少一个/错一位下标形状不变、下游全部数字静默错误(前 43 维逐位相同是 43→55 升级的契约)。
- **实况帧可能只有一半通道有真值**: 现场无示教几何时 `peg_xyz`/`hole_xyz` 段为 0(该行 `geom` 会写"缺失: 无示教几何")⇒ 几何误差 e=0、L2 群元素贴近单位元。报数时必须说明哪几段是 0、为什么是 0, 不许把 0 当成"误差为零"。

## L4 潜空间接通 (判据: z 真的来自视觉塔, 不是 PCA 回退)
`z_source` 是引擎自述, 可能一直写着"回退内建 PCA"。接通按四步做, 每步都有可复跑判据:
1. **抓帧地址必须是现役有帧的那一路**: 8791(`tools/cam_live_stream.py`)的 `/snapshot/local2.jpg` 走 8812 中央相机代理,
   那路没起时返回 **503**(不是 Connection refused) ⇒ provider 记 `成功 0/失败 N` 并回退 PCA。
   先量: `curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8791/snapshot/local.jpg`;
   `/snapshot/local.jpg` 与 `/snapshot/overlay_local.jpg` 是 200/640×480 真 JPEG, `arm` 路依赖 Orin(不通即 503)。
2. **单独跑编码器判据**: `./gui-venv311/bin/python tools/verify_l4_live.py --frames 3` —— 要看到 `f=768 · z=16 · finite=True`
   且帧间 `‖z_i − z0‖ > 0`(帧变了 z 得跟着变, 否则等于没接; 实测 0.15–0.20)。首帧含预热 ~4s, 之后 ~0.8s/帧。
3. **引擎侧开关**: 默认 `--encoder pca`; 走 L4 必须显式 `--encoder l4`(或 `ZMAX_SS_ENGINE_ENCODER=l4`), `--l4-hz` 默认 1。
   接入成功打 `🧠 L4 潜空间已接入` 且 `z_source` 形如 `帧龄 0.1s · 739ms/次 · 成功 12/失败 0`;
   仍写"回退内建 PCA"= 没接上, 不许接着说 L4。
4. **隔离实例端到端**: `run --seconds 25 --instance <x> --no-lock --encoder l4`, 回读 `engine_latest_<x>.json` 的
   `z_source`/`z_latent`/`p` 三样都要变 —— 只在日志里出现字样不算通。
落点是 `src/lerobot/manifold/l4_live.py::FRAME_URL_DEFAULT`。标定字段、度规投影、provider 线程参数、INTACT 接口见
`references/l4-latent-and-intact.md`。

## INTACT 接入在哪 (它不喂引擎)
INTACT 是 L4 的**意图解码**, 与引擎**不共用潜空间**: 它吃 `node.step(obs_frame, obs_source="engine_render",
skill_ctx=...)` 的**渲染帧 + 24 维 skill_ctx**, 自己模型编出 z_t/z_goal/delta (各 192 维),
**不消费引擎的 z(16) 也不消费 p(4)**。引擎侧调用点 `src/lerobot/engine/runtime.py:1529/1590`。
- 入口 `src/lerobot/policies/intact/service.py`: `get_service(root)` 单例(跨多次双击复用同一 worker),
  `run_once(stage, decode=True, node=None, obs_frame=None, obs_source="engine_render", skill_ctx=None)` → `IntentReport`。
  `node` 用来绑定引擎的真帧来源(不另建 worker), `obs_frame` 传显式观测帧。
- 画布侧 `library.py::_intact_service()` / `_intact_skill_ctx()`; skill 上下文布局 `[stage13 | L2_w8 | d_perp | arc_frac | grip]`(24 维)。
- 输出 `u_ff`(前馈动作) · `l3_cond` · `l4_cond`(意图增量单位向量 → DiT 额外条件 token) · `weight`/`reason`/`evidence_path`。
- **硬闸**: skill_dim>0 的 ckpt 缺 `skill_ctx` 会被模型侧直接拒绝(不静默降级) ⇒ 每条运行路径必须逐帧构造并传。
- 🧩 **引擎预测四元数 → INTACT 条件(`p_cond`)**: 引擎把 `p_next` 落 `engine_latest.json` →
  `runtime._read_engine_p_next()` 带**帧龄闸**(>2s 视为陈旧不传) → `decode(out, stage, p_cond=q)`
  换成 3 维 S³ 旋转向量放进 `DecodedIntent.p_cond`, 引擎侧存 `self._l4_p_cond`。
  这是**条件通道不是状态注入**: 不传 `p_cond` 时 `u_ff`/`l4_cond` 逐位不变。消费侧已接进 DiT
  token(零初始化残差, 见坑 21)⇒ 通道在前向里但权重为 0, **对动作影响严格为零**, 训练那层投影才生效。
  接口与判据见 `references/l4-latent-and-intact.md` §9–§10。

## 实测基线 (回归参考, 同引擎 369 步 接近→完成)
θ_total 2.86(接近) → 0.98(完成); |w| 0.14 → 0.88; 剥离残余 ≤3e-8; 层间不可交换 L2|L4=0.587;
17 个画布节点全部映射成群元素(其中 2 个本帧无数值输出 → 单位元)。

## 坑 (全踩过)
1. **数组进布尔上下文**: `float(frame.get(k) or 0.0)` 遇 ndarray → "truth value of an array is
   ambiguous" → 写 `_scalar(x)` 兜底(ndarray/0-d/None 全安全); 几何函数要兼容 `(1,N)` 批量输入。
   **装配落盘字典同样中招且更隐蔽**: `{... "p_next": [float(x) for x in (rec.get("p_next") or [])] ...}`
   会在**每一拍**抛错 ⇒ 整个周期异常、`engine_latest` 不更新, 而日志里只看到一条条 `第 N 周期异常`,
   容易当成偶发节点问题。判据: 起隔离实例后先数 `周期异常` 行数(必须为 0) 再看落盘文件有没有更新;
   写法一律 `if rec.get(k) is not None` 显式判断, 禁 `or []` / `or 0.0` 混用。
2. **harness 的假属性是 truthy**: `__getattr__` 返回 lambda ⇒ `bool(getattr(mod,"_trace",False))` 变 True
   → 走逐行 trace 分支 ⇒ "函数失败且无日志"的假象。显式给 `_trace_nodes=False` 等属性。
3. **画布加载会重映射节点 id**: 断言/查找一律按**节点名**(或 params 键), 不能按 json id。
4. **同一关键词只能注册一次**: 两条注册用同一组关键词 → 匹配歧义(返回的 key 与 `_EXTERNAL_LOC`/
   画布 id 不一致)。保留与画布节点 id 对齐的那一条。
5. **改完必须"杀掉重起"验证**: 语法检查过 ≠ 能起来(运行时 NameError); 旧进程内存里是旧代码,
   只有真重启才暴露。
6. 映射表放 `data/`(常被 .gitignore) → 代码里内置默认值 + 文件缺失回退, 否则换机器即崩。
7. **面板化节点双击 = 开观测面板**(不跑节点函数); 想让 ▶运行 也真跑一次, 给 demo 路径加"轻量真执行"
   分支(跳过冷加载, 只用缓存) —— 见 `simulink-flow-engineering` 断点根因④。
8. **"点了 ▶运行, SU2 轨迹球不动"**: 轨迹球原来只读 `zmax_data/ss_live/quat_truth_calls.jsonl`,
   而这份只有画布 ssobs 节点的 `quat_truth.observe()` 被逐点执行时才写; ▶运行 实际启的是
   `tools/ss_engine_loop.py` (10Hz 独立进程), 它只把每拍 `p`(SU(2) 四元数) 写进 tap
   `/dev/shm/zmax_ss_engine/engine_<场景>.jsonl` + `engine_latest.json`, **从不写 quat_truth**
   ⇒ 两条链没接上, 球永远停在旧轨迹/空态。修法: 轨迹球首选读运行流 tap(按 mtime 取最新,
   帧龄 >5s 视为没在跑 ⇒ 回退 quat_truth 真值源), 取最近 120 拍 `p` 直接当轨迹(10Hz 已够密, 不必 slerp)。
   判别口诀: 先量 `engine_latest.json` 两拍 `p`/`cycle` 有没有变 —— 变了是**显示源错**, 没变才是引擎卡住。
9. **改 `tools/gui/*.py` 后老面板不会自动用新代码**: 面板在页面构建时实例化一次, 模块已进
   `sys.modules` 缓存 ⇒ 必须重启界面(或让页面重建)才生效; 只改文件就宣布"修好了"= 假修复。
10. **S³ 测地角 ≠ 物理转角 (差 2 倍)**: `s3_angle(q1,q2)` 返回 S³ 上的测地距离 = **半个**物理旋转角,
   而 `SU2Element.theta()`/`rotvec_from_q()` 是物理角。把 `s3_angle` 当物理角直接喂给
   "步长 = ω·dt" ⇒ 实际走了双倍角 (实测残余恒 0.2 rad = 2×0.1)。正确: 物理步长 ω·dt ⇒ S³ 上走
   ω·dt/2; 对外一律报物理角, 并在返回里同时给 `s3_angle_rad` 与 `theta_deg` 免混。
11. **U_scene (四层群乘) 不能当"待消除误差"解码成 ω**: L3(进度)/L4(动作/接触/效能) 不是误差量,
   有界映射在饱和区把它们压到 π 附近 ⇒ 实测 U_scene 的 θ 全程 138~175°, 从不到 0;
   拿它解码会给出恒定的巨大"纠偏"指令。可执行路只用 **U_L2 (几何误差 e=光模块头−孔位,
   U=I ⇔ 到位)**; U_scene 只做理解/判据/层分解。两路分开报 (exec_*/scene_*)。
12. **43D obs 有两套不兼容布局**: `ideal_obs` (状态空间理想档) `[4:7]=光模块位置 [36:39]=孔位`
   与 su2 一致; `engine/sim._build_obs` (metaworld) `[4:7]=末端速度 [7:10]=光模块 [36:39]=阶段子目标`
   ⇒ 直接把 sim 的 obs 喂 su2 会把"速度−子目标"当几何误差 (实测 ~500mm / θ≈140° 假误差)。
   交叉验证前先核对通道语义; 在役口径用 `build_ideal_plan()+ideal_obs.frame()`。
13. **`manifold_engine.project()` 吃的是 state 向量(标准 55 / 老 43 自动补 0), 不是条件/潜向量**: 它的语义是 state→编码→潜→群投影。
   把 16 维条件向量直接塞进去 ⇒ `broadcast (1,16) vs (55,)`。要真让"逻辑条件"进潜空间,
   得训练带条件的编码器; 没做就如实标 `z_cond_used=False / latent_calibrated=False`, 只报 state→潜对照。
14. **双覆盖两个真坑 (2026-11-03 实测抓到并修)**:
   (a) `pose_caliper.s3_angle` 原来先 `canonical()` 再点乘 ⇒ **w≈0 附近符号规范不唯一**:
   实测 q=[0.0036,-0.545,-0.826,-0.143] 与 [-0.0087,+0.558,+0.817,+0.145] 是同一旋转,
   但 canonical 后两点积 −0.9998 ⇒ 算出 178.9°(×2=357.8°) 假巨角。**距离一律用 |⟨q1,q2⟩|**
   (与 `SU2Element.distance_fs` 同式), 与 w 符号无关。
   (b) `SU2Element.log()` 用 `atan2(‖v‖,w)` **不折叠主值**: w<0 时返回 >π 的角
   (实测创新算成 278° 而真差 7° ⇒ EKF 一步过冲 61° 直接崩到正交)。**log 前先 canonical**。
   修后回归: 群公理自检全项 ≤1e-15 · 统一状态空间 θ/层剥离不变 · 轨迹球 UI 全项通过。
15. **「这是流形卡尔曼」要分两层说**: 结构镜像(测量/预测/新息/更新)成立 ✓, 但现有
   `quat_truth.observe(alpha=0.5)` 与 `cognition.state_correction(K=0.5)` 是**固定增益互补滤波**
   —— 没有 P/Q/R, 增益不随不确定度变, 不能叫 KF。真 KF 已实现在 `s3_chain.S3EKF`
   (误差状态 δθ∈R³, q⊖=q⊗exp(ωdt), P⁺=FPFᵀ+Q, K=P(P+R)⁻¹, q←q⊗exp(Kr), P←(I−K)P);
   合成验证 (已知真值+噪声): σ=2° 时 RMSE 3.56°(纯测)→3.98°(固定增益)→**1.23°(EKF)**,
   σ=5° 时 8.53→6.22→**1.76°**。**Q/R 必须现场标定**, 合成数字不得当真机精度报。
16. **形状 + 引擎吃外部四元数: `src/lerobot/manifold/s3_chain.py`** (S3Chain: predict 测地线计划 /
   predict_next 切空间状态预测 / decode 逐步增量 ω / S3EKF), `tools/verify_s3_chain.py [--sim]`,
   已并联进 `ss_engine_loop.cycle()` (只加 `s3` 键, 不下发真机)。
   引擎接口: `step(..., p_override=q)` + 回路开关 `ZMAX_SS_P_FROM_UNIFIED=1` (默认关)。
   · 代价(必报): 当**解码点**用 q_exec, 动作留出 RMSE 0.0453 → 0.3947 (**8.72×**) —— z 仍走 43D
     编码而 readout 按 p 拟合; U_scene 与 L2 同值(L3/L4/L5 无 frame 落单位元)。
   · 所以分工固定: q = 几何锚(phi/navigate/判据/一致性), 动作解码用 p。要 q 解码須真机 (q,u) 重训 readout。
   · 实验 `tools/exp_p_vs_q_action.py` → `reports/p_vs_q_action.json`。
   自检 `python src/lerobot/manifold/s3_chain.py`; ideal 451 帧 p50 0.38ms、ω 超限 0、
   几何误差 move 380mm→grip 30mm 单调收敛、解码残余 1.5e-8。
   落盘 `s3_chain_latest.json`/`s3_chain_run.jsonl`(按实例加后缀, 见坑 17), 不下发真机。
17. **调试实例会污染在役落盘**: `ss_engine_loop --instance X --no-lock` 的隔离实例若不做后缀,
   会覆盖在役同名 `s3_chain_latest.json` / `s3_chain_run.jsonl` ⇒ 报告里引用的"在役快照"其实是调试实例的数。
   落盘名一律 `name_<instance>.json`(只有 main 用裸名), 跑完 A/B 再回读确认在役文件 mtime 没被改。
18. **改共享"尺子"函数先数引用面**: `s3_angle` 这类被 29 处调用的函数, 修完必须跑三套回归才敢收 ——
   群公理自检(≤1e-15) · 统一状态空间 θ/层剥离(值应与改前一致) · 端到端/UI(轨迹球 120 点);
   只跑单元自检就宣布修好, 下游(AR/球/判据)会带着旧噪声继续算。
19. **外部注入状态点 (`p_override`) 会"假生效"**: `project()` 把算出的 p 存进
   `self.current_manifold_point`, 而 `gradient_flow()` 读的是这个缓存(不是 `rec["p"]`)。
   只替换 `r["p"]` ⇒ 导航/解码走了新点, 势与梯度仍走旧点, 日志全绿却没有真注入。
   **注入必须同步 `self.current_manifold_point`**, 并在 rec / `engine_latest` 带 `p_source`
   (`project` / `external`), 否则下游会把注入值当 project 继续报数。
   验证三件(缺一即假): ① 默认路径重跑逐位相同(0 差) ② 注入后 ‖p−q‖=0 且 phi/action 确实变
   ③ 随后再走默认, p 与基线逐位相同(没污染引擎跨拍状态)。
20. **接任何额外信号进引擎前, 先量它对动作的解释力**: 动作真值做岭回归对照(前 70% 训 / 后 30%
   **时序**留出, 不随机切), 四元数先统一符号(q 与 −q 同旋转, 线性模型会当成两个输入)。
   实测 p_project 留出 RMSE 0.0453, q_exec 与 U_scene 都是 0.3947 = **8.72×** ⇒ 统一状态空间的
   四元数对动作的解释力远弱于引擎自己的 p, 只能当几何锚、不能当解码点。
   脚本 `tools/exp_p_vs_q_action.py` → `reports/p_vs_q_action.json`, 换数据即复跑; 报结论必须带这组对照,
   不许凭"架构上应该能喂"就接线。
21. **给已训练模型加新条件信号: 不要拼维度, 用零初始化残差挂到同一 token**:
   `apply_l4_cond`/`ensure_l4_cond` 在 `in_features` 变化时会**懒重建** `l4_cond_proj`(随机初始化)
   ⇒ 把条件从 192 维拼到 195 维, 冲掉的是**已训练的投影**, 得到噪声而**不是**零回退。
   正确做法: 新信号 → `nn.Linear(k, out_dim, bias=False)` + `weight.zero_()`, 输出**加到**原 token 上
   (token 数与维度都不变 ⇒ 已训练部分不动)。判据四条, 缺一即不算:
   ①不传 ⇒ 逐位相同 ②给了但零初始化 ⇒ 逐位相同(`max|Δ|=0`) ③手动把权重置非零 ⇒ 输出确实变
   (证明通道真参与前向, 不是死代码) ④没有 `l4_cond` 时能单独出一个 token 且原 token 不变。
   脚本 `tools/verify_p_cond_token.py`(最小替身绑方法, 不必加载整颗模型)。
   透传要点(每层默认 None): `_l3_forward(..., p_cond=)` → `select_action(batch, l4_cond=, p_cond=)`
   → `predict_action_chunk` → `predict_action` → `apply_l4_cond(tokens, l4_cond, p_cond)`;
   漏透一层就是"接线了但没进前向"。
   口径纪律: 零初始化 ⇒ **通道在、影响严格为零** —— 不许说"已生效", 也不许说"没接";
   要生效必须训这层投影(zero-init residual adapter 的标准做法)。
22. **四元数分量顺序是两个世界**: `quat_truth` / pc 侧内部是 **(w,x,y,z)**, 执行器是 **(x,y,z,w)**。
   不做转换 = "z 对 −z" 发成 "z 对 +z" —— **差 180° 且结果仍是单位四元数**, 模长/单位性校验全查不出。
   ⇒ 传参考姿态必须带显式 `quat_ref_order="xyzw"` 标记, 读方验证不符即拒发(fail-closed), 不许按位置猜。
23. **画布常驻回路会被自进化"让显存停掉"**: `tools/evolve_ar_world.py` 的 `SHED_UNITS=`
   `["zmax-ss-canvas-loop.service"]`(8GB 卡上引擎 1.8G + 画布 2.2G + INTACT 1.3G 必然 OOM), 训练结束
   `restore_gpu()` 起回。⇒ 回答"某节点有没有输出 / 球不动 / 改造好没好"之前, 先 `systemctl is-active
   zmax-ss-canvas-loop`; 引擎回路 `zmax-ss-engine-loop` 在跑只证明 `p`/`p_next` 在刷新(其 `goal_point=None`),
   **它不吐 `quat_ref` 也不跑 ssobs** —— 把引擎回路当成"状态空间在输出"是口径错。
24. **画布节点的 `outputs` 声明与实际链路可以不一致**: ssobs 声明 `["out1","out2"]` 而链路
   `lk0924_ssobs_ss_mani_eng` 用的是 `out3` —— 运行时取得到(代码里有), 但声明缺口会让面板/校验看不到。
   加/改出口时同步 `params.outputs`, 并在验收里核"声明 ⊇ 被链路引用"。
