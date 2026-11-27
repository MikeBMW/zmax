#!/bin/bash
# 重启 L2 常驻执行器 (加载新的 plan_stage 代码)。按显式 pid 杀, 不用模式串收尾(避免自匹配)。
set -u
PIDS=$(ps -eo pid,cmd | grep -E 'tools/l2_daemon\.py' | grep -v grep | awk '{print $1}')
echo "  重启前实例: ${PIDS:-无}"
for p in $PIDS; do kill "$p" 2>/dev/null && echo "    kill $p"; done
sleep 3
echo "  跑 PIDS=$(ps -eo pid,cmd | grep -E 'tools/l2_daemon\.py' | grep -v grep | awk '{print $1}' | wc -l) (应为 0)"
bash "$HOME/.hermes/scripts/l2_daemon_keepalive.sh" 2>&1 | tail -3
sleep 8
echo
echo "  重启后实例:"; ps -eo pid,etime,cmd | grep -E 'tools/l2_daemon\.py' | grep -v grep | sed 's/^/    /'
echo "  FIFO:"; ls -l --time-style=+%H:%M:%S "$HOME/zmax/zmax_data/l2_cmd.fifo"
echo "  启动横幅(尾 5 行):"; tail -5 "$HOME/zmax/zmax_data/l2_daemon_stdout.log" | sed 's/^/    /'
