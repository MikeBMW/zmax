# Z-MAX 平台数据目录说明

本目录为 Z-MAX 平台的数据根目录，采用统一分区结构：工程数据、标定数据、场景数据、技能库、记忆层与数据集各自独立成区，顶层仅保留六个分区，便于交付、备份与迁移。

## 分区结构

| 分区 | 内容 | 关联模块 |
|---|---|---|
| `database/` | 产品数据目录，按产品分子目录：`zmax/` = Z-MAX 平台标准产品数据路径，内含 `zmax_engineering.db`（唯一工程数据库）、`zmax_space.proj`（状态空间总工程）、`README.md`（产品手册）、`archive/`（历史工程快照）；参数变更事件记录于库内 `param_events` 表 | `tools/engineering_db.py`、`tools/gui/project_file.py`、`platform_spec.py`、`param_center.py` |
| `skills/` | 技能库：`l2_atomic/`（原子技能注册表与示教点）、`l2_muscle/`、变更记录 | `l2_daemon`、`l2_skill_dialog`、`l2_skill_learn` |
| `scene/` | 场景、叠加与感知：`scene_state.json`（感知链单一数据源）、`overlay_spec.json`、`cam_calib.json`、`traj_display.json` | `sync_scene_state`、`scene_overlay`、`traj_display`、视频推流与叠加 |
| `memory/` | 记忆层：`memory_layers.json`（分层开关）、`shared_memory.json`、`macro_memory.json`、`assembly_memory.json`、`muscle_memory.json`、`intact_robot_state.json` | `src/lerobot/memory/*`、画布记忆层节点 |
| `calib/` | 标定：`handeye/`（手眼标定采集与结果）、`selfcal/`、`aoi_caliber_bench/` | `a5_handeye_collect`、`selfcal_kinematic`、`aoi_caliber_*` |
| `datasets/` | 数据集：检测/分割/深度/域随机、状态空间数据集、仿真数据集、演示数据集、点云与录制数据 | 训练、评测与标注全链 |

## 约定

1. **数据归位**：工程相关文件统一置于 `database/`，数据集统一置于 `datasets/`，不再向数据根目录直接写入文件。
2. **路径解析统一入口**：按名称动态构造数据路径（数据集枚举、按名称定位目录）须经由 `tools/gui/data_locate.py`：

   ```python
   from data_locate import data_dir, datasets_root
   dp = data_dir(root, "metaworld_peg")     # 解析至 data/datasets/…，未命中时回退至旧顶层布局
   ```

   直接拼接 `os.path.join(root, "data", "xxx")` 在分区调整后不会报错，但会静默查找失败。

3. **数据库为生成物**：修改真源后执行 `python3 tools/engineering_db.py build` 重建，`check` 判据全部通过方视为同步。
4. **布局迁移工具**：`python3 tools/data_layout.py --dry|--apply`，自带备份与迁移清单。

## 真源对应关系

| 数据 | 真源（纳入版本管理） | 本目录内 |
|---|---|---|
| 状态空间工程七段 | `config/**` 与 `flows/state_space_obs.json` | `database/zmax/*.proj`（快照，由控制台或 `project_archive.py` 写入） |
| 工程数据库 | 上述真源 | `database/zmax/zmax_engineering.db`（生成物） |
| 标定 | `config/calib/zmax_calib.json` | `calib/`（采集数据与结果） |
| 能力数据库 | `feature.dbc` | — |

---

迁移留痕：`zmax_data/backups/DATA_LAYOUT_MANIFEST_20261009_211940.jsonl`（56 项搬迁、131 个文件路径改写）。
