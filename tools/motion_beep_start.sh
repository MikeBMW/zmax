#!/bin/bash
# motion_beep_start.sh — 移动/抬升提示音常驻启动器 (tools/motion_beep.py)
#   口径: 机器人在动 → 响(660Hz 慢 / 1050Hz 快, 间隔随速度); **正在抬升 → 专用警报音(880Hz×3 颤音)**;
#         不动 → 完全静音; 位姿读不到 → 静音(宁可不响, 不谎报"在动")。
#   2026-10-08 老倪: 「也可以抬升, 但要慢一些, 而且要发出警报声音」 ⇒ 抬升警报(判别 = TCP 真值 z 分量在涨)。
set -u
ROOT=/home/ubuntu/zmax
PY="$ROOT/gui-venv311/bin/python"
LOG="$ROOT/zmax_data/motion_beep.log"
PIDF="/tmp/zmax_motion_beep.pid"

p=$(ss -tlnp 2>/dev/null | sed -n "s/.*pid=\([0-9]*\).*motion_beep.*/\1/p" | head -1)
p=$(pgrep -f "tools/motion_beep.py" | head -1)
if [ -n "${p:-}" ]; then
  echo "  · 停旧提示音 pid=$p"
  kill "$p" 2>/dev/null; sleep 1
fi
cd "$ROOT" || exit 1
ulimit -n 4096 2>/dev/null || true
nohup "$PY" tools/motion_beep.py >> "$LOG" 2>&1 &
echo $! > "$PIDF"
sleep 2
if pgrep -f "tools/motion_beep.py" >/dev/null; then
  echo "  · ✅ 提示音已起 pid=$(cat $PIDF)  (音效: motion_tick_slow.wav / motion_tick_fast.wav / lift_alarm.wav)"
  echo "  · 日志: $LOG"
  tail -3 "$LOG"
else
  echo "  · ❌ 没起来, 看 $LOG"
  tail -5 "$LOG"
  exit 1
fi
