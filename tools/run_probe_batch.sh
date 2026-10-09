#!/usr/bin/env bash
# 推理/联通 探针批跑 (离线可跑, 与训练并行; 每项单独日志)
set -u
cd /home/ubuntu/zmax || exit 1
export QT_QPA_PLATFORM=offscreen
PY=gui-venv311/bin/python
OUT=/tmp/probes_$(date +%H%M%S)
mkdir -p "$OUT"; echo "$OUT" > /tmp/probes_dir.txt
run () {
  local name="$1"; shift
  env -u PYTHONPATH "$PY" "$@" > "$OUT/$name.log" 2>&1
  local rc=$?
  local bad; bad=$(grep -ac "❌" "$OUT/$name.log" || true)
  printf "  %-22s exit=%-3s ❌=%-3s %s\n" "$name" "$rc" "$bad" "$(grep -aE '全部通过|失败|✅ .*项|❌' "$OUT/$name.log" | tail -1 | cut -c1-70)"
}
echo "══ 探针集 $(date '+%F %T') ══"
run ss_pipeline       tools/probe_ss_pipeline.py
run smolvla_lew       tools/probe_smolvla_lew.py
run l4_callchain      tools/probe_l4_callchain.py
run text_labels       tools/probe_text_labels.py
run canvas_nodes      tools/probe_canvas_nodes.py
run library_sync      tools/probe_library_sync.py
run ss_node_impl      tools/ss_node_impl_audit.py
echo "══ 完 $(date '+%F %T') ══"
