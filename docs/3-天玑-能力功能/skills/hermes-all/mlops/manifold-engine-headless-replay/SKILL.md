---
name: manifold-engine-headless-replay
version: 1.0.0
author: Hermes Agent
license: private
description: "Use when 要让流形引擎离线重放一条录制轨迹产出 latent/势能序列, 或节点只认 GUI 播放态而离线跑空。"
metadata:
  hermes:
    tags: [manifold, engine, replay, headless, verification, zmax]
    related_skills: [l2-node-signal-linkage, zmax-state-space-architecture]
---

# 流形引擎离线重放 (录制轨迹 → 潜坐标/势能序列)

## When to Use

- 节点只从 `ctx["module"]._ss_tr` (GUI 播放态内存) 取轨迹, 离线调用一律返回 False 报「无引擎轨迹」。
- 要离线验证/回归涉及引擎量的下游 (潜空间、接触流形、性能流形、LoRA 条件、标定层)。
- 要拿引擎真算的 `z / p / p_next / action / residual` 序列做测试夹具。

## 引擎接口 (manifold_engine.py)

```python
from lerobot.manifold.manifold_engine import ManifoldEngine
eng = ManifoldEngine(homeostasis=False)
info = eng.fit(X_obs)          # X_obs: (N, 43)  必须先做
rec  = eng.step(state_43, dt=0.1)
```
`rec` 关键键: `z`(16维, 取前 4 = 位置3+预测力1) / `p` / `p_next` / `action` / `residual` /
`phi` / `manifold`(只是字符串如 `"sphere"`) / `z_source` / `M` / `guided`。

## 两个必踩的坑

### ① 不 fit 全轨迹 ⇒ z 恒全零
默认 `z_source` 是「内建 PCA 编码器 (Encoder.fit, 对当前状态拟合)」。逐帧 `step` 时每帧只有
**一个样本** ⇒ PCA 方差为 0 ⇒ 潜坐标全 0、`phi=0`、`residual=0`, 但**不报错**。
GUI 点 ▶ 是先 fit 全轨迹再 step 的。离线重放必须复刻这个顺序, 否则下游拿到全零当真值。
自检: `info['explained_var']` 第一项应显著非零 (实测 0.9648), 且末帧 `‖z‖ > 0`。

### ② 与常驻回路抢落盘文件
常驻引擎回路 (`tools/ss_engine_loop.py`, 10Hz) 每周期写 `zmax_data/ss_live/manifold_homeostasis.json`
及其 `.tmp`。再起一个默认构造的引擎会撞 `os.replace` ⇒
`FileNotFoundError: ...json.tmp -> ...json`。
- 开跑前先确认有没有常驻回路在跑 (按 `/proc` 或 `pgrep -af ss_engine_loop`; 不要用 `ps|grep 名字`)。
- 离线重放一律 `ManifoldEngine(homeostasis=False)` —— 关掉内稳态盘写, 不抢文件, 也不污染现场快照。

## 组装 GUI 播放态桩 (_ss_tr)

录制文件 `ss_traj_last.json` 只有 `obs(N,43)` / `u_exec_vec` / `t` / `stage`,
**没有** `latent_vec` / `prior_vec` / `corrected_vec` —— 这些正是引擎运行时算的, 所以必须重放。
节点读哪个键就填哪个, 实测最小列集:

```python
class _Mod:                      # 传给节点 ctx["module"]
    _ss_tr = {
        "t": [...], "stage": [...], "obs": obs.tolist(),
        "latent_vec": [z_i], "prior_vec": [p_next_i], "corrected_vec": [p_i],
        "x": obs[:, 0:3], "peg_head": obs[:, 11:14], "target": obs[:, 36:39],
        "v_vec": u_exec[:, 0:3],
        # 标定层真读这三列, 缺了就静默退默认值 (stage=接近, speed=0):
        "u_sat": [‖action_i‖], "residual": [residual_i],
        "contact_p": [σ(8·|residual_i|)],
    }
    _ss_round = N - 1
```
- `contact_p` 按引擎同口径 `σ(8·‖residual‖)` 算, 不要自己另定。
- `u_sat` 是**标量范数**不是向量 (历史 bug: 按 `[:3]` 索引会抛 too many indices 并被 try 吞掉)。
- `stage` 列缺失时给全长同值占位, 不要让节点自己越界。
- 节点可能读 `mani_progress / mani_risk / mani_eta` —— 引擎当前**不发布**这些真值列,
  取不到就交 `None` 并标未就绪, 不许伪造。

## 用法

把重放做成验证器的开关 (`--engine`), 而不是另写一个跑分脚本: 一次拓扑执行同时验证
「节点能跑」+「端口有值」+「值与引擎同源」。跑完必须打印一行自证
(帧数 / fit 耗时 / 潜维 / 末帧 z), 否则没法判断是不是又跑了全零。

## 铁律

- 重放结果只当**测试夹具**喂离线验证; 别把离线重放的量写回现场真源文件 (`*_last.json`, `engine_latest.json`)。
- 报「引擎跑过了」必须带三个数: 帧数、explained_var 首项、末帧 ‖z‖。只看「没报错」等于没跑。
- 引擎 `rec["manifold"]` 是类型标记不是真值; `phi=0 / residual=0` 往往说明标定或目标未就绪,
  不是引擎算对了零。
