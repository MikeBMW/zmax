# configs/generated_train_configs/ — 训练生成的配置（不是手写配置）

2026-10-08 从仓库根目录收编进来的。**这些文件是训练脚本生成的运行产物，不是人手写的源配置。**

## 里面是什么

| 文件 | 谁生成 | 说明 |
|---|---|---|
| `config_smolvla_lew_lora_<steps><tag>.yaml` | `tools/joint_train_all.py`（L3 段 `mkcfg` 步骤） | 每跑一轮联合训练就生成一份，文件名带 steps 与 tag。`<tag>` 里带 `l5260928_070442` 形式的是**轮次时间戳** |
| `config_smolvla_lew_sim.yaml` | `tools/mk_smolvla_sim_cfg.py`（仿真有界步数用） | `--out` 默认值已指向本目录 |

## 为什么留着不删

它们是**训练留痕**：每轮训练目录 `reports/joint_train_<时间戳>/summary.json` 与 `L3_mkcfg.log` 里记的是**这些文件名**，
删掉文件名还在、文件没了 ⇒ 回溯"那一轮到底用什么配置跑的"就断了。所以按"生成物统一收纳"处理，而不是清理掉。
逐文件的 `from → to` 与"被哪些训练目录引用"记录在 `zmax_data/backups/root_yaml_tidy_20261008.jsonl`。

## 注意

- 已被 `.gitignore` 覆盖（`config_smolvla_lew_lora_*.yaml`，gitignore 的无斜杠模式在任意层级都匹配）⇒ 入库不会因此变大。
- ⚠️ 配置里的 `dataset.root`（如 `data/smolvla_peg_v8_d1`）是 **CWD 相对**的：lerobot 侧是 `Path(cfg.dataset.root)` 直通，
  不会按配置文件所在目录去拼。**所以训练必须在仓库根 `cd /home/ubuntu/zmax` 下启动**，放哪个子目录都不影响解析。
- 手写的策略配置在 `configs/policies/{act,smolvla,smolvla_lew,hybrid}/`，不要往这里放。
