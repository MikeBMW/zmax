#!/usr/bin/env bash
# 归档 v5.49.3 产物 → ~/zmax/zmax_data/release_5.49.3_YYYYMMDD
#   本轮主题: 标准打开流程收口 —— 双击图标→配置中心 / 任务表三列(工程·实时监控·3D场景) / 右下角启动按钮 /
#             3D 窗跟随场景(修真 bug) / 配置×任务×场景×信号实时监控 自动测试
#   约定沿用 archive_release_5_41_0.sh: 代码 + 真源快照 + 证据 + 文档 + 画布备份, 末尾 MANIFEST.md + sha256sums.txt
set -u
REPO=/home/ubuntu/zmax
DST=$HOME/zmax/zmax_data/release_5.49.3_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,gui,config,canvas,evidence,reports,docs}
cd "$REPO" || exit 1

echo "=== ① 本轮改动的代码 (逐文件拷贝 + sha256) ==="
cp -f tools/gui/veh6_config_page.py tools/gui/studio.py tools/gui/launch_studio.sh "$DST/gui/"
cp -f tools/verify_zmax_open_flow.py tools/verify_task_scene_matrix.py tools/zmax_open.py \
      tools/ss_scene_switch.py tools/ss_task_bind.py tools/bump_version.py \
      tools/archive_release_5_49_3.sh "$DST/tools/" 2>/dev/null
ls "$DST/gui" | sed 's/^/  gui: /'; ls "$DST/tools" | sed 's/^/  tool: /'

echo "=== ② 真源快照 (配置/场景/画布) ==="
cp -f config/ss_task_binding.json config/task_state.json config/task_state_manual.json \
      config/task_state_ledger.json "$DST/config/" 2>/dev/null
mkdir -p "$DST/config/topics"; cp -f config/topics/scene_tags.json "$DST/config/topics/" 2>/dev/null
cp -f flows/state_space_obs.json "$DST/canvas/state_space_obs.json" 2>/dev/null
cp -f reports/projects/SS_主工程_任务配置.zmaxproj "$DST/canvas/" 2>/dev/null
for f in src/lerobot/engineering/flows/state_space_obs.json; do
  [ -f "$f" ] && cp -f "$f" "$DST/canvas/state_space_obs__src_copy.json"
done
echo "  画布 md5: $(md5sum flows/state_space_obs.json 2>/dev/null | cut -d' ' -f1)"

echo "=== ③ 本轮证据 (判据报告 + 现场截图 + 版本核对) ==="
cp -f reports/task_scene_matrix_*.json reports/task_scene_matrix_*.md "$DST/reports/" 2>/dev/null
cp -f reports/shots/matrix_TASK-*.png "$DST/evidence/" 2>/dev/null
gui-venv311/bin/python tools/verify_zmax_open_flow.py > "$DST/evidence/verify_zmax_open_flow.txt" 2>&1 || true
tail -3 "$DST/evidence/verify_zmax_open_flow.txt" | sed 's/^/  /'
gui-venv311/bin/python tools/verify_version_sync.py --offline > "$DST/evidence/verify_version_sync.txt" 2>&1 || true
{ echo "version_repo: $(grep -m1 -oP 'CURRENT_VERSION = \K.*' tools/gui/update_checker.py)";
  echo "git_head: $(git rev-parse --short HEAD 2>/dev/null)";
  echo "git_tag: $(git describe --tags --always 2>/dev/null)";
  echo "canvas_md5: $(md5sum flows/state_space_obs.json | cut -d' ' -f1)";
  echo "scene_tags_md5: $(md5sum config/topics/scene_tags.json | cut -d' ' -f1)";
  echo "binding_sha: $(sha256sum config/ss_task_binding.json | cut -d' ' -f1)"; } > "$DST/evidence/refs.txt"
sed 's/^/  /' "$DST/evidence/refs.txt"

echo "=== ④ 文档 ==="
cp -f VERSION.md docs/STANDARD_STARTUP_FLOW_20261012.md "$DST/docs/" 2>/dev/null
mkdir -p "$DST/docs/skills"; cp -f docs/skills/hermes-all/software-development/zmax-console/references/standard-open-flow.md \
      "$DST/docs/skills/standard-open-flow.md" 2>/dev/null

echo "=== ⑤ MANIFEST + sha256 ==="
( cd "$DST" && find . -type f ! -name sha256sums.txt ! -name MANIFEST.md -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt )
{ echo "# 归档 v5.49.3 — 标准打开流程收口 (双击图标→配置中心 · 三列 · 右下角启动按钮 · 3D窗随场景)";
  echo; echo "生成: $(date '+%F %T')  源: $REPO  HEAD: $(git rev-parse --short HEAD 2>/dev/null)";
  echo; echo "## 目录"; echo '```'; ls -1 "$DST"; echo '```';
  echo; echo "## 判据"; echo "- verify_zmax_open_flow.py: $(tail -1 "$DST/evidence/verify_zmax_open_flow.txt" 2>/dev/null)";
  echo "- verify_task_scene_matrix.py: $(ls "$DST/reports"/task_scene_matrix_*.md >/dev/null 2>&1 && tail -1 "$(ls -t "$DST"/reports/task_scene_matrix_*.md | head -1)" || echo '见 reports/')";
  echo; echo "## 校验"; echo "sha256sum -c sha256sums.txt  (本目录内)"; } > "$DST/MANIFEST.md"

echo
echo "✅ 归档完成: $DST"
echo "   文件 $(find "$DST" -type f | wc -l) 个 · 大小 $(du -sh "$DST" | cut -f1)"
echo "   校验: (cd $DST && sha256sum -c sha256sums.txt | tail -3)"
