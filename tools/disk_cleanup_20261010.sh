#!/usr/bin/env bash
# 磁盘清理 (2026-10-10 老倪: 「磁盘空间紧张，清理历史垃圾，回到安全线以下」)
# 口径来自 disk-redline-guard 技能:
#   · 追加型日志只能 truncate 不能 rm (服务持着 fd, 删了它继续往悬空 inode 写)
#   · 删训练 run 前已用 tools/disk_cleanup_audit.py 逐个 grep 活引用 (在役链/被 tools 引用的整目录不删)
#   · 写台账 (含大小/原因), 删完复核保护区仍在
set -u
LEDGER=/home/ubuntu/zmax/reports/disk_cleanup_20261010_ledger.json
TRAIN=/home/ubuntu/zmax/external/lerobot-smolvla-lew/outputs/train
ROOT=/home/ubuntu/zmax
DRY=${DRY:-0}
freed_log=()

log() { echo "  $*"; }
# 记一笔台账
rec() { freed_log+=("{\"path\":\"$1\",\"what\":\"$2\",\"size\":\"$3\",\"why\":\"$4\"}"); }

before=$(df --output=used -BG / | tail -1 | tr -dc '0-9')

if [ "$DRY" = "1" ]; then echo "=== DRY RUN (不删任何东西) ==="; fi

echo "── 阶段 1: 日志 / 缓存 / 转储 (零风险, 可再生) ──"
# 1a. 追加型日志 → truncate
for f in /var/log/syslog /var/log/syslog.1 /var/log/zmax-dds-agg.log /var/log/zmax-dds-pub.log \
         /var/log/zmax-dds-ss.log /var/log/auth.log.1 /var/log/zmax-traj-pub.log /var/log/zmax-tunnel.log; do
  [ -f "$f" ] || continue
  sz=$(sudo du -h "$f" | cut -f1)
  if [ "$DRY" = "1" ]; then log "[dry] truncate $f ($sz)"; else
    sudo truncate -s 0 "$f" && { log "truncate $f ($sz)"; rec "$f" "追加型日志截断" "$sz" "服务持 fd, 只能截断; 可再生"; }
  fi
done
# 1b. 缓存目录 (可再生)
# ⛔ 2026-10-10 事故: ~/.local/share/uv 下**同时住着 uv 装的 Python 解释器**(python/cpython-3.11.15…),
#   而本机 5 个 venv (gui-venv311/lerobot/gs/dds/cuda-nvcc) 的 bin/python 全是软链指过去 —— 整目录清空
#   = 5 个 venv 当场全废 (控制台起不来, 训练跑不了)。**只能清 ~/.local/share/uv/{cache,archives}**。
for d in /home/ubuntu/.cache/pip /home/ubuntu/.cache/uv \
         /home/ubuntu/.local/share/uv/cache /home/ubuntu/.local/share/uv/archives \
         /home/ubuntu/.cache/torch_extensions /home/ubuntu/.local/share/mamba \
         /home/ubuntu/.cache/LarkShell /home/ubuntu/.config/LarkShell; do
  [ -d "$d" ] || continue
  sz=$(du -sh "$d" 2>/dev/null | cut -f1)
  if [ "$DRY" = "1" ]; then log "[dry] clear $d ($sz)"; else
    du -sh "$d" >/dev/null 2>&1
    rm -rf "${d:?}"/* 2>/dev/null && { log "清空 $d ($sz)"; rec "$d" "可再生缓存" "$sz" "包/客户端缓存, 需要时自动重建"; }
  fi
done
# 1c. 崩溃转储 / journal / apt
if [ "$DRY" != "1" ]; then
  sudo rm -rf /var/crash/* 2>/dev/null; log "清空 /var/crash"
  sudo journalctl --vacuum-size=200M >/dev/null 2>&1 && log "journal 压到 200M"
  sudo apt-get clean >/dev/null 2>&1 && log "apt clean"
  sudo rm -rf /var/lib/snapd/cache/* 2>/dev/null; log "清 snap 下载缓存"
fi
# 1d. 已安装的安装包 (zip/deb) —— 老倪规矩: 安装包不进仓库/不常驻本机
for f in /home/ubuntu/Downloads/vector-autosar-viewer-1-8-10.zip /home/ubuntu/Downloads/x.deb; do
  [ -f "$f" ] || continue
  sz=$(du -h "$f" | cut -f1)
  if [ "$DRY" = "1" ]; then log "[dry] rm $f ($sz)"; else rm -f "$f" && { log "删安装包 $f ($sz)"; rec "$f" "已安装的安装包" "$sz" "下载件, 可重下"; }; fi
done
# 1e. hermes 缓存 (保留 scratch)
sz=$(du -sh /home/ubuntu/.hermes/cache 2>/dev/null | cut -f1)
if [ "$DRY" = "1" ]; then log "[dry] 清 .hermes/cache/* (保留 scratch) ($sz)"; else
  find /home/ubuntu/.hermes/cache -mindepth 1 -maxdepth 1 ! -name scratch -exec rm -rf {} + 2>/dev/null
  log "清 .hermes/cache ($sz 中除 scratch)"; rec "/home/ubuntu/.hermes/cache" "agent 缓存" "$sz" "可再生成"
fi
# 1f. snap 旧修订
if [ "$DRY" != "1" ]; then
  snap list --all 2>/dev/null | awk '/disabled/{print $1, $3}' | while read -r n r; do
    sudo snap remove "$n" --revision="$r" >/dev/null 2>&1 && log "删 snap 旧修订 $n rev$r"
  done
fi

echo
echo "── 阶段 2: 被取代的训练 run (已逐个 grep 过活引用, 保护区不删) ──"
RUNS=(
  smolvla_lew_lora_200_ownlora smolvla_lew_lora_200_r5 smolvla_lew_lora_200_r7
  smolvla_lew_lora_30_r2 smolvla_lew_lora_30_r3 smolvla_lew_lora_3_r3
  smolvla_lew_lora_40_l5261007_182553 smolvla_lew_lora_40_l5261007_200232
  smolvla_lew_lora_40_l5261008_200833 smolvla_lew_lora_40_l5261009_073129
  smolvla_lew_lora_40_l5261009_222811 smolvla_lew_lora_500
  state_space_20260825_052855 state_space_20260825_060122 state_space_20260825_061409
  state_space_20260904_232841 state_space_20260904_233120 state_space_20260904_233213
  state_space_20260904_233501 state_space_mw2 state_space_mw3 state_space_mw4
  state_space_mw4probe state_space_mw4w
)
for r in "${RUNS[@]}"; do
  d="$TRAIN/$r"
  [ -d "$d" ] || { log "跳过(不存在) $r"; continue; }
  sz=$(du -sh "$d" | cut -f1)
  # 兜底: 删前再 grep 一次活引用 (排除审计脚本自身与 outputs/reports 记录)
  # ⚠️ 必须排除"本脚本自己" —— RUNS 数组里写着这些名字, 会自我匹配导致全部误判为活引用
  #   (与 pgrep -f "studio.py" 把本 shell 杀了是同一类自匹配坑)
  hits=$(grep -rl "$r" "$ROOT/tools" "$ROOT/src" "$ROOT/config" /home/ubuntu/.hermes/scripts 2>/dev/null \
         | grep -v disk_cleanup | grep -v "/outputs/" | grep -v "/reports/" | head -3)
  if [ -n "$hits" ]; then log "🔒 跳过(活引用): $r ← $(echo "$hits" | head -1)"; continue; fi
  if [ "$DRY" = "1" ]; then log "[dry] rm -rf $r ($sz)"; else
    rm -rf "$d" && { log "删 $r ($sz)"; rec "$d" "被取代的训练 run" "$sz" "同族留最新; 无活引用; 可由 joint_train_all.py 重训"; }
  fi
done

echo
echo "── 阶段 3: 零引用原料 (已确认无 glob/变量引用) ──"
for d in "$ROOT/zmax_data/raw_parts"; do
  [ -d "$d" ] || { log "跳过(不存在) $d"; continue; }
  sz=$(du -sh "$d" | cut -f1)
  hits=$(grep -rl "raw_parts" "$ROOT/tools" "$ROOT/src" "$ROOT/config" /home/ubuntu/.hermes/scripts 2>/dev/null | grep -v disk_cleanup | head -3)
  if [ -n "$hits" ]; then log "🔒 跳过(活引用): $d"; continue; fi
  if [ "$DRY" = "1" ]; then log "[dry] rm -rf $d ($sz)"; else
    rm -rf "$d" && { log "删 $d ($sz)"; rec "$d" "零引用原料" "$sz" "无任何脚本/glob 引用"; }
  fi
done

after=$(df --output=used -BG / | tail -1 | tr -dc '0-9')
echo
echo "════════════════════════════════════"
echo "根分区 used: ${before}G → ${after}G   (释放 $((before - after))G)"
df -h / | tail -1
echo "════════════════════════════════════"
if [ "$DRY" != "1" ]; then
  {
    echo "{"
    echo "  \"ts\": \"$(date -Is)\","
    echo "  \"trigger\": \"老倪: 磁盘空间紧张，清理历史垃圾，回到安全线以下\","
    echo "  \"before_used_gb\": $before, \"after_used_gb\": $after, \"freed_gb\": $((before - after)),"
    echo "  \"items\": ["
    ( IFS=,; echo "${freed_log[*]}" )
    echo "  ]"
    echo "}"
  } > "$LEDGER"
  echo "台账: $LEDGER"
fi
