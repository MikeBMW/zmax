# 8797 服务的开关方式（实测 2026-11-16）

## 结论：走 systemd，别手工 kill

`zmax-traj-ar.service` 已托管 8797：

```
Loaded: loaded (/etc/systemd/system/zmax-traj-ar.service; enabled)
Drop-In: killmode.conf, speed60.conf
Restart=always  RestartSec=3
User=ubuntu  WorkingDirectory=/home/ubuntu/zmax
Environment=ZMAX_REPO=/home/ubuntu/zmax
StandardOutput=append:/var/log/zmax-traj-ar.log
StandardError=append:/var/log/zmax-traj-ar.log
```

```bash
sudo systemctl status  zmax-traj-ar
sudo systemctl restart zmax-traj-ar     # 改了 .py（路由/逻辑）必须重启
sudo systemctl start   zmax-traj-ar     # 挂了/停机后起
systemctl is-enabled zmax-traj-ar       # → enabled（开机自启）
```

## 什么要重启、什么只要刷新页面

| 改动 | 是否重启 |
|---|---|
| `tools/tcp_ar_server.py`（路由、API 逻辑） | **要**，路由是代码不是热读 |
| `tools/web/tcp-ar.html` | 不用，每次请求读磁盘，Ctrl+F5 |
| `tools/web/traj_adj.json`（点位修正表，`/api/traj_adj` 热读） | 不用，刷新页面 |

## 手工 kill 的坑（踩过）

手工 `kill -TERM` 旧 pid 再 `setsid nohup python tools/tcp_ar_server.py >> /var/log/zmax-traj-ar.log`：

1. 重定向报 `Permission denied` —— 日志文件属 root，由 systemd 以 root 打开，ubuntu 身份写不了；
2. 手工进程起不来，但 3 秒后 systemd 因 `Restart=always` 自动拉一个新的 ⇒ 端口有服务、pid 却不是 `$!`，
   看着像“我重启成功了”，其实是 systemd 起的。
3. 判据：`systemctl status` 看 `Main PID` 与 `Scheduled restart job, restart counter is at N`；
   `CGroup` 里能看到那个 pid 才说明是托管进程。

## 对外入口

```
页面      http://<host>:8797/ar3d      独立三维页（vrfull 版式）
摆盘场景  http://<host>:8797/tray      同一份页面，换场景默认值+左栏白名单（2026-11-16 新增）
点位修正  http://<host>:8797/api/traj_adj   浏览器直接打开就是 JSON
```

## 按 ID 修正回放点位的机制（2026-11-16）

- 磁盘上的 215 点录制真值（`tools/web/real_traj_joints.json`、`derived/points_mm.json`）**一字节不动**；
  覆盖表在 `tools/web/traj_adj.json`，页面 `ensureTrajJoints()` 加载后只改内存里的帧 ⇒
  回放/单步/真机执行/读数自动全走修正值，不会漏改某条路径。
- 改 X/Y/Z 必须重解关节角（回放是关节驱动的）；**只约束位置会让姿态跟着漂** ——
  要纯平动就上 6 自由度约束（位置增量 + 姿态增量严格 0），URDF 有限差分雅可比 + 阻尼最小二乘，
  3 次迭代收敛，复算姿态变化 0.000000°。
- 读数带「·已修正」标记，便于目检哪些点被改过。
