#!/bin/bash
# 重启 8797 AR/VR 台 (systemctl stop 会超时: SIGTERM 后线程收不掉 ⇒ 这里 stop --no-block + 兜底 kill)
# 用法: bash tools/restart_traj_ar.sh
set -u
SVC=zmax-traj-ar
old=$(systemctl show -p MainPID --value $SVC 2>/dev/null)
echo "old main pid=$old"
systemctl stop --no-block $SVC
for i in $(seq 1 25); do
  sleep 1
  cur=$(systemctl show -p MainPID --value $SVC 2>/dev/null)
  [ "${cur:-0}" = "0" ] && { echo "stopped after ${i}s"; break; }
  [ $((i % 5)) -eq 0 ] && echo "  still alive ${i}s (pid=$cur)"
done
cur=$(systemctl show -p MainPID --value $SVC 2>/dev/null)
if [ "${cur:-0}" != "0" ]; then
  echo "⛔ SIGTERM 收不掉, 兜底 SIGKILL pid=$cur"
  kill -TERM "$cur" 2>/dev/null
  sleep 4
  kill -KILL "$cur" 2>/dev/null
  sleep 2
fi
systemctl start --no-block $SVC
for i in $(seq 1 20); do
  sleep 1
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8797/ar3d || true)
  if [ "$code" = "200" ]; then
    echo "✅ 起来了 (${i}s) · new main pid=$(systemctl show -p MainPID --value $SVC)"
    curl -s --max-time 5 "http://127.0.0.1:8797/ar3d" | grep -o '构建 2026-10-26 r[0-9]*' | head -1
    exit 0
  fi
done
echo "❌ 20s 内 /ar3d 没起来, 看 /var/log/zmax-traj-ar.log"
exit 1
