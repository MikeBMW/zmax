# 现场数据快照 — 20261014_L4_latent_chain

> 主题: **L4 潜空间 (VLM 编码器 → 黎曼度规约束) + L4 后段链 (意图解码器 → INTACT LoRA 微调 → 流形专家预测器 → 接触/性能流形)**
> 快照时间: 2026-10-14 20:42:10 · 触发: 老倪「保存数据，小版本迭代到 5.50.71」

`data/` 与 `zmax_data/` 被 .gitignore 排除 ⇒ 真源/证据必须拷贝进本目录才能进版本库。

## 文件清单

| 文件 | 来源 | 说明 | 大小 | sha256[:16] |
|---|---|---|---|---|
| state_space_obs.json | data/database/zmax/sources/canvas/state_space_obs.json | 画布真源 (LoRA 入链 + 元任务预测接 LoRA) | 112565 | f60e05a6077571a1 |
| ss_task_binding.json | config/ss_task_binding.json | 任务↔节点绑定真源 | 32591 | cd08c796b6466aa0 |
| zmax_manifold.json | config/calib/zmax_manifold.json | 主参数 M 真源 | 1232 | c1daa6fdf659d5ca |
| l4_latent_calib.json | models/l4_latent_calib.json | L4 潜空间标定 (μ/g_f/V/n 帧) | 311729 | fb3372e628d7d763 |
| meta_tasks.json | zmax_data/ss_live/meta_tasks.json | 元任务派生件 | 25478 | 5731733905435ed9 |
| meta_pred.json | zmax_data/ss_live/meta_pred.json | 元任务预测值 (LoRA 门控真源) | 3399 | a653ba7c3f3ebd62 |
| engine_loop_status.json | zmax_data/ss_live/engine_loop_status.json | 常驻回路状态 | 413 | f2a7dd4bd1ae2de9 |
| engine_latest.json | zmax_data/ss_live/engine_latest.json | 常驻回路最新一帧 | 1582 | 9a154663522faa10 |
| zmax_engineering.db | data/database/zmax/zmax_engineering.db | 工程库单文件 | 1400832 | ca30183196d348fd |
| tap 末 3 帧 | tap 末 3 帧 | 回路每周期一行 (含 encoder/z_source/z_latent) | 4434 | - |

## 本轮判据 (原文见同目录 txt)

- **本机 python**: Python 3.14.7
- **L4 潜空间判据**: 判据 10/10 PASS (完整输出见 L4_潜空间判据.txt)
- **L4 LoRA 链判据**: 判据 8/8 PASS (完整输出见 L4_LoRA_链判据.txt)

## 复现命令

```bash
cd /home/ubuntu/zmax
INTACT_POLICY=intact_l4_current STABLEWM_HOME=$PWD/zmax_data/stable-wm-cache \
  ./gui-venv311/bin/python tools/verify_l4_latent_space.py     # L4 潜空间 10/10
./gui-venv311/bin/python tools/verify_l4_lora_chain.py         # L4 后段链 8/8
./gui-venv311/bin/python tools/verify_ss_engine_loop.py        # 常驻回路 16/16
```

## ⚠️ 未进版本库的件 (按老倪 Git 精简口径: 库里只留清单)

- `data/database/zmax/zmax_engineering.db` (工程库单文件, 1.34 MB 二进制) —— 由 `tools/repo_guard.py` 拦下 (>300KB)。
  磁盘路径: `/home/ubuntu/zmax/data/database/zmax/zmax_engineering.db`
  sha256: `ca30183196d348fd8bbe1fd144cf886f5bc9dad48c2a27bd18c1ebaefe29ff1b`
  复现: `./gui-venv311/bin/python tools/engineering_db.py build` 可从库内 sources 重建 (判据 check 全绿)。
