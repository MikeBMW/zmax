#!/bin/bash
# L3 SmolVLA 低显存补跑 (2026-10-18): 原 pipeline 用 batch=4 需要 6GB,
# 8GB 卡上被在役进程 (引擎回路 476MB + 推理服务 98MB + YOLO 168MB + gs_train 636MB ≈1.4GB) 挤爆
# → CUDA OOM。这里降到 batch=2 并把分配器改成 expandable_segments, 其余环境与编排器逐项一致。
set -o pipefail
cd /home/ubuntu/zmax || exit 1
TS=$(date +%Y%m%d_%H%M%S)
OUT=outputs/train/smolvla_lew_lora_b2_$TS
CFG=configs/generated_train_configs/config_smolvla_lora_b2_$TS.yaml
LOG=zmax_data/ops/rerun_l3_b2_$TS.log
mkdir -p zmax_data/ops

echo "=== ① 生成配置 (batch=2) ===" | tee -a "$LOG"
./gui-venv311/bin/python tools/mk_smolvla_sim_cfg.py --steps 200 --batch 2 \
    --out "$CFG" --outdir "$OUT" 2>&1 | tail -3 | tee -a "$LOG"

echo "=== ② 训练 (LoRA, 基座冻结) ===" | tee -a "$LOG"
export HF_HOME=/home/ubuntu/zmax/zmax_data/hf_cache
export HF_HUB_CACHE=/home/ubuntu/zmax/zmax_data/hf_cache/hub
export HF_HUB_OFFLINE=1
export PYTHONPATH=/home/ubuntu/zmax/src
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export WANDB_MODE=disabled
export ZMAX_LORA_LOCAL=1
export ZMAX_LORA_MOD=/home/ubuntu/zmax/tools/lora_inject.py
export ZMAX_LORA_R=8
export ZMAX_LORA_ALPHA=16
export ZMAX_LORA_EXCLUDE=vision_model,lm_expert,projector
export ZMAX_LORA_TARGETS=q_proj,k_proj,v_proj,o_proj,action_model,le_world_model
export ZMAX_LORA_OUT=/home/ubuntu/zmax/reports/l3_b2_$TS/lora_l3_init.pt
mkdir -p /home/ubuntu/zmax/reports/l3_b2_$TS

/home/ubuntu/zmax/venvs/lerobot-venv/bin/python -m lerobot.scripts.lerobot_train \
    --config_path="$CFG" >> "$LOG" 2>&1
RC=$?
echo "=== ③ 结果 rc=$RC · 产物 $OUT · 日志 $LOG ===" | tee -a "$LOG"
ls -l "$OUT"/checkpoints/ 2>/dev/null | tail -3
exit $RC
