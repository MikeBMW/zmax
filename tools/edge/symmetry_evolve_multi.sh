#!/usr/bin/env bash
# Intel 550C: 对称性引擎自主进化 —— 4 路不同种子的搜索并行跑, 吃满空闲核 (XPU 归 YOLO 训练)
# 每路 40 代后自己退出, 由 systemd Restart=always 再拉起新一轮 (种子来自时间戳 ⇒ 永不重复)
set -u
T=/home/intel/zmax_map/tools/symmetry_evolve.py
PY=/home/intel/train_venv/bin/python
export EVO_WORK=/home/intel/evolve
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
cd /home/intel/zmax_map || exit 1
for i in 1 2 3 4 5 6; do
  "$PY" -u "$T" --gens 40 --pop 18 &
  sleep 2
done
wait
