#!/usr/bin/env bash
# 桌面快捷方式安装/核验 — 真源入库, 一键把 ~/Desktop 与应用菜单恢复成正确内容
#
# 用法:
#   bash tools/desktop/install_launchers.sh          # 安装/修复 + 核验
#   bash tools/desktop/install_launchers.sh --check  # 只核验, 不改
#
# 为什么要有这个脚本(2026-10-08 事故): 家目录整合把仓库从 zmax_rel/ 收进 zmax/ 后,
#   ~/Desktop/XSpace-Studio.desktop 里 Exec 还写着 /home/ubuntu/zmax_rel/... (已不存在)
#   ⇒ 双击零反应(不报错、不弹窗)。快捷方式真源入库 + 这个脚本, 以后改路径不会再丢。
set -u
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK=0; [ "${1:-}" = "--check" ] && CHECK=1
DESK="$HOME/Desktop"
APPS="$HOME/.local/share/applications"
fail=0

# 显示会话 (DING 扩展要在这个会话里重启)
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -S "$XDG_RUNTIME_DIR/bus" ]; then
    export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
fi
for d in "${DISPLAY:-}" :0 :1; do
    [ -n "$d" ] || continue
    if DISPLAY="$d" xset q >/dev/null 2>&1; then export DISPLAY="$d"; break; fi
done

check_one() {   # $1 = desktop文件路径
    local f="$1" name exec_line icon t gt
    [ -f "$f" ] || { echo "  ❌ 不存在: $f"; fail=1; return; }
    name=$(grep -m1 '^Name=' "$f" | cut -d= -f2-)
    exec_line=$(grep -m1 '^Exec=' "$f" | cut -d= -f2- | awk '{print $1}')
    icon=$(grep -m1 '^Icon=' "$f" | cut -d= -f2-)
    t=ok
    [ -e "$exec_line" ] && [ -x "$exec_line" ] || { t="❌ Exec 目标不存在或不可执行"; fail=1; }
    case "$icon" in
        /*) [ -e "$icon" ] || { t="$t / ❌ Icon 不存在"; fail=1; } ;;
    esac
    gt=$(gio info "$f" 2>/dev/null | grep -c 'metadata::trusted: true')
    [ "$gt" -ge 1 ] || t="$t / ⚠️ 未信任(DING 会显示叉号)"
    printf "  %-42s Exec=%s [%s]\n" "$name → $(basename "$f")" "$exec_line" "$t"
}

echo "════ ① 核验当前位置的两个快捷方式 ════"
check_one "$DESK/Hermes.desktop"
check_one "$DESK/XSpace-Studio.desktop"
check_one "$APPS/XSpace-Studio.desktop"

if [ "$CHECK" = 1 ]; then
    echo "  (--check: 未改动)"; exit $fail
fi

echo "════ ② 按真源安装/修复 ════"
mkdir -p "$DESK" "$APPS"
install -m755 "$SRC_DIR/XSpace-Studio.desktop" "$DESK/XSpace-Studio.desktop"
install -m755 "$SRC_DIR/XSpace-Studio.desktop" "$APPS/XSpace-Studio.desktop"
install -m755 "$SRC_DIR/Hermes.desktop"        "$DESK/Hermes.desktop"
install -m755 "$SRC_DIR/Hermes.desktop"        "$APPS/Hermes.desktop"

echo "════ ③ 信任元数据 + 触发 DING 重载 ════"
for f in "$DESK/XSpace-Studio.desktop" "$DESK/Hermes.desktop" "$APPS/XSpace-Studio.desktop" "$APPS/Hermes.desktop"; do
    touch "$f"                                     # 触发 IN_MODIFY, 让扩展重读
    gio set "$f" metadata::trusted true 2>/dev/null && echo "  trusted → $(basename "$f")"
done
if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions disable ding@rastersoft.com >/dev/null 2>&1 && sleep 1 && \
    gnome-extensions enable ding@rastersoft.com >/dev/null 2>&1 && echo "  DING 扩展已重启" || \
    echo "  ⚠️ DING 重启失败(可能不在桌面会话) — 桌面图标若仍有叉号, 注销重登即可"
fi

echo "════ ④ 语法核验(desktop-file-validate) ════"
if command -v desktop-file-validate >/dev/null 2>&1; then
    for f in "$SRC_DIR"/*.desktop; do
        out=$(desktop-file-validate "$f" 2>&1) && echo "  ✅ $(basename "$f")" || { echo "  ❌ $(basename "$f"): $out"; fail=1; }
    done
else
    echo "  (desktop-file-validate 未安装, 跳过)"
fi

echo "════ ⑤ 安装后复验 ════"
check_one "$DESK/Hermes.desktop"
check_one "$DESK/XSpace-Studio.desktop"
check_one "$APPS/XSpace-Studio.desktop"
echo "  提示: 双击若无反应, 先看 /tmp/studio_launch.log (launch_studio.sh 的输出都写这里)"
exit $fail
