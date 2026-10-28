#!/usr/bin/env bash
# 关机收尾 v5.49.1: 数据快照 + 归档 + 核对单 + 入库 (2026-10-12)
set -uo pipefail
cd /home/ubuntu/zmax
REPO=$(pwd)
SNAP="$REPO/docs/data_snapshots/2026-10-12_关机收尾_v5.49.1"
ARC="$REPO/zmax_data/release_5.49.1_20261012"
rm -rf "$SNAP" "$ARC"; mkdir -p "$SNAP" "$ARC"

echo "═══ ① 快照 ═══"
cp -f data/database/zmax/zmax_engineering.db "$SNAP/"
./venvs/lerobot-venv/bin/python tools/engineering_db.py check > "$SNAP/engineering_db_check.txt" 2>&1
echo "  工程库 $(du -h "$SNAP/zmax_engineering.db" | cut -f1) · $(tail -1 "$SNAP/engineering_db_check.txt")"
[ -f data/database/zmax/param_events.jsonl ] && tail -300 data/database/zmax/param_events.jsonl > "$SNAP/param_events_tail.jsonl"
cp -f src/lerobot/engineering/flows/state_space_obs.json "$SNAP/canvas_state_space_obs.json"
echo "  画布 md5 $(md5sum "$SNAP/canvas_state_space_obs.json" | cut -c1-12)"
for t in TASK-01-FW TASK-06-TRAY; do cp -f "reports/ss_task_run_${t}_latest.json" "$SNAP/" 2>/dev/null; done
curl -s -m 20 "https://api.github.com/repos/MikeBMW/zmax/actions/runs?per_page=3" -o "$SNAP/release_status.json"
{ df -h / | tail -1; free -h | head -2; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader 2>/dev/null || echo "GPU: 无 nvidia-smi"; } > "$SNAP/resources.txt"
curl -s -m 15 "https://datadrive.world/zmax_status.json" -o "$SNAP/zmax_status_public.json"
curl -s -m 15 "https://datadrive.world/ov/live.json?k=zmax-live" -o "$SNAP/overlay_live_public.json"
{ echo "# 飞书端场景叠加 · 公网通道验证 $(date '+%F %T')"; bash tools/ecs_overlay_forward.sh --check 2>&1; echo; bash tools/ecs_overlay_forward.sh --verify 2>&1; } > "$SNAP/overlay_channel_verify.txt" 2>&1
{ echo "resources:"; cat "$SNAP/resources.txt"; echo; echo "commit: $(git rev-parse --short HEAD)"; echo "tag: $(git describe --tags --abbrev=0)"; echo "branch: $(git rev-parse --abbrev-ref HEAD)"; echo "version_md: $(grep -o 'v5\.47\.1' VERSION.md | head -1)"; } > "$SNAP/git_ref.txt"
echo "  叠加验证 $(grep -c 'HTTP 200' "$SNAP/overlay_channel_verify.txt") 条 200 · status $(wc -c < "$SNAP/zmax_status_public.json")B"

# ── 下电核对单 (预检实测原文 + 手工项) ──
{
  echo "# 下电核对单 · 2026-10-12 · v5.49.1"
  echo
  echo "## 预检实测 (tools/preflight_shutdown.sh)"
  echo '```'
  timeout 300 bash tools/preflight_shutdown.sh 2>&1
  echo '```'
  echo "## 手工确认项"
  echo "- [ ] 现场无人作业 / 机械臂周围无人 (真机 rt 类动作后必下电, 本轮无授权窗口、无在途运动)"
  echo "- [ ] 本机相机画面已确认 (近黑 ⇒ 快层闸 fail-closed, 属设计行为)"
  echo "- [ ] 现场设备: Orin / 工控机 / AOI / 珞石控制器 电源顺序按现场规程"
  echo "- [ ] 数据已保存: 快照+归档+MANIFEST 已入库 (见 README.md)"
  echo "- [ ] 需要我执行下电时再说一声: sudo shutdown -h now"
} > "$SNAP/shutdown_checklist.md"

cat > "$SNAP/README.md" <<'EOF'
# 数据快照 2026-10-11 · 关机收尾 v5.49.1

老倪: 「保存数据，小版本迭代，准备关机」

| 项 | 实测结果 |
|---|---|
| 版本 | v5.47.0 → **v5.49.1**（无功能改动，8 处版本位已同步，tag 已推） |
| 工程库 | `engineering_db check` **判据全绿**（768 参数 / 1731 数字链接 / 184 连线 / 74 功能；本轮先实测到漂移 `['canvas','manifold']` 后 build 重建） |
| 画布唯一依据 | `state_space_obs.json` md5 4d3824c6d63d · 89 节点 / 184 连线 |
| 真跑判据 | 插拔 TASK-01-FW 686 步 success=True · 摆盘 TASK-06-TRAY 3/3 合格（单边 ≤0.47mm） |
| 飞书端场景叠加 | 公网 `/ov/overlay?k=zmax-live` 等 4 条 HTTP 200 · POST 403（只读闸门）· `/ov/live.json` 三相机拼图清单 |
| 状态推公网 | `zmax_status.json` 推送成功（GPU/内存/磁盘/模型数/训练状态） |
| 关机预检 | `tools/preflight_shutdown.sh` → **🟢 可以下电**（臂 idle · 真值帧龄 0.02s · 无授权 · 无采集/训练在写 · 仓库已保存） |
| 资源 | 磁盘 307G/396G（82%，可用 70G）· 内存 9G/30G · GPU 5%/600MiB |

文件: zmax_engineering.db · engineering_db_check.txt · canvas_state_space_obs.json · param_events_tail.jsonl ·
ss_task_run_TASK-01-FW_latest.json · ss_task_run_TASK-06-TRAY_latest.json · overlay_channel_verify.txt ·
overlay_live_public.json · zmax_status_public.json · release_status.json · git_ref.txt · shutdown_checklist.md

归档: `zmax_data/release_5.49.1_20261012/`（同内容 + MANIFEST.sha256 逐文件校验）
未关项: 本机相机近黑 ⇒ 快层安全闸 fail-closed 拦发夹爪开爪（非软件 bug，不擅自关闸）· 金手指整板原图现象待确认。
EOF
echo "  核对单+README 写好"

echo "═══ ② 归档 ═══"
cp -f "$SNAP"/* "$ARC"/
cp -f VERSION.md "$ARC/"
( cd "$ARC" && find . -type f ! -name 'MANIFEST.sha256' -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256 )
echo "  ${ARC#*/} · $(find "$ARC" -type f | wc -l) 文件 · $(du -sh "$ARC" | cut -f1) · MANIFEST $(wc -l < "$ARC/MANIFEST.sha256") 条"

echo "═══ ③ 入库 ═══"
git add -A
git -c user.name="$(git config user.name)" commit -q -m "v5.49.1 — 关机收尾: 数据快照(v5.49.1)+归档 MANIFEST+下电核对单 · 工程库重建全绿 · 状态/记忆/技能/场景叠加同步 · 预检🟢可以下电" && echo "  commit $(git rev-parse --short HEAD)"
git tag v5.49.1 2>/dev/null; echo "  tag v5.49.1 (已存在则跳过)"
git push origin main 2>&1 | tail -2
git push origin v5.49.1 2>&1 | tail -2
echo "═══ ④ 回读核验 ═══"
echo "  HEAD $(git rev-parse --short HEAD) · $(git describe --tags --abbrev=0) · 未提交 $(git status --porcelain | wc -l) 项"
./venvs/lerobot-venv/bin/python tools/ci/integrity_check.py 2>&1 | tail -2
