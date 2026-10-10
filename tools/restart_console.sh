#!/usr/bin/env bash
# 重启 Z-MAX 控制台 —— ⚠️ 2026-10-10 起本脚本只做**转发**: 一律走 tools/studio_ctl.sh。
#
# 为什么改: 旧版在这里自己扫 /proc 找控制台, 判据是 `readlink -f /proc/<pid>/exe` 匹配
#   "*/gui-venv311/bin/python*"。但 venv 的 python 是指向 uv 解释器的**软链**, readlink -f 会
#   解析到 /home/ubuntu/.local/share/uv/python/cpython-3.11.x/bin/python3.11 ⇒ 永远不匹配 ⇒
#   实测"控制台进程: 无"(其实 PID 1126080 活着), 于是新起一个 —— **同时跑两个控制台** (老倪投诉过的场景)。
#   而且它只停不起, 名字却叫 restart。studio_ctl.sh 是按 argv 精确匹配 + status/stop/start/restart 齐全,
#   已经是对的, 别再维护第二份逻辑。
#
# 用法: bash tools/restart_console.sh            # = studio_ctl.sh restart
#       bash tools/restart_console.sh status     # 透传任意子命令 (status|stop|start|restart)
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$REPO/tools/studio_ctl.sh" "${1:-restart}"
