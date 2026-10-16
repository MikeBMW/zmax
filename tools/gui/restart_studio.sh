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
        # 🪟 2026-10-16 老倪: 「太阳系和万有引力都显示不全」—— 根因之一是窗口被存成了小尺寸
        #   (1400×900 ⇒ M 页只有 ~509px)。 ⇒ 起来后**显式铺满屏幕**, 保证两窗有高度可用。
        # 🪟 2026-10-16 老倪: 「合力被遮挡, 看不到」—— 真因: 窗口底边**跑到屏幕外面**了
        #   (实测 1854×1060 @ y=86 ⇒ 底边 1146 > 屏幕 1080 ⇒ M 页下半截(合力行)在屏外)。
        #   ⇒ 交给窗管**最大化**(自己会贴住工作区), 再复核底边在屏内; 不在就硬贴到 (x, 0)。
        _wid=$(DISPLAY="${DISPLAY:-:0}" xdotool search --name 'XSpace ZMAX' 2>/dev/null | tail -1)
        if [ -n "$_wid" ]; then
            # ① 先去最大化态 (最大化态会**吃掉**后续 resize 请求 ⇒ 之前怎么改都不生效)
            DISPLAY="${DISPLAY:-:0}" wmctrl -i -r "$_wid" -b remove,maximized_vert,maximized_horz 2>/dev/null || true
            sleep 1
            # ② 只**复核**(不再由脚本改窗口尺寸 —— 应用自己按可用区 96% 开窗 + 自己夹进屏内;
            #    脚本硬改会和应用的 show/after-show fit 抢, 实测会把窗口顶到屏外 ⇒ 只读不写)
            _sw=$(DISPLAY="${DISPLAY:-:0}" xdotool getdisplaygeometry 2>/dev/null | awk '{print $1}'); _sw=${_sw:-1920}
            _sh0=$(DISPLAY="${DISPLAY:-:0}" xdotool getdisplaygeometry 2>/dev/null | awk '{print $2}'); _sh0=${_sh0:-1080}
            sleep 2
            _geo=$(DISPLAY="${DISPLAY:-:0}" xdotool getwindowgeometry --shell "$_wid" 2>/dev/null || true)
            _gx=$(echo "$_geo" | sed -n 's/^X=\(-*[0-9]*\)$/\1/p'); _gx=${_gx:-0}
            _gy=$(echo "$_geo" | sed -n 's/^Y=\(-*[0-9]*\)$/\1/p'); _gy=${_gy:-0}
            _gw=$(echo "$_geo" | sed -n 's/^WIDTH=\([0-9]*\)$/\1/p'); _gw=${_gw:-0}
            _gh=$(echo "$_geo" | sed -n 's/^HEIGHT=\([0-9]*\)$/\1/p'); _gh=${_gh:-0}
            if [ $((_gx + _gw)) -le "$_sw" ] && [ $((_gy + _gh)) -le "$_sh0" ]; then
                echo "🪟 窗口 ${_gw}x${_gh} @ (${_gx},${_gy}) · 屏 ${_sw}x${_sh0} ⇒ 右 $((_gx + _gw)) 底 $((_gy + _gh)) ✓全在屏内" | tee -a "$LOG"
            else
                echo "🪟 ⚠️ 窗口 ${_gw}x${_gh} @ (${_gx},${_gy}) 越界 (屏 ${_sw}x${_sh0}) — 看 /tmp/studio_show_diag.log" | tee -a "$LOG"
            fi
        fi
        exit 0
    fi
    sleep 3
done
echo "❌ 起不来: pid=${PID:-无} 窗口=$WIN" | tee -a "$LOG"
exit 1
