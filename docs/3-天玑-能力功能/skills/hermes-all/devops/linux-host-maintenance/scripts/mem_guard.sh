#!/bin/bash
# mem_guard.sh —— 内存红线守护: MemAvailable 低于阈值先砍训练类 unit, 绝不留给整机冻死
# 背景: 整机冻死的机制是内存耗尽后内核无法前进 —— journal 会在一秒内戛然而止,
#       无关机序列、无 oom-kill 行, 事后只能靠日志 mtime 与 uptime -s 相减定责。
# 装法 (每分钟一次, 用 systemd timer 不要用 cron):
#   /etc/systemd/system/<name>.service → ExecStart=<此脚本>
#   /etc/systemd/system/<name>.timer   → OnUnitActiveSec=60s
# 阈值可用环境变量覆盖: WARN_MB KILL_MB GUARD_UNITS GUARD_LOG
def_warn=4000; def_kill=2500
def_units="l3-smolvla-train l3-diag l3-scale"
WARN=${WARN_MB:-$def_warn}
KILL=${KILL_MB:-$def_kill}
UNITS=${GUARD_UNITS:-$def_units}
LOG=${GUARD_LOG:-$HOME/zmax/logs/mem_guard.log}
mkdir -p "$(dirname "$LOG")" 2>/dev/null
TS=$(date '+%F %T')
AVAIL=$(awk '/^MemAvailable:/{printf "%d", $2/1024}' /proc/meminfo)
[ "$AVAIL" -ge "$WARN" ] && exit 0
TOP=$(ps -eo pid,rss,comm --sort=-rss | awk 'NR>1 && NR<7 {printf "%s:%dMB ", $1, $2/1024}')
echo "$TS avail=${AVAIL}MB TOP=$TOP" >> "$LOG"
if [ "$AVAIL" -lt "$KILL" ]; then
  for u in $UNITS; do
    if systemctl is-active --quiet "$u"; then
      echo "$TS   → 停 $u (avail=${AVAIL}MB < ${KILL}MB)" >> "$LOG"
      systemctl stop "$u"
    fi
  done
fi
tail -n 500 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
exit 0
