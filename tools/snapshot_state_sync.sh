#!/usr/bin/env bash
# ============================================================
# snapshot_state_sync.sh — 「同步飞书端的记忆/技能/场景叠加任务, 保存数据, 同步信息」状态快照
#
# 老倪 (2026-10-16) 原话:
#   「同步飞书端的记忆，技能，以及飞书端完成的场景叠加任务，保存数据，同步信息。发送给 dataworld」
# (同口径首发 2026-10-11 — 见 tools/finalize_data_sync.sh; 本脚本是它的二次版, 数字全部当场实测)
#
# 产出:
#   docs/data_snapshots/<DATE>_状态同步_<VER>_.../   (人读快照 + 判据原始输出 + 通道取证)
#   zmax_data/release_sync_<DATE>_<VER>/             (归档 + MANIFEST.sha256)
#
# 用法: bash tools/snapshot_state_sync.sh            # 采+建快照, 不提交
#       bash tools/snapshot_state_sync.sh --commit   # 采+建+commit+push+飞书
# ============================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)
DATE="${SNAP_DATE:-20261016}"
VER="${SNAP_VER:-v5.50.735}"
LABEL="状态同步_${VER}_元任务性能物理值全链+场景迭代+球面归一化"
SNAP="$ROOT/docs/data_snapshots/${DATE}_${LABEL}"
ARC="$ROOT/zmax_data/release_sync_${DATE}_${VER}"
PY="$ROOT/gui-venv311/bin/python"
mkdir -p "$SNAP" "$ARC"
echo "📦 采集中 → ${SNAP#*/}"

# ── ① 记忆 + 技能 同步 (走既有同步脚本: zmax-console 全家 + 关键技能 + 全量镜像 + 记忆备份)
bash tools/sync_hermes_to_repo.sh --no-push > "$SNAP/sync_hermes.txt" 2>&1
MEM_SHA=$(sha256sum ~/.hermes/memories/MEMORY.md | cut -d' ' -f1)
USER_SHA=$(sha256sum ~/.hermes/memories/USER.md | cut -d' ' -f1)
BMEM_SHA=$(sha256sum docs/memory/hermes-jingjing-memory-2026-10-16.md 2>/dev/null | cut -d' ' -f1)
BUSER_SHA=$(sha256sum docs/memory/hermes-jingjing-user-2026-10-16.md 2>/dev/null | cut -d' ' -f1)
N_LOCAL=$(find ~/.hermes/skills -name SKILL.md | wc -l)
N_ALL=$(find docs/skills/hermes-all -name SKILL.md | wc -l)
N_XSPACE=$(find docs/skills/xspace -name SKILL.md | wc -l)
diff ~/.hermes/memories/MEMORY.md docs/memory/hermes-jingjing-memory-2026-10-16.md > "$SNAP/memory_diff.txt" 2>&1
MEM_DIFF=$([ -s "$SNAP/memory_diff.txt" ] && echo "有差异" || echo "无差异(逐行一致)")
{
  echo "记忆同步 (老倪: 一点不能丢)"
  echo "  MEMORY.md       本地 sha256 ${MEM_SHA}"
  echo "  备份(仓库) sha256 ${BMEM_SHA}"
  echo "  逐行比对: ${MEM_DIFF}"
  echo "  USER.md         本地 sha256 ${USER_SHA} / 备份 ${BUSER_SHA}"
  echo "技能同步"
  echo "  本地技能 ${N_LOCAL} · hermes-all 全量镜像 ${N_ALL} · xspace 关键镜像 ${N_XSPACE}"
  echo "  缺失项: $(printf '%s\n' "$(comm -23 <(find ~/.hermes/skills -name SKILL.md | sed "s|$HOME/.hermes/skills/||;s|/SKILL.md||" | sort) <(find docs/skills/hermes-all -name SKILL.md | sed 's|docs/skills/hermes-all/||;s|/SKILL.md||' | sort) | tr '\n' ' ')")"
} | tee "$SNAP/memory_skills_sync.txt"

# ── ② 飞书端「场景叠加任务」公网通道端到端取证 (不信返回值, 当场回读)
{
  echo "# 公网叠加通道取证 $(date '+%F %T')"
  for u in "https://datadrive.world/ov/overlay?k=zmax-live" "https://datadrive.world/ov/wall.jpg?k=zmax-live"; do
    printf "%-52s " "$u"
    curl -s -o /tmp/_ov_probe.bin -w "HTTP %{http_code} %{size_download}B\n" --max-time 25 "$u"
  done
  printf "%-52s " "/ov/live.json (无口令: 应 403 只读闸门)"
  curl -s -o /dev/null -w "HTTP %{http_code}\n" --max-time 25 "https://datadrive.world/ov/live.json"
  printf "%-52s " "POST /ov/live.json (应 403)"
  curl -s -o /dev/null -w "HTTP %{http_code}\n" --max-time 25 -X POST -d '{}' "https://datadrive.world/ov/live.json"
} > "$SNAP/overlay_channel_verify.txt" 2>&1
curl -s --max-time 25 "https://datadrive.world/ov/live.json?k=zmax-live" -o "$SNAP/overlay_live_public.json"
cat "$SNAP/overlay_channel_verify.txt"

# ── ③ 判据 (离屏; 原始输出入快照)
QT_QPA_PLATFORM=offscreen $PY tools/verify_scene_phase_iteration_panel.py > "$SNAP/judge_scene_phase_panel.txt" 2>&1
$PY tools/verify_sphere_manifold.py                > "$SNAP/judge_sphere_manifold.txt" 2>&1
$PY tools/verify_meta_perf_matrix.py               > "$SNAP/judge_meta_perf_matrix.txt" 2>&1
$PY tools/verify_skill_physics_calls.py            > "$SNAP/judge_skill_physics_calls.txt" 2>&1
$PY tools/verify_skill_physics_calib.py            > "$SNAP/judge_skill_physics_calib.txt" 2>&1
for f in judge_scene_phase_panel judge_sphere_manifold judge_meta_perf_matrix judge_skill_physics_calls judge_skill_physics_calib; do
  printf "  %-26s %s\n" "$f" "$(grep -oE '[0-9]+/[0-9]+ (PASS|通过)|结论: ✅ 全过' "$SNAP/$f.txt" | tail -1)"
done

# ── ④ 工程库一致性 (漂移就重建)
$PY tools/engineering_db.py check > "$SNAP/engineering_db_check.txt" 2>&1
if grep -q "判据失败" "$SNAP/engineering_db_check.txt"; then
  $PY tools/engineering_db.py build >> "$SNAP/engineering_db_check.txt" 2>&1
  $PY tools/engineering_db.py check > "$SNAP/engineering_db_check.txt" 2>&1
fi
cp -f data/database/zmax/zmax_engineering.db "$SNAP/" 2>/dev/null
echo "  工程库: $(tail -1 "$SNAP/engineering_db_check.txt")"

# ── ⑤ 状态同步到公网 + 回读
/usr/bin/python3 tools/publish_status.py > "$SNAP/publish_status.txt" 2>&1
curl -s --max-time 25 "https://datadrive.world/zmax_status.json" -o "$SNAP/zmax_status_public.json"
echo "  公网状态: HTTP $(curl -s -o /dev/null -w '%{http_code}' --max-time 20 https://datadrive.world/zmax_status.json) $(stat -c%s "$SNAP/zmax_status_public.json")B"

# ── ⑥ git 真源点 + 台账
{ echo "commit: $(git rev-parse --short HEAD)"; echo "tag: $(git describe --tags --abbrev=0 2>/dev/null)"; echo "branch: $(git rev-parse --abbrev-ref HEAD)"; echo "at: $(date '+%F %T')"; } > "$SNAP/git_ref.txt"
cp -f docs/eval/元任务性能物理值全链验证_v5.50.735.md "$SNAP/" 2>/dev/null
cp -f docs/eval/Phase0_L2速度反馈延迟_全测_v5.50.735.md "$SNAP/" 2>/dev/null
cp -f docs/eval/归一化球面实现方案_落地_v5.50.735.md "$SNAP/" 2>/dev/null
cp -f docs/eval/评估分析页_场景迭代面板_v5.50.735.md "$SNAP/" 2>/dev/null
cp -f docs/memory/hermes-jingjing-memory-2026-10-16.md "$SNAP/" 2>/dev/null

# ── ⑦ 归档 + MANIFEST
rm -rf "$ARC"; mkdir -p "$ARC"; cp -f "$SNAP"/* "$ARC"/ 2>/dev/null
( cd "$ARC" && find . -type f ! -name 'MANIFEST.sha256' -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256 )
echo "  归档: ${ARC#*/} · $(find "$ARC" -type f | wc -l) 文件 · $(du -sh "$ARC" | cut -f1) · MANIFEST $(wc -l < "$ARC/MANIFEST.sha256") 条"
echo "✅ 快照就绪: ${SNAP#*/}"
