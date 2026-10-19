#!/usr/bin/env bash
# 接力编排: 等 YOLO 全量训练结束 → 自动跑 L4/L3 约束训练 → 生成综合评估报告
# 老倪要求"数据闭环训练 + 评估分析有结果"; 无人值守, 每步只报一次。
set -u
ROOT=/home/ubuntu/zmax
cd "$ROOT" || exit 1
LOG=$ROOT/reports/pipeline_$(date +%Y%m%d_%H%M%S).log
mkdir -p "$ROOT/reports"
exec >> "$LOG" 2>&1
echo "===== 接力开始 $(date '+%F %T') ====="

# ── ① 等 YOLO 训练进程退出 (最多 3 小时) ──
waited=0
while pgrep -f '[t]rain_yolo_full.py' >/dev/null; do
  sleep 60; waited=$((waited+60))
  if [ $waited -gt 10800 ]; then echo "⚠️ YOLO 等待超 3h, 继续下一步"; break; fi
  if [ $((waited % 600)) -eq 0 ]; then
    echo "  [$(date '+%H:%M')] 仍在训练 (已等 $((waited/60))min) · $(tail -1 runs/peg_full/full30/results.csv 2>/dev/null | cut -d, -f1,7,8)"
  fi
done
echo "[$(date '+%H:%M')] YOLO 结束 (等了 $((waited/60))min)"
tail -3 runs/peg_full/full30/results.csv 2>/dev/null | cut -d, -f1,2,6-9

# ── ② L4 + L3 约束训练 (GPU 空出来再跑) ──
sleep 20
echo "===== L4/L3 约束训练开始 $(date '+%F %T') ====="
./gui-venv311/bin/python tools/joint_train_all.py --only L4,L3 --steps 100 --gpu-wait 900
echo "L4/L3 退出码=$?"

# ── ③ 约束 A/B 复跑 (大样本, 与训练同口径) ──
echo "===== 约束 A/B 大样本复跑 $(date '+%F %T') ====="
./gui-venv311/bin/python tools/ab_engine_geometry.py --k 30 --eps 150 --steps 40
./gui-venv311/bin/python tools/ab_engine_geometry.py --k 150 --eps 150 --steps 40

# ── ④ 汇总: 生成综合评估报告 ──
echo "===== 生成综合报告 ====="
./gui-venv311/bin/python tools/eval_report_joint.py

echo "===== 接力完成 $(date '+%F %T') · 日志 $LOG ====="
df -BG / | tail -1 | awk '{print "磁盘 已用 "$3" 可用 "$4}'
