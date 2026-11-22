#!/usr/bin/env bash
# 训练窗口 2: 补跑 L3 (起点已修) + 用"录制真机帧"做 L2 同口径对照 (实时源帧多样性不足被判无效)
set -uo pipefail
cd /home/ubuntu/zmax
TS=$(date +%Y%m%d_%H%M%S)
LOG="reports/train_window2_$TS.log"
UNITS="zmax-ss-engine-loop zmax-fw-render zmax-hil-bridge"
PROBES="zmax-probe@arm zmax-probe@local"
BEST="runs/detect/outputs/yolo_annot/annot_lora_20261122_215849/weights/best.pt"

{
  echo "=== 窗口2 开始 $TS"
  sudo systemctl stop $UNITS
  systemctl --user stop $PROBES 2>/dev/null || true
  sleep 4
  echo "显存让出: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"

  echo "--- L3 (起点 outputs/train/smolvla_lew_lora_200r4b1/checkpoints/last, n_obs=7)"
  ./gui-venv311/bin/python tools/joint_train_all.py --only L3 --steps 200 --gpu-wait 180
  echo "L3 rc=$?"

  echo "--- L2 同口径对照 (录制真机帧 62 张: 标注集 train 49 + live_1115 13)"
  FR=zmax_data/eval_frames/rec62
  rm -rf "$FR"; mkdir -p "$FR"
  i=0; for f in data/datasets/yolo_annot/dataset/images/train/*.jpg zmax_data/eval_frames/live_1115_232959/*.png; do
    [ -f "$f" ] || continue; i=$((i+1)); cp -l "$f" "$FR/$(printf 'r%03d' $i)_$(basename $f)" 2>/dev/null || cp "$f" "$FR/$(printf 'r%03d' $i)_$(basename $f)"
  done
  echo "帧数 $(ls $FR | wc -l)"
  ./gui-venv311/bin/python tools/yolo_live_eval.py --weights models/yolo_peg_live.pt "$BEST" \
      --frames-dir "$FR" --imgsz 640 --conf 0.25 \
      --out reports/yolo_samesource_$(basename $TS).json --vis-dir reports/yolo_samesource_vis_$TS
  echo "eval rc=$?"

  sudo systemctl start $UNITS
  systemctl --user start $PROBES 2>/dev/null || true
  sleep 5
  for u in $UNITS; do echo "$u $(systemctl is-active $u)"; done
  echo "显存 $(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)"
  echo "=== 窗口2 结束 $(date +%Y%m%d_%H%M%S)"
} 2>&1 | tee "$LOG"
echo "LOG=$LOG"
