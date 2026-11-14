#!/bin/bash
# 建图提质: 在 550C(XPU) 上用**今天这轮**的 session 训 24k (视角是新的, 才是"抬头更糊"的解)
# 为什么不用合并 1800 帧: Intel 可用内存只有 5~6G, 1800 帧会顶到 OOM; 900 帧此前跑通过(96 分钟)
set -u
LOG=/home/ubuntu/zmax/zmax_data/reports/gs_today_1114.log
mkdir -p "$(dirname "$LOG")"
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
S=/home/intel/gs_autocap/sessions/20261114_104907_f4e1
OUT=/home/intel/zmax_data/gs_rt/out_today_1114
say "等 550C 内存 >=5G 且没有别的 gs_train"
for i in $(seq 1 120); do
  read -r MEM BUSY <<<"$(ssh -o ConnectTimeout=8 intel "free -g | awk '/^Mem:/{printf \"%s \", \$7}'; pgrep -fc gs_train.py || true" | tr '\n' ' ')"
  [ "${BUSY:-0}" -gt 0 ] && { say "已有一个 gs_train 在跑, 等 60s"; sleep 60; continue; }
  if [ "${MEM:-0}" -ge 5 ]; then say "内存 ${MEM}G 可用 ⇒ 开训"; break; fi
  say "内存 ${MEM}G < 5G, 等 60s"; sleep 60
done
ssh -o ConnectTimeout=8 intel "cd /home/intel/zmax_map && nohup bash /home/intel/zmax_map/tools/run_gs_train_intel.sh --data $S --out $OUT --steps 24000 --holdout 20 --sh-degree 2 --init-points 80000 > /home/intel/zmax_data/gs_rt/train_today_1114.log 2>&1 & echo started"
sleep 30
ssh -o ConnectTimeout=8 intel "tail -3 /home/intel/zmax_data/gs_rt/train_today_1114.log" | tee -a "$LOG"
say "训练中(后台). 完成后自动被渲染循环按 PSNR 选中"
