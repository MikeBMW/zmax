#!/bin/bash
# start_probes.sh — 双路 L2 探针 (2026-11-15 老倪: 手臂相机和中央相机都要用)
#
# 为什么两个进程: local(1280x720 中央相机, 看料盘/废料盘) 与 arm(640x480 臂上D435, 有深度)
# 分辨率、内参、是否取深度都不同, 用 --cam 各起一路最干净, 互不干扰。
# 文件名不含被杀的 pattern, 且 SELF=$$ 排除自己(否则 pkill -f 会杀掉启动它的 shell)。
set -u
cd /home/ubuntu/zmax || exit 1
PAT="l2""_probe.py"
SELF=$$
for p in $(pgrep -f "$PAT"); do
  [ "$p" = "$SELF" ] && continue
  kill "$p" 2>/dev/null
done
sleep 2

export PYTHONPATH=/home/ubuntu/zmax/src
mkdir -p zmax_data/reports
TS=$(date +%H%M%S)
for cam in local arm; do
  LOG=zmax_data/reports/l2_probe_${cam}_${TS}.log
  setsid -f ./gui-venv311/bin/python -u tools/l2_probe.py \
      --seconds "${PROBE_SECONDS:-1800}" --every "${PROBE_EVERY:-3}" \
      --conf "${PROBE_CONF:-0.05}" --cam "$cam" > "$LOG" 2>&1 < /dev/null
  echo "起 $cam → $LOG"
  sleep 1
done
sleep 14
echo "--- 进程 ---"
pgrep -af "$PAT" | cut -c1-78
echo "--- 两路各抓到几帧 ---"
python3 - <<'PY'
import json, collections
rows = [json.loads(l) for l in open('zmax_data/ss_live/l2_probe/frames.jsonl')]
per = collections.defaultdict(lambda: [0, 0])
for r in rows[-40:]:
    c = r.get('cam') or '?'
    per[c][0] += 1
    per[c][1] += len(r.get('det') or [])
for c, (n, d) in per.items():
    print('  %-6s 帧=%-3d 检出总=%-3d' % (c, n, d))
PY
