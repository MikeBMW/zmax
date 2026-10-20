#!/usr/bin/env bash
# 重启本机相机流服务 (8791), 用**它自己当前的完整 argv** 重启 —— 不手抄参数, 免得漏掉 --overlay 之类
#   背景: 2026-10-20 它把 USB RealSense D435 抢走, 导致 AR 服务 pyrealsense EBUSY / D435 "不好使"
set -u
cd /home/ubuntu/zmax || exit 1
PID=$(pgrep -f "tools/cam_live_stream.py --port 8791" | head -1)
if [ -n "$PID" ]; then
  ARGV=$(tr '\0' '\n' < "/proc/$PID/cmdline" | tail -n +2)   # 去掉 argv[0] (python 解释器)
  echo "旧进程 pid=$PID · 参数 $(echo "$ARGV" | tr '\n' ' ' | cut -c1-120)…"
  kill "$PID" 2>/dev/null
  for i in $(seq 1 20); do kill -0 "$PID" 2>/dev/null || break; sleep 0.3; done
  kill -0 "$PID" 2>/dev/null && { kill -9 "$PID"; sleep 0.5; }
  echo "已停 (pid $PID)"
else
  ARGV="tools/cam_live_stream.py --port 8791 --station-port 8793 --quality 72 --fps 30 --local-dev 0 --local2-dev -1 --depth-fps 4 --aoi-fps 0.25 --ctl-motion --overlay --overlay-src all --overlay-fps 10"
  echo "没在跑 ⇒ 用默认参数起"
fi
# shellcheck disable=SC2086
nohup /home/ubuntu/zmax/gui-venv311/bin/python $ARGV > /tmp/cam_live_stream.log 2>&1 &
NEW=$!
echo "started pid=$NEW · log /tmp/cam_live_stream.log"
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8791/ 2>/dev/null)
  [ "$code" = "200" ] && { echo "✅ 8791 已应答 ($i×0.5s)"; break; }
  sleep 0.5
done
echo "--- 它现在开的 video 节点 (应当只有内置相机 video0..3, 不许有 RealSense video4..9) ---"
for f in /proc/$NEW/fd/*; do readlink "$f" 2>/dev/null; done | grep -o '/dev/video[0-9]*' | sort -u | while read -r d; do
  echo "  $d ← $(v4l2-ctl -d "$d" --info 2>/dev/null | grep -m1 'Card type' | sed 's/.*: //')"
done
