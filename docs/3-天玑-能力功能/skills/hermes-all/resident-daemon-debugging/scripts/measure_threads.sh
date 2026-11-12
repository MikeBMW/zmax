#!/bin/bash
# measure_threads.sh —— 离屏起一个 GUI/脚本, 反复采样线程数 + 线程名, 结束杀掉。
# 用途: 用户说"你现在还有 N 条线程"时, 给出 before/after 的实测数, 而不是靠 env 声称。
#
# 用法:  bash measure_threads.sh <脚本相对仓库根的路径> [采样总秒数] [工作目录]
# 例:    bash measure_threads.sh tools/gui/studio.py 60 tools/gui
#        bash measure_threads.sh tools/ss_canvas_loop.py 30
#
# 注意:
#  · 默认 QT_QPA_PLATFORM=offscreen —— 不在用户屏幕上弹窗口; 只看"起不起来/线程多少"够用。
#  · 只是**度量**用, 跑完必须杀掉; 常驻服务/GUI 的启停仍由用户点名。
#  · 采样输出"每 6 秒一行", 稳态看最后两三行; 启动期的尖峰不代表稳态。
set -u
REPO="${REPO:-/home/ubuntu/zmax}"
PY="${PY:-$REPO/gui-venv311/bin/python}"
SCRIPT="${1:?用法: measure_threads.sh <脚本路径> [秒数] [cwd] }"
SECS="${2:-60}"
CWD="${3:-$REPO}"

cd "$CWD" || exit 1
QT_QPA_PLATFORM=offscreen HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  "$PY" "$SCRIPT" >/tmp/measure_threads.log 2>&1 &
PID=$!
for i in $(seq 1 $((SECS / 6))); do
  sleep 6
  if [ ! -d "/proc/$PID" ]; then echo "[$((i * 6))s] 进程已退出 (日志: /tmp/measure_threads.log)"; break; fi
  N=$(ls "/proc/$PID/task" | wc -l)
  NAMES=$(for t in /proc/$PID/task/*; do cat "$t/comm" 2>/dev/null; done | sort | uniq -c | sort -rn | head -6 | tr '\n' ' ')
  echo "[$((i * 6))s] pid=$PID 线程=$N : $NAMES"
 done
kill "$PID" 2>/dev/null; sleep 2; kill -9 "$PID" 2>/dev/null
echo "已结束 pid=$PID (全量日志 /tmp/measure_threads.log)"
