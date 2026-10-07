---
name: manifold-engine-energy
description: Use when 给流形引擎做能量层或挂 ss_energy 话题。
---

# 流形引擎 · 能量层 (发动机类比)

## 何时用
- 用户要「引擎像发动机一样」有输出功率/效率/转数/能量，且能量要跟 L2/L3/L4/L5+LoRA 映射。
- 要把某层的"能力"做成可观测、可测量、可记录的量，并挂到全局数据空间 topic。
- 训完一轮要回答"各层到底做出了多少能力"。

## 口径（先定后跑，写进契约就别改）
单位 CJ（能力焦耳）= 把归一化势能下降 1.0 的能力。每层两个分量：
- **存量能力** `standing_cj = 能力水平 c ∈[0,1] × 循环数 N` —— 基座在场就有 = 用户的"基础 L2 能量"。
- **做功增量** `energy_cj = τ × N` —— 本轮真做出来的功 = "L3/L4/L5 增强能量"。
- `energy_total_cj = standing + work`；`E_total = Σ energy_total_cj` = 各层能力总量。
- `τ = |Δ势能| / 循环数`（扭矩）；`ω` = 该层更新频率(Hz)；`P = τ·ω`；`η = E_total / 电功(CJ/J)`。
- 能力水平 c 取该层**真实指标**：L2 = mAP50 末值；L3/L4 = 1 − pot_end/pot_start（clamp 0..1）；L5 = 意图收敛水平（运行口径）。
- LoRA boost = `energy × gain`，gain 必须来自 A/B 实测 Δ（没有对照就不给增益）。
- 能级壳层：壳 1..4 = L2..L5，`e_cum` 单调不减（能量向上扩张）、`feasible_r` 单调不增（权限向上收窄）。

## 三步落地
1. **公式层** `src/lerobot/manifold/energy_manifold.py`：`EnergyManifold.absorb_stage(layer, secs, cycles, loss_series, level_c, lora, src)`，`total()` 出总量/壳层/占比。自带 `--selftest`（可加性、单调、收窄、能量非负、η 符号口径）。
2. **实测层** `tools/manifold_energy_probe.py`：
   - `run --only L4,L3,L2,LLM --steps N [-- --l4-epochs 2]` 真跑一轮 pipeline 迭代，全程 `nvidia-smi` 采电功率，逐阶段窗口折算。
   - `ingest --run reports/joint_train_<ts> [--power-file reports/power_<ts>.jsonl]` 离线复算。
   - 落盘：`zmax_data/ss_live/energy_<ts>.jsonl`（**最后一行才是 payload**）+ `reports/manifold_energy_<ts>.json` + `reports/power_<ts>.jsonl`。
3. **观测层** topic `zmax/ss_energy`：`dds/ss_types.py` 加 `SSEnergy`/`SSEnergyLayer` → `dds/zmax_node.py` 的 `_SS_TOPICS` + `QOS_CLASS` → `src/lerobot/dataspace/topics.py` 的 `TOPICS`/`MODE_TOPICS`/`PRODUCERS`/`QUALITY_RULES` → `tools/dds/ss_daemon.py` 的 `read_energy()`/`pub_energy()`/tick。

## 坑（都实测踩过）
- **动态加载带 @dataclass 的模块必须先 `sys.modules[spec.name] = m` 再 `exec_module`**，否则 dataclasses 取 `sys.modules.get(cls.__module__).__dict__` 报 `'NoneType' object has no attribute '__dict__'`。
- **透传给 `joint_train_all.py` 的额外参数必须放 `--` 之后**：直接写 `--l4-epochs 2` 会被 argparse 拆成 `["2"]`+`["--l4-epochs"]`，拼出 `… 2 --l4-epochs` ⇒ `expected one argument`。
- **INTACT 的 `validate/loss` 是负值**（越负越好）：势能取 `−loss`，能量折算分母用 `abs(loss0)`，否则 −3.5→−3.9 也算成"下降"。
- **L4 测 τ 必须 `--l4-epochs ≥ 2`**：单点无下降区间，τ 只能记 0（如实，不补数）。
- **`validate/loss` 两种格式都要收**：rich 表格行 `validate/loss  |  -3.815  |` 与 lightning 汇总 `validate/loss: -3.815`；统一 `validate/loss\s*[|:]\s*(-?[\d.eE+-]+)` 并按序去重。
- **能量 ≠ τ·ω·秒**：`omega_hz_measured`（实测步率）只替换转速读数与输出功率，能量保持 `τ·循环数`（实测步率与 循环数/时长 非同量）。
- **守护要读工程根下的 tap**：`SS_REMOTE` 默认若指向空目录（如 `~/zmax_ss_remote`），话题全静默；应按 "显式 env > 工程根 `zmax_data/ss_live` > 旧默认" 解析。
- **每轮聚合量给单独的帧龄预算**：能量是"一轮一份"，用状态的 5s 阈值会永远"过期"；`STALE_ENERGY_S=900`，过期就**不发**并写日志，绝不把上上轮的数当现在。
- **画布节点注册关键词要避开更短关键字的抢先**：`match_node` 取**最长**匹配，所以 `流形引擎能量` 可安全共存于 `流形引擎`（对照验证两者分别命中 ss_energy / ss_mani_eng）。

## 取证（交付前必做）
- 自检：`Σ分层 == E_total`（1e-12）、壳层单调、可行域收窄、每层能量 ≥ 0。
- 端到端订阅：另起一个 DDS 订阅者收 `zmax/ss_energy`，**逐位核对** `e_total_cj` 与 tap 最后一行一致（不是"看起来像"）。
- 报数必带：`P_in` 来源、采样点数、阶段窗口、η 符号（无采样就 `η=-1` 如实）。

## 整合后环境链路（2026-10-07 修，别再踩）
- 工程根 `/home/ubuntu/zmax`，HF 家在 `zmax_data/hf_cache`（`~/.cache/huggingface` 已空）⇒ 各训练阶段必须带 `HF_HOME`/`HF_HUB_CACHE`。
- `import torch` 报 `libcusparseLt.so.0` 找不到 = `/etc/ld.so.conf.d/nvidia-pip.conf` 还指整合前已删路径；改指 `~/zmax/gui-venv311/lib/python3.11/site-packages/nvidia/*/lib`（`cusparselt` 需补一个去 `nvidia/` 前缀的兼容软链，因为 torch RPATH 那一项没带 `nvidia/`）。
- 数据集 yaml 里的绝对路径会残留整合前路径：`tools/yolo_annot_dataset.py --build` 重建即可。
