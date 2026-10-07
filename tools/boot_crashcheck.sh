#!/bin/bash
# boot_crashcheck.sh — 开机留痕: crash 内核有没有加载成功 + 上一轮是不是崩溃回来的
#
# 为什么要有它(2026-10-07 事故后): 10-02 那次是"卡死→人工断电→5 天没开机",
# 事后什么都查不到 —— 没有任何一处在开机时记录"上次是怎么走的"。
# 现在: 每次开机都往 boot_selfcheck.log 记一行 kdump 状态; 一旦发现 /var/crash 里有 vmcore,
# 立刻推一条飞书(静界群), 老倪不用登录就知道"机器是自己崩回来的, 转储在这儿"。
#
# 装法: crontab 里 `@reboot sleep 120 && bash /home/ubuntu/zmax/tools/boot_crashcheck.sh`
# 口径: 正常开机只写日志不打扰; 只有真有 vmcore 才发消息。
set -uo pipefail
LOG=/home/ubuntu/zmax/zmax_data/boot_selfcheck.log
NOTIFY_LOG=/home/ubuntu/zmax/zmax_data/boot_crashcheck_notify.log
TS=$(date '+%F %T %Z')

STATE=$(sudo -n /usr/sbin/kdump-config show 2>/dev/null | awk -F: '/current state/{print $2}' | xargs)
CSZ=$(cat /sys/kernel/kexec_crash_size 2>/dev/null || echo 0)
CRASH_KB=$(( ${CSZ:-0} / 1024 ))
DUMPS=$(ls -1d /var/crash/*/ 2>/dev/null | wc -l)
DMESG_CMD=$(grep -o 'crashkernel=[^ ]*' /proc/cmdline 2>/dev/null || echo 'crashkernel=未配置')

{
  echo "$TS | kdump=${STATE:-读不到} | crash预留=${CRASH_KB}MB | 参数=$DMESG_CMD | /var/crash 份数=$DUMPS"
} >> "$LOG" 2>/dev/null || echo "boot_crashcheck: 日志写不进去 $LOG" >&2

if [ "${DUMPS:-0}" -gt 0 ]; then
  LATEST=$(ls -1dt /var/crash/*/ 2>/dev/null | head -1)
  SIZE=$(du -sh "$LATEST" 2>/dev/null | cut -f1)
  PREV=$(last -x reboot 2>/dev/null | sed -n '2p' | cut -c1-52)
  MSG="🚨 工位机(4060)刚从崩溃回来: /var/crash 里有 ${DUMPS} 份转储
最近一份: ${LATEST} (${SIZE})
上一轮: ${PREV}
诊断: sudo kdump-config show · 转储在 ${LATEST} · dmesg 见其中的 dmesg.txt"
  python3 /home/ubuntu/.hermes/scripts/feishu_notify.py "$MSG" >> "$NOTIFY_LOG" 2>&1 \
    && echo "$TS 已推飞书" >> "$NOTIFY_LOG" \
    || echo "$TS 飞书推送失败(见 $NOTIFY_LOG)" >> "$NOTIFY_LOG"
fi
exit 0
