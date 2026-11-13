#!/usr/bin/env bash
# archive_snapshot_5_50_773_1330.sh — 5.50.773 第二轮保存点（含「同步操作」真机腿）
# 老倪 2026-11-13「保存数据，准备关机」
# 产物: zmax_data/snapshot_5.50.773_20261113_1330/
set -uo pipefail
cd "$(dirname "$0")/.."
VER=5.50.773
DATE=20261113
STAMP=1330
BASE=e94877ac                      # v5.50.772 tag（含 773 发布 + 同步操作全部改动）
DST="zmax_data/snapshot_${VER}_${DATE}_${STAMP}"

echo "═══ 保存点 v$VER → $DST ═══"
rm -rf "$DST"
mkdir -p "$DST"/{code,data,logs,evidence}

# ① 本轮改动的代码
echo "[1/7] 代码"
git diff --name-only "$BASE"..HEAD | while read -r f; do
  [ -f "$f" ] || continue
  case "$f" in
    *.py|*.sh|*.md|*.json|*.html|*.yml|*.yaml|*.conf) : ;;
    *) continue ;;
  esac
  case "$f" in
    *probe_*|*_tmp.py|*scratch*) continue ;;
    docs/3-天玑-能力功能/skills/hermes-all/*) continue ;;
  esac
  mkdir -p "$DST/code/$(dirname "$f")"
  cp "$f" "$DST/code/$f"
done
echo "     $(find "$DST/code" -type f | wc -l) 个文件"

# ② 参数真源
echo "[2/7] 参数真源"
mkdir -p "$DST/data/config"
for d in calib topics platform; do
  cp -r "data/database/zmax/sources/config/$d" "$DST/data/config/" 2>/dev/null
done
echo "     $(find "$DST/data/config" -type f | wc -l) 个文件"

# ③ 场景/画布/工程库
echo "[3/7] 场景数据"
mkdir -p "$DST/data/canvas"
cp data/database/zmax/sources/canvas/state_space_obs.json "$DST/data/canvas/" 2>/dev/null
cp data/database/zmax/zmax_engineering.db "$DST/data/" 2>/dev/null
echo "     canvas + engineering.db"

# ④ AR/回放/同步操作数据
echo "[4/7] AR + 同步操作数据"
mkdir -p "$DST/data/ar" "$DST/data/sync_step"
cp zmax_data/ar_mujoco/tray_pose_measured.json "$DST/data/ar/" 2>/dev/null
cp zmax_data/ar_mujoco/ar_station.xml "$DST/data/ar/" 2>/dev/null
cp tools/web/real_traj_joints.json "$DST/data/ar/" 2>/dev/null
# 真机逐点走：指令 / 实测日志 / 状态（这三份是「同步操作」真机腿的唯一执行凭证）
cp zmax_data/rokae_sdk/traj_step_cmd.json   "$DST/data/sync_step/" 2>/dev/null
cp zmax_data/rokae_sdk/traj_step_out.log    "$DST/data/sync_step/" 2>/dev/null
cp zmax_data/rokae_sdk/traj_step_state.json "$DST/data/sync_step/" 2>/dev/null
cp zmax_data/ctl_auth.json                  "$DST/data/sync_step/" 2>/dev/null
mkdir -p "$DST/evidence/img"
for j in /tmp/ar_sync/arm_tray_sync.jpg /tmp/ar_sync/tray_sync_3up.jpg \
         /tmp/ar_sync/rtraj_joints_done.jpg /tmp/ar_sync/syncstep_done.jpg; do
  [ -f "$j" ] && cp "$j" "$DST/evidence/img/"
done
echo "     $(find "$DST/data/ar" "$DST/data/sync_step" "$DST/evidence/img" -type f 2>/dev/null | wc -l) 个文件"

# ⑤ 关机前状态快照（链接 / GPU / 磁盘 / 真机）
echo "[5/7] 关机前快照"
{
  echo "# 关机前服务与链路快照 $(date '+%F %T')"
  echo
  echo "## 端口"
  ss -ltnp 2>/dev/null | grep -E ':(8791|8793|8797|8788|8802|8804|10082|10083)\b'
  echo
  echo "## GPU / 负载 / 磁盘"
  nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null
  uptime
  df -h /home 2>/dev/null | tail -1
  echo
  echo "## 真机（sdk_ctl state 最近一份）"
  ls -t zmax_data/rokae_sdk/logs/sdk_ctl_state_*.json 2>/dev/null | head -1 | xargs -r cat | head -c 1200
  echo
  echo "## 产线网"
  ip -br a 2>/dev/null | grep -v '^lo'
} > "$DST/logs/pre_shutdown_snapshot.txt" 2>&1
echo "     logs/pre_shutdown_snapshot.txt"

# ⑥ 实测证据
echo "[6/7] 证据"
{
  echo "# v$VER 保存点实测数字（$(date '+%Y-%m-%d %H:%M')）"
  echo
  echo "## 「同步操作」真机逐点走（tools/rokae/arm_step_traj.py，MoveAbsJ 关节角真值）"
  echo '```'
  ./gui-venv311/bin/python - <<'PY' 2>/dev/null
import json as _j
rows = []
for _l in open('zmax_data/rokae_sdk/traj_step_out.log'):
    _l = _l.strip()
    if _l.startswith('{') and chr(34)+'steps'+chr(34) in _l:
        rows.append(_j.loads(_l))
print('日志里共 %d 轮真机逐点' % len(rows))
for i, d in enumerate(rows):
    print('[%d] %d点 速度%.0f%% => ok=%s 走到位 %s/%s · %s' % (
        i + 1, d['n_req'], d['speed'], d['ok'], d.get('n_done'), d['n_req'], d.get('why')))
    print('    起始 %s deg' % d.get('joints_before_deg'))
    for s in d['steps']:
        print('    第%d点 跳变%.1f deg 误差%s deg 用时%s s' % (
            s['i'] + 1, s['max_jump_deg'], s.get('err_deg', '未走'), s.get('secs', '未走')))
PY
  echo '```'
  echo
  echo "## 页面侧同步（/ar3d 实测，浏览器采样）"
  echo '```'
  echo '  仿真 sim 与真值 real 六轴逐帧差 maxd = 0.0 ~ 0.3°（跟随循环 100ms 读 /api/tcp.joints）'
  echo '  文案序列: 仿真逐点 → 真机 第 k/N 点 → ✅ 真机走完 3/3 点 · 全部 3 点走到位'
  echo '  注: 3 点成功轮(日志已被下一轮覆盖, 数字取自当轮 tail): 15.33 / 6.74 / 9.16 s, 到位误差全 0.12°, n_done=3'
  echo '  修复前两真因: /api/tcp 字段是 joints(复数) 却读 d.joint ⇒ 跟随空转; 关节速度 5% 实测 0.3°/s 太慢'
  echo '```'
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
PY
  echo '```'
  echo
  echo "## CI 出包（本轮从 0 打通）"
  echo '```'
  echo '  run 43356488365 · head 0be09118 · Windows 27/27 success · macOS 22/22 success'
  echo '  资产: Z-MAX_Console.exe 206.7MB / win64-nounpack.zip 212.0MB / macOS.zip 122.8MB'
  echo '  修的四堵点: flows 软链不入库 / pack_guard+内联断言 cp1252 / 资产核验查已删目录 / policies-aoi 漏打'
  echo '```'
  echo
  echo "## 桌面缓冲区 BufferGraph"
  echo '```'
  echo '  verify_buffer_graph.py: PASS 54 / FAIL 0'
  echo '  verify_state100.py:     PASS 27 / FAIL 0（前 55 位零回归）'
  echo '```'
} > "$DST/evidence/measured_${DATE}.md"
echo "     evidence/measured_${DATE}.md"

# ⑦ MANIFEST
{
  echo "# v$VER 保存点（$DATE $STAMP）"
  echo
  echo "- 版本: $VER（未升号，老倪未指定新版本）"
  echo "- 基线: $BASE (v5.50.772)"
  echo "- 主题: 「同步操作」= 仿真先走 N 点 + 真机按同一批关节角帧逐点走 N 点；页面实时跟随真机"
  echo
  echo "## 目录"
  echo "- \`code/\` — git diff $BASE..HEAD 的代码改动"
  echo "- \`data/config/\` — 参数真源（calib / topics / platform）"
  echo "- \`data/canvas/state_space_obs.json\` — 画布真源"
  echo "- \`data/ar/\` — ar_station.xml + 料盘位姿台账 + real_traj_joints.json（215 帧）"
  echo "- \`data/sync_step/\` — 真机逐点执行凭证：cmd / out.log / state / ctl_auth"
  echo "- \`logs/pre_shutdown_snapshot.txt\` — 关机前 端口/GPU/磁盘/真机状态/产线网"
  echo "- \`evidence/measured_${DATE}.md\` — 实测数字"
  echo
  echo "## 本次关键改动"
  echo "1. \`tools/rokae/arm_step_traj.py\` — 真机逐点走（MoveAbsJ 关节绝对目标，每点等到位，失败即停）"
  echo "2. \`tools/tcp_ar_server.py\` — POST /api/arm/step_traj + GET status（异步 + 逐点进度），三道闸"
  echo "3. \`tools/web/tcp-ar.html\` — ⏭ 同步操作 + 点数输入 + 真机也走 + syncArmFollow 实时跟随"
  echo "4. \`tools/systemd/zmax-traj-ar-killmode.conf\` — KillMode=process（restart 不打断真机任务）"
  echo "5. CI: \`.github/workflows/build-win-exe.yml\` + \`tools/pack_guard.py\` + \`.gitignore\` 四处修"
  echo
  echo "## 未做 / 待办"
  echo "- 料盘 yaw 校正证据不足（已回滚，applied=false）"
  echo "- 演示视频未内置（datadrive.world 从 runner 下载失败，老倪自行处理）"
  echo "- 10082 曝光档位未定（在线写被拒，现 20000us×8）"
} > "$DST/MANIFEST.md"

# sha256
( cd "$DST" && find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt )

echo
echo "═══ 校验 ═══"
( cd "$DST" && sha256sum -c sha256sums.txt --quiet && echo "✅ sha256 全 OK" || echo "❌ 有不一致" )
echo "文件数: $(find "$DST" -type f | wc -l)   体积: $(du -sh "$DST" | cut -f1)"
