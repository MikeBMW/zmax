# 下电核对单 · 2026-10-11 · v5.47.2

## 1) 代码与版本
- [x] 小版本迭代完成：**v5.47.1 → v5.47.2**（`bump_version.py --to 5.47.2`，9 处版本位同步）
- [x] 版本同源判据：GUI 显示 5 处一致、陈旧 0 处（远端 tag/Release 由 push 补齐）
- [x] 工程库重建 + 判据全绿（`engineering_db.py build|check`）
- [x] 入库前闸：`repo_guard.py --staged` + `secret_scan.py --staged`（凭据一律不入库）

## 2) 数据（已落盘、可复核）
- [x] 画布真源快照：`canvas_state_space_obs.json`（md5 `e53e6f4c53b19373f662d79b480435d9`）
- [x] 产品大屏数据源：`dashboard_v5.47.2.json`（含 `screen` 段 = 工位总览 :8793 在役状态）
- [x] 工程库判据原文 / 版本同源原文 / 5 套判据结果（本目录）
- [x] 真机视频/截图证据（本机 `/tmp/gw_pin_shot.png`、`/tmp/gw_final_shot.png`、`~/.hermes/cache/scratch/flicker/f0*.png`）—— 大文件不入库

## 3) 在役链路状态（下电前确认）
- [x] 机械臂：`power=off` · `operation=idle` · `estop=false` · 手动闸 `motion_armed=false` ⇒ **无需下电动作**（本就未上电）
- [x] 臂上 D405（Orin）：在线 29.8fps、帧龄 0.01s
- [x] 工位通道：10/10 在线（`local2` MAXHUB 20.7fps 正常；`local` USB 帧龄 ~108s 无帧 — 源侧未出帧，已记录）
- [x] 控制台 `XSpace Studio`（v5.47.2）与 `📈 实时监控 · Graphic 信号分析` 均为最新版
- [x] 遥测 DDS：仅标定/调试用，非量产开

## 4) 下电动作
1. 关掉 GUI：控制台 + 实时监控窗（本轮我起的只读服务 `dashboard_server :8799` 随之结束）
2. 在役推流服务 `cam_live_stream`（8791/8793）随系统关机自行停止，无需手工
3. 关机前确认真源无写入中（画布真源 md5 与本快照一致 = `e53e6f4c…`）
4. 断电

## 5) 下次开机第一件事
- `bash tools/studio_ctl.sh restart --force` 起控制台；`bash tools/gui/open_graphic_window.sh` 起实时监控窗
- `./gui-venv311/bin/python tools/engineering_db.py check` 看工程库是否仍全绿
- 若要在手机上打开产品大屏：本机只读服务 `./gui-venv311/bin/python tools/dashboard_server.py --port 8799`，
  手机同网访问 `http://192.168.23.50:8799/`
