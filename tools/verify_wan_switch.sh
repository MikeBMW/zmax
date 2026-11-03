#!/bin/bash
# verify_wan_switch.sh — 550C 独立外网口(wan3/enp3s0)接入后的逐项判据
# 用法: bash tools/verify_wan_switch.sh
# 判据: ① enp3s0 起来并有 IP  ② 默认路由走 wan3 网关  ③ ICMP 出网
#       ④ DNS 解析 feishu  ⑤ HTTPS 到 feishu  ⑥ 飞书 gateway WS 无新失败
set -u
PASS=0; FAIL=0
ok()   { echo "  PASS  $*"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL  $*"; FAIL=$((FAIL+1)); }

echo "════ 550C 独立外网口判据 $(date '+%F %T') ════"

# ① 接口与地址
STATE=$(nmcli -t -f DEVICE,STATE device 2>/dev/null | awk -F: '$1=="enp3s0"{print $2}')
IP=$(ip -br a show enp3s0 2>/dev/null | awk '{print $3}')
if [ "$STATE" = "connected" ] && [ -n "${IP:-}" ]; then
    ok "enp3s0 已连 · $IP"
else
    bad "enp3s0 未连（state=${STATE:-none} ip=${IP:-none}）—— 网线没插或没起 DHCP"
fi

# ② 默认路由
GW=$(ip route show default 2>/dev/null | awk '/enp3s0/{print $3; exit}')
DEF=$(ip route show default 2>/dev/null | head -1)
if [ -n "${GW:-}" ]; then
    ok "默认路由已走 enp3s0 网关 $GW"
else
    bad "默认路由仍不在 enp3s0（当前: ${DEF:-无}）"
fi

# ③ ICMP 出网
for h in 223.5.5.5 8.8.8.8; do
    if timeout 5 ping -c2 -W2 "$h" >/dev/null 2>&1; then ok "ping $h 通"; else bad "ping $h 不通"; fi
done

# ④ DNS
if timeout 8 getent hosts open.feishu.cn >/dev/null 2>&1; then
    ok "DNS 解析 open.feishu.cn → $(getent hosts open.feishu.cn | awk '{print $1}' | head -1)"
else
    bad "DNS 解析 open.feishu.cn 失败"
fi

# ⑤ HTTPS
CODE=$(timeout 10 curl -sS -o /dev/null -w '%{http_code}' https://open.feishu.cn/ 2>/dev/null || echo 000)
if [ "$CODE" != "000" ]; then ok "HTTPS open.feishu.cn → $CODE"; else bad "HTTPS open.feishu.cn 连不上"; fi

# ⑥ 飞书 gateway 最近是否有连接失败
LOG="$HOME/.hermes/logs/agent.log"
if [ -f "$LOG" ]; then
    N=$(tail -400 "$LOG" | grep -ci "Lark: connect failed" || true)
    P=$(pgrep -f "gateway run" | head -1)
    if [ "${N:-0}" -eq 0 ]; then ok "飞书 WS 近 400 行无 connect failed（gateway pid ${P:-?}）"
    else bad "飞书 WS 近 400 行仍有 $N 次 connect failed"; fi
else
    bad "找不到 $LOG"
fi

echo "──────── 结果: $PASS PASS / $FAIL FAIL ────────"
[ "$FAIL" -eq 0 ] && echo "✅ 可以拔 USB 网卡" || echo "⛔ 先别拔 USB 网卡"
exit 0
