#!/bin/bash
# XSpace Studio 控制台快捷启动 (桌面图标点击调用)
# 硬编码 gui-venv311 的 Python, 不依赖 run_studio.sh 的自动探测
# 2026-09-26: 不再硬编码检出路径 —— 按本脚本位置推仓库根
#   (共享检出 /home/ubuntu/zmax 会被并行线切到别的分支 → 那儿没有 flows/ 画布 + 是旧 GUI)
GUI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$GUI_DIR/../.." && pwd)"
VENV_PY=""
for c in "$REPO_ROOT/gui-venv311/bin/python" "/home/ubuntu/zmax/gui-venv311/bin/python"; do
    [ -x "$c" ] && { VENV_PY="$c"; break; }
done
[ -n "$VENV_PY" ] || { echo "找不到 gui-venv311 解释器"; exit 1; }
LOG="/tmp/studio_launch.log"

# 本机 Xorg 显示 (桌面会话一般已设, 兜底 :0)
export DISPLAY="${DISPLAY:-:0}"

# 🔴 2026-10-09 老倪: 「重启后控制台不见了」——真根因: agent 在同一个 shell 里跑过
#   `export QT_QPA_PLATFORM=offscreen` 的离屏判据, 于是重启控制台时**继承了这个变量**:
#   GUI 起在 offscreen 平台 → 进程活着、日志正常、窗口"visible=True", 但**根本没有窗口** (没有 X 连接)。
#   ⇒ 这里强制回到真 X11 平台, 免得测试环境把线上界面弄没。
unset QT_QPA_PLATFORM
export QT_QPA_PLATFORM=xcb

# 🔴 2026-09-27 老倪: 「点了场景叠加什么都没打开」的真根因 —— 控制台从终端/服务启动时会带
#   DBUS_SESSION_BUS_ADDRESS=disabled:(本机实测就是这样), 于是 snap 版 chromium 连不上 snapd,
#   报 "…is not a snap cgroup for tag snap.chromium.chromium" 后静默退出(exit 1, 零窗口)。
#   ⇒ 启动前把会话总线补上(桌面会话里本来就是好的, 这里只是不让终端启动的实例掉坑里)。
if ! echo "${DBUS_SESSION_BUS_ADDRESS:-}" | grep -q '^unix:'; then
    if [ -S "/run/user/$(id -u)/bus" ]; then
        export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus"
    fi
fi
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# 🚀 2026-10-12 老倪: 「双击启动图标后, 先打开配置中心」——
#   新实例: studio.py 按 ZMAX_BOOT_PAGE 启动后跳页 (默认 config = 配置中心);
#   已有实例: 直接写命令通道把它弹到配置中心 (双击图标一定落到配置中心, 不用记快捷键)。
export ZMAX_BOOT_PAGE="${ZMAX_BOOT_PAGE:-config}"

# 已有实例在跑 → 激活已有窗口 + 弹到配置中心, 不重复启动
if pgrep -f "[g]ui-venv311/bin/python studio.py" >/dev/null 2>&1; then
    printf '%s\n' "$ZMAX_BOOT_PAGE" > /tmp/zmax_nav_cmd 2>/dev/null || true
    WIN=$(DISPLAY="$DISPLAY" xdotool search --onlyvisible --name "XSpace ZMAX" 2>/dev/null | head -1)
    if [ -n "$WIN" ]; then
        DISPLAY="$DISPLAY" xdotool windowactivate "$WIN" 2>/dev/null
    fi
    exit 0
fi

# 🔴 2026-10-12 老倪: 「点开启动图标后, 3D场景不要自动启动, 我要先检查任务配置, 然后启动工程」
#   真根因候选: /tmp/zmax_nav_cmd 里若残留上一轮(`open_all`/`ss_3d`)的命令, **新进程**的去重表是空的
#   ⇒ 界面一建好就执行旧命令 ⇒ 老倪看到"3D 自己开起来了"。启动前一律清空命令文件。
: > /tmp/zmax_nav_cmd 2>/dev/null || true

cd "$GUI_DIR" || exit 1
# 只启动控制台本体: 不设任何自动开窗开关 (ZMAX_AUTO_RUN/ZMAX_AUTO_SS/ZMAX_AUTO_SS_RUN/ZMAX_AUTO_TEST
# 一律不导出) —— 双击图标 = 落到配置中心, 由老倪自己检查任务配置后点「🚀 启动工程 · 信号 · 场景」。
unset ZMAX_AUTO_RUN ZMAX_AUTO_SS ZMAX_AUTO_SS_RUN ZMAX_AUTO_SS_3D ZMAX_AUTO_TEST
exec nice -n 10 "$VENV_PY" studio.py >> "$LOG" 2>&1
