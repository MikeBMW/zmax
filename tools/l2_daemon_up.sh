#!/usr/bin/env bash
# 起 l2_daemon · 带 MoveJ 开关 (2026-10-18 老倪「选C」)
set -u
cd /home/ubuntu/zmax
export ZMAX_MOVEJ_RETRY=1
export ZMAX_L2_FORCE_J=1
# 2026-10-26 老倪「移动的速度太快了」+「ZMAX_L2_MM_S=200 忘了什么时候设置的了, 改成10mm/s」
#   改前 200mm/s(260mm 只要 3s), 现场嫌快; 现固定 10mm/s。
#   页面档位(5/10/50)经段表 speed_mm_s 下发, 优先级高于本 env。
export ZMAX_L2_MM_S=10
setsid ./gui-venv311/bin/python tools/l2_daemon.py >> zmax_data/l2_daemon_stdout.log 2>&1 < /dev/null &
sleep 8
for p in /proc/[0-9]*; do
  pid="${p#/proc/}"
  [ "$pid" = "$$" ] && continue
  cmd=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null) || continue
  case "$cmd" in *"/tools/l2_daemon.py"*) echo "daemon pid=$pid $(ps -o etime= -p $pid)";; esac
done
