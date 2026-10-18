#!/bin/bash
# 停所有 bridge_* 跟随进程: 只认 pid 文件 + /proc 里 comm=python 的进程, 绝不用 pkill -f
set -u
cd /home/ubuntu/zmax
for f in zmax_data/ss_live/bridge_async.pid zmax_data/ss_live/bridge_path.pid zmax_data/ss_live/bridge_episode.pid; do
  [ -f "$f" ] || continue
  p=$(cat "$f" 2>/dev/null)
  [ -n "${p:-}" ] || continue
  c=$(cat /proc/"$p"/comm 2>/dev/null || true)
  case "$c" in
    python|python3) kill -TERM "$p" 2>/dev/null && echo "已停 $(basename "$f") pid=$p";;
  esac
  rm -f "$f"
done
# 兜底: 扫 /proc 命令行里含 bridge_ 且 comm=python 的进程 (排除本脚本)
for d in /proc/[0-9]*; do
  p=${d#/proc/}
  [ "$p" = "$$" ] && continue
  c=$(cat "$d/comm" 2>/dev/null || true)
  case "$c" in python|python3) ;; *) continue;; esac
  cl=$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null || true)
  case "$cl" in
    *tools/bridge_stage_*|*tools/bridge_episode_path*|*tools/bridge_follow_live*)
      kill -TERM "$p" 2>/dev/null && echo "已停残留 pid=$p";;
  esac
done
sleep 1
echo "现存活:"; ps -eo pid,args | grep -E "tools/bridge_(stage|episode|follow)" | grep -v grep | cut -c1-90 || true
