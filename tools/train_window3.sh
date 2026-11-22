#!/usr/bin/env bash
# 训练窗口 3: 补跑 L3 (续训起点已修到 n_obs=7) + L2 同口径对照(62 帧录制真机帧, 命名 live_*.png)
set -uo pipefail
cd /home/ubuntu/zmax
TS=$(date +%Y%m%d_%H%M%S)
LOG="reports/train_window3_$TS.log"
UNITS="zmax-ss-engine-loop zmax-fw-render zmax-hil-bridge"
PROBES="zmax-probe@arm zmax-probe@local"
BEST="runs/detect/outputs/yolo_annot/annot_lora_20261122_215849/weights/best.pt"
FR="zmax_data/eval_frames/rec62b"

{
  echo "=== 窗口3 开始 $TS"
  sudo systemctl stop $UNITS
  systemctl --user stop $PROBES 2>/dev/null || true
  sleep 4
  echo "显存让出: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)"

  echo "--- L2 同口径对照 (录制真机帧 $(ls $FR | wc -l) 张, 同帧同阈值 conf 0.25)"
  ./gui-venv311/bin/python tools/yolo_live_eval.py --weights models/yolo_peg_live.pt "$BEST" \
      --frames-dir "$FR" --imgsz 640 --conf 0.25 \
      --out "reports/yolo_samesource_$TS.json" --vis-dir "reports/yolo_samesource_vis_$TS"
  echo "eval rc=$?"

  echo "--- L3 (起点已修: n_obs=7 产物)"
  ./gui-venv311/bin/python tools/joint_train_all.py --only L3 --steps 200 --gpu-wait 180
  echo "L3 rc=$?"

  sudo systemctl start $UNITS
  systemctl --user start $PROBES 2>/dev/null || true
  sleep 5
  for u in $UNITS; do echo "$u $(systemctl is-active $u)"; done
  echo "显存 $(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)"
  echo "=== 窗口3 结束 $(date +%Y%m%d_%H%M%S)"
} 2>&1 | tee "$LOG"
echo "LOG=$LOG"
