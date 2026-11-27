# v5.35.0 现场数据存档 (2026-10-09)

**主题**: 平台/实例解耦 + 工程根目录整合（中版本）

## 本目录文件
| 文件 | 是什么 |
|---|---|
| `zmax_engineering.db` | 单一工程库（24 表；本版 check 全绿） |
| `canvas_state_space_obs.json` | 状态空间画布真源（v5.35.0 当时状态） |
| `zmax_space.proj` | 总工程（7 段：画布/面板/标定/主参数/测量/任务/指纹） |
| `ss_task_binding.json` | 任务绑定（活跃 TASK-01-FW） |
| `zmax_calib.json` / `zmax_manifold.json` | 标定真源 + 主参数（M） |
| `judges.txt` | 本版判据实跑输出（工程库 check + 平台/实例 边界体检） |

## 本版关键变化
- 真源（config/ · feature.dbc · 画布）搬进实例数据包 `data/database/zmax/sources/`，
  平台仓库内为符号链接；换一套数据 = 迁移一个目录（`tools/instance_init.py --link`）。
- `defaults/` = 出厂骨架（结构同构、数值清空），全新安装用 `instance_init.py --new` 铺开。
- `docs/` 平铺归零（17 桶），商务交付资产移出公开仓库 → `zmax_data/backups/商务交付/`。

## 恢复方式
```bash
cp docs/data_snapshots/2026-10-09_v5.35.0_平台实例解耦/zmax_engineering.db  data/database/zmax/
cp docs/data_snapshots/2026-10-09_v5.35.0_平台实例解耦/canvas_state_space_obs.json \
   data/database/zmax/sources/canvas/state_space_obs.json
python3 tools/engineering_db.py build && python3 tools/engineering_db.py check
```
