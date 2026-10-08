# 相机「没帧/画面冻住」先查设备重枚举（2026-10-08）

## 判据
- `/stats` 该路 `fps=0.0 · age_s 很大 · frames_served` 不涨；日志刷 `[local] 读帧失败 xNNNN`。
- `/dev/v4l/by-id/<卡名>` 的**建立时间 = 插拔/重枚举时刻**（本次 14:30 建立 ⇒ USB 相机 `video4` → `video5`）。
- 设备清单核对：内置 video0-3 · MAXHUB video6-7 · USB2.0 Camera=video5/video8。
- 根因：服务启动时按卡名解析一次就抱住设备号，重枚举后旧号失效。

## 恢复
- 用**固化启动脚本**重启（`tools/start_station_8793.sh`，启动时按卡名重扫）⇒ `[local] 出图: /dev/video5 = USB2.0 Camera`。
- 用户自救：页面相机②的「内置/USB」切一下即触发按卡名重扫（`POST /cam/src`）。
- 待点头的自愈：worker 连续读帧失败 ≥N 秒自动按卡名重扫重开。

## 血泪：重启这类服务必须带**原始参数**
- 裸启动 `python tools/cam_live_stream.py` 会同时打掉 `--overlay`（叠加全 503）、`--local2-dev 6`（MAXHUB 无帧）、`--ctl-motion`（手动退化成「仅演练」）。
- ⇒ 唯一真源 = `tools/start_station_8793.sh`（参数逐项注释 + 停旧 + 起新 + 逐路验收），别再手敲。
- 重启前先看**谁占着端口**（按端口占用者 pid 精确重启），否则新实例 bind 失败 core dump。
