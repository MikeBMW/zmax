#!/bin/bash
# 等这一轮 215 点走完 → 用今天这轮(图像+位姿) + 1113 基线 session 合并 → 训 24k 步 → 出 PSNR
# 口径与 17.22 基线同源: 同一个 gs_train.py / holdout=20 / --data 为 session(cameras.json+images)
set -u
LOG=/home/ubuntu/zmax/zmax_data/reports/gs_after_run_1114.log
mkdir -p "$(dirname "$LOG")"
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
say "等待 arm 215 点走完 (每 30s 查一次, 最多 50 分钟)"
for i in $(seq 1 100); do
  st=$(python3 - <<'EOF' 2>/dev/null
import json
try:
    d=json.load(open('/home/ubuntu/zmax/zmax_data/ss_live/traj_flow.json'))
    print("%s %s %s" % (d.get('phase'), d.get('cursor'), d.get('total')))
except Exception:
    print("none 0 0")
EOF
)
  ph=$(echo "$st" | awk '{print $1}'); cur=$(echo "$st" | awk '{print $2}')
  run=$(curl -s --max-time 3 http://127.0.0.1:8797/api/arm/step_traj/status 2>/dev/null | python3 -c "import json,sys;print(json.load(sys.stdin).get('running'))" 2>/dev/null)
  if [ "$ph" = "DONE" ] || { [ "$cur" != "0" ] && [ "${cur%%.*}" -ge 215 ] 2>/dev/null && [ "$run" != "True" ]; }; then
    say "轨迹结束: phase=$ph cursor=$cur running=$run"; break
  fi
  sleep 30
done

S_TODAY=/home/intel/gs_autocap/sessions/20261114_104907_f4e1
S_BASE=/home/intel/gs_autocap/sessions/20261113_193134_2a34
MERGED=/home/intel/zmax_data/gs_rt/ds_merged_1114
OUT=/home/intel/zmax_data/gs_rt/out_big3_1114
say "帧数: today=$(ssh -o ConnectTimeout=8 intel "ls $S_TODAY/images | wc -l") base=$(ssh -o ConnectTimeout=8 intel "ls $S_BASE/images | wc -l")"
FREE=$(ssh -o ConnectTimeout=8 intel "df -Bg --output=avail /home/intel | tail -1 | tr -dc '0-9'")
MEM=$(ssh -o ConnectTimeout=8 intel "free -g | awk '/^Mem:/{print \$7}'")
say "550C 磁盘可用 ${FREE}G · 内存可用 ${MEM}G"
if [ "${FREE:-0}" -ge 8 ]; then
  say "合并数据集 → $MERGED"
  ssh -o ConnectTimeout=8 intel "/home/intel/gsxpu-venv/bin/python /home/intel/zmax_map/tools/gs_dataset_merge.py --out $MERGED --in $S_TODAY $S_BASE 2>&1 | tail -5" | tee -a "$LOG"
  DATA=$MERGED
else
  say "磁盘不足(${FREE}G) → 直接用今天这轮 session"
  DATA=$S_TODAY
fi
# 内存闸: 550C 30G 里要给渲染留空间; 可用 <8G 时等它缓过来(最多 20 分钟)
for k in $(seq 1 40); do
  MEM=$(ssh -o ConnectTimeout=8 intel "free -g | awk '/^Mem:/{print \$7}'")
  [ "${MEM:-0}" -ge 8 ] && break
  say "内存可用 ${MEM}G < 8G ⇒ 等 30s"; sleep 30
done
say "开训 24000 步 · data=$DATA · out=$OUT · 内存可用 ${MEM}G"
ssh -o ConnectTimeout=8 intel "cd /home/intel/zmax_map && nohup bash /home/intel/zmax_map/tools/run_gs_train_intel.sh --data $DATA --out $OUT --steps 24000 --holdout 20 --sh-degree 2 > /home/intel/zmax_data/gs_rt/train_big3_1114.log 2>&1 & echo started pid=\$!"
sleep 20
ssh -o ConnectTimeout=8 intel "tail -3 /home/intel/zmax_data/gs_rt/train_big3_1114.log" | tee -a "$LOG"
say "训练已起(后台). 日志 550C:/home/intel/zmax_data/gs_rt/train_big3_1114.log"
say "等训练结束(最多 300 分钟) …"
for k in $(seq 1 300); do
  sleep 60
  alive=$(ssh -o ConnectTimeout=8 intel "pgrep -fc 'gs_train.py --data .*out_big3_1114' || true")
  [ "${alive:-0}" = "0" ] && break
  [ $((k % 10)) -eq 0 ] && say "训练中… 已 ${k} 分钟"
done
say "训练进程结束, 回读报告"
ssh -o ConnectTimeout=10 intel "python3 - <<'EOF'
import json
try:
    d=json.load(open('/home/intel/zmax_data/gs_rt/out_big3_1114/train_report.json'))
    print('NEW  psnr_holdout=%.3f  psnr_train=%.3f  gaussians=%s  steps=%s  data=%s' % (
        d.get('psnr_holdout_db') or 0, d.get('psnr_train_db') or 0,
        d.get('n_gaussians'), d.get('steps'), d.get('data')))
except Exception as e:
    print('读不到报告:', e)
EOF" | tee -a "$LOG"
echo "基线 map_big2_081214: psnr_holdout=17.223  gaussians=445521  steps=24000" | tee -a "$LOG"
