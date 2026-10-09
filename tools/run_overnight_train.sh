#!/usr/bin/env bash
# 全量模型训练 (L5+L4+L3+L2) —— 无人值守跑一夜
set -u
cd /home/ubuntu/zmax || exit 1
TS=$(date +%Y%m%d_%H%M%S)
OUT="reports/joint_train_overnight_$TS"
mkdir -p "$OUT"
echo "$OUT" > /tmp/zmax_train_out_dir.txt
export HF_HOME=/home/ubuntu/zmax/zmax_data/hf_cache
export PYTHONUNBUFFERED=1
echo "=== 全量联合训练开始 $(date '+%F %T') → $OUT ==="
exec ./gui-venv311/bin/python tools/joint_train_all.py \
    --steps 500 --yolo-epochs 30 --l5-steps 120 --l5-merge \
    > "$OUT/run.log" 2>&1
