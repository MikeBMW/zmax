#!/usr/bin/env bash
# 归档 v5.34.0 产物 → ~/zmax/zmax_data/release_5.34.0_YYYYMMDD
#   本轮主题: 控制台界面定版 (产品/系统/功能 三级 + MCD 数据 + 侧栏极简) + 单一工程数据库 + 参数中心(数据库服务)
#   约定沿用 archive_release_5_21_0.sh: 代码 + 真源快照 + 证据 + 文档 + 画布备份, 末尾 MANIFEST.md + sha256sums.txt
set -u
REPO=/home/ubuntu/zmax
DST=$HOME/zmax/zmax_data/release_5.34.0_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,gui,src,config,canvas,data,docs,evidence,reports}
cd "$REPO" || exit 1

echo "=== ① 本轮新增/改动的代码 ==="
cp -f tools/engineering_db.py tools/param_registry.py tools/verify_platform_spec.py tools/verify_param_center.py \
      tools/bump_version.py tools/archive_release_5_34_0.sh \
      "$DST/tools/" 2>/dev/null
cp -f tools/gui/studio.py tools/gui/platform_spec.py tools/gui/param_center.py "$DST/gui/" 2>/dev/null
cp -f src/lerobot/engineering/flows/state_space_obs.json "$DST/src/" 2>/dev/null
ls "$DST/tools" | wc -l | sed 's/^/  tools 文件: /'
ls "$DST/gui" | wc -l | sed 's/^/  gui 文件: /'

echo "=== ② 真源快照 (平台/参数/标定/画布) ==="
mkdir -p "$DST/config/platform" "$DST/config/calib" "$DST/config/library"
cp -f config/platform/zmax_platform.json config/platform/param_spec.json "$DST/config/platform/" 2>/dev/null
cp -f config/calib/zmax_calib.json config/calib/zmax_manifold.json "$DST/config/calib/" 2>/dev/null
cp -f config/library_curation.json config/ss_task_binding.json "$DST/config/" 2>/dev/null
find "$DST/config" -type f | wc -l | sed 's/^/  配置真源文件: /'

echo "=== ③ 数据 (单一工程库 + 改数留痕) ==="
cp -f data/database/zmax_engineering.db "$DST/data/" 2>/dev/null
cp -f data/database/param_events.jsonl "$DST/data/" 2>/dev/null
cp -f data/database/README.md "$DST/data/" 2>/dev/null
ls -l "$DST/data" | tail -n +2 | awk '{print "  ", $9, $5, "B"}'

echo "=== ④ 画布真源 + 最近备份 ==="
ls -t src/lerobot/engineering/flows/_archive/*.json 2>/dev/null | head -1 | while read -r f; do
  cp -f "$f" "$DST/canvas/$(basename "$f")"
done
ls -1 "$DST/canvas" | sed 's/^/  /'

echo "=== ⑤ 实测证据 ==="
{
  echo "# v5.34.0 证据 (生成 $(date '+%F %T %Z'))"
  echo
  echo "## 判据"
  ( cd "$REPO" && QT_QPA_PLATFORM=offscreen env -u PYTHONPATH timeout 420 gui-venv311/bin/python -u tools/verify_platform_spec.py 2>&1 | grep -E "✅|❌|全部通过|失败" )
  echo
  ( cd "$REPO" && python3 tools/engineering_db.py check 2>&1 | tail -22 )
} > "$DST/evidence/judges.txt" 2>&1
tail -6 "$DST/evidence/judges.txt" | sed 's/^/  /'

echo "=== ⑥ 文档 ==="
cp -f VERSION.md docs/design/v5.34.0_summary.txt docs/design/v5.33.0_summary.txt docs/design/v5.33.2_summary.txt \
      docs/design/v5.32.0_summary.txt docs/design/v5.31.0_summary.txt docs/design/v5.30.0_summary.txt \
      docs/design/param_registry_20261009.md docs/design/platform_engineering_db_20261009.md "$DST/docs/" 2>/dev/null
cp -f docs/data_snapshots/2026-10-09_v5.34.0_侧栏UI定版/README.md "$DST/docs/data_snapshot_README.md" 2>/dev/null
ls "$DST/docs" | wc -l | sed 's/^/  文档: /'

echo "=== ⑦ MANIFEST + sha256 ==="
cd "$DST" || exit 1
{
  echo "# v5.34.0 归档 MANIFEST ($(date '+%F %T %Z'))"
  echo
  echo "- 仓库: MikeBMW/zmax @ $(cd "$REPO" && git rev-parse --short HEAD) (main) · tag v5.34.0"
  echo "- 主题: 控制台界面定版 — 产品/系统/功能 三级 + MCD 数据面 + 侧栏极简 UI + 单一工程数据库"
  echo "- 工程库: data/zmax_engineering.db (平台1/产品2/特征18/子系统4/功能74/模块74/能力31/接口62/诊断57/"
  echo "  画布 74 节点 184 连线/params 162/param_links 375/mcd 5)"
  echo "- MCD: 产品 M9/C45/D57 · sys0 M9/C41/D38 · sys2 C4/D11 · sys1 D8"
  echo "- 桌面版: Windows Z-MAX_Console.exe + macOS Z-MAX_Console-macOS.zip (tag 触发 build-win-exe.yml 双平台并行)"
  echo "- 判据: verify_platform_spec 14 项 · verify_param_center 8 项 · engineering_db check 17 项"
  echo
  echo "## 文件清单"
  find . -type f ! -name MANIFEST.md ! -name sha256sums.txt -printf "%s\t%p\n" | sort -k2 \
    | awk -F'\t' '{printf "- %s (%.0f B)\n", $2, $1}'
} > MANIFEST.md
rm -f sha256sums.txt
find . -type f ! -name MANIFEST.md ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt

echo "归档: $DST · 文件 $(find "$DST" -type f | wc -l) · 大小 $(du -sh "$DST" | cut -f1) · sha256 $(wc -l < sha256sums.txt) 条"
