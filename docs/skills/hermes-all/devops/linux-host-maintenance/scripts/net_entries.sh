#!/bin/bash
# 当前网络下页面入口速查 (切了 WiFi/热点/换 IP 之后跑这条, 别去重启服务)
#
# 为什么不用重启: 8791/8793/8797/8798 都监听 0.0.0.0, 换网只改对外 IP, 服务不动。
# 用户手里的链接是 IP 形式 ⇒ 换网后他一定会报"无法打开", 先跑这条给出新 IP + 逐条探活码。
set -u
ROW=$(ip -4 -br addr show up 2>/dev/null | awk '$3 ~ /^[0-9]/ && $1 !~ /^(lo|docker)/ {print $1, $3; exit}')
IF=$(echo "$ROW" | awk '{print $1}')
IP=$(echo "$ROW" | awk '{print $2}' | cut -d/ -f1)
SSID=$(iw dev "$IF" link 2>/dev/null | awk '/SSID/{print $2}')
echo "网卡 ${IF:-?}  SSID ${SSID:-n/a}  IP ${IP:-none}"
[ -z "${IP:-}" ] && { echo "没有可用 IPv4 ⇒ 网没连上"; exit 1; }
echo
probe() { printf '  %-30s %s\n' "$1" "$(curl -sL -m 6 -o /dev/null -w '%{http_code}' "$2")"; }
# 一律 curl -sL 跟跳转: 8793/ar 给 302 是正常的(跳 8797/ar), 只看 302 会误报"无法打开"
probe "工位总览 /station"  "http://$IP:8793/station"
probe "AR 页 /ar"          "http://$IP:8793/ar"
probe "AR 服务根 /"        "http://$IP:8797/"
probe "AR3D /ar3d"         "http://$IP:8797/ar3d"
probe "推流服务 /"         "http://$IP:8791/"
echo
echo "给用户的链接示例: http://$IP:8793/ar"
