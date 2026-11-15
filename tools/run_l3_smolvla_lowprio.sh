#!/bin/bash
# run_l3_smolvla_lowprio.sh —— 在本机 4060 上低优先级训 L3 (SmolVLA-LEW), 不抢 550B 的单线程调试
#   4060 就是本机: 10.163.146.76 = 本机 wlp0s20f3, RTX 4060 Laptop 8G (不用 SSH 到别处)
# 用法: bash tools/run_l3_smolvla_lowprio.sh [config_path]
set -u
REPO=/home/ubuntu/zmax
CFG=${1:-$REPO/configs/policies/smolvla/config_smolvla_live1115.yaml}
LOG=$REPO/zmax_data/reports/l3_smolvla_train_$(date +%m%d_%H%M).log
mkdir -p "$REPO/zmax_data/reports"

cd "$REPO" || exit 1
export PYTHONPATH=$REPO/src
export CUDA_VISIBLE_DEVICES=${ZMAX_TRAIN_GPU:-0}
export OMP_NUM_THREADS=4              # 别把 CPU 吃满, 550B 单步调试要响应
export MKL_NUM_THREADS=4
export TOKENIZERS_PARALLELISM=false
export HF_HOME=$HOME/.cache/huggingface
export HF_HUB_OFFLINE=1               # 本机权重已在缓存, 不联网

echo "[$(date +%H:%M:%S)] 训练开始 cfg=$CFG → $LOG"
# nice 19 = CPU 最低优先级; ionice -c3 = 只在空闲 IO 跑 —— 550B 断点/编辑器不受影响
exec nice -n 19 ionice -c3 ./gui-venv311/bin/python -u -m lerobot.scripts.lerobot_train \
  --config_path "$CFG" 2>&1 | tee "$LOG"
