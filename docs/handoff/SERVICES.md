# 服务清单 · 端口 · 启动方式（2026-11-27 实测）

## Windows 侧（本机，10.163.148.87 / 192.168.23.100）

| 端口 | 服务 | 启动方式 | 备注 |
|---|---|---|---|
| 8793 | `server/cam_live_stream.py` 工位总览 | `launch_zmax.ps1` 或 `Z-MAX_Console.exe server/cam_live_stream.py --port 8793`（cwd=D:\ZMAX，须设 `ZMAX_ROOT`） | 页面 `/station`；AOI 检测 `/api/aoi/detect` |
| 8797 | `server/tcp_ar_server.py` 机械臂通道 | 同上 `--port 8797` | **只许一个进程**（曾出现两进程抢端口 ⇒ 全部 000，杀掉留一个即恢复） |
| 8799 | `server/dashboard_server.py` 服务汇总 | 同上 | 服务索引 |
| 8818 | 550C 服务状态（在 550C 上跑） | — | — |
| 8821 | 550C 金手指 YOLO（在 550C 上跑） | — | `/health` `/predict_tiles` |

**端口被孤儿占用的处理**（高频坑）：
```
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -like '*tcp_ar_server*'} | Select ProcessId,ParentProcessId"
```
主程序退出后子服务会变孤儿继续占端口 → 首页「功能模块」空白 + 左上平台卡「取不到」。
**先杀孤儿再启动**。

## 550C（Intel，10.163.149.123 / 192.168.23.70）

| 端口 | 服务 | systemd unit |
|---|---|---|
| 8793 | 工位总览（Windows 镜像版，2026-11-27 起） | 无 unit，`setsid nohup python3 tools/cam_live_stream.py --port 8793` |
| 8797 | `tcp_ar_server.py` | 在听 |
| 8799 | dashboard | 在听 |
| 8805 | Calabi-Yau 流形切片 | `zmax-cy-slice.service` |
| 8816 | 3DGS 渲染流 | `zmax-gs-render-stream.service` |
| 8818 | 服务状态汇总 | `zmax-svcstatus.service` |
| 8821 | 金手指缺陷 YOLO | `gold_defect_server.py` |
| 8888 | nginx 服务站索引 | `zmax-console.conf` |
| 8901 | 相机中继 | `zmax-cam-relay.service` |
| 8794 | Agent 中枢 | `zmax-agent-hub.service` |

其余在跑：`zmax-aoi-bypass` / `zmax-aoi-frame-sentinel` / `zmax-dataspaces-loop` / `zmax-dataspaces-probe` / `zmax-bili-proxy`

## 外部设备

| 设备 | 地址 | 端口 |
|---|---|---|
| 工控机（AOI） | 192.168.23.23 | 10082 金手指 · 10083 表面 |
| Orin | 192.168.23.66 | 22 · 8792 相机帧 · 39061 位姿 · 39062 夹爪 |
| 珞石控制器 | 192.168.23.160 | 39061（SDK） |
| 相机（金手指） | OPT-CC1-GG50 · sn D265250070 | 生产档 **2000us / 10dB** |

## 网络坑（背下来）

1. **USB 以太网一掉，192.168.23.100 就消失，整段 23 网段断** —— 表现为 ping 通但 TCP 全闭（WLAN 会经网关抢走路由），别被 ICMP 骗。
2. **WLAN 是 10.163.x**，这是 corp guest，跨平台迁移走这条（550C 的 10.163.149.123 可达）。
3. 550C 有两个地址，产线网段断了还能从 10.163 进。
