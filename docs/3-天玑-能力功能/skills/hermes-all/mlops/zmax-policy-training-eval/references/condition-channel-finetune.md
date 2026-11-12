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

## 判断顺序 (省时间)

```
① loss.requires_grad ?  ── False ─→ 查装饰器 → 仍 False ─→ 查 numpy 出口
② 显存 ≥24GB 可用 ?    ── 否 ───→ 换机 或 两段式
③ 三行判据能算 ?       ── 是 ───→ 才写训练循环
```
先跑 ①②, 不要先写 epoch 循环 —— 本次就是先写了循环, 卡在 backward 才回头查出口。
