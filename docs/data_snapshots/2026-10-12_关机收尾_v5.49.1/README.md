# 数据快照 2026-10-11 · 关机收尾 v5.49.1

老倪: 「保存数据，小版本迭代，准备关机」

| 项 | 实测结果 |
|---|---|
| 版本 | v5.47.0 → **v5.49.1**（无功能改动，8 处版本位已同步，tag 已推） |
| 工程库 | `engineering_db check` **判据全绿**（768 参数 / 1731 数字链接 / 184 连线 / 74 功能；本轮先实测到漂移 `['canvas','manifold']` 后 build 重建） |
| 画布真源 | `state_space_obs.json` md5 4d3824c6d63d · 89 节点 / 184 连线 |
| 真跑判据 | 插拔 TASK-01-FW 686 步 success=True · 摆盘 TASK-06-TRAY 3/3 合格（单边 ≤0.47mm） |
| 飞书端场景叠加 | 公网 `/ov/overlay?k=zmax-live` 等 4 条 HTTP 200 · POST 403（只读闸门）· `/ov/live.json` 三相机拼图清单 |
| 状态推公网 | `zmax_status.json` 推送成功（GPU/内存/磁盘/模型数/训练状态） |
| 关机预检 | `tools/preflight_shutdown.sh` → **🟢 可以下电**（臂 idle · 真值帧龄 0.02s · 无授权 · 无采集/训练在写 · 仓库已保存） |
| 资源 | 磁盘 307G/396G（82%，可用 70G）· 内存 9G/30G · GPU 5%/600MiB |

文件: zmax_engineering.db · engineering_db_check.txt · canvas_state_space_obs.json · param_events_tail.jsonl ·
ss_task_run_TASK-01-FW_latest.json · ss_task_run_TASK-06-TRAY_latest.json · overlay_channel_verify.txt ·
overlay_live_public.json · zmax_status_public.json · release_status.json · git_ref.txt · shutdown_checklist.md

归档: `zmax_data/release_5.49.1_20261012/`（同内容 + MANIFEST.sha256 逐文件校验）
未关项: 本机相机近黑 ⇒ 快层安全闸 fail-closed 拦发夹爪开爪（非软件 bug，不擅自关闸）· 金手指整板原图现象待确认。
