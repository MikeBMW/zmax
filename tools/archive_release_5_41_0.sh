#!/usr/bin/env bash
# 归档 v5.41.0 产物 → ~/zmax/zmax_data/release_5.41.0_YYYYMMDD
#   本轮主题: 3D 场景页可用性 — 台面几何与场景真源同源 / 两个侧栏向左折叠 / 八阶段面板折叠成一行
#             / 删两处说明文字 / 修「点插拔看着跟摆盘一样」(切场景原来不重建几何)
#   约定沿用 archive_release_5_34_0.sh: 代码 + 真源快照 + 证据 + 文档 + 画布备份, 末尾 MANIFEST.md + sha256sums.txt
set -u
REPO=/home/ubuntu/zmax
DST=$HOME/zmax/zmax_data/release_5.41.0_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,gui,src,config,canvas,data,docs,evidence,reports}
cd "$REPO" || exit 1

echo "=== ① 本轮改动的代码 ==="
cp -f tools/gui/ss_dreamview.py tools/gui/dreamview_scene_edit.py "$DST/gui/"
cp -f tools/tests/test_sim_real_3d_scene_view.py tools/tests/test_scene_pick_link.py \
      tools/bump_version.py tools/archive_release_5_41_0.sh "$DST/tools/" 2>/dev/null
mkdir -p "$DST/tools/tests"; cp -f tools/tests/test_sim_real_3d_scene_view.py tools/tests/test_scene_pick_link.py "$DST/tools/tests/"
cp -f VERSION.md docs/design/v5.41.0_summary.txt "$DST/docs/" 2>/dev/null
ls "$DST/gui" | sed 's/^/  gui: /'
ls "$DST/tools/tests" | sed 's/^/  tests: /'

echo "=== ② 生成物真源 (场景库 + 仿真真源 + 配置) ==="
mkdir -p "$DST/config/scenes" "$DST/config/mcd" "$DST/config/calib" "$DST/config/orders"
cp -f data/scene/scenes/index.json "$DST/config/scenes/" 2>/dev/null
for s in SS-EPI-CORNER SS-TRAY-PLACE SIM-PEG-L4 SCN-07-UP SCN-01-PEG; do
  if [ -d "data/scene/scenes/$s" ]; then
    mkdir -p "$DST/config/scenes/$s"
    cp -f "data/scene/scenes/$s/objects3d.json" "data/scene/scenes/$s/overlay_spec.json" "$DST/config/scenes/$s/" 2>/dev/null
  fi
done
cp -f data/scene/sim/sim_scenes.json "$DST/config/scenes/" 2>/dev/null
cp -f data/scene/objects3d.json data/scene/overlay_spec.json "$DST/config/scenes/" 2>/dev/null
cp -f config/mcd/*.json "$DST/config/mcd/" 2>/dev/null
cp -f config/calib/*.json "$DST/config/calib/" 2>/dev/null
cp -f config/orders/*.json "$DST/config/orders/" 2>/dev/null
cp -f config/library_curation.json "$DST/config/" 2>/dev/null
find "$DST/config" -type f | wc -l | sed 's/^/  配置真源文件: /'

echo "=== ③ 画布真源 + 改动前备份 (回滚面) ==="
cp -fL src/lerobot/engineering/flows/state_space_obs.json "$DST/canvas/" 2>/dev/null
ls -t src/lerobot/engineering/flows/_archive/*.json 2>/dev/null | head -1 | while read -r f; do
  cp -f "$f" "$DST/canvas/$(basename "$f")"
done
ls -1 "$DST/canvas" | sed 's/^/  canvas: /'

echo "=== ④ 数据 (单一工程库) ==="
cp -f data/database/zmax/zmax_engineering.db "$DST/data/" 2>/dev/null
ls -l "$DST/data" | tail -n +2 | awk '{print "  ", $9, $5, "B"}'

echo "=== ⑤ 实测证据 (本轮本机真跑出来的) ==="
A=$REPO/zmax_data/artifacts_20261010/evidence
cp -f "$A"/*.log "$DST/evidence/" 2>/dev/null
cp -f "$A"/*.json "$DST/evidence/" 2>/dev/null
cp -f "$A"/scene_*.tar.gz "$DST/evidence/" 2>/dev/null
mkdir -p "$DST/evidence/scripts"; cp -f "$A"/scripts/*.py "$DST/evidence/scripts/" 2>/dev/null
{
  echo "# v5.41.0 判据汇总 ($(date '+%F %T %Z'))"
  echo
  echo "## 离线取证 (DISPLAY=:0 真 GL 渲染)"
  for f in probe_fold probe_switch_geom probe_table_box; do
    echo "### $f"; tail -2 "$A/$f.log" 2>/dev/null; echo
  done
  echo "## 回归"
  for f in test_scene_pick_link test_sim_real_3d_scene_view; do
    echo "### $f"; tail -2 "$A/$f.log" 2>/dev/null; echo
  done
  echo "## 版本/真源判据"
  tail -1 "$A/integrity_check.log" 2>/dev/null
  tail -1 "$A/scene_registry_check.log" 2>/dev/null
  tail -1 "$A/sim_scene_def_check.log" 2>/dev/null
} > "$DST/evidence/judges.txt" 2>&1
tail -8 "$DST/evidence/judges.txt" | sed 's/^/  /'

echo "=== ⑥ 文档 ==="
cp -f reports/关机交接_2026-10-10_晚.md docs/notes/2026-10-10_handoff_晚.md "$DST/reports/" 2>/dev/null
cp -f docs/notes/2026-10-10_handoff.md docs/design/v5.40.2_summary.txt "$DST/docs/" 2>/dev/null
ls "$DST/reports" "$DST/docs" | sed 's/^/  /'

echo "=== ⑦ MANIFEST + sha256 ==="
cd "$DST" || exit 1
{
  echo "# v5.41.0 归档 MANIFEST ($(date '+%F %T %Z'))"
  echo
  echo "- 仓库: MikeBMW/zmax @ $(cd "$REPO" && git rev-parse --short HEAD) (main) · tag v5.41.0"
  echo "- 主题: 3D 场景页可用性 — 台面几何与场景真源同源 / 侧栏左折叠 / 八阶段面板折叠 / 切场景真重建几何"
  echo "- 判据: 折叠 20 项 · 切场景 13 项 · 点选联动 26 项 · Sim&Real 页 92 项 · integrity 五处一致 · 场景库全绿"
  echo "- 场景快照: zmax_data/snapshots/scene_20261010_171513.tar.gz (43 文件, 自校验过)"
  echo "- 桌面版: tag 触发 build-win-exe.yml 双平台出包"
  echo
  echo "## 文件清单"
  find . -type f ! -name MANIFEST.md ! -name sha256sums.txt -printf "%s\t%p\n" | sort -k2 \
    | awk -F'\t' '{printf "- %s (%.0f B)\n", $2, $1}'
} > MANIFEST.md
rm -f sha256sums.txt
find . -type f ! -name MANIFEST.md ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt

echo "归档: $DST · 文件 $(find "$DST" -type f | wc -l) · 大小 $(du -sh "$DST" | cut -f1) · sha256 $(wc -l < sha256sums.txt) 条"
