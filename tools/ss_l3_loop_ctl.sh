#!/usr/bin/env bash
# L3 常驻回路 起停/查 (训练要独占 GPU 时停, 训练完起回来) —— 老倪 2026-10-14
#   用法: ss_l3_loop_ctl.sh {start|stop|status}
set -u
cd /home/ubuntu/zmax
PIDF=zmax_data/ss_live/l3_live.pid
LOG=zmax_data/ss_live/l3_live.log
PY=./gui-venv311/bin/python
case "${1:-status}" in
  start)
    if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then
      echo "already running pid=$(cat $PIDF)"; exit 0
    fi
    setsid "$PY" tools/ss_l3_live_loop.py --interval 1.0 --seconds 0 >>"$LOG" 2>&1 </dev/null &
    sleep 8
    echo "started pid=$(cat $PIDF 2>/dev/null)"; tail -3 "$LOG" | cut -c1-160
    ;;
  stop)
    if [ -f "$PIDF" ]; then kill "$(cat "$PIDF")" 2>/dev/null && echo "stopped pid=$(cat $PIDF)"; else echo "no pid file"; fi
    ;;
  status)
    if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then echo "running pid=$(cat $PIDF)"; else echo "not running"; fi
    tail -2 "$LOG" 2>/dev/null | cut -c1-160
    ;;
esac
