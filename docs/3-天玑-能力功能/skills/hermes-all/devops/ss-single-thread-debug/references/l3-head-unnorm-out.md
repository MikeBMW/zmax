# action head 出口直出真机口径（unnorm_out）

默认契约: `predict_action` 出口是**归一化空间** `[-1,1]`（MIN_MAX），毫米换算在下游 `post()`。
用户要求「就在 action head 里输出可执行 chunk、不要 node 补」时，按下面的做法落 —— 已实测 PASS，且训练路径零影响。

## 为什么默认不塞进 head
- `action_head.py` 里对 `stats/min/max/unnorm` 的引用数本来就是 0：它只从 `config.action_dim` 知道维度，学的是已归一化的训练标签。
- 归一化方式在 `configuration_smolvla_lew.py`（ACTION=**MIN_MAX**，不是 mean/std），具体 min/max 在数据集 `meta/stats.json`，由 `make_pre_post_processors` 造出的 post 持有。
- 这份 head 与 `vla_jepa` / `groot` 共用同构逻辑，硬编码一套统计量等于把三条 policy 绑死。

⇒ 所以用**开关 + config 注入**，默认关，不动别人的路径。

## 落地四处（缺一处就双重反归一化或静默错值）

1. **config 加四个字段**（`configuration_smolvla_lew.py`，紧跟 `normalization_mapping`）：
```python
unnorm_out: bool = False                   # True ⇒ predict_action 出口直出真机口径
action_min: list[float] | None = None      # 数据集 action.min
action_max: list[float] | None = None       # 数据集 action.max
grip_binary_thresh: float = 35.0            # 真机夹爪只有 0=合 / 70=开
```
2. **head 在 `return actions` 前做三步**（`action_head.py`，在 flow-matching 采样循环之后、return 之前）：
```python
if getattr(self.config, "unnorm_out", False) and self.config.action_min is not None \
        and self.config.action_max is not None:
    _mn = torch.tensor(self.config.action_min, dtype=actions.dtype, device=actions.device)
    _mx = torch.tensor(self.config.action_max, dtype=actions.dtype, device=actions.device)
    actions = (actions + 1.0) / 2.0 * (_mx - _mn) + _mn          # MIN_MAX 逆变换
    actions = torch.clamp(actions, min=_mn, max=_mx)             # 硬边界 = 数据集工作空间
    if actions.shape[-1] >= 4:                                   # 夹爪二值化
        _th = float(getattr(self.config, "grip_binary_thresh", 35.0))
        _g = actions[..., 3]
        actions = torch.cat([
            actions[..., :3],
            torch.where(_g >= _th, torch.full_like(_g, float(self.config.action_max[3])),
                        torch.zeros_like(_g)).unsqueeze(-1),
            actions[..., 4:],
        ], dim=-1)
return actions
```
`clamp` 不是可选项：未训好/分布外输入时归一化输出会越界（实测随机权重跑出 x=45 / x=1012），
越界目标交给机械臂就是撞界点，宁可钉在边界。
3. **ckpt config.json 注入** `unnorm_out/action_min/action_max/grip_binary_thresh`。
   训练产出的 config 不带这三项（draccus 从 yaml 生成，yaml 里没写）⇒ 每次新 ckpt 都要补：
```bash
python tools/inject_unnorm_stats.py --all outputs/train/<实验名>
```
4. **下游必须跳过 `post()`**（`smolvla_lew_l3.py` 的 infer）：
```python
_head_unnorm = bool(getattr(getattr(pol, "config", None), "unnorm_out", False))
if _head_unnorm:
    act = pred                      # head 出口已是真机口径, 再 post 一次 = 双重反归一化, 动作全废
    lmeta["unnorm"] = "head(出口直出真机口径)"
else:
    act = post(pred) if post is not None else pred
    lmeta["unnorm"] = "node(post)"
```

## 双重反归一化的连带雷区
同一份 ckpt 换到还写着 `post(pred)` 的脚本上跑，会把 mm 再当 `[-1,1]` 拉伸 ⇒ 相关性/误差全错，
而且不报错、只是“模型看起来很蠢”。改 config 前先 grep 这些调用点：
```bash
grep -rn "post(pred)" --include=*.py src/lerobot/engineering/ tools/
```
已知存量（都要加同样的判断）：`tools/eval_policy_corr.py`、`tools/rollout_smolvla_lew.py`、
`tools/probe_smolvla_lew.py`、`tools/fork_experiments/eval2.py`。

## 验证（不加载 500M VLM，只造 head）
从 ckpt 的 `config.json` 构造 `SmolVLALewConfig` → `SmolVLALewActionHead(cfg, cross_attention_dim=960)`
→ `predict_action(torch.randn(1, num_vision_tokens, 960), state=torch.randn(1, state_dim))`，判三条：
- shape == `(1, chunk_size, action_dim)`
- x/y/z 全落在 `[action_min, action_max]`（clamp 生效）
- grip 取值集合 ⊆ {0, action_max[3]}（二值化生效）
⚠️ 这条测试用的是**随机权重**，所以输出会被 clamp 顶在边界上 —— 它证的是「代码路径和出口形态」，
不是模型水平。报结果时必须写明这点，否则用户会以为模型输出就是 211.19/817.84。

## 断点位置随之改变
`return actions` 从原行号下移到反归一化/二值化之后（加代码会让后面的行整段下移，每次改完重新 grep）：
```bash
grep -n "torch.clamp(actions\|夹爪: 真机只有\|return actions" <action_head.py>
```
停在 `torch.clamp` 那行 = 反归一化后、二值化前；停在 `return actions` = 最终 chunk，`actions` 直接就是 mm，不需要 Watch 表达式。
