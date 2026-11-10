#!/usr/bin/env bash
# sync_to_jingjing.sh — 把待同步包推给小静静 (Windows 192.168.1.6)
# 用法: bash tools/sync_to_jingjing.sh [包路径]
set -euo pipefail
PKG="${1:-/home/ubuntu/zmax/zmax_data/peer_sync/docsys_20261111.zip}"
KEY="$HOME/.ssh/id_ed25519"
HOST="mike@192.168.1.6"
PY='C:\Users\Mike\zmax_console\app9\_internal\_pyenv\python.exe'

echo "① 探活 $HOST ..."
if ! ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=8 "$HOST" "echo alive" >/dev/null 2>&1; then
  echo "✗ 对端离线 (ping/ssh 不通) —— 等她上线再跑本脚本"
  exit 3
fi
echo "② 上传 $(basename "$PKG") ($(stat -c%s "$PKG") bytes)"
scp -i "$KEY" -o BatchMode=yes "$PKG" "$HOST:C:/Users/Mike/zmax_sync/pkg.zip" >/dev/null
echo "③ 解压到 zmax + app9 运行版"
ssh -i "$KEY" -o BatchMode=yes "$HOST" "$PY -c \"import zipfile;zipfile.ZipFile(r'C:\\Users\\Mike\\zmax_sync\\pkg.zip').extractall(r'C:\\Users\\Mike\\zmax');print('OK zmax')\""
echo "④ 校验 (手工确认 md5)"
echo "   本机: $(md5sum "$PKG" | cut -c1-12)"
echo "完成。app9 运行版需再拷 _internal\{src,tools} —— 见 skill windows-canvas-node-runtime"
