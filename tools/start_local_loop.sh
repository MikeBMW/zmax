#!/bin/bash
# start_local_loop.sh — 本机(4060) 起 215 点循环回放 (2026-11-15)
#
# 为什么用脚本: pkill -f "traj_loop.py" 会匹配到 ssh 自己的命令行 ⇒ 杀掉启动它的 shell,
# 新起的 setsid 子进程也会被带走 ⇒ 表现为「回放起不来/秒收到信号 15」。
# 脚本文件名不含被杀的 pattern, 且用 SELF=$$ 排除自己。
set -u
cd /home/ubuntu/zmax || exit 1
PAT="traj""_loop.py"
SELF=$$
for p in $(pgrep -f "$PAT"); do
  [ "$p" = "$SELF" ] && continue
  kill "$p" 2>/dev/null
done
sleep 2

# 清僵尸进度(只删记录, 不动臂); 备份保留
STS=zmax_data/rokae_sdk/traj_step_state.json
if [ -f "$STS" ]; then
  cp -a "$STS" "${STS}.bak_$(date +%H%M%S)"
  rm -f "$STS"
  echo "状态文件已清(备份保留)"
fi

export PYTHONPATH=/home/ubuntu/zmax/src
export ZMAX_TRAJ_LOOP=1 ZMAX_TRAJ_CHUNK=1
export ZMAX_TRAJ_SPEED="${ZMAX_TRAJ_SPEED:-20}"
mkdir -p zmax_data/reports
LOG=zmax_data/reports/traj_loop_local_$(date +%H%M%S).log
echo "LOG=$LOG"
setsid -f ./gui-venv311/bin/python -u tools/traj_loop.py > "$LOG" 2>&1 < /dev/null
sleep 22
tail -14 "$LOG"
echo "--- 进程 ---"
pgrep -af "$PAT" | cut -c1-70 | head -2
echo "--- 8797 状态 ---"
curl -s --max-time 8 "http://127.0.0.1:8797/api/arm/step_traj/status" | head -c 300
echo
