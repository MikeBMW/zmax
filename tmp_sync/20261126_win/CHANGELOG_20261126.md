# Z-MAX 改动记录 · 2026-11-26

> 本文件由 Hermes 生成，记录当天在 **Windows 工位机 (D:\ZMAX)** 与 **Intel 550C (192.168.23.70)** 两侧的全部改动。
> 两边互为副本：550C 侧在 `/home/intel/zmax_550c/tmp_sync/20261126_win/`，Windows 侧在 `D:\ZMAX\_sync_from_550c_20261126\`。

---

## 一、Intel 550C（192.168.23.70）

| 时间 | 文件 | 改动 | 备份 |
|---|---|---|---|
| 17:43 | `zmax_map/tools/arm_pose_relay_intel.py` | 位姿 relay 源从失效的 `192.168.23.100:8797/api/tcp` 改为 `127.0.0.1:8811/pose`（与 autocap/训练同源），并兼容 `quat[]` 与 `qx/qy/qz/qw` 两种字段 | `.bak-20261126` |
| 17:48 | `zmax_map/tools/gs_render_stream_intel.py` | 修 8816 渲染全黑：cameras.json 全帧 `_normalized=True` 时不再二次做 `S*(t-center)`，避免相机被推出点云 8 米 | `.bak-20261126b` |
| 17:51 | `zmax_map/tools/gs_render_loop.sh` | `--sync on` 改为 `--sync ${GSRENDER_SYNC:-on}`，可用 drop-in 切 off | `.bak-20261126` |
| 18:38 | `zmax_map/tools/svc_status_server.py` | **新增**只读服务，`:8818` 输出 `systemctl list-units` 全量单元（67 项） | — |
| 18:57 | `zmax_web/console/index.html` | 服务站首页改造：8799 改名为「工位总览」并置于首位、清除「产品大屏」、新增 Windows 工位机 9 个端口（带 `192.168.23.100` 前缀与 Windows 徽章） | `.bak-20261126` |
| 18:44 | `/etc/nginx/conf.d/zmax-station-8799.conf` | **新增**：8799 反代到 `192.168.23.100:8793`（工位总览六路同屏），关闭 buffering/cache | — |
| 18:57 | `/etc/nginx/conf.d/zmax-console.conf` | 8888 加 `Cache-Control: no-store` | `/root/*.bak-20261126` |
| 17:53 | `/etc/systemd/system/zmax-svcstatus.service` | **新增**并 enable，随 svc_status_server.py 启动 | — |
| 17:56 | `zmax-gs-autocap.service.d/cooldown.conf` | **新增**：`GS_COOLDOWN_S=60`、`GS_MIN_FRAMES=120`（原 600s/160 帧） | — |

服务开关变更：
- `zmax-dashboard`：stop + **disable**（原 8799 静态大屏，已由 nginx 反代取代）
- `zmax-symmetry-evolve`：enable 改 **disable**（防止重启后自动复活）
- `zmax-550c-shadow`：**disable**（实测 4.25 核 CPU，只读影子推理）
- `zmax-evolve-intel`：**disable**（两个实例各占 6.5GB 内存）
- 背景：15:00 后 load 长期 24→37，内存 20G→29G（free 仅 154MB、swap=0），18:37 与 18:44 两次全网响应超时

---

## 二、Windows 工位机（D:\ZMAX）

| 时间 | 文件 | 改动 | 备份 |
|---|---|---|---|
| 17:58 | `server/web/unified_app.html` | 服务汇总改「所有服务汇总」：端口/单元分开统计、`failed` 与 `kind=unit` 状态、端口为 None 显示「–」、无缓存 | `.bak-20261126` |
| 18:52 | `server/dashboard_server.py` | `/api/services` 增加远端 systemd 单元合并（拉 550C `:8818`）；整机可达性预判（只认 8888/80，20 秒缓存）避免对端卡死时逐端口等超时；`listening` 只统计端口项 | `.bak-20261126` |
| 19:25 | `tools/rokae_sdk_run.sh` | Windows 适配：SDK 路径优先 `/d/ZMAX/zmax_data/rokae_sdk`；`sudo` 改为实测 `sudo -n true` 才使用（Windows 11 自带被禁用的 sudo.exe 会误判） | `.bak-20261126` |
| 19:18 | `zmax_data/rokae_sdk/` | **新增** 23MB，从 550C `/home/intel/zmax_550c/zmax_data/rokae_sdk` 同步（含 `xcoresdk_python`） | — |
| 19:2x | docker 镜像 | 新增 `ros:humble-ros-base`（1.16GB），move-rel 执行环境 | — |

进程变更：
- `8797 tcp_ar_server.py`：原为孤儿且 HTTP 空回复，重启并带 `-RedirectStandardOutput/-RedirectStandardError` 后恢复（200）
- `8799 dashboard_server.py`：多次重启以加载代码改动

---

## 三、未同步 / 平台特定（**不要互相覆盖**）

| 项 | 归属 | 原因 |
|---|---|---|
| `nginx` 全部配置 | 仅 550C | Windows 无 nginx |
| `systemd` unit / drop-in | 仅 550C | Windows 用 Z-MAX_Console.exe 拉起子进程 |
| `docker` 镜像 `ros:humble-ros-base` | 仅 Windows | 550C 无 docker |
| `zmax_data/rokae_sdk` 副本 | 两边各一份 | 550C 是源（SDK 原件），Windows 是执行副本 |
| `server/dashboard_server.py` vs `zmax_550c/tools/dashboard_server.py` | **同名不同物** | Windows 版是服务汇总服务（27KB），550C 版是静态文件服务（3.6KB），不可互覆盖 |
| `server/web/unified_app.html` | 仅 Windows | 550C 用 `zmax_web/console/index.html` |

---

## 四、待决

1. `server/dashboard_server.py` 与 550C 同名文件的职责差异是否要合并成一个？
2. 550C 上 `zmax-gs-render-stream` 目前 `GSRENDER_SYNC=off`（手臂实时同步因 handeye 与历史资产不匹配，位姿差 1.2m / 旋转差 1.69），是否要重新标定后切回 on？
3. 训练质量：今日 3000 步 job PSNR 13.4–14.9 dB，而 `out_merged_3k` 为 20.88 dB（21.9 万高斯 / 326 帧多源）。是否提高步数到 15000 并放开高斯上限？
