# L4 潜空间: VLM 通用视觉编码器 → 黎曼度规约束 → INTACT 意图解码 (2026-10-14)

口径 (老倪): 「VLM 通用视觉编码器是输入，流形引擎根据黎曼度规加约束，INCACT 负责意图解码；这才是 L4 的潜空间」

## 三段分工 (每段可单独验证, 换任一段不影响另两段)
1. **编码 (通用, 冻结)**: `src/lerobot/manifold/encoder_vlm.py` — 载本地 HF 缓存的 SmolVLM2-500M，
   取 `mdl.model.vision_model` (SmolVLMVisionTransformer, 86.4M)。**输出 (13 tiles, 1024 tok, 768) ⇒ 两级池化 = 768 维**。
   实测 ~0.79s/帧 (4060) ⇒ 绝不可放进 10Hz 回路现算。
2. **度规约束 (有标定)**: `src/lerobot/manifold/l4_latent.py` — 特征空间度规 `g_f=(1/M)diag(σ²)` 对数域归一 to `det=1`,
   广义特征分解 `Cov v = λ g_f v`, `z = Vᵀ g_f^{-1/2}(f−μ) ∈ R^16`。
3. **意图解码 (只解码)**: 画布 `ssintact_dec`; 潜空间里给 `Δz = z_goal − z_t`。

## 坑 (都实测踩过)
- **`det(g_f)` 必须在对数域算**: 768 维 diag 矩阵显式乘积下溢 ⇒ `det=0/inf ⇒ nan` 传遍全链。改成
  `log_g -= log_g.mean()` (⇒ Σln g = 0 ⇔ det=1)。
- **白化因子是 `g^{-1/2}` 不是 `g^{+1/2}`**: 度规定标是 σ² ⇒ 乘 sqrt(g) 会把各维方差变成 σ⁴
  (实测 var max/min = 5.3e7)。
- **`det=1` 归一只定整体尺度 ⇒ 不变量是「各维等方差」(各向同性), 不是 var=1**: 断言写成 max/min≈1。
- **零方差维要剔**: VLM 池化特征里有跨帧恒定的维 (padding 等) ⇒ 白化放大噪声, 度规在那里没定义。
  拟合时 `var >= 1e-8*max(var)` 掩码并存 `dim_mask`, 投影时同样过滤。
- **视觉塔输出是 3D 不是 2D**: `mean(axis=0)` 只塌了 tile 维 ⇒ 拿到 786432 维「特征」; 必须 `mean(axis=(0,1))`。
- **`proc(images=…).get(k) or …` 会炸**: 张量的布尔求值 `RuntimeError: Boolean value of Tensor ... ambiguous`;
  必须 `if k in o: pix = o[k]`。
- **接了 CUDA 编码器后进程收尾会 Aborted** (torch/CUDA 上下文在常驻线程里析构): `run --seconds N` 结束时
  `l4.stop()` + flush + `os._exit(rc)` 交付同一退出码 (同项目 `_finish` 惯例)。

## 落地与取证
- 回路接入: `tools/ss_engine_loop.py --encoder l4 [--l4-hz 1] [--l4-frame-url …]` (默认 `pca` = 零回归)。
- **潜表示来源必须随每步带出**: 引擎 `project()` 的 `z_source` 要进 `step()` 的 rec ⇒ tap 每行有
  `encoder` / `z_source` / `z_latent` —— 否则「接线接了但看不见喝的是哪条链」。
- **provider 返回 None = 没新鲜输入 ⇒ 回退内建 PCA 并明写** (`_z_fallback`), 不许静默回退
  (静默会让上层以为在吃 L4 潜表示)。
- 判据 `tools/verify_l4_latent_space.py` 10 项 (编码维度/时延 · 真实帧标定 · 潜坐标非退化 · 引擎接入 ·
  零回归 · 度规白化等方差 · 度规下解耦 · Δz · INTACT 现状)。
- 画布边: `n_vlm_llm --out1→ ss_mani_eng`「通用视觉编码器 → 流形引擎潜表示输入 (L4 潜空间)」;
  改后按纪律 `ss_task_bind --check` (需重绑) · `canvas_level_audit` · `engineering_db build+check`。

## L4 后段链: 意图解码器 → INTACT LoRA 微调 → 流形专家预测器 → 接触/性能流形 (2026-10-14 追加)
老倪: 「L4 INTACT LoRA 微调节点接在意图解码器后面 (不动 INTACT 原权重, 只改 LoRA 节点); 元任务预测的输出
也要接到 LoRA 节点; 向后接流形专家预测器 + 接触流形 + 性能流形; UI 连线顺序改正确。」

- 数学层 `src/lerobot/manifold/manifold_chain.py` (自检 9/9): `L4Adapter` (冻结 W0, Δu=γ_eff·(α/r)·mean_j(B_jA_jφ),
  限幅 ‖Δu‖≤ρ·容量) · `ManifoldExpert` (ẑ=z−δ·g⁻¹∇Φ+R, 度规步长‖dz‖_g 才是真口径) ·
  `ContactConstraint` (摩擦锥投影 + 穿透罚) · `PerformanceConstraint` (V_p/η + g_p 度量 + 黎曼梯度 + 帕累托闸)。
- 节点: `node_ss_lora_l4` 重写 (真读产物 + 真算 Δu + 元任务预测门控 + 写 `_SS_STATE["lora_l4"]`);
  `node_ss_pred` / `node_ss_mani` 增加 ⛓ 承接日志 (接线≠被消费 ⇒ 必须真读数)。
- 画布 `tools/canvas_l4_lora_chain.py` (幂等): 插 LoRA 到意图解码器后, 元任务预测→LoRA, LoRA→{专家预测器,接触,性能,DiT},
  **删掉两条旁路** (意图解码器→专家预测器/DiT, 留着就是绕过微调), 位置按 x 递增排 + 判据 `tools/verify_l4_lora_chain.py` 8/8。

## 坑 (本轮实测)
- **`merged_*` 产物不能用**: 它是 LoRA 已折叠进原权重 (323 键无 lora_A/B) ⇒ 用它就等于"动了原权重", 与口径冲突;
  要取 `weights_epoch_1.pt` (547 键, 112 组 lora_A/B, r8/α16)。
- **`if tr and tr.get("t")` 在 ndarray 上炸**: 画布给的 `_ss_tr` 是 list 所以平时没事, 一旦拿 ndarray 喂
  (自己写的取证桩) 就 `truth value of an array is ambiguous` ⇒ 取证要按**真实类型**喂, 或写 `len(x)>0`; 
  同坑还扫到 `node_ss_pred`/`node_ss_mani` 里同款写法 (未改, 保持原样)。
- **f_n<0 = 没接触 ⇒ 摩擦锥不适用**, 不能说"越锥"; 不然日志会误报约束生效。
- 元任务预测目前 `frozen=true` (驱动扭矩恒定) ⇒ γ_eff 接近均匀, 要在日志里如实标, 不能当成"预测有效"。

- **INTACT `z_pred` = NaN**, 因为动作块空 (`⚠️ INTACT chunk 空或含 NaN/Inf`; 二次调用报
  `Action history contains non-finite values`) ⇒ 「流形是被预测出来的」的".预测"那一段没通;
  勿用有限的 `z_t` 冒充 `z_pred`。
- 标定只 24 帧 (办公室/工位) ⇒ 要"通用"得按场景扩到数百帧并复查解释方差。
