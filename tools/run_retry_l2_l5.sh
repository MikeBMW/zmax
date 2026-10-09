#!/usr/bin/env bash
# 复跑 2026-10-09 夜间训练挂掉的两层 (L2 / L5) —— 根因都是数据整合后路径没跟上:
#   L2: dataset/data.yaml 里 path 还指 data/yolo_annot (旧) → 已用 --build 重建为 data/datasets/yolo_annot
#   L5: 清单 38/38 图路径是旧绝对路径 → 已用 tools/fix_l5_manifest_paths.py 修正 (215 条全可解析)
#   L5 另有代码 bug: evaluate() 里 _req 未初始化 → 样本全失败时 UnboundLocalError, 已修
# 单卡纪律: 串行跑 (同刻只一个模型进程)
set -u
cd /home/ubuntu/zmax
TS=$(date +%Y%m%d_%H%M%S)
OUT=reports/joint_train_retry_$TS
mkdir -p "$OUT"
echo "=== L2/L5 复跑 $TS → $OUT ===" | tee "$OUT/run.log"

echo "▶ L5 · SmolVLM2-500M LoRA (120 步 + merge)" | tee -a "$OUT/run.log"
./gui-venv311/bin/python tools/l5_vlm_lora_train.py --steps 120 --max-pixels 200704 \
    --model smolvlm --max-side 448 --tag "$TS" --merge > "$OUT/L5.log" 2>&1
echo "  L5 rc=$? 用时见日志" | tee -a "$OUT/run.log"
tail -3 "$OUT/L5.log" | tee -a "$OUT/run.log"

echo "▶ L2 · YOLO 真机帧域适应微调 (30 epochs, 基座=在役软链)" | tee -a "$OUT/run.log"
./gui-venv311/bin/python tools/yolo_annot_train.py --epochs 30 --imgsz 640 \
    --name "annot_lora_$TS" --base /home/ubuntu/zmax/models/yolo_peg_live.pt > "$OUT/L2.log" 2>&1
echo "  L2 rc=$?" | tee -a "$OUT/run.log"
tail -5 "$OUT/L2.log" | tee -a "$OUT/run.log"

echo "=== 完 $OUT ===" | tee -a "$OUT/run.log"
