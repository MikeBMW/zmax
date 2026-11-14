#!/usr/bin/env bash
# 重启 8797 (tcp_ar_server) —— 老倪 2026-11-14「你来重启，我要重新测试了」
set -u
cd /home/ubuntu/zmax || exit 1

OLD=$(ss -ltnp 2>/dev/null | awk '/:8797 /{print}' | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
echo "旧 pid: ${OLD:-无}"
if [ -n "${OLD:-}" ]; then
  kill -TERM "$OLD" 2>/dev/null
  for i in $(seq 1 20); do sleep 0.3; kill -0 "$OLD" 2>/dev/null || break; done
  kill -0 "$OLD" 2>/dev/null && { echo "TERM 无效 ⇒ KILL"; kill -KILL "$OLD" 2>/dev/null; sleep 0.5; }
fi

LOG=/tmp/tcp_ar_server.log
: > "$LOG"
setsid nohup ./gui-venv311/bin/python -u tools/tcp_ar_server.py >> "$LOG" 2>&1 < /dev/null &
sleep 4

NEW=$(ss -ltnp 2>/dev/null | awk '/:8797 /{print}' | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
echo "新 pid: ${NEW:-未起}"
echo "HTTP : $(curl -s -o /dev/null -w '%{http_code} %{time_total}s' -m 5 http://127.0.0.1:8797/api/tcp)"
echo "状态 : $(curl -s -m 5 http://127.0.0.1:8797/api/arm/step_traj/status | head -c 160)"
echo "--- 启动日志尾"
tail -5 "$LOG"
