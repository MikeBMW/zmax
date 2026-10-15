#!/bin/bash
# 🚦 控制台重启 (2026-10-15) —— 停 → **等旧进程真死** → 再起
#
# 为什么不能直接 `systemctl --user restart zmax-studio.service`:
#   launch_studio.sh 里有"单实例"检查 (pgrep -f "gui-venv311/bin/python studio.py"):
#   已有实例 → 只写导航命令 + 激活旧窗口 + exit 0。重启瞬间旧进程可能还在 ⇒ 新实例被挡掉 ⇒
#   服务报"启动成功"、窗口还在(其实是旧的)、代码是旧的 ⇒ **假绿**。
#   2026-10-15 实测: 这么重启过一次, 结果连窗口都没了 (旧进程退掉 + 新实例没起)。
#
# 判据: 结束后必须 ① 有新 pid ② 有 'XSpace ZMAX' 窗口, 否则 rc=1。
set -u
LOG=/tmp/zmax_studio_restart.log
echo "=== $(date '+%F %T') 重启控制台 ===" | tee -a "$LOG"
# 锚定整条 cmdline (2026-10-15 加固): 子串匹配会把"任何 cmdline 里含这串字的进程"(例如我在终端里
# 跑 pgrep -af '...studio.py') 当成控制台实例 ⇒ 判活/判死都错。只认"就是那个解释器在跑 studio.py"。
PAT='^[^ ]*gui-venv311/bin/python studio\.py$'

systemctl --user stop zmax-studio.service 2>/dev/null
for _ in $(seq 1 30); do
    pgrep -f "$PAT" >/dev/null || break
    sleep 1
done
if pgrep -f "$PAT" >/dev/null; then
    echo "⚠ 旧进程 30s 未退, 显式结束: $(pgrep -f "$PAT" | tr '\n' ' ')" | tee -a "$LOG"
    pkill -f "$PAT"
    sleep 3
fi
: > /tmp/zmax_nav_cmd 2>/dev/null || true
systemctl --user start zmax-studio.service

PID=""; WIN=0
for i in $(seq 1 40); do
    PID=$(pgrep -f "$PAT" | head -1)
    WIN=$(DISPLAY="${DISPLAY:-:0}" wmctrl -l 2>/dev/null | grep -c 'XSpace ZMAX')
    if [ -n "$PID" ] && [ "$WIN" -gt 0 ]; then
        echo "✅ 新实例 pid=$PID · 'XSpace ZMAX' 窗口 $WIN 个 (第 $((i * 3))s)" | tee -a "$LOG"
        exit 0
    fi
    sleep 3
done
echo "❌ 起不来: pid=${PID:-无} 窗口=$WIN" | tee -a "$LOG"
exit 1
