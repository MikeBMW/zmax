#!/usr/bin/env bash
# 昼夜架构的数据摄取 (跑在产线主机): 把本机真机相点收进白天日志, 再推到 550C。
# 分工: 采集/推理必须在产线机(相机、桥、机器人都在这里); 学习与训练全部在 550C。
set -euo pipefail
cd "$(dirname "$0")/.."
PY=./gui-venv311/bin/python
export PYTHONPATH=src
DAY_ID="$($PY -c "from lerobot.manifold.daynight import phase,daylog;st=phase.read_state();print(st.get('day_id') or daylog.new_day_id())")"
$PY -m lerobot.manifold.daynight.cli collect --day "$DAY_ID" --tail 6000 | tail -3
rsync -a -e "ssh -o BatchMode=yes -o ConnectTimeout=8" \
  zmax_data/daynight/day/ intel:zmax_550c/zmax_data/daynight/day/
# 最近的真机实测序列(自主值班自我校验要用)
ssh -o BatchMode=yes intel "mkdir -p ~/zmax_550c/zmax_data/rokae_sdk/logs" || true
ls -t zmax_data/rokae_sdk/logs/meas_*.jsonl 2>/dev/null | head -2 | xargs -r rsync -a -e "ssh -o BatchMode=yes" -t intel:zmax_550c/zmax_data/rokae_sdk/logs/ 2>/dev/null || true
echo "[ingest] day=$DAY_ID + meas 已推送到 550C"
