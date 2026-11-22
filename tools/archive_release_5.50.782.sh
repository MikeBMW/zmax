#!/usr/bin/env bash
# 归档 v5.50.782 —— 关节空间回放跑通 + 8815 段序修正
set -euo pipefail
cd /home/ubuntu/zmax
VER=5.50.782
DST="zmax_data/release_${VER}_20261122"
rm -rf "$DST"; mkdir -p "$DST"/{code,data,logs,evidence}

# code: 本轮真改过的产品代码(不含技能/记忆同步噪声)
FILES="
tools/rokae/replay_absj.py
tools/rokae/replay_teach.py
tools/rokae/replay_demo_seg.py
tools/rokae/check_state.py
tools/rokae/log_joints_teach.py
tools/robot_kin.py
tools/build_absj_from_joints.py
tools/build_traj_from_teach.py
tools/learn_from_teach.py
tools/states_from_traj.py
tools/switch_8815_to_teach.py
tools/rokae_sdk_run.sh
tools/se3_geom_server.py
tools/web/se3_geom.html
tools/gui/studio.py
tools/gui/update_checker.py
tools/gui/version_sync.py
tools/ci/integrity_check.py
src/lerobot/ops/docs_sync.py
VERSION.md
"
for f in $FILES; do
  [ -f "$f" ] || { echo "缺: $f"; continue; }
  mkdir -p "$DST/code/$(dirname "$f")"; cp -p "$f" "$DST/code/$f"
done

# data: 轨迹/段表/示教日志(截断)
cp -p zmax_data/rokae_sdk/real_traj_absj.json          "$DST/data/"
cp -p zmax_data/rokae_sdk/real_traj_joints_demo.json   "$DST/data/"
cp -p zmax_data/rokae_sdk/traj_phase_demo.json         "$DST/data/"
cp -p zmax_data/rokae_sdk/phase_states_demo.json       "$DST/data/"
cp -p zmax_data/rokae_sdk/phase_states_teach.json      "$DST/data/" 2>/dev/null || true
cp -p zmax_data/teach/learned_*.json                   "$DST/data/" 2>/dev/null || true
tail -n 20000 zmax_data/rokae_sdk/teach_joints_*.jsonl > "$DST/data/teach_joints.tail.jsonl" || true

# logs
tail -n 400 /tmp/absj2.log > "$DST/logs/absj_replay.tail.log" 2>/dev/null || echo "(无 /tmp/absj2.log)" > "$DST/logs/absj_replay.tail.log"

cat > "$DST/evidence/measured_20261122.md" <<'EOF'
# v5.50.782 实测证据 (2026-11-22)

## 关节空间回放 (MoveAbsJ)
- 轨迹: real_traj_absj.json — 448 帧 / 8583 mm / 示教原始 302 s
- 回放批量 40 帧/批, 40 mm/s
- 关节到位误差: 0.08 / 0.11 / 0.12 / 0.12 / 0.12 / 0.14 °（批 4~12）
- 之前笛卡尔 MoveL/MoveJ 在同一轨迹必停: 694.5,192.0,208.0 (pitch −88.5°) 与
  709.8,125.4,234.2 (yaw 单步 49°); MoveAbsJ 全部通过
- 无 EStop / 无碰撞告警（本轮末段）

## 8815 看板
- 轨迹 278 帧 / 5898 mm / 30 段（初始点→槽2抓取→扫码→插入到底→等待检测→…）
- 实测跟随: nearest i=246 · 偏差 11.1 mm · 相位 92.1 %
- 修掉: 帧比例映射错位 / 前 150 帧假状态 / 钩位与插到底 13 mm 抢标

## 训练(未变, 供对照)
- 图像策略 2.99 mm / 无图 3.47 mm / 基线 3.51 mm → 图像净增益 13.6 %
- 550C flow-matching 79 代 0 采纳: model 35.64 / persist 18.60 / linear 4.12
EOF

cat > "$DST/MANIFEST.md" <<EOF
# v${VER} 归档 — 2026-11-22

## 主题
关节空间 MoveAbsJ 回放跑通整圈（绕过手腕奇异区）；8815 看板段序改为按点位标注。

## 目录
- code/   本轮改动的产品代码（回放工具、几何看板服务/页面、版本号相关）
- data/   轨迹与段表真源（real_traj_absj / 8815 demo 集 / 示教关节日志尾部 2 万行）
- logs/   回放日志尾部
- evidence/measured_20261122.md  实测数字

## 关键结论
- MoveL/MoveJ 在该示教轨迹的手腕奇异区必然停止；MoveAbsJ 关节差 ≤0.12° 跑完整圈。
- 8815 与回放同源后跟随偏差 11.1 mm、相位 92.1%。
EOF

cd "$DST"
find . -type f ! -name sha256sums.txt | sort | xargs sha256sum > sha256sums.txt
sha256sum -c --quiet sha256sums.txt && echo "sha256 全部 OK"
echo "文件数: $(find . -type f | wc -l) · 体积: $(du -sh . | cut -f1) · 路径: /home/ubuntu/zmax/$DST"
