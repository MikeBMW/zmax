#!/usr/bin/env bash
# train_smoke_real.sh —— 用真机数据集跑 SmolVLA 冒烟训练（只验证管线，不看精度）
# 让出 GPU: 停引擎/渲染/HIL 三服务 + 探针；跑完原样恢复（和 train_window.sh 同口径）。
set -u
cd /home/ubuntu/zmax || exit 2
CFG="${1:-configs/generated_train_configs/config_smolvla_real_smoke.yaml}"
LOG="reports/smoke_real_$(date +%H%M%S).log"
SVC="zmax-ss-engine-loop zmax-fw-render zmax-hil-bridge"

echo "=== 冒烟训练开始 $(date +%H%M%S) · $CFG"
for s in $SVC; do systemctl stop "$s" 2>/dev/null; done
for u in $(systemctl list-units --plain --no-legend 'zmax-probe@*' 2>/dev/null | awk '{print $1}'); do systemctl stop "$u" 2>/dev/null; done
sleep 3
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader | sed 's/^/让出后显存: /'

t0=$(date +%s)
PYTHONPATH=src HF_HUB_OFFLINE=1 WANDB_MODE=disabled \
  PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  ./venvs/lerobot-venv/bin/python -m lerobot.scripts.lerobot_train --config_path="$CFG" 2>&1 | tee "$LOG" | grep -E "step:|loss|Error|error|Traceback|CUDA|OOM" | tail -40
rc=${PIPESTATUS[0]}
t1=$(date +%s)
echo "=== 训练结束 rc=$rc 用时 $((t1-t0))s · 日志 $LOG"

echo "--- 恢复在役服务"
for s in $SVC; do systemctl start "$s" 2>/dev/null; done
sleep 2
for s in $SVC; do printf '%s=%s ' "$s" "$(systemctl is-active $s)"; done; echo
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader | sed 's/^/恢复后显存: /'
exit $rc
