#!/usr/bin/env bash
# 磁盘清理·零引用盘点 (只读): 输出 候选名/大小/引用数/引用文件(前2)
# 用法: bash /home/ubuntu/.hermes/cache/scratch/disk_ref_scan.sh <目标目录> [类型 d|f]
set -u
cd /home/ubuntu/zmax
BASE="${1:?用法: disk_ref_scan.sh <目录> [d|f]}"
KIND="${2:-d}"
SCAN="tools dds src config docs external/lerobot-smolvla-lew/tools external/lerobot-smolvla-lew/src external/lerobot-smolvla-lew/config /home/ubuntu/.hermes/scripts"
for p in "$BASE"/*; do
  [ -e "$p" ] || continue
  if [ "$KIND" = "d" ]; then [ -d "$p" ] || continue; else [ -f "$p" ] || continue; fi
  n=$(basename "$p")
  refs=$(grep -rl --exclude-dir=outputs --exclude-dir=.git \
        --include='*.py' --include='*.sh' --include='*.json' --include='*.yaml' --include='*.md' \
        "$n" $SCAN 2>/dev/null | grep -v "disk_cleanup" | head -3)
  cnt=$(echo "$refs" | grep -c . )
  sz=$(du -sh "$p" 2>/dev/null | cut -f1)
  if [ "$cnt" = "0" ]; then tag="🔴零引用"; else tag="  引用$cnt"; fi
  printf "  %-6s %s %-44s %s\n" "$sz" "$tag" "$n" "$(echo $refs | tr ' ' '\n' | xargs -n1 basename 2>/dev/null | tr '\n' ' ')"
done
