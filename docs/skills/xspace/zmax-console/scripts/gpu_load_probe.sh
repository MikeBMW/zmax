#!/usr/bin/env bash
# GPU 负载实测采样 — 用在“GPU 怎么没满负荷 / 到底哪一层在跑”这类问题上。
# 用法: bash scripts/gpu_load_probe.sh [采样次数] [间隔秒]
# 输出: 利用率均值/最高/最低 + 显存/功耗均值 + 同时段的训练进程 (谁在跑、跑多久、CPU 占比)。
# 纪律: 不要用单次 nvidia-smi 瞬时值下结论 —— 训练在“取数/加载/评测”阶段 GPU 本来就是 0~个位数。
set -u
N="${1:-30}"
IV="${2:-2}"
echo "════ GPU 采样 (${IV}s x ${N}) ════"
for _ in $(seq 1 "$N"); do
  nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw --format=csv,noheader
  sleep "$IV"
done | awk -F',' '{gsub(/[^0-9.]/,"",$1); gsub(/[^0-9.]/,"",$2); gsub(/[^0-9.]/,"",$3);
  su+=$1; sm+=$2; sp+=$3; if($1>mx)mx=$1; if($1<mn||mn=="")mn=$1}
  END {printf "  利用率: 均值 %.1f%% / 最高 %.0f%% / 最低 %.0f%%  样本 %d\n  显存: 均值 %.0fMB  功耗: 均值 %.1fW\n", su/NR, mx, mn, NR, sm/NR, sp/NR}'
echo "════ 采样期间的训练进程 ════"
ps -eo pid,etime,pcpu,pmem,cmd \
  | grep -E "lerobot_train|yolo_annot_train|joint_train_all|intact" | grep -v grep | cut -c1-150 \
  || echo "  (没有训练进程在跑)"
