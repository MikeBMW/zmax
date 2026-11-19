#!/bin/bash
# 按端口取 pid 杀掉 8817, 再起 se3_follow (20Hz, 只读真值)
set -u
PORT=${1:-8817}
PID=$(ss -ltnp 2>/dev/null | awk -v p=":$PORT" '$4 ~ p {print $0}' | grep -o 'pid=[0-9]*' | cut -d= -f2 | head -1)
if [ -n "${PID:-}" ]; then kill -9 "$PID" 2>/dev/null; echo "[kill] pid=$PID on :$PORT"; sleep 1; fi
cd /home/ubuntu/zmax || exit 1
setsid nohup python3 -u tools/se3_follow.py --port "$PORT" --rate 20 > /tmp/se3_follow.log 2>&1 < /dev/null &
sleep 3
echo -n "[health] "; curl -s --max-time 5 "http://127.0.0.1:$PORT/healthz"; echo
