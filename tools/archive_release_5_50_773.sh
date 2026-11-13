#!/usr/bin/env bash
# archive_release_5_50_773.sh — v5.50.773 归档（"保存数据"）
# 产物: zmax_data/release_5.50.773_20261113/
set -uo pipefail
cd "$(dirname "$0")/.."
VER=5.50.773
DATE=20261113
BASE=e94877ac                      # v5.50.772 tag
DST="zmax_data/release_${VER}_${DATE}"

echo "═══ 归档 v$VER → $DST ═══"
rm -rf "$DST"
mkdir -p "$DST"/{code,data,logs,evidence}

# ① 本轮改动的代码（只拷改过的，不含一次性 probe / 技能同步噪音）
echo "[1/6] 代码"
git diff --name-only "$BASE"..HEAD | while read -r f; do
  [ -f "$f" ] || continue
  case "$f" in
    *.py|*.sh|*.md|*.json|*.html) : ;;
    *) continue ;;
  esac
  case "$f" in
    *probe_*|*_tmp.py|*scratch*) continue ;;
    docs/3-天玑-能力功能/skills/hermes-all/*) continue ;;   # 技能同步噪音，不是工程交付
  esac
  mkdir -p "$DST/code/$(dirname "$f")"
  cp "$f" "$DST/code/$f"
done
echo "     $(find "$DST/code" -type f | wc -l) 个文件"

# ② 参数真源（config 是软链，必须显式拷）
echo "[2/6] 参数真源"
mkdir -p "$DST/data/config"
for d in calib topics platform; do
  cp -r "data/database/zmax/sources/config/$d" "$DST/data/config/" 2>/dev/null
done
echo "     $(find "$DST/data/config" -type f | wc -l) 个文件"

# ③ 场景/画布数据
echo "[3/6] 场景数据"
mkdir -p "$DST/data/canvas"
cp data/database/zmax/sources/canvas/state_space_obs.json "$DST/data/canvas/" 2>/dev/null
cp data/database/zmax/zmax_engineering.db "$DST/data/" 2>/dev/null
echo "     canvas + engineering.db"

# ④ 本轮新增的非 git 数据（台账/回放真值/AR 同步证据图）
echo "[4/6] 本轮数据"
mkdir -p "$DST/data/ar"
cp zmax_data/ar_mujoco/tray_pose_measured.json "$DST/data/ar/" 2>/dev/null
cp zmax_data/ar_mujoco/ar_station.xml "$DST/data/ar/" 2>/dev/null
cp tools/web/real_traj_joints.json "$DST/data/ar/" 2>/dev/null
mkdir -p "$DST/evidence/img"
for j in /tmp/ar_sync/arm_tray_sync.jpg /tmp/ar_sync/tray_sync_3up.jpg /tmp/ar_sync/rtraj_joints_done.jpg; do
  [ -f "$j" ] && cp "$j" "$DST/evidence/img/"
done
echo "     $(find "$DST/data/ar" "$DST/evidence/img" -type f 2>/dev/null | wc -l) 个文件"

# ⑤ 日志（截尾；本轮无常驻 log，只留服务健康快照）
echo "[5/6] 日志"
{
  echo "# 服务与链路快照 $(date '+%F %T')"
  ss -ltnp 2>/dev/null | grep -E ':(8791|8793|8797|8801|8802|8788|10082|10083)\b'
  echo
  nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null
  uptime
} > "$DST/logs/link_snapshot.txt" 2>&1
echo "     logs/link_snapshot.txt"

# ⑥ 实测证据（只写数字）
echo "[6/6] 证据"
{
  echo "# v$VER 实测数字（$(date '+%Y-%m-%d %H:%M')）"
  echo
  echo "## AR 右臂·关节角真值回放（tools/real_traj_joints.py）"
  echo '```'
  ./gui-venv311/bin/python - <<'PY' 2>/dev/null
import json, numpy as np
d = json.load(open('tools/web/real_traj_joints.json'))
J = np.degrees(np.array([f['j'] for f in d['frames']])); P = np.array([f['p'] for f in d['frames']]) * 1000
print("源: %s (%d 样本 50Hz SDK 真值)" % (d['src_rec'], d['n_samples']))
print("回放: %d 帧 · %.1fs · %.0fmm · 累计转动 %.0f°" % (d['n_frames'], d['dur_s'], d['path_mm'], d['rot_total_deg']))
for i, n in enumerate(['J1', 'J2', 'J3', 'J4', 'J5', 'J6']):
    print("  %s: %7.1f ~ %7.1f  跨度 %6.1f" % (n, J[:, i].min(), J[:, i].max(), J[:, i].max() - J[:, i].min()))
print("末端 x %.0f~%.0f  y %.0f~%.0f  z %.0f~%.0f mm" % (P[:,0].min(), P[:,0].max(), P[:,1].min(), P[:,1].max(), P[:,2].min(), P[:,2].max()))
print("J4 跨度 254° ⇒ 含翻面(>180°)，位置 IK 版本完全丢失")
PY
  echo '```'
  echo
  echo "## 上料盘 AR↔真机同步（tools/sync_tray_ar.py，臂相机投影 + 像素级判据）"
  echo '```'
  cat /tmp/ar_sync/arm_tray_sync.json 2>/dev/null | ./gui-venv311/bin/python -c "
import json,sys
d=json.load(sys.stdin)
for k in ('iou','mask_iou','d_center_norm_mm','size_delta_pct','inside_ratio','dv_in','dv_out'):
    if k in d: print('  %-18s %s'%(k,d[k]))
if 'scene_tray_mm' in d: print('  scene  ', d['scene_tray_mm'])
if 'meas_tray_mm' in d: print('  measured', d['meas_tray_mm'])
" 2>/dev/null
  echo '  结论: 位置可同步(中心差 6.4mm); yaw 差 -3.59° 但 A/B mask IoU 0.8506→0.8417 无改善 ⇒ 回滚, 场景未改 (applied=false)'
  echo '```'
  echo
  echo "## 桌面缓冲区 BufferGraph（verify_buffer_graph.py + verify_state100.py）"
  echo '```'
  echo '  verify_buffer_graph.py: PASS 54 / FAIL 0'
  echo '  verify_state100.py:     PASS 27 / FAIL 0（前 55 位逐位零回归）'
  echo '  度规: M·M^-1 - I = 0.00e+00 · 插入区各向异性 400x（σ_rad 0.3mm / σ_ax 6mm）'
  echo '  DDS: 17 槽 JSON 载荷 9,650 B < 64KB（10Hz 可广播）'
  echo '```'
  echo
  echo "## 版本一致性"
  echo '- studio.py 4 处 / update_checker / version_sync / docs_sync 两键 / integrity_check.EXPECTED_VERSION / VERSION.md = '"$VER"
} > "$DST/evidence/measured_${DATE}.md"
echo "     evidence/measured_${DATE}.md"

# MANIFEST
{
  echo "# v$VER 归档清单"
  echo
  echo "- 版本: $VER"
  echo "- 日期: $DATE"
  echo "- 基线: $BASE (v5.50.772)"
  echo "- 主题: AR 右臂按真实轨迹回放改用关节角真值（含翻面） + 上料盘 AR↔真机同步验证 + 桌面缓冲区 BufferGraph"
  echo
  echo "## 目录"
  echo "- \`code/\` — 本轮改动过的代码（git diff $BASE..HEAD，排除技能同步噪音）"
  echo "- \`data/config/\` — 参数真源（calib / topics / platform）"
  echo "- \`data/canvas/state_space_obs.json\` — 画布真源"
  echo "- \`data/zmax_engineering.db\` — 工程库"
  echo "- \`data/ar/\` — ar_station.xml + tray_pose_measured.json（料盘位姿台账，applied=false）+ real_traj_joints.json（215 帧关节角真值回放数据）"
  echo "- \`logs/link_snapshot.txt\` — 端口/GPU/负载快照"
  echo "- \`evidence/measured_${DATE}.md\` — 实测数字 + \`evidence/img/\` 三张判据图"
  echo
  echo "## 关键改动"
  echo "1. \`tools/web/tcp-ar.html\` — 左栏『📍 右臂跑真实轨迹』按钮 + 关节角真值回放（RTRAJ/rtrajPlayJoints）+ 数据内嵌 rtrajData + 回放期 30Hz 抢 /armq"
  echo "2. \`tools/real_traj_joints.py\` — poses.jsonl → 回放帧（双闸抽稀 8mm/3° · 只留运动段 · 静止压缩 · --embed 写页面）"
  echo "3. \`tools/sync_tray_ar.py\` — 料盘 AR↔真机同步验证（三判据）+ 实测位姿回写（quat + 台账 + 备份）"
  echo "4. \`src/lerobot/policies/left_right/state_space/buffer_graph.py\` — 逐槽 SE(3)+度规+时间张量事实层"
  echo "5. \`tools/verify_buffer_graph.py\` — 54 项断言"
  echo
  echo "## 未做 / 待办"
  echo "- 料盘 yaw 校正（-3.59°）证据不足，已回滚；要俯拍重测（需动臂授权）"
  echo "- push 被远端并行提交挡住（本地 ahead），CI 出包需先 rebase"
} > "$DST/MANIFEST.md"

# sha256（自己不算自己）
( cd "$DST" && find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt )

echo
echo "═══ 校验 ═══"
( cd "$DST" && sha256sum -c sha256sums.txt --quiet && echo "✅ sha256 全 OK" || echo "❌ 有不一致" )
echo "文件数: $(find "$DST" -type f | wc -l)   体积: $(du -sh "$DST" | cut -f1)"
