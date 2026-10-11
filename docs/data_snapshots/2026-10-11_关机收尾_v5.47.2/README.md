# 数据快照 2026-10-11 · 关机收尾 v5.47.2

本次小版本迭代（v5.47.1 → **v5.47.2**）收口快照。老倪本轮指令：两个入口走同一套"加载后归一"；
删 Z700 按钮、增实时监控；工位总览 → 产品大屏；状态空间独立页删除恢复原样且与工程文件一致；
"不要闪烁"；实时监控窗口删掉 (CANoe 式)；"同步时间轴不要消失"。

## 内容
| 文件 | 是什么 |
|---|---|
| `canvas_state_space_obs.json` | 画布真源快照（状态空间工程，md5 `e53e6f4c53b19373f662d79b480435d9`） |
| `engineering_db_check.txt` | 工程库判据原文（重建后全绿） |
| `version_sync.txt` | 版本同源判据原文（本地 9 处一致；远端 tag/Release 待 push 补齐） |
| `dashboard_v5.47.2.json` | 产品大屏单一数据源（含 `screen` 段 = 工位总览服务 :8793 在役状态） |
| `product_screen_status.txt` | 产品大屏/工位通道人读摘要（逐通道在线/帧率/帧龄/卡死） |
| `verify_results.txt` | 本轮 5 套判据最终结果（全 PASS） |
| `shutdown_checklist.md` | 下电核对单 |
| `git_ref.txt` | 提交/tag 参考 |

## 本轮判据（全 PASS，原文见 `verify_results.txt`）
- `verify_no_flicker` 12 项 —— 画布「状态空间」同一份 ⇒ 不重建（clear 0 次、item 对象同一批）；换内容必须真重建；重建被冻结重绘包住；真源 md5 不变
- `verify_pin_persist` 10 项 —— 3D 停下后竖线留在停下的那一刻（7.500 不跳走）、仍可见、🕒 时刻自洽、反向拖动保护
- `verify_time_corr` / `verify_playback_cursor` / `verify_monitor_graphic` —— 无回归
- 真机取证：连拍 8 帧像素差 0.0000（`shutter_flicker_probe.py`）；watch 日志 `fresh=False` 后竖线 x 原地不动

## 未闭环（如实记录，不假成功）
1. **公网推流缺口**：`datadrive.world/factory-dashboard.html` 可达，但 `dashboard.json` 与 `/dl/*.apk` 仍 404 ⇒ 需 web 侧（ECS nginx）接管；任务单已发飞书（code=0, `om_x100b638ca7aef8a4df95ffee272cb7d`）。
2. **local USB 相机**：帧龄 ~108s、无帧（源侧未出帧；`local2` MAXHUB 20.7fps 正常，Orin 臂相机 29.8fps 正常）。
