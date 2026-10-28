# 让产线网段(192.168.23.0/24)的设备经本机 WiFi 上网

场景: 产线机只有内网口(192.168.23.x), 没网关/网关写错 ⇒ 装不了包。本机(4060 工控机)有 WiFi 出口。

## 三步
1. 本机开转发 + NAT (持久化 systemd unit, 已存在: `zmax-lan-nat.service` → `/usr/local/sbin/zmax-lan-nat.sh`)
   ```
   sysctl -w net.ipv4.ip_forward=1
   iptables -I FORWARD 1 -i <LAN网卡> -o <WAN网卡> -j ACCEPT
   iptables -I FORWARD 1 -i <WAN网卡> -o <LAN网卡> -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
   iptables -t nat -I POSTROUTING 1 -s 192.168.23.0/24 -o <WAN网卡> -j MASQUERADE
   ```
   本机 FORWARD 默认策略是 DROP ⇒ 不加这两条 ACCEPT 会"ping 通外网但 TCP 全挂"。
2. 客户端默认路由指到本机 + DNS:
   `sudo ip route replace default via 192.168.23.50 metric 50` (临时)
   NM 持久: `nmcli con mod "<名字>" ipv4.addresses "IP/24" ipv4.gateway 192.168.23.50 ipv4.dns "223.5.5.5,119.29.29.29"` 然后 `con up`
   下发 `con up` 会瞬断 SSH ⇒ 用 `setsid nohup bash -c 'sleep 1; nmcli con up ...' &`，8s 后重连验证。
3. 验证: 比本机直连的下载速率 (speed.cloudflare.com/__down?bytes=20000000)，两者相近才算真通。

## 坑
- NM 的 profile 里 `ipv4.address1: "192.168.23.70/24,192.168.1.1"` 会写进一个**别的网段的网关**(192.168.1.1)，
  路由表里就有 `default via 192.168.1.1` 永不生效 ⇒ 看着有默认路由实际没网。先 `ip route` 核对网关是不是同网段。
- `https://pypi.org/simple/` 本身 34 MB，慢不等于不通；`files.pythonhosted.org/...` 返回 302/0 字节是正常重定向，别当失败。
- 只有 IPv4 NAT，IPv6 不通(`curl -6` = 000)，属预期。
- MTU 实测 1500 端到端通(`ping -M do -s 1472` 过)，一般不需要 MSS clamp。
