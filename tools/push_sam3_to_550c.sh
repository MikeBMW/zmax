#!/bin/bash
# push_sam3_to_550c.sh —— 把 SAM3(权重 3.3G + 离线 wheel) 推到 550C 并在那边装好/自检
#
# 为什么用"重试循环 + --partial + 限速": 2026-10-25 实测这条经 ECS 的隧道会被对端周期性踢,
# 一次性 rsync 3.3G 必断; --partial 让每次续传, 限速别把隧道打崩, watchdog 20s 内补端口。
set -u
SRC_W=/home/ubuntu/zmax/zmax_data/models/sam3_hf
SRC_WH=/tmp/sam3_wheels
DST=127.0.0.1
PORT=18822
USER=intel
RDIR=/home/intel/zmax_550c
BW=${BW:-6000}
LOG=/tmp/push_sam3.log

rsh="ssh -p $PORT -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=15"

say() { echo "$(date '+%H:%M:%S') $*" | tee -a "$LOG"; }

try_rsync() {   # $1=src $2=dst
  for i in $(seq 1 ${TRIES:-40}); do
    rsync -a --partial --inplace --bwlimit=$BW -e "$rsh" "$1" "$2" 2>&1 | tail -2 | tee -a "$LOG"
    if [ "${PIPESTATUS[0]}" = "0" ]; then say "✅ 完成: $1"; return 0; fi
    say "第 $i 次中断, 25s 后续传 (--partial 不重头)"
    sleep 25
  done
  say "❌ 多次失败: $1"; return 1
}

say "开始推送 SAM3 → 550C"
ssh -p $PORT -o BatchMode=yes -o StrictHostKeyChecking=no $USER@$DST "mkdir -p $RDIR/models/sam3_hf $RDIR/wheels" || true

try_rsync "$SRC_WH/" "$USER@$DST:$RDIR/wheels/" || exit 1
say "wheel 已到, 远侧安装"
ssh -p $PORT -o BatchMode=yes $USER@$DST \
  "/home/intel/train_venv/bin/pip install -q --no-index --find-links $RDIR/wheels transformers==5.16.1 tokenizers safetensors huggingface_hub regex PyYAML requests tqdm filelock packaging 2>&1 | tail -3; /home/intel/train_venv/bin/python -c 'import transformers; from transformers import Sam3Model, Sam3Processor; print(\"sam3 可导入:\", transformers.__version__)'" 2>&1 | tee -a "$LOG"

try_rsync "$SRC_W/" "$USER@$DST:$RDIR/models/sam3_hf/" || exit 1

say "校验权重 sha256"
LOCAL_SHA=$(cat "$SRC_W/model.safetensors.sha256" 2>/dev/null | awk '{print $1}')
REMOTE_SHA=$(ssh -p $PORT -o BatchMode=yes $USER@$DST "sha256sum $RDIR/models/sam3_hf/model.safetensors | awk '{print \$1}'")
say "本地 sha=${LOCAL_SHA:-无} 远端 sha=${REMOTE_SHA:-无}"
if [ -n "$LOCAL_SHA" ] && [ "$LOCAL_SHA" = "$REMOTE_SHA" ]; then say "✅ 权重一致"; else say "⚠️ 权重 sha 不一致或缺失, 需人工确认"; fi
say "全部结束"
