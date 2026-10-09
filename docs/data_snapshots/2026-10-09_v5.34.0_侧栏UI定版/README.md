# v5.34.0 现场数据快照 (2026-10-09 定版)

老倪: 「定版, 小版本升级, 发布 windows mac 版本, 保存数据, 推送代码, 准备关机。」

`data/` 在 `.gitignore` 里 (runtime state), 所以要归档的现场数据必须**拷进受版本管理**的目录才算真保存。
本目录 = v5.34.0 定版当天在本机跑出来的数据真源。

## 文件

| 文件 | 是什么 | 当天实测数字 |
|---|---|---|
| `zmax_engineering.db` | **单一工程数据库** (一个文件 = 一套工程; GUI 只认它) | 平台 1 · 产品 2 · 产品特征 18 · 子系统 4 · 子系统三轴 48 · 功能 74 · 功能三轴 1594 · 标定参数 41 · 模块 74 · 模块代码 74 · 能力 31 · 接口 62 · 诊断 57 · 画布节点 74 / 连线 184 · 工程 7 段 27 行 · 关系链 368 · params 162 · param_links 375 · mcd 5 行 |
| `param_events.jsonl` | 改数留痕流水 (谁/什么时候/把哪个数字改成什么) | 见文件行数; 与库 `param_events` 表同源 |
| `canvas_state_space_obs.json` | 状态空间画布真源快照 (89 节点 / 184 连线 / 16 行带) | 与 `src/lerobot/engineering/flows/state_space_obs.json` 同源 |

## 当天关键数字 (与库一致, 可对账)

- MCD 三轴 (测量/标定/诊断): 产品 M9/C45/D57 · System 0 M9/C41/D38 · System 2 C4/D11 · System 1 D8 · 平台支撑 M9/C45/D57
- 功能: System 2 = 30 · System 1 = 4 · System 0 = 27 · 平台支撑 = 13 (合计 74)
- 可改数字 162 个: 🟡标定/真源 45 · 🔵画布 78 · 🟣代码常量与函数默认参数 25 · 🟢产品性能 8 · 🟠运行开关 6

## 关联路径

- 重建库: `python3 tools/engineering_db.py build` (从真源重扫) · 校验: `check` (17 项)
- 只读服务: systemd `zmax-engdb.service` → 127.0.0.1:8798
- 现场归档 (代码+真源+证据+文档+MANIFEST+sha256): `zmax_data/release_5.34.0_<日期>/`
- 本版说明: `docs/design/v5.34.0_summary.txt`
