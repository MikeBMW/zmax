#!/usr/bin/env bash
# GPU 判据补跑 (训练已结束, 卡空了): 之前 OOM/超时的项
set -u
cd /home/ubuntu/zmax
export QT_QPA_PLATFORM=offscreen
PY=gui-venv311/bin/python
OUT=/tmp/vf3_$(date +%H%M%S); mkdir -p "$OUT"; echo "$OUT" > /tmp/vf3_dir.txt
echo "══ GPU 判据补跑 $(date '+%F %T') → $OUT ══"
run () {
  local name="$1"; shift
  timeout 900 env -u PYTHONPATH "$PY" "$@" >"$OUT/${name}.log" 2>&1
  printf "  %-24s exit=%-4s ❌=%-3s %s\n" "$name" "$?" "$(grep -ac '❌' "$OUT/${name}.log" || echo 0)" \
     "$(grep -aE '^(✅|❌|→ 总判定|总判定)' "$OUT/${name}.log" | tail -1 | cut -c1-56)"
}
run unified_backbone   tools/probe_unified_backbone.py
run smolvla_lew        tools/probe_smolvla_lew.py
run l4_optical_chain   tools/verify_l4_optical_chain.py
run fiber_zero_regress tools/verify_fiber_zero_regression.py
run annot_labeling     tools/verify_annot_labeling.py
run view_render        tools/probe_view_render.py
run pages_sweep        tools/probe_pages_sweep.py
echo "══ 完 $(date '+%F %T') ══"
