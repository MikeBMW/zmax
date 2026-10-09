# data/ 数据与工程文件布局 (2026-10-09 老倪: 「所有工程文件和数据库文件都放在 data/database；继续整合所有数据文件，现在的数据太杂乱了」)

## 目标形态

```
/home/ubuntu/zmax/data/                 # 📦 数据根 (顶层只此 6 桶 + 本说明)
├── README.md                           # 顶层说明 (每桶是什么/谁在用/真源在哪)
├── database/                           # 🗄 工程文件 + 数据库
│   ├── zmax_engineering.db             #   单一工程数据库 (SQLite, 生成物)
│   ├── zmax_space.proj                 #   🗂 总工程 (GUI 文件 → 打开总工程, 集成式回填 7 段)
│   ├── (无 jsonl)                       #   改数留痕已在库里: param_events 表 (build 不清空)
│   ├── README.md                       #   工程文件+库说明
│   └── archive/                        #   历史工程快照 + 按需导出件 (只读留档)
├── skills/                             # 💪 技能库: l2_atomic/ (注册表+示教点) · l2_muscle/ · CHANGELOG
├── scene/                              # 🎬 场景·叠加·感知: scene_state.json · overlay_spec.json · cam_calib.json
├── memory/                             # 🧠 记忆层: memory_layers / shared / macro / assembly / muscle / intact
├── calib/                              # 📐 标定: handeye/ · selfcal/ · aoi_caliber_bench/
└── datasets/                           # 📊 数据集: yolo_* · ss_* · metaworld_* · smolvla_* · orin_* · *.npz/*.mp4
```

顶层从 **60 个条目** (40 多个指向 `external/lerobot-smolvla-lew/data/` 的软链 + 十来个真目录) 收到 **6 个桶**。

## 代码口径

| 位置 | 约定 |
|---|---|
| 工程文件目录 | `tools/gui/project_file.py::project_dir()` → `<root>/data/database` |
| 总工程路径 | `project_file.space_path()` → `data/database/zmax_space.proj` |
| 工程库路径 | `tools/engineering_db.py::DB_DEFAULT` / `PROJ_DIR` → `data/database` |
| 按名字动态找数据集 | **必须**走 `tools/gui/data_locate.py`: `data_dir(root, name)` / `datasets_root(root)` |

**写死 `os.path.join(root, "data", "xxx")` 在分区后不报错、只是找不到** (`isdir` 为 False ⇒ 静默跳过)。
所以凡"枚举数据集 / 候选表按名字拼路径"的地方一律用 `data_locate`。

## 迁移做法 (可复现)

```bash
python3 tools/data_layout.py --dry      # 先看: 命中多少行/哪些文件 + 要搬哪些项
python3 tools/data_layout.py --apply    # tar 备份 → 改写代码 → 搬迁 (软链原样搬, payload 不动)
```

- 迁移器纪律 (写死在脚本里):
  1. 只改**可执行代码区** (`tools/ src/ config/ flows/` 顶层); `docs/ reports/ zmax_data/ external/` 与任何
     `_archive/` (历史快照 = 证据) 一律不动。
  2. 🔴 逐行排除 `lerobot-smolvla-lew/data/` —— 那是**另一个仓库**的 data 目录, 命中即错
     (实测 `tools/diag_aoi_frame.py` 就有 `~/zmax/external/lerobot-smolvla-lew/data/orin_live/*`)。
  3. 三种写法一起改: `data/<name>` · `os.path.join(..., "data", "<name>")` · 单引号版;
     名字长的先匹配, 避免 `data/scene` 吃掉 `data/scene_state.json`。
  4. 搬迁用 `mv` (同盘 rename, 数据不动); 软链保留原目标 (不把 fork 里的 payload 搬来搬去)。
  5. 留痕 `zmax_data/backups/DATA_LAYOUT_MANIFEST_<ts>.jsonl` (逐项 from→to + 逐文件改写行数),
     源码备份 `zmax_data/backups/data_layout_pre_<ts>.tar.gz`。

## 坑 (实测)

| 坑 | 症状 | 处置 |
|---|---|---|
| 动态拼路径扫不到 | 枚举数据集/候选表还在拼 `"data", name` ⇒ 分区后**静默为空** | 统一走 `tools/gui/data_locate.py` (studio / data_space / simulink_module 三处已改) |
| 别的仓库同名目录 | `external/lerobot-smolvla-lew/data/...` 被一起改写 | 逐行排除 `lerobot-smolvla-lew/data/` |
| 画布真源被顺带改 | 画布 desc 里写着 `data/xxx` ⇒ 改了画布 ⇒ 绑定 `canvas_md5` 失配 | 改完画布必须 `python3 tools/ss_task_bind.py --activate <task>` 重绑定, 再 `--check` |
| 长跑进程揣着老字符串 | 代码改完但进程还是老路径(静默重建老目录) | 改前先确认哪些脚本被改写 (`DATA_LAYOUT_MANIFEST`), 命中在跑服务就按官方脚本重启 |
| `data/` 整体被 .gitignore | `data/README.md` 进不了库 (父目录被排除时 `!` 无效) | 说明性文档放 `docs/notes/data_layout.md`; `data/README.md` 只当盘上指引 |

## 验收判据 (全绿)

```bash
python3 tools/engineering_db.py check            # 17 项 (含工程 7 段齐)
python3 tools/ss_task_bind.py --check            # 任务绑定一致
QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/verify_platform_spec.py   # 22 项
QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/verify_param_center.py    # 参数中心
QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/verify_project_archive.py # 7 段存档
python3 tools/repo_guard.py                      # 入库边界
ls -A data/                                      # 只有 6 桶 + README
```
