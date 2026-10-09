#!/usr/bin/env bash
# 探针批②: 控制台页面/能力栈/分层 联通 (离线, 与训练并行)
set -u
cd /home/ubuntu/zmax || exit 1
export QT_QPA_PLATFORM=offscreen
PY=gui-venv311/bin/python
OUT=/tmp/probes2_$(date +%H%M%S)
mkdir -p "$OUT"; echo "$OUT" > /tmp/probes2_dir.txt
run () {
  local name="$1"; shift
  env -u PYTHONPATH "$PY" "$@" > "$OUT/$name.log" 2>&1
  local rc=$?
  local bad; bad=$(grep -ac "❌" "$OUT/$name.log" || true)
  printf "  %-22s exit=%-3s ❌=%-3s %s\n" "$name" "$rc" "$bad" "$(grep -aE '全部通过|失败|项✅|✅ .*通过' "$OUT/$name.log" | tail -1 | cut -c1-70)"
}
echo "══ 探针批② $(date '+%F %T') ══"
run capability_stack  tools/probe_capability_stack.py
run canvas_menu       tools/probe_canvas_menu.py
run unified_backbone  tools/probe_unified_backbone.py
run scene_geom        tools/probe_scene_geom.py
run tray_slots        tools/probe_tray_slots.py
run ui_metrics        tools/probe_ui_metrics.py
run view_render       tools/probe_view_render.py
run ecs_upload        tools/probe_ecs_upload.py
echo "══ 完 $(date '+%F %T') ══"
