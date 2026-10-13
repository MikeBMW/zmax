#!/usr/bin/env bash
# 磁盘清理 2026-10-13 (老倪: 清理磁盘, 保证在 300G 以下)
# 阶段 2: git 垃圾包 + 同族零引用训练 run + 零引用 ckpt 目录
# 台账: /home/ubuntu/zmax/reports/disk_cleanup_20261013_ledger.json
set -u
cd /home/ubuntu/zmax
LED=reports/disk_cleanup_20261013_ledger.json
echo "开始前:"; df -h / | tail -1

echo "=== A) lerobot-smolvla-lew .git 临时包垃圾 ==="
cd /home/ubuntu/zmax/external/lerobot-smolvla-lew
before=$(git count-objects -vH | awk -F': ' '/size-garbage/{print $2}')
n_before=$(ls .git/objects/pack/tmp_pack_* 2>/dev/null | wc -l)
echo "  垃圾: $before ($n_before 个 tmp_pack_*)"
git gc --prune=now --quiet 2>&1 | tail -2
rm -f .git/objects/pack/tmp_pack_* 2>/dev/null
after=$(git count-objects -vH | awk -F': ' '/size-garbage/{print $2}')
echo "  清理后垃圾: $after"; git count-objects -vH | grep -E 'size-pack|garbage'
du -sh .git | awk '{print "  .git 现在: "$1}'

echo "=== B) 同族零引用训练 run (lora_40 / l526101*) ==="
cd /home/ubuntu/zmax/external/lerobot-smolvla-lew/outputs/train
KEEP="smolvla_lew_lora_40_l5261013_124042"          # 最新一份留证
for d in smolvla_lew_lora_40_l5261010_061856 smolvla_lew_lora_40_l5261010_172525 \
         smolvla_lew_lora_40_l5261011_222807 smolvla_lew_lora_40_l5261012_081308 \
         smolvla_lew_lora_40_l5261013_104327 smolvla_lew_lora_40_l5261013_113847; do
  if [ -d "$d" ]; then
    if [ -L "$d/../$KEEP" ] || [ "$d" = "$KEEP" ]; then echo "  跳过(留证): $d"; continue; fi
    sz=$(du -sh "$d" | cut -f1)
    refs=$(grep -rl --exclude-dir=outputs --exclude-dir=.git "$d" /home/ubuntu/zmax/tools /home/ubuntu/zmax/dds /home/ubuntu/zmax/src /home/ubuntu/zmax/config /home/ubuntu/zmax/docs /home/ubuntu/.hermes/scripts 2>/dev/null | grep -v disk_cleanup | wc -l)
    if [ "$refs" != "0" ]; then echo "  ⚠ 有引用($refs), 跳过: $d"; continue; fi
    echo "  删 $d ($sz, 零引用)"
    rm -rf "$d"
  fi
done

echo "=== C) 零引用 ckpt 目录 (A/B 消融与旧 stage) ==="
cd /home/ubuntu/zmax/zmax_data/stable-wm-cache/checkpoints
for d in abA_v6only abB_v6plusl5 unified_intense unified_plus_l5 unified_v16_s1 unified_v6expand; do
  [ -d "$d" ] || continue
  refs=$(grep -rl --exclude-dir=outputs --exclude-dir=.git "$d" /home/ubuntu/zmax/tools /home/ubuntu/zmax/dds /home/ubuntu/zmax/src /home/ubuntu/zmax/config /home/ubuntu/zmax/docs /home/ubuntu/.hermes/scripts 2>/dev/null | grep -v disk_cleanup | wc -l)
  if [ "$refs" != "0" ]; then echo "  ⚠ 有引用($refs), 跳过: $d"; continue; fi
  echo "  删 $d ($(du -sh $d | cut -f1))"
  rm -rf "$d"
done

echo "=== D) 保留区复核 ==="
cd /home/ubuntu/zmax
for p in zmax_data/stable-wm-cache/datasets/cube_single_expert.h5 \
         zmax_data/stable-wm-cache/datasets/optical_insert_v5_disturb.h5 \
         zmax_data/stable-wm-cache/datasets/l5_gen_1010_big.h5 \
         zmax_data/stable-wm-cache/checkpoints/unified_v16 \
         zmax_data/stable-wm-cache/checkpoints/stage_moe \
         zmax_data/models/yolo_peg_live.pt \
         external/lerobot-smolvla-lew/outputs/train/smolvla_lew_v10 \
         external/lerobot-smolvla-lew/outputs/train/smolvla_lew_lora_40_l5261013_124042 \
         data/database/zmax/zmax_engineering.db ; do
  [ -e "$p" ] && echo "  ✅ 在: $p" || echo "  ❌ 丢失: $p"
done
echo "服务存活:"; systemctl is-active zmax-engdb zmax-torque-bus 2>&1 | tr '\n' ' '; echo
echo "结束后:"; df -h / | tail -1
