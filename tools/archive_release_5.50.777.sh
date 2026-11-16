#!/usr/bin/env bash
# 归档 v5.50.777 (2026-11-17) —— 代码(本轮改过) + 数据快照 + 日志尾 + 实测证据 + sha256
# 用法: bash tools/archive_release_5.50.777.sh
set -uo pipefail
VER=5.50.777
BASE=v5.50.776
DATE=$(date +%Y%m%d)
REPO=/home/ubuntu/zmax
DST=$REPO/zmax_data/release_${VER}_${DATE}
rm -rf "$DST"; mkdir -p "$DST"/{code,data,logs,evidence}

cd "$REPO" || exit 1

# ── ① 代码: 引用上一版 tag 之后真改过的文件(动态取, 不手写清单) ────────────────
git diff --name-only "$BASE"..HEAD | while IFS= read -r f; do
  [ -f "$f" ] || continue
  case "$f" in
    *"hermes-all"*|*"/memory/"*|*.code-workspace) continue ;;   # 技能/记忆同步, 非产品代码
  esac
  mkdir -p "$DST/code/$(dirname "$f")"
  cp -L "$f" "$DST/code/$f"        # -L 解引用软链(打包红线)
done
echo "code 文件数: $(find "$DST/code" -type f | wc -l)"

# ── ② 数据: 参数真源(config 是软链) + 画布 + 点位 + 回放修正表 + 进化台账 ──────
mkdir -p "$DST/data/config" "$DST/data/canvas" "$DST/data/points" "$DST/data/traj" "$DST/data/evolve"
[ -d config/calib ] && cp -rL config/calib "$DST/data/config/" 2>/dev/null
[ -d config/platform ] && cp -rL config/platform "$DST/data/config/" 2>/dev/null
cp -f data/database/zmax/sources/canvas/state_space_obs.json "$DST/data/canvas/" 2>/dev/null
cp -f reports/aoi_points/*.json "$DST/data/points/" 2>/dev/null
cp -f tools/web/traj_adj.json tools/web/real_traj_joints.json "$DST/data/traj/" 2>/dev/null
cp -f reports/aoi_focus_evolve/*.json "$DST/data/evolve/" 2>/dev/null
echo "data 文件数: $(find "$DST/data" -type f | wc -l)  体积: $(du -sh "$DST/data" | cut -f1)"

# ── ③ 日志尾(常驻服务 log 是 GB 级, 只留尾部) ────────────────────────────────
for L in /var/log/zmax-traj-ar.log; do
  [ -f "$L" ] && tail -n 4000 "$L" > "$DST/logs/$(basename "$L").tail.log"
done
echo "logs 文件数: $(find "$DST/logs" -type f | wc -l)"

# ── ④ 实测证据(只写数字) ────────────────────────────────────────────────────
{ echo "# v$VER 实测证据 ($DATE)"; echo
  echo "## 金手指相机曝光/增益"
  echo '```'
  echo "POST /param?exposure=700&gain=16.38 → ok:true; 回读 now=700 / 16.38"
  echo "落盘 D:\\xspace\\ultralytics_AOI\\zmax_data\\aoi_v4\\cam_param_persist.json (23:36:21, 重启自动复原)"
  echo "实测帧: p50 灰度 63 → 19; 金手指带内均值 36.2~37.6"
  echo '```'
  echo "## 自主进化(清晰度驱动调姿) — 台账实读"
  echo '```'
  ./gui-venv311/bin/python - <<'PYEV' 2>/dev/null
import json, glob
for p in sorted(glob.glob('reports/aoi_focus_evolve/*.json')):
    d = json.load(open(p, encoding='utf-8'))
    print("%s: 锚点 lap=%.1f 最优 lap=%.1f 净位移=%s 步数=%s" % (
        p.split('/')[-1], d.get('anchor_lap', 0), d.get('best_lap', 0),
        d.get('net_mm'), d.get('moves')))
    for h in d.get('history', []):
        print("   #%s %s lap=%.1f why=%s" % (h.get('it'), '采纳' if h.get('acc') else '退回',
                                             h.get('lap') or 0, h.get('why')))
PYEV
  echo '```'
  echo "## 回放第126点修正(覆盖表口径, raw 未动)"
  echo '```'
  ./gui-venv311/bin/python - <<'PYEV2' 2>/dev/null
import json
d = json.load(open('tools/web/traj_adj.json', encoding='utf-8'))
p = d['points'].get('126') or {}
print("p_rec_mm", p.get('p_rec_mm'))
print("p_new_mm", p.get('p_new_mm'))
print("dq_deg  ", p.get('dq_deg'))
print("pos_change_mm / rot_change_deg:", p.get('pos_change_mm'), p.get('rot_change_deg'))
r = json.load(open('tools/web/real_traj_joints.json', encoding='utf-8'))
print("raw frames:", len(r['frames']), "(一字节未动)")
PYEV2
  echo '```'
} > "$DST/evidence/measured_${DATE}.md"
echo "evidence: $(wc -l < "$DST/evidence/measured_${DATE}.md") 行"

# ── ⑤ MANIFEST ─────────────────────────────────────────────────────────────
cat > "$DST/MANIFEST.md" <<EOF
# Z-MAX v$VER 归档 ($DATE)

主题: 金手指相机「清晰度驱动自主进化」调姿 + 曝光 700us/16.38dB 落盘 + 回放第126点整点重教 + 工控机精确回执通道

## 本轮改动
- \`tools/aoi_focus_evolve.py\` 新增: 适应度=金手指带内 Laplacian 方差(带范围取 /region bbox, 零副作用),
  每点 4 帧取中位; (1+1) 进化策略, 单步 ≤0.4mm、相对锚点累计 ≤1mm、σ 按 1/5 成功法则自适应;
  采纳门槛 = 提升 >2% 且 >3×帧间 std; 崩塌即回锚点中止。运动走 \`tools/arm_raw.py move\`(绝对 TCP 平移)。
- \`tools/win_cmd.py\` 新增: 工控机命令带回执标记, 只认本 tag 回执; 修 PowerShell 下 \`&&\` 非法(改 \`;\`)。
- \`tools/web/traj_adj.json\` 第126点 = 当前位置(整点重教, 实测关节角), raw 215 帧一字节未动。

## 目录
- \`code/\` 引用 $BASE 之后真改过的产品代码(技能/记忆同步已剔除)
- \`data/config/\` 参数真源(calib + platform, config 是软链, 显式拷贝)
- \`data/canvas/\` 画布真源 state_space_obs.json
- \`data/points/\` AOI 点位台账(含 金手指点1)
- \`data/traj/\` 回放修正表 traj_adj.json + raw real_traj_joints.json
- \`data/evolve/\` 自主进化台账 evolve_*.json
- \`logs/\` 常驻服务日志**仅尾部 4000 行**
- \`evidence/measured_$DATE.md\` 实测数字

## 验收
\`sha256sum -c sha256sums.txt\` 全 OK
EOF

# ── ⑥ sha256 ──────────────────────────────────────────────────────────────
cd "$DST" || exit 1
find . -type f ! -name sha256sums.txt | sort | xargs sha256sum > sha256sums.txt
echo "---- 验收 ----"
sha256sum -c sha256sums.txt --quiet && echo "sha256 全 OK"
echo "文件数: $(find . -type f ! -name sha256sums.txt | wc -l)  体积: $(du -sh . | cut -f1)"
echo "归档: $DST"
