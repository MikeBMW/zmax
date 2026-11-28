---
name: linux-wifi-troubleshooting
description: "Use when WiFi 连不上/转圈/没网 — 分层定责到密钥·DHCP·门户。"
version: 1.0.0
author: Hermes Agent
license: MIT
tags: [wifi, networkmanager, wpa_supplicant, linux, association, psk]
platforms: [linux]
metadata:
  hermes:
    tags: [wifi, networkmanager, wpa_supplicant, linux, association, psk]
    related_skills: [linux-host-maintenance, orin-wifi-failover, remote-link-operations]
---

# WiFi 连不上: 先分层定责, 再动配置

## When to Use
- 用户说「corp/guest/某个 WiFi 上不去 / 一直转圈 / 密码输了还是连不上 / 连上了没网」。
- 换过 SSID 后本机 IP 变了、页面链接打不开(接着看 `linux-host-maintenance` §9)。
- 要判定「是 AP 的问题还是本机的问题」。

## 0. 铁律
1. **先只读取证, 再动连接。** 本机当前连着的那条很可能就是你自己在被远程访问的路径 —— 贸然 `nmcli con up/down` 会把自己踢下线。先看日志, 再决定要不要切。
2. **密码永远不由我输入、也不在对话里出现。** 需要重输时: 删掉旧配置, 让用户在桌面网络菜单里自己输一次。可以比较哈希/长度, 不许打印明文。
3. **删配置前先备份。** `cp` 到 `~/.hermes/cache/scratch/nm_bak/` 再 `nmcli con delete`。
4. **报「密码不对」必须有 wpa_supplicant 原话做证据**, 不能只凭「试了几次没上去」。

## 1. 四层定位(顺序固定, 每层一条命令)

| 层 | 命令 | 结论 |
|---|---|---|
| ① 设备/连接态 | `nmcli -t -f DEVICE,TYPE,STATE,CONNECTION dev status` | `wlp*:wifi:connected:<SSID>` = 链路在; `disconnected` = 还没关联 |
| ② 扫描/信号 | `nmcli -f SSID,BSSID,SIGNAL,CHAN,SECURITY dev wifi list` | 目标 SSID 在列表里且 signal 不低 ⇒ **不是信号问题**; 同 SSID 多个 BSSID = 多 AP |
| ③ 关联/四步握手 | `journalctl -u wpa_supplicant --since '-2 days' --no-pager \| grep -iE 'handshake\|pre-shared\|deauth\|reason'` | 见 §2 —— 这一层定 90% 的责 |
| ④ DHCP / 门户 / 出口 | `journalctl -u NetworkManager --since 'HH:MM' \| grep -E 'dhcp4\|state change\|Activation'` | 走到 `dhcp4 … new lease` = 关联 OK; 拿到 IP 但无外网 ⇒ 门户/限速 |

状态机读法(NM 日志里的 `supplicant interface state`):
`scanning → authenticating → associating → 4way_handshake → completed → ip-config → activated`。
**停在哪一步就报哪一层**, 不要把它们混成一句「连不上」。

## 2. `4-Way Handshake failed - pre-shared key may be incorrect` = 密码不匹配(客户端侧)

```
wlp0s20f3: CTRL-EVENT-DISCONNECTED bssid=… reason=3 locally_generated=1
wlp0s20f3: WPA: 4-Way Handshake failed - pre-shared key may be incorrect
wlp0s20f3: CTRL-EVENT-SSID-TEMP-DISABLED id=0 ssid="Corp-Guest" auth_failures=1 duration=10 reason=WRONG_KEY
```
判读:
- 有这几行 ⇒ **存的 PSK 与 AP 现用密码不一致**(或 AP 侧改过密码)。这与信号、DHCP、门户认证**无关** —— 4-way 过不了, 后面都不执行。
- **多个 BSSID 都同样失败** ⇒ 更确定是本机存的密码错, 不是某一台 AP 坏。
- 反过来: 4-way `completed` 但 `ip-config` 卡住 ⇒ 才是 DHCP/地址池; `activated` 但网页跳登录页 ⇒ 门户认证。
- `reason=3 locally_generated=1` 表示断连是**本地发起的**(如随即切到别的 profile), 不要读成 AP 踢人。

## 3. 本机 profile 不在 `/etc/NetworkManager/system-connections`

netplan 渲染 + `plugins=ifupdown,keyfile` 的机器上, 每个连接落成 `/etc/netplan/90-NM-<uuid>.yaml`,
而 `system-connections/` 可能是**空目录** ⇒ 在那里 `No such file or directory` **不代表没存配置**, 别据此下结论。
```bash
nmcli -t -f NAME,UUID,TYPE con show | grep -i <ssid>          # 拿 uuid
sudo grep -rE 'password|psk' /etc/netplan/90-NM-<uuid>.yaml
grep -rE 'plugins|keyfile' /etc/NetworkManager/NetworkManager.conf /etc/NetworkManager/conf.d/
```
比对多个同名 profile 的密码是否一致 —— **只输出 `len` 与 `sha256[:8]`, 绝不打印明文**:
```bash
sudo python3 - <<'PY'
import hashlib,re
for u in ["<uuid1>","<uuid2>"]:
    t=open(f"/etc/netplan/90-NM-{u}.yaml").read()
    for x in re.findall(r'password:\s*"?([^"\n]+)"?',t):
        print(u[:8],"len=",len(x),"sha8=",hashlib.sha256(x.encode()).hexdigest()[:8])
PY
```
两个 profile 存两个不同长度/哈希的密码 = 历史改密留下的双份, 其中至多一份能用, 现场无从判断哪份对 ⇒ 全删重输。

## 4. 修法(可交付的一条路径)

1. 备份: `sudo cp /etc/netplan/90-NM-<uuid>*.yaml ~/.hermes/cache/scratch/nm_bak/`
2. 删掉同名 SSID 的所有 profile: `nmcli con delete "<SSID>" "<SSID> 1"`
3. 复核: `nmcli -t -f NAME con show | grep -i <ssid>` 应为空
4. 交给用户: 在桌面右上角网络菜单点该 SSID, **弹框里自己输当前密码**(我输入不了, 也不该进对话)。
5. 连上后复核: `ip -4 -br addr show wlp*` 拿 IP + 一层出口探针(`curl -s -o /dev/null -w '%{http_code}' http://<内网服务>/`)。

## 5. 自动回退/抢占的读法

办公 SSID 的 `autoconnect-priority` 通常高于访客/热点。手动连 guest 失败(4-way 挂)后 NM 会在几秒内
自动切回办公网 —— 日志表现为 `disconnecting for new activation request` + 紧接着 `Activation: starting connection '<办公SSID>'`。
**这是回退, 不是 guest 被拒绝**, 别把这条当根因。
要长期稳定: `nmcli con mod "<办公SSID>" connection.autoconnect-priority 20` + 访客/热点设 `0`。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 凭「试了几次没上去」就说密码错 | 无证据, 方向可能是信号/DHCP | 先取 wpa_supplicant 的 `WRONG_KEY` 原话再下结论 |
| 去 `system-connections/` 找不到文件就说「没存配置」 | 本机配置在 `/etc/netplan/90-NM-*.yaml` | 按 uuid 去 netplan 目录找(§3) |
| 把 `SSID-TEMP-DISABLED … reason=WRONG_KEY` 当 AP 封禁 | 是 wpa_supplicant 自己按错误密钥临时禁用 10s | 修密码, 不要改 AP/等封禁解除 |
| 为了测试直接 `nmcli dev wifi connect` | 可能把自己(或用户正在用的连接)踢下线 | 先只读; 要切就说明会断什么 |
| 打印 psk 明文做对比 | 密码进日志/进对话 | 只比 `len` 与 `sha256[:8]` |
| 反复删配置却不交代下一步 | 用户以为「你帮我连」, 实际要他自己输密码 | 报告里写清「下一步是你点一下、输当前密码」 |
