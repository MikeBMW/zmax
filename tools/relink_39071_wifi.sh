#!/bin/bash
# 39071 隧道重挂：把执行腿从已弃用的 ECS 入口(127.0.0.1:22022)切到 Orin WiFi(192.168.43.19)
# 用户要求断 USB 产线网卡，执行腿必须走手机热点，否则 l2_daemon 完全失联。
set -u
OLD_PID=$(pgrep -f "39071:127.0.0.1:39061 orin" | head -1)
if [ -n "${OLD_PID:-}" ]; then
  echo "杀旧隧道 pid=$OLD_PID"
  kill "$OLD_PID" 2>/dev/null || true
  sleep 1
fi
# 等 39071 端口释放，最多 10s
for i in $(seq 1 10); do
  ss -ltn 2>/dev/null | grep -q ':39071' || break
  sleep 1
done
echo "起新隧道: 127.0.0.1:39071 -> orin-wifi(192.168.43.19) 127.0.0.1:39061"
setsid ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o TCPKeepAlive=yes \
  -o ConnectTimeout=15 \
  -L 127.0.0.1:39071:127.0.0.1:39061 orin-wifi >/tmp/ss_tunnel_39071.log 2>&1 &
sleep 4
echo "--- 端口 ---"
ss -ltn 2>/dev/null | grep ':39071' || echo "39071 未监听"
echo "--- 健康 ---"
curl -s -m 8 http://127.0.0.1:39071/health || echo "(无响应)"
echo
