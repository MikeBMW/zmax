#!/bin/bash
# 分段并发下载 XPU torch wheel
# 为什么: download.pytorch.org 的 CDN 边缘缓存不一致 —— 前段 6.6MB/s, 后段 574B/s。
#         分段独立连接后, 有缓存的段先到, 慢段重试, 整体快得多。
set -u
URL="https://download.pytorch.org/whl/xpu/torch-2.7.1%2Bxpu-cp312-cp312-linux_x86_64.whl"
TOTAL=709343044
N=16
DIR=/tmp/xpu_parts
mkdir -p "$DIR"
SEG=$(( (TOTAL + N - 1) / N ))

echo "总大小 $((TOTAL/1048576))MB, 分 $N 段, 每段 $((SEG/1048576))MB"

fetch_seg() {
  local i=$1
  local st=$((i*SEG))
  local en=$((st+SEG-1))
  [ $en -ge $TOTAL ] && en=$((TOTAL-1))
  local f="$DIR/part_$(printf %02d $i)"
  local want=$((en-st+1))
  for try in 1 2 3 4 5 6; do
    local have=0
    [ -f "$f" ] && have=$(stat -c%s "$f")
    [ "$have" -ge "$want" ] && return 0
    curl -sL --max-time 600 -r ${st}-${en} -o "$f" "$URL" 2>/dev/null
    have=$(stat -c%s "$f" 2>/dev/null || echo 0)
    [ "$have" -ge "$want" ] && return 0
    sleep 2
  done
  return 1
}

for i in $(seq 0 $((N-1))); do
  fetch_seg $i &
done
wait

# 校验并合并
OK=1
for i in $(seq 0 $((N-1))); do
  st=$((i*SEG)); en=$((st+SEG-1)); [ $en -ge $TOTAL ] && en=$((TOTAL-1))
  want=$((en-st+1))
  have=$(stat -c%s "$DIR/part_$(printf %02d $i)" 2>/dev/null || echo 0)
  [ "$have" -lt "$want" ] && echo "  段 $i 不完整: $have/$want" && OK=0
done

if [ $OK -eq 1 ]; then
  cat "$DIR"/part_* > "$DIR/torch-2.7.1+xpu-cp312-cp312-linux_x86_64.whl"
  SZ=$(stat -c%s "$DIR/torch-2.7.1+xpu-cp312-cp312-linux_x86_64.whl")
  echo "合并完成: $((SZ/1048576))MB (期望 $((TOTAL/1048576))MB)"
  [ "$SZ" -eq "$TOTAL" ] && echo "✅ 大小一致" && mv "$DIR/torch-2.7.1+xpu-cp312-cp312-linux_x86_64.whl" /tmp/xpu_whl/ && echo "✅ 已移到 /tmp/xpu_whl/" || echo "❌ 大小不符"
else
  echo "❌ 有段未完成, 重跑本脚本会续传"
fi
