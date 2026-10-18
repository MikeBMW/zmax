#!/bin/bash
# 停常驻的异步跟随 (只按 pid 杀, 不用 pkill -f 以免匹配到自己)
set -u
PIDF=/home/ubuntu/zmax/zmax_data/ss_live/bridge_async.pid
if [ -f "$PIDF" ]; then
  p=$(cat "$PIDF")
  c=$(cat /proc/$p/comm 2>/dev/null || true)
  case "$c" in
    python|python3) kill -TERM "$p" && echo "已停 pid=$p";;
    *) echo "pid=$p 不是 python 进程 (comm=${c:-none}), 不动";;
  esac
  rm -f "$PIDF"
else
  echo "没有 pid 文件, 进程可能已经停了"
fi
