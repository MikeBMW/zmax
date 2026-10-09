#!/usr/bin/env bash
# run_gui_verifiers.sh — 一次跑完 GUI 判据集 (每个都真建窗口, 总耗时 ~3-6 分钟)
set -u
cd /home/ubuntu/zmax
export QT_QPA_PLATFORM=offscreen
PY=gui-venv311/bin/python
run () {
  local name="$1"; shift
  local out="/tmp/vf_${name//[^A-Za-z0-9]/_}.log"
  env -u PYTHONPATH "$PY" "$@" >"$out" 2>&1
  local rc=$?
  local bad
  bad=$(grep -c "❌" "$out")
  printf "  %-26s exit=%-3s ❌=%-3s %s\n" "$name" "$rc" "$bad" "$(grep -E '^(✅ 全部通过|❌ 失败)' "$out" | tail -1)"
  return $rc
}
echo "══ GUI 判据集 $(date '+%F %T') ══"
run entries_cleanup   tools/verify_entries_cleanup.py
run mparam_page       tools/verify_mparam_page.py
run calib_measure     tools/verify_calib_measure.py
run project_archive   tools/verify_project_archive.py
run run_cfg_panel     tools/verify_run_cfg_panel.py
run step_follow       tools/verify_step_follow.py
run l2_compat         tools/verify_l2_compat_checkbox.py
run engineering       tools/verify_engineering.py
run canvas_render     tools/verify_canvas_render.py
run node_impl_audit   tools/ss_node_impl_audit.py
echo "══ 完 ══"
