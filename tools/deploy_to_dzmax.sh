#!/usr/bin/env bash
# 把 v5.50.785 的 Windows onedir 免解包版部署到 D:\ZMAX（从 Linux 主节点直接写 NTFS）
# 用法: bash tools/deploy_to_dzmax.sh <zip_url 或 本地zip路径>
set -euo pipefail
ZIP_SRC="${1:?用法: deploy_to_dzmax.sh <zip_url|zip_path>}"
DST=/mnt/wD/ZMAX
TMP=$(mktemp -d /tmp/zmax_dep.XXXX)
trap 'rm -rf "$TMP"' EXIT

echo "── 1) 挂载 D 盘 (nvme0n1p4)"
if ! mountpoint -q /mnt/wD; then
  sudo -n mkdir -p /mnt/wD
  sudo -n mount -o rw /dev/nvme0n1p4 /mnt/wD
fi
df -h /mnt/wD | tail -1

echo "── 2) 取包"
case "$ZIP_SRC" in
  http*) curl -fL --retry 3 -o "$TMP/pkg.zip" "$ZIP_SRC" ;;
  *)     cp "$ZIP_SRC" "$TMP/pkg.zip" ;;
esac
ls -lh "$TMP/pkg.zip"

echo "── 3) 解压"
unzip -q -o "$TMP/pkg.zip" -d "$TMP/x"
# zip 内可能是 顶层目录/Z-MAX_Console.exe，也可能是根目录直出 —— 两种都认
_EXE=$(find "$TMP/x" -maxdepth 3 -name "Z-MAX_Console.exe" | head -1)
if [ -z "$_EXE" ]; then echo "❌ 包里没找到 Z-MAX_Console.exe"; find "$TMP/x" -maxdepth 2 | head -20; exit 1; fi
_SRC_DIR=$(dirname "$_EXE")
echo "包内程序目录: $_SRC_DIR"

echo "── 4) 落地到 $DST (只覆盖程序文件, 不动 config/data/models)"
cp -rf "$_SRC_DIR"/. "$DST"/
ls -lh "$DST/Z-MAX_Console.exe"
du -sh "$DST/_internal" 2>/dev/null || echo "⚠ 没有 _internal 目录 (可能是 onefile 版)"

echo "── 5) 版本戳"
printf "v5.50.785  commit=0d466fdf  deployed=%s\n" "$(date '+%F %T')" | sudo -n tee "$DST/VERSION.txt" >/dev/null
cat "$DST/VERSION.txt"

echo "── 6) 校验 (不许少文件)"
printf "config 文件数: %s (期望 1223)\n" "$(find "$DST/config" -type f | wc -l)"
printf "data   文件数: %s (期望 94478)\n" "$(find "$DST/data" -type f | wc -l)"
printf "models 文件数: %s (期望 49)\n"    "$(find "$DST/models" -type f | wc -l)"
printf "src    文件数: %s (期望 2205)\n"  "$(find "$DST/src" -type f | wc -l)"
printf "docs   文件数: %s (期望 4484)\n"  "$(find "$DST/docs" -type f | wc -l)"
echo "── 完成: 双击 $DST/启动控制台.bat 即可"
