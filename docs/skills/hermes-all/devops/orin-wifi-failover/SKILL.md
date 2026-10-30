---
name: orin-wifi-failover
description: "Use when 拔 USB 网卡后要经手机热点连 Orin。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [orin, wifi, hotspot, ssh-tunnel, failover, zmax]
    related_skills: [remote-link-operations, orin-lan-direct-access, systemd-boot-services]
---

# 拔 USB 产线网卡后改走手机热点连 Orin

## When to Use

- 要拔掉产线 USB 网卡（`192.168.23.x` 网段），但仍需访问 Orin
- `ssh orin` 突然超时/`Connection timed out`
- 执行腿 `127.0.0.1:39071/health` 空返回

不适用：只想换 Orin 的产线口地址（用 `Host orin-lan`）。

## 关键判据：先比网段，不要直接拔

```bash
ip -br addr | grep -v lo          # 本机 WiFi 在哪段
ssh <orin> 'ip -br addr'          # Orin WiFi 在哪段
```

**两端口不在同一网段 ⇒ 拔 USB 必然失联**，而且失联后无法再 ssh 去改配置。必须先建好新路再拔。

Orin 典型两个口：
- `enP8p1s0` = 192.168.23.66（产线网段，只服务于珞石控制器 .160）
- `wlP1p1s0` = 192.168.43.x（手机热点 DHCP）

## 步骤

### 1. 本机切到同一个热点

```bash
nmcli -t -f NAME,TYPE con show | grep -i wifi   # 看有没有存过（存过就不需要密码）
nmcli -t -f SSID,SIGNAL dev wifi list --rescan yes | grep -i <热点名>
sudo nmcli con up <热点名>
ip -br addr show wlp0s20f3                       # 拿到新 IP
ping -c3 <Orin 热点 IP>                          # 0% 丢包才算通
```

### 2. 建 ssh Host（不要复用旧条目）

`~/.ssh/config` 里加独立块，**不要 改 `Host orin`**（它可能还指着已弃用的 ECS）：

```
Host orin-wifi
    HostName 192.168.43.19
    Port 22
    User tashan
    IdentityFile ~/.ssh/id_ed25519
    ServerAliveInterval 5
    ServerAliveCountMax 3
```

### 3. 执行腿隧道改成 systemd 常驻

```ini
[Service]
ExecStart=/usr/bin/ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o ConnectTimeout=15 \
    -L 127.0.0.1:39071:127.0.0.1:39061 orin-wifi
Restart=always
RestartSec=5
```

`ExitOnForwardFailure=yes` 是关键：端口占不到就退出交给 Restart，避免“进程活着但端口不监听”的假活。

### 4. 验收（四个面都要过）

```bash
curl -s http://127.0.0.1:39071/health     # → ok:true sdk:true
curl -s http://<Orin WiFi>:39061/health   # → 直连也通
ssh orin-wifi 'hostname; echo ok'
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8797/   # 200
curl -s -o /dev/null -w '%{http_code}' https://open.feishu.cn   # 外网通
systemctl is-active zmax-l2-daemon zmax-orin-tunnel
```

## 坑（都是真实踩过的）

| 现像 | 根因 | 做法 |
|---|---|---|
| `ssh orin` 超时 `connection to X port Y` | `Host orin` 的 HostName 还指着已弃用的 ECS（`39.102.211.79:22022`） | 建独立 `Host orin-wifi`，不去改旧条目 |
| `Too many authentication failures` | 用户名错（Orin 是 `tashan` 不是 `ubuntu`），且裸 IP 不带 IdentityFile | 必须走 Host 别名，不要 `ssh user@bare-ip` |
| `39071` 无监听但进程在 | 隧道指向 `orin-ecs`（`127.0.0.1:22022`，ECS 弃用后的死口） | 重挂到 `orin-wifi`，并用 systemd 接管 |
| 命令被 SIGTERM 自杀 | `pkill -f "39071..."` 匹配到自己的 shell 命令行 | 用 `ss -ltnp` 找 pid，或直接让 systemd 接管 |
| 热点重启后失联 | Orin WiFi 是 DHCP | 只改 `Host orin-wifi` 的 HostName 一行，再 `systemctl restart zmax-orin-tunnel` |

## 边界

- 手机热点 RTT 约 200~300ms。AR 仿真/300UPH 不受影响（位姿走 Orin 本地、真机零下发）；**真机 50Hz 遥测不够用**
- 产线网段设备（AOI `.23`、550C `.70`、珞石 `.160`）在本机侧全断。珞石不受影响，因为 Orin 用自己的 `enP8p1s0` 去控
