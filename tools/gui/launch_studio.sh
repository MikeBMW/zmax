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

# 本机 Xorg 显示 (桌面会话一般已设, 保障 :0)
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

# 🚀 2026-10-19 老倪: 「更改打开的首个界面 —— 第一眼应该是主控制台的界面; 之后用户可以单独打开
#   配置中心, 再从配置中心打开状态空间工程」 ⇒ 默认落点从 config 改成 home (主控制台)。
#   新实例: studio.py 按 ZMAX_BOOT_PAGE 启动后跳页 (home = 主控制台, 本来就是初始页 ⇒ 不跳);
#   已有实例: 写命令通道把它带回主控制台 (双击图标 = 回到第一眼那个界面, 不用记快捷键)。
#   要临时落到别的页: ZMAX_BOOT_PAGE=config tools/gui/launch_studio.sh
export ZMAX_BOOT_PAGE="${ZMAX_BOOT_PAGE:-home}"

# 已有实例在跑 → 激活已有窗口 + 弹到配置中心, 不重复启动
# 🔴 2026-10-15 加固: 原来用 `pgrep -f "[g]ui-venv311/bin/python studio.py"` —— 这是**子串匹配**,
#   任何 cmdline 里出现过这串字的进程(比如我自己在终端里跑 `pgrep -af 'gui-venv311/bin/python studio.py'`)
#   都会被当成"控制台已在跑" ⇒ 本脚本 exit 0 不干活 ⇒ **服务报启动成功但一个窗口都没有**(实测踩到)。
#   ⇒ 改成锚定整条 cmdline: 只有"就是那个解释器在跑 studio.py"才算实例。
STUDIO_RE='^[^ ]*gui-venv311/bin/python studio\.py$'
# 🔔 2026-10-16 老倪「第一次总是没反应」: studio.py 从进程起来到**主窗口 map 出来**要 ≈50s
#    (2026-10-19 提速后实测 3.1s: 只先建首页+配置中心, 其余页在窗口出来后按需/后台建)
#   (启动期预读配置唯一依据 + 自动加载 L2 YOLO 2.4s / L3 SmolVLA 18.5s · 1289MB / L4 INTACT 5.9s),
#   这段时间桌面**一点反馈都没有** ⇒ 人会以为没点到、再双击一次。这里补两条可见反馈:
#   · 新实例: 立刻弹一条"正在启动"通知 (告诉他大概要等多久, 别急着再点)
#   · 已有实例但窗口还没出来: 也弹一条 —— 原来这里是静默 exit 0, 正是"第二次点了也没反应"的由来
_notify() {   # $1=标题 $2=正文
    command -v notify-send >/dev/null 2>&1 || return 0
    notify-send -a "XSpace Studio" -i "$GUI_DIR/logo.png" -- "$1" "$2" >/dev/null 2>&1 || true
}
if pgrep -f "$STUDIO_RE" >/dev/null 2>&1; then
    printf '%s\n' "$ZMAX_BOOT_PAGE" > /tmp/zmax_nav_cmd 2>/dev/null || true
    WIN=$(DISPLAY="$DISPLAY" xdotool search --onlyvisible --name "XSpace ZMAX" 2>/dev/null | head -1)
    if [ -n "$WIN" ]; then
        DISPLAY="$DISPLAY" xdotool windowactivate "$WIN" 2>/dev/null
    else
        # 进程在、窗口还没 map ⇒ 正在启动中 (不是没反应)
        _notify "控制台正在启动中" "进程已在运行, 主窗口还没出来 (常规 3~5 秒)。请勿重复双击。"
    fi
    exit 0
fi

# 🔴 2026-10-12 老倪: 「点开启动图标后, 3D场景不要自动启动, 我要先检查任务配置, 然后启动工程」
#   真根因候选: /tmp/zmax_nav_cmd 里若残留上一轮(`open_all`/`ss_3d`)的命令, **新进程**的去重表是空的
#   ⇒ 界面一建好就执行旧命令 ⇒ 老倪看到"3D 自己开起来了"。启动前一律清空命令文件。
: > /tmp/zmax_nav_cmd 2>/dev/null || true

cd "$GUI_DIR" || exit 1
# 🔔 新实例: 先给一条可见反馈再 exec (窗口 ≈50s 后才出来, 这段空窗期正是"第一次没反应"的由来)
_notify "XSpace Studio 正在启动" "主窗口约 3 秒出现 (先出首页+配置中心, 其余页面随后在后台建好)。请勿重复双击。"
# 只启动控制台本体: 不设任何自动开窗开关 (ZMAX_AUTO_RUN/ZMAX_AUTO_SS/ZMAX_AUTO_SS_RUN/ZMAX_AUTO_TEST
# 一律不导出) —— 双击图标 = 落到配置中心, 由老倪自己检查任务配置后点「🚀 启动工程 · 信号 · 场景」。
unset ZMAX_AUTO_RUN ZMAX_AUTO_SS ZMAX_AUTO_SS_RUN ZMAX_AUTO_SS_3D ZMAX_AUTO_TEST
# 📚 2026-10-17 老倪: 「Trace 的 signal 与信号分析的 signal 都要来自统一的数据库」
#   统一信号库守护: 把本机真值文件并成 zmax_data/dataspace/signals.db (2Hz, 单实例自锁)。
#   控制台起之前先确保它在跑 —— 否则两个窗口会回落到"各自读文件"(虽有告警, 但就不算同库了)。
if ! pgrep -f "signal_store_daemon.py" >/dev/null 2>&1; then
    nohup "$VENV_PY" "$REPO_ROOT/tools/signal_store_daemon.py" --hz 2 \
        >> "$REPO_ROOT/zmax_data/dataspace/signal_store.log" 2>&1 &
    echo "📚 统一信号库已启动 (signals.db · 2Hz)"
fi

# 🔀 2026-10-28 老倪: 「画布打开, 数据源不是 AR场景, 刚才我已经改了啊」
#   根因: 控制台启动时把当时的 src_state 读进内存, 之后文件被守护改对了 → 界面还是旧值。
#   ⇒ 启动前先把数据源对齐 (守护只认 ar_scene 有效 ⇒ AR场景; 用户关了 AR 就不碰)
if [ -x "$REPO_ROOT/tools/ensure_ar_source.py" ] || [ -f "$REPO_ROOT/tools/ensure_ar_source.py" ]; then
    "$VENV_PY" "$REPO_ROOT/tools/ensure_ar_source.py" >> "$LOG" 2>&1 || true
fi

exec nice -n 10 "$VENV_PY" studio.py >> "$LOG" 2>&1
