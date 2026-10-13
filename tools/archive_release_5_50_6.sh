#!/usr/bin/env bash
# 归档 v5.50.6 产物 → ~/zmax/zmax_data/release_5.50.6_YYYYMMDD
#   本轮主题: 功能级 topic 输入输出实测 + 两场景(摆盘/插拔)交付文档(配置模板) + 供应商SOR×2 + 合作协议
#   约定沿用 archive_release_5.49.3.sh: 代码 + 真源快照 + 证据 + 文档, 末尾 MANIFEST.md + sha256sums.txt
set -u
REPO=/home/ubuntu/zmax
DST=$HOME/zmax/zmax_data/release_5.50.6_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,config,canvas,evidence,reports,docs}

cd "$REPO" || exit 1

echo "=== ① 本轮改动的代码 (逐文件拷贝) ==="
for f in tools/verify_feature_io.py tools/delivery/gen_scene_doc.py tools/delivery/gen_contract_pack.py \
         tools/delivery/gen_scene_acceptance.py tools/verify_driving_torque_topic.py \
         tools/ss_bus_topics.py ; do
  [ -f "$f" ] && { mkdir -p "$DST/$(dirname "$f")"; cp "$f" "$DST/$f"; echo "  + $f"; }
done

echo "=== ② 真源快照 (配置/画布/绑定) ==="
for f in config/calib/zmax_calib.json config/calib/zmax_manifold.json feature.dbc \
         config/ss_task_binding.json config/topics/scene_tags.json config/platform/zmax_perf_spec.json \
         data/database/zmax/zmax_engineering.db; do
  [ -f "$f" ] && { mkdir -p "$DST/$(dirname "$f")"; cp "$f" "$DST/$f"; echo "  + $f"; }
done
cp data/database/zmax/sources/canvas/state_space_obs.json "$DST/canvas/" 2>/dev/null && echo "  + canvas/state_space_obs.json"

echo "=== ③ 证据 (真跑产物: 两场景 episode/trace + 逐功能 topic 实测) ==="
for f in $(ls -t reports/ss_episode_20261013_*.npz 2>/dev/null | head -1) \
         $(ls -t reports/tray_place_20261013_*.npz 2>/dev/null | head -1) \
         reports/ss_task_run_TASK-01-FW_latest.json reports/ss_task_run_TASK-06-TRAY_latest.json \
         reports/feature_io_test.json reports/driving_torque_judge.json; do
  [ -f "$f" ] && { cp "$f" "$DST/reports/"; echo "  + $f"; }
done
# 判据输出留痕 (本次跑过的那几条)
{ echo "# 本轮判据实跑输出 (原样留痕)"; } > "$DST/evidence/criteria_output.txt"
for c in "tools/ss_bus_topics.py status" "tools/engineering_db.py check" "tools/ss_task_bind.py --check"; do
  echo "" >> "$DST/evidence/criteria_output.txt"
  echo "\$ python3 $c" >> "$DST/evidence/criteria_output.txt"
  timeout 300 python3 $c >> "$DST/evidence/criteria_output.txt" 2>&1
done
echo "  + evidence/criteria_output.txt"

echo "=== ④ 文档 (交付版 5.50.C / 开发版 5.50.6) ==="
for f in docs/deliverables/交付文档_摆盘_TASK-06-TRAY_* docs/deliverables/交付文档_插拔_TASK-01-FW_* \
         docs/deliverables/SOR_供应商要求_摆盘_TASK-06-TRAY_* docs/deliverables/SOR_供应商要求_插拔_TASK-01-FW_* \
         docs/deliverables/合作协议_机器人数据平台与解决方案_* docs/deliverables/两场景验收报告_* \
         docs/deliverables/功能topic_输入输出测试报告_* docs/deliverables/全系统配置清单_* ; do
  [ -f "$f" ] && { cp "$f" "$DST/docs/"; }
done
echo "  + docs/ ($(ls "$DST/docs" | wc -l) 个文件)"

echo "=== ⑤ MANIFEST + sha256sums ==="
cd "$DST" || exit 1
( cd "$DST" && find . -type f ! -name MANIFEST.md ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum ) > sha256sums.txt
{
  echo "# MANIFEST · Z-MAX v5.50.6 产物归档"
  echo ""
  echo "- 归档时间: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "- 开发版: 5.50.6 (tools/gui/update_checker.py::CURRENT_VERSION)"
  echo "- 交付版: 5.50.C (量产交付版; 见 docs/deliverables/版本策略_5.50.A_B_C.md)"
  echo "- 本轮主题: 功能级 topic 输入输出实测 + 两场景交付文档(配置模板) + 供应商 SOR×2 + 合作协议"
  echo "- 目录: tools/(本轮代码) · config/(真源快照) · canvas/(画布) · evidence/(判据输出) · reports/(真跑证据) · docs/(交付文档)"
  echo ""
  echo "## 文件清单 (sha256)"
  echo '```'
  cat sha256sums.txt
  echo '```'
} > MANIFEST.md
echo "→ $DST"
echo "   文件 $(find . -type f | wc -l) 个 · 大小 $(du -sh . | cut -f1)"
