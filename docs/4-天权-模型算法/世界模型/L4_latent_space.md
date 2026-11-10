# L4 潜空间设计 (VLM 通用视觉编码器 → 黎曼度规约束 → INTACT 意图解码)

口径 (老倪 2026-10-14): 「VLM 通用视觉编码器是输入，流形引擎根据黎曼度规加约束，INCACT 负责意图解码；
这才是 L4 的潜空间」。

## 1. 改之前的三个问题

1. **引擎的"编码"是拟合不是编码**。`ManifoldEngine` 内建 `Encoder` 是 PCA: 对**当前状态 43 维**现拟合
   (`models/manifold_engine.npz`: `mu(43) + W(43,16)`, n_fit=120 帧)。它没有视觉输入 —— 相机画面
   与引擎之间**一根线都没有**，画面里的信息进不了潜空间。
2. **"预测"是空的**。`Encoder.lift`(丛映射) 在引擎里是声明未接的空壳；潜坐标不是被预测出来的。
3. **意图解码缺输入**。INTACT 在画布上挂着 `ssintact_dec`，但引擎侧没有把潜坐标提供给它；
   且 INTACT 自身的动作块(chunk)返回空/NaN ⇒ 它的 `z_pred` 也是 NaN (见 §5)。

## 2. 设计 (三段分工，每段都可单独验证)

```
真实帧 (8791 相机 / L5 槽位图 …)
   │
   │ ① 编码 (通用, 冻结, 不训练)                      ← src/lerobot/manifold/encoder_vlm.py
   ▼    SmolVLM2-500M 视觉塔 (86.4M, SmolVLMVisionTransformer)
   f ∈ R^768              实测 (13 tiles, 1024 tok, 768) 池化 · ~0.79s/帧 · cuda
   │
   │ ② 度规约束 (几何, 有标定)                        ← src/lerobot/manifold/l4_latent.py + 引擎
   ▼    特征空间度规 g_f = (1/M)·diag(σ²)  (对数域归一 ⇒ det(g_f)=1, 体积保持)
        广义特征分解: Cov(f) v = λ g_f v ⇒ V 在 g_f 下正交
        z = Vᵀ g_f^{-1/2} (f − μ) ∈ R^16            ← **L4 潜坐标** (16 = 6 度量主方向 + 10 残差)
        再交引擎: 度规 g = M·G(x), det G = 1 ⇒ 漂移/异常/测地线导航 (约束是否成立)
   │
   │ ③ 意图解码 (语义, 只解码不编码)                  ← 画布 ssintact_dec (INTACT)
   ▼    z_t / Δz = z_goal − z_t → 意图 (goal/from/skill/gate)
```

**为什么这样分**：①给出与任务无关的通用视觉表示(可换编码器, 换后只需重标定)；②只做几何约束，
把"像元空间"变成"有度量的潜空间"（各向异性被 M 和 σ² 定标，距离 = Mahalanobis 距离
Σ(Δf)²/σ²）；③只做意图，不碰编码 —— 编码换 VLM 不影响意图解码的语义。

## 3. 节拍与新鲜度 (工程落地，不是纸面)

* 视觉塔 **0.79s/帧** ⇒ 10Hz 回路里现算会把回路拖死。
* 所以 L4 潜表示由**独立线程**按自己的节拍 (默认 1Hz) 抓帧→编码→约束投影，引擎每周期只读**最新值**，
  并带**帧龄**；超期 (>8s) 返回 None ⇒ 引擎回退内建 PCA **并明写** (不静默)。
* 落点：`tools/ss_engine_loop.py --encoder l4` (默认 `pca`)。tap 每行带 `encoder` / `z_source` /
  `z_latent` —— 上下游能核出这一周期喝的是哪条编码链。

## 4. 唯一依据与标定

| 件 | 路径 | 说明 |
|---|---|---|
| 主参数 M | `config/calib/zmax_manifold.json` | M=3.643 (度规定标，非自由拟合) |
| L4 标定 | `models/l4_latent_calib.json` | μ / g_f / V / n 帧 / 解释方差 / 源 sha，可复核 |
| 编码器权重 | `zmax_data/hf_cache/hub/…SmolVLM2-500M…` | 离线 (HF_HUB_OFFLINE=1) |
| 输入帧 | 8791 `/snapshot/local2.jpg` 等 | 真实相机 (本次标定 24 帧: L5 槽位图 8 + AR 快照 16) |

## 5. 实测 (判据 `tools/verify_l4_latent_space.py` · 10/10 PASS)

```
① VLM 视觉编码器   特征 (24, 768) · 792ms/帧 · cuda · 视觉塔 86.4M 参数
② 拟标定 (真实帧)   n=24 · det(g_f)=1.000000 · 解释方差 100.0% · latent=16
③ 帧 → 潜坐标       z(8,16) · 各维 std 0.0197~1.63 (非退化)
④ 引擎接入          z_source = "L4 潜空间 (VLM 视觉编码器 → 黎曼度规约束 16 维 · 标定 n=24 帧)"
                    帧龄 0.1s · 752ms/次 · 成功 5/失败 0 · encoder=l4
④ 零回归            无 provider ⇒ z_source = "内建 PCA 编码器 (Encoder.fit …)"  逐位不变
⑤a 度规白化         各维等方差 var max/min = 1.0000 (各向同性) · det(g_f)=1
⑤b 度规下解耦       潜坐标协方差 非对角/对角 = 4.1e-16
⑥ 潜空间 Δz          Δz = z_goal − z_t 在 L4 潜空间算 (真实两帧) ⇒ ‖Δz‖₂=3.85
⑥ INTACT             z_t(192) 有限；**z_pred = NaN** —— 上游动作块空 ⇒ 预测潜表示拿不到 (如实标)
```

在役回路回归：重启 `zmax-ss-engine-loop` 后 `encoder=pca · z_source=内建 PCA …`，11.1Hz，cycle 正常 ✔

## 6. 画布

新增边 `n_vlm_llm --out1→ ss_mani_eng` (标签「通用视觉编码器 → 流形引擎潜表示输入 (L4 潜空间)」)。
改后按纪律跑过：`ss_task_bind --check` ✅ (重绑后) · `canvas_level_audit` 真缺口 5 (与改前同，未新增) ·
`engineering_db build+check` ✅ 判据全绿 · 任务→节点集合未变 (TASK-07-AOI 31 个) ✔

---

# L4 后段链 (2026-10-14 追加): 意图解码器 → **INTACT LoRA 微调** → 流形专家预测器 → 接触/性能流形

老倪口径: 「L4 INTACT LoRA 微调节点接到 INTACT 意图解码器后面 —— 不想动 INTACT 原始模型权重，只需要
修改 LoRA 节点；元任务预测节点的输出也要接到 INTACT LoRA 微调节点；然后向后连接流形专家预测器，
以及接触流形、性能流形。」

## 1. 链路与数学 (src/lerobot/manifold/manifold_chain.py, 可单跑: 自检 9/9 PASS)

```
u_int  ← INTACT 意图解码器 (冻结 W0)
  ▼ ① L4Adapter      u_lora = u_int + γ·Δu ,  Δu = γ_eff·(α/r)·mean_j(B_j A_j φ)
                     原权重冻结 · γ_eff = g(元任务预测值) (L4/L5 层元任务得分焦点权重)
                     限幅 ‖Δu‖ ≤ ρ·容量, 容量=(α/r)‖B_j‖_F‖A_j‖_F‖φ_j‖, ρ=0.35 (可复核上界)
  ▼ ② ManifoldExpert  ẑ = z − δ·g⁻¹∇Φ(z) + R(z,u_lora);  g=M·G(x), det G=1 (度规步长才是真口径)
  ▼ ③ ContactConstraint   f = f_n n̂ + f_t ; 可行 ‖f_t‖ ≤ μ f_n (越锥投影回锥); Φ_c = ½k_n max(0,h)² + μ k_t‖v_t‖
  ▼ ④ PerformanceConstraint V_p=½δᵀWδ · η=exp(−V_p/σ²) · 黎曼梯度 g_p⁻¹∇V_p · 帕累托非劣闸 (Δπ_i ≥ −tol_i)
```

设计取舍 (为什么这么写):
- **LoRA 只改 ΔW, 不碰 W0** ⇒ 与 `tools/lora_inject.py` 同口径 (112 层, r=8, α=16, scaling 2.00);
  产物唯一依据 = `zmax_data/stable-wm-cache/checkpoints/intact_goal_optical_insert_v6lora_200/weights_epoch_1.pt`
  (含 lora_A/B)。**merged_* 一律排除** —— 那是已折叠 = 改了原权重, 与口径冲突。
- **元任务预测 → LoRA 增益**: 元任务预测值 (meta_pred.json: top-k 元任务 + 层 + 得分) 里 L4/L5 层的
  焦点权重做 γ_eff ∈[0,1]; 预测 frozen(驱动扭矩恒定) 时如实标注"增益≈均匀"。
- **接触流形**: 复用 `manifold_layer.ContactManifold.decompose` 的真实几何 (e∥/e⊥/通道轴), 本层只加
  摩擦锥可行域与穿透罚; **f_n<0 = 没接触 ⇒ 锥约束不适用** (不能说"越锥")。
- **性能流形**: 复用 `PerformanceManifold` 的 V_p/η 口径 (σ=4mm 标定尺度) + 新增度量 g_p 与帕累托闸。

## 2. 画布 (UI 顺序已改正确, tools/canvas_l4_lora_chain.py 幂等)

```
👁 VLM / 📦数据源 / 🖥真机 / 🧠意图丛 / 🧮流形引擎 ─┐
                                                  ▼
                                     🎯 INTACT 意图解码器 (x=10016)
                                                  ▼ 意图 m_int (z_t/Δz)
   🧾 元任务预测 (x=9600,y=1720) ──元任务预测值──▶ 🎛 L4 INTACT LoRA 微调 (x=10430)
                                                  ▼ u_lora
                                     🧠 流形专家预测器 (x=10872) ──┬─▶ 🧮 接触流形 (x=11346) ─┐
                                                                  └─▶ 🧮 性能流形 (x=11666) ─┤
                                     🎛 L4 LoRA ──L4 条件──▶ 🎯 Flow-Matching Action Head (x=12166)
```
- 删掉了两条**旁路** (意图解码器 → 专家预测器 / → DiT): 留着就是绕过微调, 与"接在解码器后面"自相矛盾。
- 下游三节点**真读** LoRA 节点输出 (未读时报"接线≠被消费", 日志里以 ⛓ 打出承接的数)。

## 3. 判据 (tools/verify_l4_lora_chain.py · 8/8 PASS)

```
① 画布拓扑 (边全 + 旁路已删)     ② UI 顺序 x 递增 10016→10430→10872→11346→11666→12166
③ 节点执行注册 73/74 (未命中 1 = ss_moe, 老账)   ④ 产物唯一依据 112 组 r8/α16 scaling 2.00 (merged 已排除)
⑤ 数学自检 9/9 (Δu 非零 · 限幅真生效 · 无产物恒等 · 锥投影 · 帕累托)
⑥ 真被消费: LoRA→专家预测器→接触流形→性能流形 四节点连跑, ⛓ 承接日志 4 条
⑦ 元任务预测门控 γ_eff=0.822 (10 候选/L4-L5 3 个, frozen 如实标) · 原权重冻结
```
实测数 (在役回路 z_latent 作意图输入): ‖u_int‖=0.67~0.77 · ‖Δu‖≈3.7e-05 / 容量上限 ≈0.035 (未限幅) ·
度规步长 ‖dz‖_g=0.001048 · 接触流形 f_n<0(无接触, 锥不适用) · 性能流形 V_p=0.00391 η≈0 (σ=4mm, 真实距离尺度)。

## 4. 未打通 / 待办 (如实)

1. LoRA A/B **未证明提升**: 按纪律不进默认档; 需与统一主干/阶段专家同口径 A/B (留出集 + 平凡基线)。
   历史诊断 (reports/diag_lora_du_*): 最终指令与解析链逐位相同 200/200 帧, 根因=幅值比中位 5.2~5.8×(红线 1.5×)
   被 L2 收口闸逐帧否决。
2. Φ 零填充嵌入该层输入空间 (φ∈R^192 → R^{in_j}) 是**声明口径**, 不是"估计出来的动作";
   要更强得让 INTACT 真前向出该层激活 (把 LoRA 挂进 INTACT 前向), 工作量在 INTACT 侧。
3. 专家预测器的残差头 R 未训练 (纯测地线一步); 接触力输入目前来自几何误差合成, 真机要有力传感才是真接触力。

## 7. 已知缺口 (不粉饰)

1. **INTACT 的 z_pred 还是 NaN**：根因在动作块 (日志「⚠️ INTACT chunk 空或含 NaN/Inf」；二次调用报
   `Action history contains non-finite values`) ⇒ 动作头没给有效动作，预测器无从前推。
   ⇒ 「流形是被预测出来的」这句目前只到 `z_t/Δz`，**预测那一段没打通**。两条路：走
   `tools/intact_direct_rollout.py` 的原生路径 (真实渲染帧 + 3 帧历史 + env.step 动作)，
   或先查动作头为何出 NaN。
2. **标定只有 24 帧**，且来自办公室/工位场景。要做成"通用"需按场景扩充 (每场景 ≥ 数百帧) 并复查解释方差。
3. **1Hz 潜表示**：真机节拍若要求 ≥10Hz，需蒸馏小编码器或用 INTACT 的 z_t (更快) 替代视觉塔。
4. **编码器登记不一致**：画布节点 `n_vlm_llm` 名字写的是 Qwen2.5/3-VL，实际在役并已标定的是
   SmolVLM2 视觉塔 (本地缓存里两者都有)。要么把节点名对齐 SmolVLM2，要么给 Qwen2.5-VL 也做一份标定。
