#!/bin/bash
# 备份"原轨迹"(215 点录制) 及其派生数据, 出 sha256 清单。
# 用法: bash tools/backup_traj_215.sh [tag]
set -u
cd /home/ubuntu/zmax || exit 1
TS=$(date +%Y%m%d_%H%M%S)
TAG=${1:-$TS}
DST="zmax_data/traj_backup/traj_215_${TAG}"
mkdir -p "$DST/files"

FILES=(
  "tools/web/real_traj_joints.json"
  "tools/web/real_traj_grip.json"
  "tools/web/traj_adj.json"
  "zmax_data/rokae_sdk/traj_phase.json"
  "zmax_data/rokae_sdk/traj_hopf.json"
  "zmax_data/rokae_sdk/traj_step_cmd.json"
  "zmax_data/rokae_sdk/traj_step_state.json"
  "zmax_data/se3_layers/layers_215.json"
  "zmax_data/se3_layers/selftest.json"
)
# 跑批日志 (可能多份)
for f in zmax_data/rokae_sdk/traj_step_geom*.log zmax_data/rokae_sdk/traj_step_flow_full_*.log; do
  [ -f "$f" ] && FILES+=("$f")
done

n=0
: > "$DST/sha256sums.txt"
for f in "${FILES[@]}"; do
  [ -f "$f" ] || { echo "  !! 缺失 $f" >&2; continue; }
  cp -p "$f" "$DST/files/"
  sha256sum "$f" >> "$DST/sha256sums.txt"
  n=$((n+1))
done

{
  echo "# 原轨迹备份 (215 点录制, 2026-11-11 采, rec_20261111_181020)"
  echo
  echo "- 备份时间: $(date '+%F %T %Z')"
  echo "- 目的: 老倪 2026-11-19 起改用**新轨迹(实际抓取光模块)**, 旧轨迹留档, 防被覆盖"
  echo "- 文件数: $n"
  echo
  echo '## 口径'
  echo '- `real_traj_joints.json`: 215 帧 `p(m)/q(x,y,z,w)/j(rad)/t(s)` —— 轨迹真值, **只读锁**: 任何新轨迹都不许写它'
  echo '- `traj_phase.json`: 相位 s(i)/s_mm (L_open 7861.8mm, seam 3.91mm, s_214=0.9995)'
  echo '- `traj_hopf.json`: 每帧 n(S²)/phi(S¹)'
  echo '- `layers_215.json`: 五流形逐帧 (A/B/C/D/E + TQ)'
  echo '- `traj_step_geom*.log` / `traj_step_flow_full_*.log`: 整轮跑批分块日志 (37 块/475.9s 与 36 块/477.6s)'
  echo
  echo '## 校验'
  echo '```'
  echo "cd $(pwd) && sha256sum -c $DST/sha256sums.txt"
  echo '```'
} > "$DST/MANIFEST.md"

echo "[backup] $DST · $n 个文件"
cat "$DST/sha256sums.txt"
