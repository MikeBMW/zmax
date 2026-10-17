#!/usr/bin/env bash
# ============================================================
# vscode_console_vnc.sh — 把控制台 (studio.py 的 PyQt 窗口) 送进 VSCode 编辑器区域用
#
# 原理: x11vnc 抓本机 X 桌面 (:0) → websockify 转成网页 → VSCode 内置 Simple Browser
#       打开 noVNC 页面 (编辑器标签页里就能看+点控制台)。
#       全程只监听 127.0.0.1, 不对外暴露。
#
# 幂等: 已经在跑就跳过; 结束时打印可用的 URL。
# 用法: bash tools/gui/vscode_console_vnc.sh [--status]
# ============================================================
set -u
DISPLAY_NUM="${ZMAX_VNC_DISPLAY:-:0}"
RFB_PORT="${ZMAX_VNC_PORT:-5900}"
WEB_PORT="${ZMAX_VNC_WEB_PORT:-6080}"
NOVNC_DIR="${ZMAX_NOVNC_DIR:-/usr/share/novnc}"
LOG=/tmp/zmax_console_vnc.log
XAUTH="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}"
[ -f "$XAUTH" ] || XAUTH="$(ls /run/user/"$(id -u)"/*/Xauthority 2>/dev/null | head -1)"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG" >&2; }
url() { echo "http://127.0.0.1:${WEB_PORT}/vnc.html?autoconnect=1&resize=scale&reconnect=1"; }

if [ "${1:-}" = "--status" ]; then
    ss -ltn 2>/dev/null | grep -q ":${RFB_PORT} " && echo "x11vnc  :${RFB_PORT} ✅" || echo "x11vnc  :${RFB_PORT} ❌"
    ss -ltn 2>/dev/null | grep -q ":${WEB_PORT} " && echo "websockify :${WEB_PORT} ✅" || echo "websockify :${WEB_PORT} ❌"
    echo "URL: $(url)"
    exit 0
fi

# ── 1. x11vnc (只本机, 无密码) ──
# ZMAX_VNC_CLIP=window 时只抓控制台窗口那一块 (画面大、看得清); 默认整个桌面。
CLIP_ARGS=""
if [ "${ZMAX_VNC_CLIP:-screen}" = "window" ]; then
    WIN="$(DISPLAY="${DISPLAY_NUM}" xdotool search --onlyvisible --name "XSpace ZMAX" 2>/dev/null | head -1)"
    if [ -n "${WIN:-}" ]; then
        eval "$(DISPLAY="${DISPLAY_NUM}" xdotool getwindowgeometry --shell "$WIN" 2>/dev/null)"
        if [ -n "${WIDTH:-}" ] && [ -n "${HEIGHT:-}" ]; then
            CLIP_ARGS="-clip ${WIDTH}x${HEIGHT}+${X}+${Y}"
            log "只抓控制台窗口 ${WIN}: ${WIDTH}x${HEIGHT}+${X}+${Y}"
        fi
    else
        log "没找到控制台窗口 ⇒ 退回整个桌面 (先启动控制台再起 VNC, 就能只抓窗口)"
    fi
fi

if [ "${1:-}" = "--restart" ]; then
    pgrep -x x11vnc >/dev/null && { log "--restart: 停掉旧 x11vnc"; pkill -x x11vnc; sleep 2; }
fi
if ss -ltn 2>/dev/null | grep -q ":${RFB_PORT} "; then
    log "x11vnc 已在 ${RFB_PORT}"
else
    log "起 x11vnc ${DISPLAY_NUM} → 127.0.0.1:${RFB_PORT} (auth=${XAUTH:-未指定}) ${CLIP_ARGS:+[$CLIP_ARGS]}"
    DISPLAY="${DISPLAY_NUM}" x11vnc -display "${DISPLAY_NUM}" ${XAUTH:+-auth "$XAUTH"} \
        ${CLIP_ARGS} \
        -nopw -forever -shared -localhost -rfbport "${RFB_PORT}" -o /tmp/x11vnc.log -bg >/dev/null 2>&1
    sleep 3
fi
if ! ss -ltn 2>/dev/null | grep -q ":${RFB_PORT} "; then
    log "❌ x11vnc 起不来 —— 看 /tmp/x11vnc.log (常见: XAUTHORITY 不对)"
    exit 1
fi
log "✅ x11vnc 在 127.0.0.1:${RFB_PORT}"

# ── 2. websockify (静态 noVNC 页 + ws↔VNC 转发, 只本机) ──
if ss -ltn 2>/dev/null | grep -q ":${WEB_PORT} "; then
    log "websockify 已在 ${WEB_PORT}"
else
    log "起 websockify ${WEB_PORT} → ${RFB_PORT} (web=${NOVNC_DIR})"
    setsid websockify --web="${NOVNC_DIR}" "127.0.0.1:${WEB_PORT}" "127.0.0.1:${RFB_PORT}" \
        >/tmp/websockify.log 2>&1 < /dev/null &
    sleep 3
fi
if ! ss -ltn 2>/dev/null | grep -q ":${WEB_PORT} "; then
    log "❌ websockify 起不来 —— 看 /tmp/websockify.log"
    exit 1
fi
# 只许本机监听 (安全): 若发现 0.0.0.0 就告警
if ss -ltn 2>/dev/null | grep -q "0.0.0.0:${WEB_PORT}"; then
    log "⚠️ websockify 监听了 0.0.0.0 (非仅本机) —— 请检查 --listen"
fi
log "✅ websockify 在 127.0.0.1:${WEB_PORT}"

# ── 3. 输出 URL (VSCode 内置 Simple Browser 打开它) ──
echo "$(url)"
