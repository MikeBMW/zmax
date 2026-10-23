#!/bin/bash
# 单实例重启 Z-MAX 控制台 (清旧实例 → systemctl --user start → 回读 MainPID)
set -u
pids=$(pgrep -af "studio\.py" | grep -v QtWebEngineProcess | grep -v "restart_console.sh" | awk '{print $1}')
echo "旧实例: ${pids:-none}"
for p in $pids; do kill "$p" 2>/dev/null; done
for i in $(seq 1 20); do
  sleep 0.3
  left=$(pgrep -af "studio\.py" | grep -v QtWebEngineProcess | grep -v "restart_console.sh" | awk '{print $1}')
  [ -z "$left" ] && break
done
if [ -n "${left:-}" ]; then echo "SIGTERM 未退, 强杀: $left"; for p in $left; do kill -9 "$p" 2>/dev/null; done; sleep 0.5; fi
systemctl --user reset-failed zmax-studio.service 2>/dev/null
systemctl --user start zmax-studio.service
sleep 4
echo "MainPID=$(systemctl --user show -p MainPID --value zmax-studio.service)  ActiveState=$(systemctl --user show -p ActiveState --value zmax-studio.service)"
pgrep -af "studio\.py" | grep -v QtWebEngineProcess
