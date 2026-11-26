#!/usr/bin/env bash
# 把 Windows 侧（D:\ZMAX）的迭代改动回灌到 Ubuntu 的 ~/zmax
#
# 背景：这台机器是双系统（nvme0n1p3=C, nvme0n1p4=D, nvme0n1p5=Ubuntu /）。
#       切到 Windows 时 Ubuntu 不运行 ⇒ 不能靠 SSH 连回来，"渠道"就是共享的 D 盘。
#       老倪在 Windows 上改 D:\ZMAX 里的代码/配置，切回 Ubuntu 后跑这一条命令即可。
#
# 用法:
#   bash tools/sync_from_dzmax.sh            # 只对比，列出 Windows 侧改了什么（不动文件）
#   bash tools/sync_from_dzmax.sh --apply    # 真同步（Ubuntu 侧被覆盖，先自动备份）
#
# 安全:
#   · 默认 dry-run，只报告不落盘
#   · --apply 前先把被覆盖的 Ubuntu 文件备份到 zmax_data/sync_bak/<时间戳>/
#   · 只同步代码/配置白名单目录，绝不覆盖 data/ 数据库与 outputs/ 权重（避免 Windows 侧误改覆盖真源）
set -uo pipefail

SRC=/mnt/wD/ZMAX
DST=/home/ubuntu/zmax
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

if ! mountpoint -q /mnt/wD; then
  echo "── D 盘没挂载，先挂"
  sudo -n mkdir -p /mnt/wD
  sudo -n mount -o rw /dev/nvme0n1p4 /mnt/wD || { echo "❌ 挂载失败"; exit 1; }
fi
[ -d "$SRC" ] || { echo "❌ $SRC 不存在"; exit 1; }

# 只回灌这些（代码 / 配置 / 文档 / 流程）。data、outputs、models、zmax_data、external 不覆盖。
# 2026-11-26 v5.50.786: 加 server/ —— 标准服务归集目录（22 个服务脚本 + services.json +
#   arch_map.json + web/arch_map*.html）。不加的话 Windows 侧新建的服务目录永远同步不过去。
DIRS=(server tools src services flows defaults dds config docs)
EXCL=(--exclude "__pycache__" --exclude "*.pyc" --exclude ".venv" --exclude ".git")

echo "════ 1) Windows 侧相对 Ubuntu 的变化 (dry-run) ════"
CHANGED=0
LIST=/tmp/zmax_sync_from_dzmax.tsv
: > "$LIST"
for d in "${DIRS[@]}"; do
  [ -d "$SRC/$d" ] || continue
  [ -d "$DST/$d" ] || { echo "  [新目录] $d"; CHANGED=$((CHANGED+1)); continue; }
  rsync -an --itemize-changes "${EXCL[@]}" "$SRC/$d/" "$DST/$d/" 2>/dev/null \
    | grep -E '^[<>ch]' | sed "s|^|$d: |" >> "$LIST"
done

N=$(wc -l < "$LIST")
if [ "$N" -eq 0 ]; then
  echo "  ✅ 没有差异 —— Windows 侧没改代码/配置（或改了但已同步）"
  exit 0
fi
echo "  共 $N 处差异："
head -40 "$LIST"
[ "$N" -gt 40 ] && echo "  ... 还有 $((N-40)) 处，完整清单: $LIST"

if [ "$APPLY" -ne 1 ]; then
  echo
  echo "（只对比，未落盘。确认无误后执行: bash tools/sync_from_dzmax.sh --apply）"
  exit 0
fi

echo
echo "════ 2) 备份将被覆盖的 Ubuntu 文件 ════"
TS=$(date +%Y%m%d_%H%M%S)
BAK="$DST/zmax_data/sync_bak/$TS"
mkdir -p "$BAK"
while IFS= read -r line; do
  rel=$(echo "$line" | sed -E 's/^[a-z]+: [^ ]+ +//')
  case "$rel" in */) continue ;; esac
  [ -f "$DST/$rel" ] && { mkdir -p "$BAK/$(dirname "$rel")"; cp -a "$DST/$rel" "$BAK/$rel"; }
done < "$LIST"
echo "  备份目录: $BAK ($(find "$BAK" -type f | wc -l) 个文件)"

echo
echo "════ 3) 同步 ════"
for d in "${DIRS[@]}"; do
  [ -d "$SRC/$d" ] || continue
  rsync -a "${EXCL[@]}" "$SRC/$d/" "$DST/$d/" && echo "  ✔ $d"
done

echo
echo "════ 4) 结果 ════"
cd "$DST" && git status --short | head -20
echo "（以上是 Ubuntu 仓库里现在的改动，确认后正常 git add/commit 即可）"
