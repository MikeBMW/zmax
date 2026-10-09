# 关机前核对单 (2026-10-09 夜 · v5.34.2)

## ① 代码与版本 — 全部已推, 可以关机

| 项 | 状态 |
|---|---|
| 工作区 | `git status --porcelain` = 0 (干净) |
| main | 已推 (含 v5.34.0 定版 → v5.34.1 按钮修复 → v5.34.2 收尾) |
| tag | v5.34.0 ✅ / v5.34.1 ✅ (远端已核) / v5.34.2 ✅ |
| 守卫 | integrity_check 五处一致 ✅ · repo_guard 干净 ✅ · secret_scan 干净 ✅ |
| 技能/记忆 | `sync_hermes_to_repo.sh` 已推 (docs/skills + docs/memory) |

## ② 桌面版发布 — 在 GitHub 云端跑, 本机关机不影响

- **v5.34.0 已完成** (success): `Z-MAX_Console.exe` 171.0 MB + `Z-MAX_Console-macOS.zip` 134.6 MB
- **v5.34.1 / v5.34.2** 构建中/排队 → 完成后同样挂到各自 Release
- 下载: https://github.com/MikeBMW/zmax/releases (明天开机会看到 v5.34.1 / v5.34.2)

## ③ 在跑的常驻服务 (关机即停, 开机自启会自动回来)

| 进程/单位 | 作用 | 开机是否自启 |
|---|---|---|
| 控制台 GUI (studio.py) | 主界面 | 手动启动 (`tools/studio_ctl.sh`) |
| `zmax-engdb.service` | 单一工程库只读服务 127.0.0.1:8798 | ✅ systemd enabled |
| `tools/hil_local_api.py` (8795) | HIL 本地 API | 手动 |
| `tools/l5_live_mark.py` | L5 实时标注 | 手动 |
| `zmax-dds-ss.service` (守护) | DDS 遥测模式守护 | ✅ systemd |
| cron `@reboot` | l2_daemon_keepalive · vl_safety_keepalive · hermes_cron_reclock | ✅ cron |
| cron 每 5 分钟 | l2_daemon_keepalive · vl_safety_keepalive | ✅ cron |
| cron 每 2 小时 | disk_redline (磁盘红线) | ✅ cron |

⚠️ 注意: `auto_loop.py` 的 5 分钟自启那行**仍是注释状态** (09-22 关机暂停留的口子) —— 需要它跑就取消注释。
⚠️ 另: `l2_daemon_keepalive` / `vl_safety_keepalive` / `publish_live_url` 会在开机后拉起对应链路,
   如果只想静默开机、不跑现场链路, 关机前提醒我或开机后注释掉这几行。

## ④ 资源与风险

- 磁盘 `/` 已用 **86%** (可用 54G) —— 关机不影响; 下次开机若要下模型/数据先看这条。
- GPU 空闲 (利用 34% 瞬时, 显存 323MB) —— 没有训练在跑, 关机无损失。
- 产线 USB 网卡 (192.168.23.50) 当天不在位 ⇒ Orin 192.168.23.66 不可达、珞石位姿真值停更;
  **这不是软件问题**, 插回网卡即恢复 (别手工拉)。

## ⑤ 下次开机的第一件事

1. `git pull` (拿到 v5.34.2 + 技能)
2. 打开控制台 `tools/studio_ctl.sh start` → 侧栏应为: 🏭 Z-MAX 平台 / System 2 / System 1 / System 0 / 📋 功能清单 / 🎛 参数中心
3. 画布工具栏确认有 **🧮 状态空间** + **🛰 工位总览** 两个按钮 (v5.34.1 找回的那两个)
4. 想看发布包: GitHub Releases 下 `Z-MAX_Console.exe` / `Z-MAX_Console-macOS.zip`
