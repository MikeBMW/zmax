#!/usr/bin/env bash
# run_verifiers_full.sh — 判据集② (在 GUI 判据集之外的全量功能判据), 每项 300s 超时
#   2026-10-09 自主进化: 老倪要求「每个功能都要一 一小联通」⇒ 把散落的 verify_*/probe_* 收口成一批
#   ⚠️ 只收 CPU 安全项 (不碰真运动 / 不写产线 AOI / 不装包); GPU 项另批 (等训练完)
set -u
cd /home/ubuntu/zmax
export QT_QPA_PLATFORM=offscreen
PY=gui-venv311/bin/python
OUT=/tmp/vf2_$(date +%H%M%S)
mkdir -p "$OUT"
echo "$OUT" > /tmp/vf2_dir.txt
echo "══ 判据集② $(date '+%F %T') → $OUT ══"

run () {
  local name="$1"; shift
  local f="$OUT/${name}.log"
  # ⏱ 2026-10-10: 重型判据 (每臂独立进程/多场景逐步真跑) 300s 不够 ⇒ 默认 1500s,
  #   只有单点小判据才用短超时 (旧默认导致 fiber/annot_labeling 每轮都假 124)
  local tmo="${ZMAX_JUDGE_TIMEOUT:-1500}"
  timeout "$tmo" env -u PYTHONPATH "$PY" "$@" >"$f" 2>&1
  local rc=$?
  local bad
  bad=$(grep -ac "❌" "$f" 2>/dev/null || echo 0)
  local verdict
  verdict=$(grep -aE '^(✅ 全部通过|❌ 失败|✅|❌|→ 总判定)' "$f" | tail -1 | cut -c1-58)
  printf "  %-26s exit=%-4s ❌=%-3s %s\n" "$name" "$rc" "$bad" "$verdict"
}

run node_code_map        tools/verify_node_code_map.py
run memory_potential     tools/verify_memory_potential_fields.py
run moe_stage_coverage   tools/verify_moe_stage_coverage.py
run capability_stack     tools/verify_capability_stack.py
run fiber_zero_regress   tools/verify_fiber_zero_regression.py
run l4_zero_regress      tools/verify_l4_zero_regression.py
run perception_chain     tools/verify_perception_chain.py
run projection_chain     tools/verify_projection_chain.py
run overlay_alignment    tools/verify_overlay_alignment.py
run skill_ctx            tools/verify_skill_ctx.py
run macro_memory         tools/verify_macro_memory.py
run hil_chain            tools/verify_hil_chain.py
run annot_labeling       tools/verify_annot_labeling.py
run annot_sim            tools/verify_annot_sim.py
run scene_overlay_btn    tools/verify_scene_overlay_button.py
run scene_overlay_canvas tools/verify_scene_overlay_canvas.py
run station_button       tools/verify_station_button.py
run clock_skew_guard     tools/verify_clock_skew_guard.py
run engine_live_frame    tools/verify_engine_live_frame.py
run input_source_follow  tools/verify_input_source_follow.py
run real_frame_proven   tools/verify_real_frame_provenance.py
run adaptive_gain        tools/verify_adaptive_gain.py
run intent_pair          tools/verify_intent_pair.py
run likelihood_head      tools/verify_likelihood_head.py
run manifold_layer       tools/verify_manifold_layer.py
run predictor_layer      tools/verify_predictor_layer.py
run l3_action            tools/verify_l3_action.py
run l4_intact_zeroseach  tools/verify_l4_intact_zeroseach.py
run l4_optical_chain     tools/verify_l4_optical_chain.py
run p3_metrics           tools/verify_p3_metrics.py
run canvas_id_unique     tools/verify_canvas_id_unique.py
run canvas_render2       tools/verify_canvas_render.py
run l4_layout            tools/verify_l4_layout.py
run aoi_console          tools/verify_aoi_console.py
run opt_camera           tools/verify_opt_camera.py
echo "══ 判据集② 完 $(date '+%F %T') ══"
echo "日志目录: $OUT"
