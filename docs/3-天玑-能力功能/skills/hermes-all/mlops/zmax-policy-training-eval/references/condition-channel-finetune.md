# 给已训练 policy 加条件通道 (p_cond / l4_cond_proj) — 可行性与墙

目标形态: 冻结主干, **只训一个零初始化的 residual 投影** (`p_cond_proj` 960×3,
`l4_cond_proj`), 让画布上 L4→L3 那条条件线从"零权重装饰"变成真正影响动作。

> 边界: 本文记的是**可行性判别 + 已验证的墙**。训练没跑通前别把下面的替代路线当已验证方案。

## 动手前先答两问 (答完大概率不必写训练循环)

### 问 1: 模型出口是不是 numpy?
`smolvla_lew` 的 `modeling_smolvla_lew.py` 里 `predict_action` 出口是
`torch.from_numpy(actions_np)` —— **一来一回, 计算图在源头就断**; 且 `action_head.predict_action`
与 `predict_action_chunk` 各自带 `@torch.no_grad()`。

判别顺序 (别反过来):
```python
loss = f(pred, target)
print(loss.requires_grad)      # False ⇒ 图根本没建起来
```
- 先查**装饰器** (`grep -n "@torch.no_grad()" src/lerobot/policies/smolvla_lew/`);
- 摘掉装饰器后**仍 False** ⇒ 别再继续摘, 直接查出口有没有 numpy 往返 / `.detach()` /
  `float()` / `list()`。numpy 出口不重构就没有梯度, 摘一百个装饰器也没用。

### 问 2: 显存装得下反传主干吗?
前向能过 ≠ 反传能过 (反传要留全部激活)。实测口径: 4060 **7.62 GB**, 在跑的服务已占 5.5 GB,
batch 2 直接 OOM, batch 1 前向通过但反传爆 —— 500M 主干 + 图像 token 不是 8 GB 的量级。
**结论: 要反传 SmolVLA 主干, 先确认 ≥24 GB 可用显存**, 或走下面的两段式。
显存预算当场算, 别训到一半才发现:
```bash
nvidia-smi --query-gpu=memory.total,memory.used --format=csv
```
在跑的服务占多少要先看到 —— 服务不参与训练却占着显存, 会把"够用"算成"不够"。

## 两条替代路线 (候选, 未在本机验证)

1. **两段式**: 主干 `no_grad` 前向把 conditioning token / 图像特征缓存到磁盘, **只反传 DiT 头**。
   便宜, 但头与主干表征脱耦 ⇒ 必须再做一次端到端对照评估才能上默认档。
2. **换大显存机**: 同一套 torch API 换前缀即可 (Intel Arc 走 `xpu`)。

## 数据与判据 (这部分已验证)

- 数据: `data/datasets/sim_TASK-01-FW` — 7252 帧, `videos/observation.image/chunk-000/file-000.mp4`
  128×128/30fps, `observation.state` **39D**, `action` **4D**; 与 `smolvla_lew_l3.py` 的 obs39 同构,
  这就是它能直接拿来训条件通道的原因。ckpt 默认走 `_CK_DEFAULT` / 环境变量 `SS_L3_CK`。
- 属性名: 动作头是 `pol.model.action_model` (`SmolVLALewActionHead`), **不是** `pol.action_head`。
- **三行判据** (缺一不算通道打通):
  1. 基线 `p_cond = 0` 的 val RMSE;
  2. 有条件喂真值时 RMSE 必须下降;
  3. 训好后再把 `p_cond` 置零, RMSE 必须回到基线。
- ⚠️ **零初始化下"有条件 == 基线"是正常的**: `w=0` 时 residual 通道恒等于无, 别把它当通道坏了。
  通道活着的证据是"非零权重时动作确实变"(实测 `max|Δ| = 0.0792`, 零权重时逐位相同)。
- 脚本: `tools/train_p_cond_proj.py` (冻结除 proj 外全部, `--limit/--batch/--accum/--epochs/--lr/--smoke/--out`)。
  单卡 8 GB 时 `--batch 1 --accum 4` 是唯一能起前向的组合。

## 接口对齐阶段的验证 (链路通 ≠ 有用, 但两者要分开证)

前提: `apply_l4_cond` / `predict_action(..., l4_cond=)` 在 `action_head.py` 和
`modeling_smolvla_lew.py` 里**早已存在**, 缺的只是 infer 侧没传。接通只要一行
`pol.select_action(batch, l4_cond=t)` —— 先去 grep 确认通道存不存在, 别从头造。

**三层验证, 由浅入深 (每层都实测, 别跳)**

1. **结构层 — token 真的多了一个**
   ```python
   ct  = torch.zeros(1, 7, head.cross_attention_dim, device=dev)
   ct2 = head.apply_l4_cond(ct, torch.as_tensor(cond.reshape(1, -1), device=dev))
   print(tuple(ct.shape), tuple(ct2.shape), float(ct2[:, ct.shape[1]:].norm()))
   # (1,7,960) → (1,8,960)   追加 token 范数 0.0085(只 ξ) / 0.55(ξ+manifold6)
   ```
   范数为 0 ⇒ 投影权重全零或 cond 全零, 通道没进去。

2. **注入层 — meta 自报**
   `select_action` 前把 cond 转 `(1,N)` float32 上 device, 成功后写
   `meta.l4_cond_injected=True / l4_cond_dim=N`; 转换失败写 `l4_cond_err` 并置 False。
   下游日志/页面只认 `l4_cond_injected=True`, **别用"我传了"当证据**。

3. **可证伪层 — 三态动作对比**
   `cond=None` vs `cond=真值` vs `cond=全零` 各跑一次, 打 `max|Δ|`:
   - `|真值 − None| > 0` ⇒ 通道真参与前向;
   - **`|zeros − None| > 0` 是正常的** (零向量 ≠ 不加 token, 投影有 bias/随机权重),
     别拿它判 bug;
   - 三态都撞 clamp 边界 (实测 817.839=max / 211.187=min) ⇒ 模型本身没训好,
     这个 Δ 数字不能当"条件有用"的证据。

**条件向量布局 (15 维, 从 SE(3) 引擎来)**
```
[0:6]   ξ̂         se3_log(T_goal⁻¹T); 平移 mm/行程 + 旋转 rad/π 各自归一后 clip(±1)
[6:12]  manifold6 接触3(progress/risk/V) + 性能3(η/rem/d_perp)
[12:15] intent3   L5 意图; 未接入就真是 0
```
元数据必带 `cond_real={'xi':bool,'manifold':bool,'intent':bool}` —— 12/15 是真值时要能一眼
看出剩下 3 维是 0 而不是"小值"。

⚠️ **两块分量量级差很多**: ξ̂ 在 0.012 量级而 manifold6 在 0.2~0.65, 追加 token 范数从
0.0085 跳到 0.55 (65×) ⇒ 条件信号几乎全由流形读数主导, 几何 twist 成了小量。要让两者
均衡, 得在投影前各自归一。

## 混域是硬红线: 口径对不上就标分布外, 不要凑

`WorldModelPredictor` 的 z7 训练口径是 `[x−tgt, x−peg, grasped]` (`library.py` 构造)。
真机侧能拿 `x` (tcp 真值) 和 `tgt` (215 点表), **但 `peg` 的 base_link 位置只有仿真源**
(`zmax_data/ss_live/trace_live.json`, 自带 `src='...metaworld seed=0...'`)。

⇒ 真机 z7 凑不出训练口径。只有两种可选做法, 都得如实标:
- 喂 SE(3) 的 `[平移误差, 旋转误差, grasped]` + 元数据写
  `z7_scale_note="v5 训练口径为 [x-tgt,x-peg,grasped] ⇒ 本次分布外"`;
- 或先补真机 peg 视觉位置 (AOI 检测 / 手眼投影) 再喂。

**绝不要**把仿真 peg 混进真机 z7 去"对齐口径" —— 那是混域编数。

**权重形状必须逐层对**: `WorldModelPredictor(z_dim=7, act_dim=4, hidden_dim=512, num_layers=4)`
—— `num_layers` 错一层就报 `size mismatch for predictor.mlp.4.weight: (512,512) vs (7,512)`。
判别法: `torch.load(ck, weights_only=False)` 打印全部键 shape, 数 `predictor.mlp.N` 层数反推
`num_layers` (`mlp.0..8` = 4 层隐藏), `readout.mlp.0` 的 in_features = z_dim。
`load_state_dict(sd, strict=False)` 后**必须检查 `missing_keys` 为空**才算加载对 ——
只看"没抛异常"会把静默跳过的层当成功。

## 判断顺序 (省时间)

```
① loss.requires_grad ?  ── False ─→ 查装饰器 → 仍 False ─→ 查 numpy 出口
② 显存 ≥24GB 可用 ?    ── 否 ───→ 换机 或 两段式
③ 三行判据能算 ?       ── 是 ───→ 才写训练循环
```
先跑 ①②, 不要先写 epoch 循环 —— 本次就是先写了循环, 卡在 backward 才回头查出口。
