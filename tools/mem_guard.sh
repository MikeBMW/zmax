#!/bin/bash
# mem_guard.sh —— 内存红线守护: 系统 MemAvailable 低于阈值时, 先砍训练类进程, 绝不留给整机冻死
# 背景: 2026-11-15 15:48 系统 memory pressure critical → 15:48:25 起 journal 无输出 → 15:54 硬重启
# 策略: Warn 4G(只记) / Kill 2.5G(停训练 unit) / Hard 1.5G(再停 canvas/engine 之外的可停单元)
set -u
LOG=/home/ubuntu/zmax/logs/mem_guard.log
mkdir -p "$(dirname "$LOG")"
TS=$(date '+%F %T')
AVAIL=$(awk '/^MemAvailable:/{printf "%d", $2/1024}' /proc/meminfo)
WARN=4000; KILL=2500
[ "$AVAIL" -ge "$WARN" ] && exit 0

TOP=$(ps -eo pid,rss,comm --sort=-rss | awk 'NR>1 && NR<7 {printf "%s:%dMB ", $1, $2/1024}')
echo "$TS avail=${AVAIL}MB TOP=$TOP" >> "$LOG"

if [ "$AVAIL" -lt "$KILL" ]; then
  for u in l3-smolvla-train l3-diag l3-scale; do
    if systemctl is-active --quiet "$u"; then
      echo "$TS   → 停 $u (avail=${AVAIL}MB < ${KILL}MB)" >> "$LOG"
      systemctl stop "$u"
    fi
  done
fi
# 只保留最近 500 行
tail -n 500 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
exit 0
