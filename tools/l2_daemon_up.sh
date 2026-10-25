#!/usr/bin/env bash
# 起 l2_daemon · 带 MoveJ 开关 (2026-10-18 老倪「选C」)
set -u
cd /home/ubuntu/zmax
export ZMAX_MOVEJ_RETRY=1
export ZMAX_L2_FORCE_J=1
# 2026-10-25: bridge 腿(Orin SDK 桥)速度显式给到 200mm/s —— 段内默认 60 太慢(实测 60 时 4 段 7.3s)
export ZMAX_L2_MM_S=200
setsid ./gui-venv311/bin/python tools/l2_daemon.py >> zmax_data/l2_daemon_stdout.log 2>&1 < /dev/null &
sleep 8
for p in /proc/[0-9]*; do
  pid="${p#/proc/}"
  [ "$pid" = "$$" ] && continue
  cmd=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null) || continue
  case "$cmd" in *"/tools/l2_daemon.py"*) echo "daemon pid=$pid $(ps -o etime= -p $pid)";; esac
done
