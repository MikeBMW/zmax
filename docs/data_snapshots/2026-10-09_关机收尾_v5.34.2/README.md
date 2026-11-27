# 关机收尾快照 — v5.34.2 (2026-10-09 夜)

老倪: 「保存数据, 小版本迭代, 准备关机。」(当天第二次收尾 —— 上一轮已出 v5.34.0 定版 / v5.34.1 按钮修复)

## 文件

| 文件 | 是什么 |
|---|---|
| `zmax_engineering.db` | 单一工程数据库 (当天最后一次重扫) — 一个文件 = 一套工程, GUI 只认它 |
| `param_events.jsonl` | 改数留痕流水 (与库 `param_events` 表同源) |
| `canvas_state_space_obs.json` | 状态空间画布真源快照 (节点/连线/行带) |
| `release_status.json` | 当天桌面版发布证据: tag / 运行 URL / 结论 / 资产名与字节数 (取自 GitHub API) |
| `shutdown_checklist.md` | 关机前核对单 (开机自启项 / 在跑服务 / 磁盘 GPU / 下次继续的点) |

## 当天发布结果 (实测, 非声称)

- **v5.34.0** = 定版 (侧栏 UI + 产品/系统/功能三级 + 单一工程库 + 参数中心)
  Release 资产: `Z-MAX_Console.exe` 171.0 MB + `Z-MAX_Console-macOS.zip` 134.6 MB · CI 结论 success
- **v5.34.1** = 找回画布工具栏 🧮 状态空间 / 🛰 工位总览 两个按钮 (构建中, 完成后资产同名前缀)
- 下一版看 Releases: https://github.com/MikeBMW/zmax/releases

## 关联

- 版本说明: `docs/design/v5.34.0_summary.txt` · `docs/design/v5.34.1_summary.txt` · `docs/design/v5.34.2_summary.txt`
- 上一份数据快照: `docs/data_snapshots/2026-10-09_v5.34.0_侧栏UI定版/`
- 现场归档: `zmax_data/release_5.34.0_20261009/` · `zmax_data/release_5.34.2_20261009/`
