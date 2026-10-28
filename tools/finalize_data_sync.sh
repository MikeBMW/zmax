#!/usr/bin/env bash
# 收口: 把快照/归档改到真实当前版本 (v5.47.0), 刷新工程库与判据, 重建 MANIFEST, 入库
set -uo pipefail
cd /home/ubuntu/zmax
REPO=$(pwd)
OLD="docs/data_snapshots/2026-10-11_v5.42.0_配置驱动功能切换+场景叠加"
NEW="docs/data_snapshots/2026-10-11_状态同步_v5.47.0_配置驱动功能切换+场景叠加"
ARC_OLD="zmax_data/release_5.42.0_20261011"
ARC_NEW="zmax_data/release_sync_20261011_v5.47.0"

[ -d "$OLD" ] && mv "$OLD" "$NEW" && echo "① 快照改名 → ${NEW#*/}"
# 刷新工程库 (build 后已全绿) + 判据
cp -f data/database/zmax/zmax_engineering.db "$NEW/zmax_engineering.db"
./venvs/lerobot-venv/bin/python tools/engineering_db.py check > "$NEW/engineering_db_check.txt" 2>&1
echo "  工程库刷新: $(tail -1 "$NEW/engineering_db_check.txt" | cut -c1-60) · $(du -h "$NEW/zmax_engineering.db" | cut -f1)"
# git 唯一依据点刷新
{ echo "commit: $(git rev-parse --short HEAD)"; echo "tag: $(git describe --tags --abbrev=0 2>/dev/null)"; echo "branch: $(git rev-parse --abbrev-ref HEAD)"; } > "$NEW/git_ref.txt"
cat > "$NEW/README.md" <<'EOF'
# 数据快照 2026-10-11 · 状态同步 (当前版本 v5.47.0)

本轮动作 (老倪: 「同步飞书端的记忆，技能，以及飞书端完成的场景叠加任务，保存数据，同步信息」):

| 项 | 结果 (实测) |
|---|---|
| 记忆同步 | MEMORY.md → `docs/memory/hermes-jingjing-memory-2026-10-11.md` (+latest) · 内容与仓库一致 |
| 技能同步 | `docs/skills/xspace` 31 技能 + `docs/skills/hermes-all` **215 技能** 全量镜像 (含 sim-real-scene-overlay / zmax-scene-engineering) |
| 飞书端场景叠加任务 | 公网通道**端到端实测通**: `https://datadrive.world/ov/overlay?k=zmax-live` 等 4 条 200 · POST 403 (只读闸门) · `/ov/live.json` 1395B (三相机拼图+逐路叠加流) |
| 状态同步到公网 | `publish_status.py` → `zmax_status.json` 7182B 推送成功 (手机端实时状态) |
| 工程库一致性 | 发现漂移 `['canvas','manifold']` → `engineering_db.py build` 重建 → **判据全绿** (768 参数 / 1731 链接 / 184 连线) |
| 版本/发布 | 当前 tag **v5.47.0** · CI "Build Desktop (Windows .exe + macOS)" v5.47.0 构建中 (v5.46.0/v5.45.0 已 success) |

文件: zmax_engineering.db (重建后全绿) · engineering_db_check.txt · canvas_state_space_obs.json (md5 4d3824c6d63d, 89 节点/184 连线) ·
ss_task_run_TASK-01-FW_latest.json (插拔 686 步 success=True) · ss_task_run_TASK-06-TRAY_latest.json (摆盘 3/3 合格) ·
overlay_channel_verify.txt + overlay_live_public.json (飞书端通道) · zmax_status_public.json · release_status.json · git_ref.txt

未关项: ① 本机相机近黑 ⇒ 快层安全闸 fail-closed 拦发夹爪开爪 (非软件 bug, 不擅自关闸) ② 金手指整板原图现象待确认。
EOF
echo "② README 写好"

rm -rf "$ARC_NEW"; mkdir -p "$ARC_NEW"
cp -f "$NEW"/* "$ARC_NEW"/ 2>/dev/null
cp -f docs/notes/v5.42.0_配置驱动功能切换_20261010.md "$ARC_NEW/" 2>/dev/null
cp -f reports/tray_place_judge_20261010_181505.png "$ARC_NEW/" 2>/dev/null
( cd "$ARC_NEW" && find . -type f ! -name 'MANIFEST.sha256' -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256 )
[ -d "$ARC_OLD" ] && rm -rf "$ARC_OLD"
echo "③ 归档: ${ARC_NEW#*/} · $(find "$ARC_NEW" -type f | wc -l) 文件 · $(du -sh "$ARC_NEW" | cut -f1) · MANIFEST $(wc -l < "$ARC_NEW/MANIFEST.sha256") 条"

git add -A "docs/data_snapshots" "tools/save_data_v5_42_0.sh" docs/skills docs/memory 2>/dev/null
git -c user.name="$(git config user.name)" commit -q -m "存档: 2026-10-11 状态同步 (记忆/技能/飞书端场景叠加任务/工程库重建全绿) 快照 + 归档 MANIFEST" && echo "④ commit ok: $(git rev-parse --short HEAD)"
git push origin main 2>&1 | tail -2
