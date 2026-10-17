#!/bin/bash
# 重启技能派发发布器 (只写 zmax_data/ss_live/skill_*.json, 不碰真机动作)
set -u
OLD=$(pgrep -f "tools/ss_skill_dispatch.py --hz" | head -1)
if [ -n "${OLD:-}" ]; then
  kill "$OLD" 2>/dev/null
  for i in $(seq 1 20); do kill -0 "$OLD" 2>/dev/null || break; sleep 0.2; done
fi
cd /home/ubuntu/zmax || exit 1
setsid nohup ./gui-venv311/bin/python tools/ss_skill_dispatch.py --hz 60 \
  >> /home/ubuntu/.hermes/cache/scratch/skill_dispatch.log 2>&1 &
sleep 3
NEW=$(pgrep -f "tools/ss_skill_dispatch.py --hz" | head -1)
echo "old=${OLD:-none} new=${NEW:-FAILED}"
