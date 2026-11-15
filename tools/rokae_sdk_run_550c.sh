#!/usr/bin/env bash
# rokae_sdk_run.sh — 550C 版执行入口 (2026-11-15)
#
# 和 4060 的同名脚本**接口一致**(8797 的调用方式一行都不用改), 但底层链路完全不同:
#   4060: Docker(ros:humble-ros-base) + 挂载 xcoresdk → 直连控制器 192.168.23.160
#   550C: 550C 上 docker daemon 起不来(systemctl is-active → failed), 且不允许改 Orin 现有服务
#         ⇒ 改走 Orin 的 zmax_arm_sdk_bridge.py(:39061), 逐点 POST /move_pose
#
# 为什么可以这样: real_traj_joints.json 每帧都带 p(米)/q(四元数)/j(关节角),
#   桥的 /move_pose 收的正是 p+q ⇒ 直接发末端位姿, 不需要 FK。
#
# 用法(与 4060 版相同):
#   bash tools/rokae_sdk_run.sh --script arm_step_traj.py          # 真走
#   bash tools/rokae_sdk_run.sh --script arm_step_traj.py --dry    # 只算不下发
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
PY="${ZMAX_PY:-/home/intel/gsxpu-venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"

ARGS=()
for a in "$@"; do
  case "$a" in
    --script) ;;                       # 后面的脚本名忽略(550C 只用桥执行器)
    arm_step_traj.py|arm_step_550c.py) ;;
    *) ARGS+=("$a") ;;
  esac
done

export ZMAX_REPO="$REPO"
export ZMAX_BRIDGE_URL="${ZMAX_BRIDGE_URL:-http://192.168.23.66:39061}"
exec "$PY" -u "$REPO/tools/rokae/arm_step_550c.py" "${ARGS[@]}"
