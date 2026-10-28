#!/usr/bin/env bash
# 数据保存: v5.42.0 配置驱动功能切换 + 飞书端场景叠加任务 —— 快照 + 归档 (2026-10-11)
set -uo pipefail
cd /home/ubuntu/zmax
REPO=$(pwd)
SNAP="$REPO/docs/data_snapshots/2026-10-11_v5.42.0_配置驱动功能切换+场景叠加"
ARC="$REPO/zmax_data/release_5.42.0_20261011"
mkdir -p "$SNAP" "$ARC"

echo "═══ ① 快照目录: ${SNAP#$REPO/} ═══"

# ── 工程库 (单一唯一依据) + 判据 ──
if [ -f data/database/zmax/zmax_engineering.db ]; then
  cp -f data/database/zmax/zmax_engineering.db "$SNAP/zmax_engineering.db"
  ./venvs/lerobot-venv/bin/python tools/engineering_db.py check > "$SNAP/engineering_db_check.txt" 2>&1
  echo "  工程库: $(du -h "$SNAP/zmax_engineering.db" | cut -f1) · check: $(tail -1 "$SNAP/engineering_db_check.txt" | cut -c1-90)"
fi
# ── 改数留痕 ──
[ -f data/database/zmax/param_events.jsonl ] && tail -200 data/database/zmax/param_events.jsonl > "$SNAP/param_events_tail.jsonl"
# ── 画布唯一依据 ──
cp -f src/lerobot/engineering/flows/state_space_obs.json "$SNAP/canvas_state_space_obs.json" 2>/dev/null \
  && echo "  画布: $(md5sum "$SNAP/canvas_state_space_obs.json" | cut -c1-12) ($(python3 -c "import json;d=json.load(open('$SNAP/canvas_state_space_obs.json'));print(len(d['nodes']),'节点',len(d.get('links') or []),'连线')"))"
# ── 本轮两次真跑的判据报告 ──
for t in TASK-01-FW TASK-06-TRAY; do
  [ -f "reports/ss_task_run_${t}_latest.json" ] && cp -f "reports/ss_task_run_${t}_latest.json" "$SNAP/" && echo "  判据: ss_task_run_${t}_latest.json"
done
# ── 飞书端场景叠加: 公网通道验证 + 公开 live 元数据 ──
{
  echo "# 场景叠加 · 飞书端(公网)通道验证 —— $(date '+%F %T')"
  bash tools/ecs_overlay_forward.sh --check 2>&1
  echo
  bash tools/ecs_overlay_forward.sh --verify 2>&1
} > "$SNAP/overlay_channel_verify.txt" 2>&1
curl -s -m 15 "https://datadrive.world/ov/live.json?k=zmax-live" -o "$SNAP/overlay_live_public.json"
curl -s -m 15 "https://datadrive.world/zmax_status.json" -o "$SNAP/zmax_status_public.json"
echo "  叠加验证: $(grep -c 'HTTP 200' "$SNAP/overlay_channel_verify.txt") 条公网 200 · live.json $(wc -c < "$SNAP/overlay_live_public.json")B · status $(wc -c < "$SNAP/zmax_status_public.json")B"
# ── 发布状态 (GitHub CI) ──
curl -s -m 20 "https://api.github.com/repos/MikeBMW/zmax/actions/runs?per_page=3" \
 | ./venvs/lerobot-venv/bin/python -c "
import json,sys
d=json.load(sys.stdin); out={'runs':[{'branch':r['head_branch'],'status':r['status'],'conclusion':r['conclusion'],'url':r['html_url']} for r in d['workflow_runs'][:3]]}
json.dump(out, open('/tmp/_ci.json','w'), ensure_ascii=False, indent=1)
" && cp -f /tmp/_ci.json "$SNAP/release_status.json"
echo "  CI: $(./venvs/lerobot-venv/bin/python -c "import json;d=json.load(open('$SNAP/release_status.json'));print(', '.join(f\"{r['branch']}={r['status']}/{r['conclusion']}\" for r in d['runs']))")"
# ── git 唯一依据点 ──
{ echo "commit: $(git rev-parse --short HEAD)"; echo "tag: $(git describe --tags --abbrev=0 2>/dev/null)"; echo "branch: $(git rev-parse --abbrev-ref HEAD)"; } > "$SNAP/git_ref.txt"
cat "$SNAP/git_ref.txt" | sed 's/^/  /'

echo
echo "═══ ② 归档包: ${ARC#$REPO/} ═══"
rm -rf "$ARC"/*; mkdir -p "$ARC"
cp -f "$SNAP"/* "$ARC"/ 2>/dev/null
cp -f docs/notes/v5.42.0_配置驱动功能切换_20261010.md "$ARC/" 2>/dev/null
cp -f reports/tray_place_judge_20261010_181505.png "$ARC/" 2>/dev/null
mkdir -p "$ARC/README"
cat > "$ARC/README/README.md" <<'EOF'
# 归档 release_5.42.0_20261011

主题: 配置驱动功能切换 (同一状态空间工程 插拔/摆盘 双功能真跑) + 飞书端场景叠加任务同步
- 代码: commit 见 git_ref.txt · tag v5.42.0
- 真跑判据: ss_task_run_TASK-01-FW_latest.json (686 步 success=True) · ss_task_run_TASK-06-TRAY_latest.json (3/3 合格)
- 飞书端场景叠加: overlay_channel_verify.txt (公网 /ov/ 通道 4 条 200 + POST 403) · overlay_live_public.json
- 同步: docs/skills/xspace + docs/skills/hermes-all (215 技能) · docs/memory/hermes-jingjing-{memory,user}-2026-10-11.md
- 校验: MANIFEST.sha256
EOF
( cd "$ARC" && find . -type f ! -name 'MANIFEST.sha256' -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256 )
echo "  文件 $(find "$ARC" -type f | wc -l) 个 · $(du -sh "$ARC" | cut -f1) · MANIFEST $(wc -l < "$ARC/MANIFEST.sha256") 条"
echo
echo "═══ ③ 快照清单 ═══"
( cd "$SNAP" && ls -la | tail -n +2 | awk '{printf "  %-42s %s\n", $9, $5}' )
