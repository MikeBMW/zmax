#!/bin/bash
# disk_redline_20261015.sh —— 把系统盘打回 300G 红线以下 (老倪 2026-10-15 指令)
# 用法: bash disk_redline_20261015.sh [--dry-run]
# 纪律: (1) 先列清单; (2) 保护区白名单逐个否决; (3) 删完回采; (4) 记账
set -u
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
Z=/home/ubuntu/zmax
LEW=$Z/external/lerobot-smolvla-lew
LOG=/home/ubuntu/zmax/zmax_data/backups/disk_cleanup_20261015.log
LEDGER=/home/ubuntu/zmax/zmax_data/backups/DISK_LEDGER.md
FREED=0

say(){ echo "[$(date '+%H:%M:%S')] $*"; }

# ---------- 保护区 (逐个点名, 一条都不许删) ----------
PROTECT=(
  "stable-wm-cache/datasets/cube_single_expert.h5"        # INTACT 论文复现 config/train/data/ogb.yaml 在用
  "stable-wm-cache/datasets/l5_gen_1010_big.h5"           # 10-13 清理保护区
  "stable-wm-cache/datasets/l5_gen_v6.h5"                 # backbone_cont_runner.sh 在用
  "stable-wm-cache/datasets/l5_gen_v5.h5"                 # train_cog_event_head.py 在用
  "stable-wm-cache/datasets/l5_train.h5"                  # 同上
  "stable-wm-cache/datasets/optical_insert_v5_disturb.h5" # studio.py 在用
  "stable-wm-cache/datasets/optical_insert_v6_disturb.h5" # joint_train_full.py 在用
  "stable-wm-cache/datasets/v6_train_rand.h5"             # backbone_cont_runner.sh 在用
  "stable-wm-cache/datasets/v6_sub25k.h5"                 # stage_moe_backbone.py 在用
  "stable-wm-cache/datasets/v6_holdout_rand.h5"           # 阶段MOE 判据在用
  "stable-wm-cache/datasets/l5_v6_sub10k.h5"
  "stable-wm-cache/checkpoints"
  "stable-wm-cache/models"
  "models/"                                               # 全部在役模型
  "zmax_data/models"
  "zmax_data/gs_assets" "zmax_data/gs_scan"               # 建图链
  "zmax_data/vl_safety" "zmax_data/vl_safety_fast_evt"
  "zmax_data/sim2real_dr"
  "zmax_data/backups"                                     # 备份件只列不删
  "zmax_data/hf_cache"                                    # 权重缓存(在役)
  "external/lerobot-smolvla-lew/outputs/train/smolvla_lew_d1"           # 技能点名的 v10 台阶留证
  "external/lerobot-smolvla-lew/outputs/train/smolvla_lew_lora_40_l5261013_124042"  # 10-13 保护区
)
protected(){ local p; for p in "${PROTECT[@]}"; do case "$1" in *"$p"*) return 0;; esac; done; return 1; }

rm_one(){ # $1=绝对路径
  if protected "$1"; then say "  跳过(保护区): ${1#/home/ubuntu/}"; return; fi
  case "$1" in *cube_single_expert*|*checkpoints*|*/models|*/models/*) say "  跳过(硬闸): $1"; return;; esac
  local mb; mb=$(sudo du -sm "$1" 2>/dev/null | awk '{print $1}')
  printf '%s\t%s MB\t%s\n' "$(date '+%F %T')" "${mb:-?}" "$1" | sudo tee -a "$LOG" >/dev/null 2>&1
  if [ "$DRY" = 1 ]; then say "  [dry] 删 ${1#/home/ubuntu/}  (${mb:-?} MB)"; FREED=$((FREED+${mb:-0})); return; fi
  sudo rm -rf -- "$1" && { say "  ✔ 删 ${1#/home/ubuntu/} (${mb:-?} MB)"; FREED=$((FREED+${mb:-0})); }
}

say "===== 开始 (DRY=$DRY) ====="
before=$(df -B1 / | awk 'NR==2{print $3}')
say "删除前已用: $(python3 -c "print(f'{$before/2**30:.1f}G')")"

# --- 1. 零活引用的被取代训练 run (逐个点名, 非通配) ---
say "--- 1. 被取代/无活引用的训练 run ---"
for n in smolvla_lew_lora_40_l5261013_201828 \
         smolvla_lew_lora_40_r2 smolvla_lew_lora_40_r3 smolvla_lew_lora_40_r4 \
         smolvla_lew_lora_40_r5 smolvla_lew_lora_40_r6 smolvla_lew_lora_40_r7 \
         smolvla_lew_lora_40_l5261014_210701 \
         smolvla_lew_lora_30 smolvla_lew_lora_30_r2 smolvla_lew_lora_30_r4 \
         smolvla_lew_lora_20_r2 smolvla_lew_lora_20_r3 smolvla_lew_lora_20_r4 \
         smolvla_lew_lora_20_r5 smolvla_lew_lora_20_r6 smolvla_lew_lora_20_r7 \
         smolvla_lew_lora_20_r8 \
         smolvla_lew_lora_200_r2 smolvla_lew_lora_200_r2_merged ; do
  [ -d "$LEW/outputs/train/$n" ] && rm_one "$LEW/outputs/train/$n"
done

# --- 2. git 垃圾 (tmp_pack 恒为垃圾) ---
say "--- 2. git 垃圾 ---"
if [ "$DRY" = 1 ]; then
  say "  [dry] tmp_pack_* 共 $(find "$LEW/.git/objects/pack" -name 'tmp_pack_*' 2>/dev/null | wc -l) 个, ~2.3G"
  FREED=$((FREED+2355))
else
  if [ -d "$LEW/.git" ]; then
    n=$(find "$LEW/.git/objects/pack" -name 'tmp_pack_*' 2>/dev/null | wc -l)
    find "$LEW/.git/objects/pack" -name 'tmp_pack_*' -delete 2>/dev/null
    g1=$(du -sm "$LEW/.git" | awk '{print $1}')
    ( cd "$LEW" && git gc --prune=now --quiet 2>/dev/null )
    g2=$(du -sm "$LEW/.git" | awk '{print $1}')
    say "  ✔ 清 $n 个 tmp_pack + gc: .git ${g1}M → ${g2}M"
    FREED=$((FREED+g1-g2))
  fi
fi

# --- 3. 日志/缓存 (可再生) ---
say "--- 3. 系统日志与包缓存 ---"
if [ "$DRY" = 1 ]; then say "  [dry] journal vacuum + /var/log 轮转 + apt clean (~1.5G)"; FREED=$((FREED+1500)); else
  b=$(df -B1 / | awk 'NR==2{print $3}')
  sudo journalctl --rotate >/dev/null 2>&1; sudo journalctl --vacuum-size=200M >/dev/null 2>&1
  sudo find /var/log -type f \( -name '*.log' -o -name '*.log.1' -o -name '*.gz' -o -name '*.old' \) -size +20M -delete 2>/dev/null
  sudo rm -rf /var/crash/* 2>/dev/null; sudo apt-get clean >/dev/null 2>&1
  du -sh /home/ubuntu/.cache/pip /home/ubuntu/.cache/uv 2>/dev/null
  a=$(df -B1 / | awk 'NR==2{print $3}')
  say "  ✔ 日志/缓存回收 $(( (b-a)/1048576 )) MB"; FREED=$((FREED+(b-a)/1048576))
fi

# --- 4. ss_live 按天轮转 (留最近 4 天) ---
say "--- 4. ss_live 轮转 (留最近 4 天) ---"
if [ -d "$Z/zmax_data/ss_live" ]; then
  keep=$(ls "$Z/zmax_data/ss_live"/state_*.jsonl 2>/dev/null | sort | tail -4)
  for f in "$Z"/zmax_data/ss_live/state_*.jsonl; do
    [ -e "$f" ] || continue
    printf '%s\n' "$keep" | grep -qx "$f" && continue
    rm_one "$f"
  done
fi

if [ "$DRY" = 1 ]; then
  say "===== DRY 合计可回收 ≈ $((FREED/1024))G ====="
  exit 0
fi

# --- 5. __pycache__ (可再生, 全盘 zmax 树) ---
say "--- 5. __pycache__ ---"
if [ "$DRY" = 1 ]; then
  mb=$(find "$Z" -name __pycache__ -type d -exec du -sm {} + 2>/dev/null | awk '{s+=$1} END {print s+0}')
  say "  [dry] __pycache__ 回收 ${mb} MB"; FREED=$((FREED+mb))
else
  b=$(df -B1 / | awk 'NR==2{print $3}')
  find "$Z" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
  a=$(df -B1 / | awk 'NR==2{print $3}')
  say "  ✔ __pycache__ 回收 $(( (b-a)/1048576 )) MB"; FREED=$((FREED+(b-a)/1048576))
fi

# --- 6. 老日志 (rokae tap / vl_safety 事件, 留 3 天) ---
say "--- 6. 老日志轮转 (3 天) ---"
if [ "$DRY" = 1 ]; then say "  [dry] rokae_sdk/logs + vl_safety_fast_evt (3天外)"; FREED=$((FREED+800)); else
  b=$(df -B1 / | awk 'NR==2{print $3}')
  find "$Z/zmax_data/rokae_sdk/logs" -type f -mtime +3 -delete 2>/dev/null
  find "$Z"/zmax_data/vl_safety_fast_evt -type f -mtime +3 -delete 2>/dev/null
  find "$Z/zmax_data/rokae_sdk/tcp_out" -name '*.jsonl' -mtime +3 -delete 2>/dev/null
  a=$(df -B1 / | awk 'NR==2{print $3}')
  say "  ✔ 老日志回收 $(( (b-a)/1048576 )) MB"; FREED=$((FREED+(b-a)/1048576))
fi

# --- 7. Hermes state.db 压实 (会话库, 非破坏) ---
say "--- 7. state.db VACUUM ---"
if [ "$DRY" = 1 ]; then say "  [dry] VACUUM ~0.5G"; FREED=$((FREED+500)); else
  b=$(df -B1 / | awk 'NR==2{print $3}')
  python3 - <<'PY' 2>/dev/null
import sqlite3
c = sqlite3.connect('/home/ubuntu/.hermes/state.db', timeout=30)
c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
c.execute('VACUUM')
c.close()
PY
  a=$(df -B1 / | awk 'NR==2{print $3}')
  say "  ✔ state.db 压实回收 $(( (b-a)/1048576 )) MB"; FREED=$((FREED+(b-a)/1048576))
fi

after=$(df -B1 / | awk 'NR==2{print $3}')
say "===== 实际回收 $(( (before-after)/2**30 ))G, 现用 $(python3 -c "print(f'{$after/2**30:.1f}G')") ====="
{
  echo ""
  echo "## $(date '+%F %T') 红线回收 (老倪指令: 检查磁盘, 保持磁盘红线)"
  echo "- 删除前 $(python3 -c "print(f'{$before/2**30:.1f}G')") → 删除后 $(python3 -c "print(f'{$after/2**30:.1f}G')")"
  echo "- 明细: 见 $LOG"
  echo "- 留证/不动: cube_single_expert.h5(INTACT config 在用) / l5_gen_1010_big.h5 / lora_40_l5261013_124042 / d1 / 全部在役模型与数据集"
} | sudo tee -a "$LEDGER" >/dev/null
say "已记账 $LEDGER"
