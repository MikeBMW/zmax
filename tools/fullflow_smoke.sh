#!/usr/bin/env bash
# 单任务冒烟: 证明 5 段链路真跑通 (小预算), 再上 7 任务全量
set -o pipefail
cd /home/ubuntu/zmax
mkdir -p reports/fullflow7
TS=$(date +%Y%m%d_%H%M%S)
LOG=reports/fullflow7/smoke_${TS}.log
echo "== 冒烟开始 $TS ==" >> "$LOG"
./gui-venv311/bin/python tools/fullflow_tasks7.py \
  --tasks TASK-01-FW --sim-target 6 --steps 4 --yolo-epochs 1 --l5-steps 4 --no-feishu \
  >> "$LOG" 2>&1
rc=$?
echo "== 冒烟结束 rc=$rc ==" >> "$LOG"
echo "SMOKE_RC=$rc LOG=$LOG"
tail -30 "$LOG"
