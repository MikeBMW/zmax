#!/usr/bin/env bash
# 训练窗口: 让出 GPU → 全层训练 → 原样恢复在役服务 (只恢复我停掉的那几个)
set -uo pipefail
cd /home/ubuntu/zmax
TS=$(date +%Y%m%d_%H%M%S)
LOG="reports/train_window_$TS.log"
UNITS="zmax-ss-engine-loop zmax-fw-render zmax-hil-bridge"
PROBES="zmax-probe@arm zmax-probe@local"

{
  echo "=== 训练窗口开始 $TS"
  echo "--- 停前状态"
  for u in $UNITS; do echo "$u $(systemctl is-active $u)"; done
  for u in $PROBES; do echo "$u(user) $(systemctl --user is-active $u)"; done
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader

  sudo systemctl stop zmax-ss-engine-loop zmax-fw-render zmax-hil-bridge
  systemctl --user stop $PROBES 2>/dev/null || true
  sleep 4
  echo "--- 让出后显存 $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"

  ./gui-venv311/bin/python tools/joint_train_all.py \
      --only L4,L3,L2,L5 --steps 200 --yolo-epochs 30 --gpu-wait 180
  RC=$?
  echo "=== 训练结束 rc=$RC  证据目录 $(ls -dt reports/joint_train_* | head -1)"

  echo "--- 恢复在役服务"
  sudo systemctl start zmax-ss-engine-loop zmax-fw-render zmax-hil-bridge
  systemctl --user start $PROBES 2>/dev/null || true
  sleep 5
  for u in $UNITS; do echo "$u $(systemctl is-active $u)"; done
  echo "显存 $(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)"
  echo "=== 窗口结束 $(date +%Y%m%d_%H%M%S)"
} 2>&1 | tee "$LOG"
echo "LOG=$LOG"
