#!/usr/bin/env bash
# 按**端口**找 8797 的进程并结束 (禁 ps|grep 名字: 会连自己这条命令一起杀)
set -u
PIDS=$(ss -ltnp 2>/dev/null | awk '/:8797 /{while (match($0, /pid=[0-9]+/)) {print substr($0, RSTART+4, RLENGTH-4); $0=substr($0, RSTART+RLENGTH)}}' | sort -u)
if [ -z "$PIDS" ]; then echo "8797 上没有监听进程"; exit 0; fi
echo "8797 上的 pid: $PIDS"
for p in $PIDS; do kill "$p" 2>/dev/null; done
for i in $(seq 1 16); do
  ss -ltn 2>/dev/null | grep -q ':8797 ' || { echo "✅ 8797 已释放"; exit 0; }
  sleep 0.5
done
PIDS=$(ss -ltnp 2>/dev/null | awk '/:8797 /{while (match($0, /pid=[0-9]+/)) {print substr($0, RSTART+4, RLENGTH-4); $0=substr($0, RSTART+RLENGTH)}}' | sort -u)
echo "还在 ⇒ kill -9: $PIDS"
for p in $PIDS; do kill -9 "$p" 2>/dev/null; done
sleep 1
ss -ltn 2>/dev/null | grep -q ':8797 ' && { echo "❌ 8797 仍被占"; exit 1; } || echo "✅ 8797 已释放 (强杀)"
