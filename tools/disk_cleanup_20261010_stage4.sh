#!/usr/bin/env bash
# 磁盘清理 阶段 4 (2026-10-10 续): 按日期轮转的历史流数据 + 可再生缓存
# 判据: 只删**按日期命名且非当天**的历史文件; 不动目录结构, 不动最新一天; 删前打印清单。
set -u
DRY=${DRY:-0}
ROOT=/home/ubuntu/zmax
rm_sz() { du -sh "$1" 2>/dev/null | cut -f1; }
total=0
note() { echo "  $*"; }

echo "── 4a. ss_live 历史状态流 (按日命名, 只留最近 2 天) ──"
KEEP1=$(date -d "4 days ago" +%Y%m%d); KEEP2=$(date +%Y%m%d)   # 保留最近 5 天(含当天)的状态流
note "保留: >= $KEEP1 (最近 5 天) 的状态流文件"
for f in "$ROOT"/zmax_data/ss_live/*.jsonl "$ROOT"/zmax_data/ss_live/*.jsonl.[0-9]*; do
  [ -f "$f" ] || continue
  b=$(basename "$f"); d=$(echo "$b" | grep -oE '[0-9]{8}' | head -1)
  [ -z "$d" ] && { note "跳过(无日期) $b"; continue; }
  [ "$d" -ge "$KEEP1" ] && continue
  sz=$(rm_sz "$f"); note "[$sz] $b  (日期 $d < $KEEP1 → 历史)"
  [ "$DRY" = "1" ] || rm -f "$f"
done

echo
echo "── 4b. snap 下载缓存 (可再生成) ──"
sz=$(rm_sz /var/lib/snapd/cache); note "cache ${sz} / seed"
[ "$DRY" = "1" ] || { sudo rm -rf /var/lib/snapd/cache/* 2>/dev/null; sudo rm -rf /var/lib/snapd/cache/.??* 2>/dev/null; }

echo
echo "── 4c. L5 视觉安全事件图 (只留最近 3 天; 09-29~10-07 的已属历史) ──"
EVT="$ROOT/zmax_data/vl_safety_fast_evt"
K3=$(date -d "3 days ago" +%Y%m%d)
if [ "$DRY" = "1" ]; then
  note "[dry] 删除日期 < $K3 的事件图: $(ls "$EVT" 2>/dev/null | cut -c1-8 | awk -v k="$K3" '$1 < k' | wc -l) 张"
else
  n=0
  for f in "$EVT"/*.jpg; do
    [ -f "$f" ] || continue
    b=$(basename "$f"); d=${b:0:8}
    case "$d" in ''|*[!0-9]*) continue;; esac
    if [ "$d" -lt "$K3" ]; then rm -f "$f"; n=$((n+1)); fi
  done
  note "删除 $n 张历史事件图 (保留 $K3 起)"
fi

echo
echo "── 4d. HF 重复缓存 (~/.cache 里的副本; 训练真源是 zmax_data/hf_cache) ──"
for d in /home/ubuntu/.cache/huggingface/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct; do
  [ -d "$d" ] || continue
  same=$( [ -d "$ROOT/zmax_data/hf_cache/hub/$(basename "$d")" ] && echo yes || echo no )
  sz=$(rm_sz "$d"); note "$(basename "$d") $sz · 训练缓存里有同名副本=$same"
  [ "$same" = "yes" ] && { [ "$DRY" = "1" ] || rm -rf "$d"; note "  → 删副本"; }
done

echo
echo "── 4e. 旧采集/记录 (按日期命名, >7 天) ──"
for f in "$ROOT"/zmax_data/real_tap_20260921/state_20260921.jsonl \
         "$ROOT"/zmax_data/rokae_sdk/tcp_out/tcp_direct_20261001.jsonl; do
  [ -f "$f" ] || continue
  sz=$(rm_sz "$f"); note "[$sz] $(basename "$f")"
  [ "$DRY" = "1" ] || rm -f "$f"
done

echo
echo "── 4f. reports 老产物目录 (保留最近 7 天 + 所有 *.json 摘要) ──"
if [ "$DRY" = "1" ]; then
  find "$ROOT/reports" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec du -sh {} + 2>/dev/null | sort -hr | head -8
else
  find "$ROOT/reports" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} + 2>/dev/null
  note "已清 reports 下 mtime>7 天的产物目录"
fi

echo
echo "════════════════════════════════════"
df -h / | tail -1
echo "════════════════════════════════════"
