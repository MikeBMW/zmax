#!/usr/bin/env bash
# 只杀探针/批跑残留 (绝不碰训练: joint_train_all / lerobot_train / train.py)
set -u
for pat in "run_probe_batch2.sh" "run_probe_batch.sh" "tools/probe_unified_backbone" \
           "tools/probe_view_render" "tools/probe_capability_stack" "tools/probe_scene_geom" \
           "tools/probe_tray_slots" "tools/probe_ecs_upload" "tools/probe_canvas_menu" \
           "tools/probe_pages_sweep"; do
  for p in $(pgrep -f "$pat" 2>/dev/null); do
    [ "$p" = "$$" ] && continue
    # 保护: 命令行里含训练关键字的进程一律不动
    if tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | grep -qE "joint_train_all|lerobot_train|INTACT|yolo_annot_train|l5_vlm"; then
      echo "  ⏭ 跳过(训练): $p"
      continue
    fi
    kill "$p" 2>/dev/null && echo "  ✂ 杀 $p ($pat)"
  done
done
sleep 1
echo "残留探针: $(pgrep -af 'tools/probe_|run_probe_batch' | grep -vc 'pgrep' || true)"
echo "训练仍在: $(pgrep -af 'joint_train_all|lerobot_train' | wc -l) 个进程"
