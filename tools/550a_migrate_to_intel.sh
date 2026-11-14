#!/bin/bash
# 550a_migrate_to_intel.sh — 把 4060(550A/550B) 的训练栈迁成 Intel 上的"550A 训练档"
# 老倪 2026-11-14:「先迁移, 等 intel 进入到自主进化时就可以运行 550A」
# 原则: Intel 上**只跑训练**, 不碰真机/相机/渲染; 资源闸先过才允许起训
set -u
INTEL=intel
DST=/home/intel/zmax_550a
say(){ echo "[$(date +%H:%M:%S)] $*"; }

say "1) 建目录"
ssh $INTEL "mkdir -p $DST/{src,tools,models,zmax_data/datasets,zmax_data/hf_cache,zmax_data/ckpt,zmax_data/reports,logs}"

say "2) 同步训练代码 (src/lerobot + tools/*.py)"
rsync -a --exclude '__pycache__' src/lerobot/ $INTEL:$DST/src/lerobot/ 2>&1 | tail -2
rsync -a --exclude '__pycache__' tools/ $INTEL:$DST/tools/ 2>&1 | tail -2

say "3) 同步权重与数据集 (models + datasets)"
rsync -a models/ $INTEL:$DST/models/ 2>&1 | tail -2
rsync -a zmax_data/datasets/ $INTEL:$DST/zmax_data/datasets/ 2>&1 | tail -2

say "4) HF 缓存 (9.5G, 后台)"
nohup rsync -a zmax_data/hf_cache/ $INTEL:$DST/zmax_data/hf_cache/ > /tmp/550a_hf_sync.log 2>&1 &
say "   HF 同步后台 pid=$! 日志 /tmp/550a_hf_sync.log"

say "5) Intel 侧 venv 复用检查"
ssh $INTEL "/home/intel/train_venv/bin/python -c 'import torch;print(\"train_venv\", torch.__version__, \"xpu\", torch.xpu.is_available())'"

say "完成代码/权重搬运"
