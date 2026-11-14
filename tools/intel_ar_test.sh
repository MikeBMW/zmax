#!/usr/bin/env bash
# Intel 上试起 8797(tcp_ar_server) 副本, 端口 8796, 不动 4060 上在跑的那个
cd /home/intel/zmax || exit 1
pkill -f 'AR_PORT=8796' 2>/dev/null
setsid nohup env AR_PORT=8796 python3 tools/tcp_ar_server.py > /tmp/tcp_ar_intel.log 2>&1 < /dev/null &
sleep 8
echo "监听 8796: $(ss -ltn 2>/dev/null | grep -c 8796)"
echo "--- 日志尾"
tail -8 /tmp/tcp_ar_intel.log 2>/dev/null | cut -c1-140
echo "--- /status"
curl -s -m 5 http://127.0.0.1:8796/status | head -c 260
echo
