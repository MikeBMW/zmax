# L4 潜空间 与 INTACT 的接口细节

配合 SKILL.md「L4 潜空间接通」「INTACT 接入在哪」两节。只写能照着查/照着跑的接口事实。

## 1. 编码器 → 特征

- `src/lerobot/manifold/encoder_vlm.py::VLMVisionEncoder`
- 模型 `HuggingFaceTB/SmolVLM2-500M-Video-Instruct`, 取 `core.vision_model`(回退 `vision_tower`), **冻结**。
- 507M 参数; 加载 0.4–12.7s(冷/热差很大, 首次进 cuda 慢); 单帧编码 **~0.8s**; 首帧含预热 ~4s。
- 输出特征维 **768**(不是 960)。`default_encoder()` 取单例, `encode(frame)` → ndarray(768,)。

## 2. 度规约束 → 16 维

`src/lerobot/manifold/l4_latent.py::L4LatentSpace`

- 标定 `models/l4_latent_calib.json`: `mu`(768) · `g_f_diag`(768) · `V`(768×16) · `n_frames` ·
  `latent_dim` · `explained_var` · `latent_offdiag_rel` · `M` · `frames_note` · 源 sha。
- `project(feat) -> (z, note)`:
  - 维数不符**抛错**(`视觉特征 d 维 != 标定 d 维 ⇒ 口径不符`), 不静默补零。
  - `z = V.T @ ((1/sqrt(g_f_diag)) * (f - mu))`, 不足 16 维补零。
  - **第二个返回值是 str note, 不是 dict** —— 按 `meta.get(...)` 取字段会 AttributeError。
- `project_sphere(z)` 是另一条(球面约束), 默认不开。

## 3. 常驻 provider

`src/lerobot/manifold/l4_live.py::L4LiveProvider`

- 参数 `frame_url` · `interval`(=1/l4_hz) · `stale_s`(默认 8.0) · `latent_dim`(16)
- 循环: 抓帧 → encode → project → 存 `z`+`z_ts`; 计 `n_ok`/`n_fail`/`last_ms`/`last_err`
- 引擎每拍读最新值; `age_s() > stale_s` ⇒ 返回 None ⇒ 引擎回退 PCA 并明写原因
- `note_base` 是 `z_source` 的固定前半段; 动态段 `帧龄 x.xs · NNNms/次 · 成功 n/失败 m`

## 4. 抓帧端点(8791)

| 路径 | 实测 | 说明 |
|---|---|---|
| `/snapshot/local2.jpg` | 503 | 走 8812 中央相机代理; 代理没起就 503(易被误读成 refused) |
| `/snapshot/local.jpg` | 200 / 640×480 | 本机 USB(MAXHUB)相机, 现役可用 |
| `/snapshot/overlay_local.jpg` | 200 | 带叠加层, 备选 |
| `/snapshot/arm.jpg` · `/snapshot/overlay_arm.jpg` | 503 | 依赖 Orin 三路, 不通即 503 |
| `/snap/0.jpg` · `/api/cams` | 404 | 不是这个服务的路由(那是 AR 页的) |

判据: `curl -s -o /tmp/f.jpg -w '%{http_code} %{size_download}' .../snapshot/local.jpg`, 再 `xxd | head` 确认头两字节 `ffd8`
(真 JPEG, 不是 JSON 错误体)。

## 5. 端到端验证脚本

`tools/verify_l4_live.py --url ... --frames N`: 打印编码器名/加载耗时、标定 n_frames/latent_dim、每帧尺寸与
fetch/enc 耗时、f 维度、z 维度、有限性、`‖z_i − z0‖`; 非 0 退出 = 有帧不合格。

## 6. 引擎侧开关

- `--encoder {pca,l4,hjepa}`, 默认 `ZMAX_SS_ENGINE_ENCODER` 或 `pca`
- `--l4-hz`(默认 1) · `--l4-frame-url`(默认空 ⇒ 用 `FRAME_URL_DEFAULT`)
- 接不上: 打 `⚠️` 并**留在 pca**; 接上: `eng.set_latent_provider(self.l4, self.l4.note_base)`

## 7. INTACT 接口

`src/lerobot/policies/intact/service.py`

- `get_service(root)` 单例 · `reset_service(root)` · `ensure_ready() -> (ok, why)`
- `run_once(stage="", decode=True, write_evidence=None, log=None, node=None, obs_frame=None,
   obs_source="engine_render", skill_ctx=None) -> IntentReport`
- `set_source(name, **kw)` · `step_once()` · `bridge_status()` · `describe()` · `close()`
- `IntentReport`: `stage` · `trained` · `chunk_shape` · `policy` · `diagnostics` · `source` · `obs_source` ·
  `robot` · `latent_keys` · `decoded` · `u_ff`+`u_ff_source` · `l3_cond`+`l3_cond_source` · `weight` ·
  `reason` · `l4_cond`+`l4_cond_source` · `decoder` · `evidence_path` · `bridge` · `ts`
- 意图用 `z_t` 与 `Δz = z_goal − z_t`; `ensure_goal()` 按 ①显式 set_goal ②数据源自报 ③默认目标帧文件 取。
- skill 上下文 24 维 `[stage13 | L2_w8 | d_perp | arc_frac | grip]`, 由 `skill_ctx.build_skill_ctx` 构造;
  `skill_dim>0` 的 ckpt 缺它就是硬报错。

## 8. q 进引擎的复跑方式(结论在 SKILL.md 表里)

- 条件调制: `tools/exp_q_conditioning.py` → `reports/q_conditioning.json`(357 帧, 前 70% 训/后 30% 留出;
  零阶保持 0.0959 / 纯 z 0.6082 / z+q 0.6073)
- p↔q 对齐: 逐帧 `ManifoldEngine.project` + `encode_obs43` 全量统计, 不许只看两帧举例
- 换数据要重跑; 同一份仿真阶梯数据正反结论都不算数

## 9. 引擎预测四元数 → INTACT 条件 (`p_cond`)

三段接线, 每段都能单独验:

1. **引擎出数**: `tools/ss_engine_loop.py` 每拍把 `rec["p_next"]`(沿梯度走一步后的四元数) 写进
   `engine_latest.json`。它与同帧 `p` 必然不同 —— 相同说明 `_evolve` 没跑或键写错。
   ⚠ `rec["p_next"]` 是 ndarray: `rec.get("p_next") or []` 触发真值歧义 ⇒ **每拍异常、整个周期不写盘**;
   用 `if rec.get("p_next") is not None` 显式判断(见 SKILL.md 坑 1)。
2. **桥**: `src/lerobot/engine/runtime.py::_read_engine_p_next(fresh_s=2.0)`, 从工程根下
   `zmax_data/ss_live/engine_latest.json` 读; 帧龄超期返回 None(不拿旧点冒充当拍预测)。
   调用点在 `_l4_intact_u_ff`: `st["p_cond"] = "engine(p_next)" | "未提供(无新鲜 p_next)"`。
3. **解码**: `IntactIntentDecoder.decode(out, stage="", cfg=None, p_cond=None)` →
   `DecodedIntent.p_cond` = 3 维 S³ 旋转向量(`θ=2·atan2(‖v‖,w)`, 双覆盖统一取 `w≥0`), `p_cond_source` 标来源;
   引擎侧 `self._l4_p_cond = d.p_cond`, `st["p_cond_dim"]` 记维度。

判据 `tools/demo_p_cond.py`: 不传 ⇒ `p_cond=None` 且 `u_ff`/`l4_cond` 逐位相同(零回退);
传 ⇒ 3 维有限向量。INTACT 真推理(metaworld 源) chunk `(8,10)`, latent 键
`z_t/z_goal/delta/z_pred/z_pred_last`。

边界: 消费侧已接进 DiT(见 §10), 但投影权重为零初始化 ⇒ **对动作影响严格为零**, 训练后才生效。
口径: 既不能说"已生效", 也不能说"没接"。`decoder` 里的 `p_cond_source` 文案仍是旧的
`待下游消费(未接=不生效)`, 接上消费方后该改成 `进 DiT token(零初始化, 待训练)` —— 文案落后于代码时
以判据脚本为准。

## 10. p_cond 进 DiT 条件 token(消费侧)

`src/lerobot/policies/smolvla_lew/action_head.py::SmolVLALewActionHead`

- `ensure_p_cond(dim, out_dim=None, device=None, dtype=None)`: 懒建
  `p_cond_proj = nn.Linear(dim, cross_attention_dim, bias=False)`, 建完立即 **`weight.zero_()`**
- `apply_p_cond(cond_token, p_cond)`: p_cond None ⇒ 原样返回; 否则 `cond_token + proj(p_cond)[:,None,:]`
  (**加到已有 token 上**, 不新建 token)
- `apply_l4_cond(conditioning_tokens, l4_cond, p_cond=None)`: 两者都 None ⇒ 原样返回;
  只有 p_cond ⇒ 追加一个 token(零初始化时不扰动)

**不要 concat 扩维**: `ensure_l4_cond` 只在 `in_features`/`out_features` 与当前条件不匹配时重建投影,
新建的 `Linear` 是随机初始化 ⇒ 192→195 维会把已训练的 token 投影冲成噪声, 不是零回退。

透传链(每层默认 None, 漏一层 = 接线了但没进前向):
`engine/runtime.py::_l3_forward(..., p_cond=)` → `select_action(batch, l4_cond=, p_cond=)` →
`predict_action_chunk(...)` → `model.predict_action(..., p_cond=)` → `apply_l4_cond`。
引擎侧供值: `self._l4_p_cond = d.p_cond`(`_l4_intact_u_ff` 里 decode 之后)。

判据 `tools/verify_p_cond_token.py`(最小替身绑方法, 不加载整颗模型):

| 判据 | 期望 | 实测 |
|---|---|---|
| p_cond=None | 与原路径逐位相同 | True |
| p_cond 给了但零初始化 | 逐位相同 | True, `max|Δ|=0.000e+00` |
| 权重手动置非零 | 输出确实变(通道真参与) | True, `max|Δ|≈0.0792` |
| 仅 p_cond(无 l4_cond) | token 5→6, 原 token 不变 | True |

下一步: 用 (p_next, 动作真值) 训这层 3→cross_attention_dim 投影, 数据可从
`ss_traj_last.json` 的 `u_exec_vec` 起步; 训练前不得把"通道已接"报成"效果已提升"。

## 11. INTACT 的 predictor 在哪 (以及它现在不参与预测)

- 定义: `external/INTACT-JEPA/module.py::ARPredictor`(Autoregressive action-conditioned latent predictor,
  (LeWM); 运行时副本 `external/INTACT-JEPA/paper_runtime/module.py`(同一份, `RUNTIME_SHA256SUMS` 校验)。
- 挂载/调用: `jepa.py` 里 `self.predictor = predictor` 与 `prediction = self.predictor(embedding, action_embedding)`;
  `history_size` 取 `model.predictor.pos_embedding.size(1)`。
- 装载: `tools/intact_worker.py` → `import stable_worldmodel as swm` 加载整颗模型(hf `INTACT-JEPA/INTACT`,
  rev `paper-e5-goal-v1`), 权重落 `zmax_data/stable-wm-cache`(`STABLEWM_HOME`); 这段必须在
  INTACT-JEPA/.venv 里跑, 与 gui-venv311 不兼容 ⇒ 只能走子进程桥。
- **判据: `policy=direct`(零搜索) 路径不调用 predictor** —— 它在内存里但没参与预测, 只有传
  `prefix_actions` 才走。先看 `describe()['node']['policy']` 与 worker 日志再下结论,
  别把"predictor 已加载"当成"predictor 在工作"。
- 别与自有"流形专家预测器"混: `src/lerobot/manifold/predictor_layer.py`
  (`LatentPredictor`/`WorldModelPredictor`/`ManifoldReadout`, 权重 `models/l4_mani_predictor_v*.pt`)
  是另一套, 不属 INTACT-JEPA。
