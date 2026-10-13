#!/bin/bash
# 干净停掉当前这一轮建图 (显式 pid, 不用 pkill -f —— 会连自己的 shell 一起杀)。
# 做法: ① 往会话目录放 STOP ⇒ gs_capture 自己收尾写 capture_summary.json
#       ② 按显式 pid 结束 gs_map_run (它此刻在等一个永远不会到的"到位")
# 用法: stop_gs_map.sh <会话目录> [gs_map_run_pid]
set -u
SESS="${1:?会话目录}"
PID="${2:-}"

echo "== 会话 $SESS"
if [ -d "$SESS" ]; then
  touch "$SESS/STOP" && echo "   ✅ 已放 STOP (采集会优雅收尾)"
else
  echo "   ⚠ 会话目录不存在, 跳过 STOP"
fi

if [ -z "$PID" ]; then
  PID=$(ps -eo pid,cmd | grep 'gs_map_run\.py' | grep -v 'bash -c' | grep -v grep | awk '{print $1}' | head -1)
fi
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
  echo "   → 结束 gs_map_run pid=$PID (TERM)"
  kill -TERM "$PID" 2>/dev/null
  for _ in $(seq 1 20); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
  kill -0 "$PID" 2>/dev/null && { echo "   → 仍在, KILL"; kill -9 "$PID" 2>/dev/null; }
else
  echo "   (gs_map_run 已不在)"
fi

sleep 3
echo "== 收尾核对"
echo -n "   gs_map_run: "; ps -eo pid,cmd | grep 'gs_map_run\.py' | grep -v 'bash -c' | grep -v grep | wc -l
echo -n "   gs_capture: "; ps -eo pid,cmd | grep 'gs_capture\.py' | grep -v 'bash -c' | grep -v grep | wc -l
[ -f "$SESS/capture_summary.json" ] && echo "   ✅ capture_summary.json 已落盘" || echo "   ⚠ 尚无 capture_summary.json"
