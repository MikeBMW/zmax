#!/usr/bin/env bash
# feishu_send.sh — feishu_send.py 的薄包装, 任意目录可调
# 用法:  ./feishu_send.sh "文本"
#        ./feishu_send.sh --image /path/pic.png --text "说明"
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/feishu_send.py" "$@"
