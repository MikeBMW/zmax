#!/usr/bin/env bash
# 昼夜双模: 白天(7-21) 采真值 + 1 代轻量影子评估; 夜间 4 代完整训练, 只采纳有提升的
set -u
H=$(date +%H); H=$((10#$H))
cd /home/intel/zmax_550c
export PYTHONPATH=src
PY=/home/intel/train_venv/bin/python
if [ "$H" -ge 7 ] && [ "$H" -lt 21 ]; then
  echo "[day] 采状态真值 40s + 轻量评估"
  $PY tools/evolve_se3_l2l4.py --collect --secs 40 --hz 5 || true
  $PY tools/evolve_se3_l2l4.py --gens 1 --epochs 200 --folds 3
else
  echo "[night] 完整进化 4 代"
  $PY tools/evolve_se3_l2l4.py --gens 4 --epochs 800 --folds 3
fi
echo "[done] $(date '+%F %T')"
