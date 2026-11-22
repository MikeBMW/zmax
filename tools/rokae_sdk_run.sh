#!/usr/bin/env bash
# rokae_sdk_run.sh — 本机(4060) 独立 SDK 直连控制的唯一入口。
#
# 口径(2026-10-07 老倪现场指令): 「不要改变 orin 原来的任何服务。你可以直接调用SDK，但要独立实现」
#   · 全程**不碰 Orin**: 不读不写 Orin 的文件/单元/服务, 不前不后依赖它的 ROS/DDS/驱动栈
#   · 走厂家 xCoreSDK(x86_64) 直连控制器 192.168.23.160; SDK 是 cpython-310 ⇒ 必须容器里跑
#   · 脚本本体在**仓库**里(tools/rokae/sdk_ctl.py), 以只读方式挂进容器 ⇒ 无副本漂移
#   · 只挂 ~/zmax/zmax_data/rokae_sdk(服务端 SDK + 采样落盘 + 证据目录), -w /sdk 因为 SDK 要写 logs/
#
# 用法:
#   bash tools/rokae_sdk_run.sh state                      # 只读: 电源/状态/模式/报警/位姿/关节
#   bash tools/rokae_sdk_run.sh pose
#   bash tools/rokae_sdk_run.sh move-rel --dz 1.0 --speed 5   # 相对运动(mm, 姿态不变)
#   bash tools/rokae_sdk_run.sh stop | reset
set -euo pipefail

SDK_DIR="${ZMAX_SDK_DIR:-/home/ubuntu/zmax/zmax_data/rokae_sdk}"
REPO_TOOLS="$(cd "$(dirname "$0")" && pwd)/rokae"
IMAGE="${ZMAX_SDK_IMAGE:-ros:humble-ros-base}"

# --script <name> : 跑 /repo/<name> 而不是默认的 sdk_ctl.py (2026-10-20 加, 给力控插入用)
SCRIPT="sdk_ctl.py"
if [ "${1:-}" = "--script" ]; then SCRIPT="$2"; shift 2; fi

if [ ! -d "$SDK_DIR/xcoresdk_python" ]; then
  echo "⛔ 找不到 SDK: $SDK_DIR/xcoresdk_python (先从 Orin 拷一份, 见技能 rokae-direct-control)" >&2
  exit 2
fi

exec sudo docker run --rm --network host \
  -e ZMAX_HOST_TS="$(date +%s)" \
  -e ZMAX_ROBOT_IP="${ZMAX_ROBOT_IP:-192.168.23.160}" \
  -e ZMAX_REPLAY_N="${ZMAX_REPLAY_N:-}" \
  -e ZMAX_REPLAY_SPEED="${ZMAX_REPLAY_SPEED:-}" \
  -e ZMAX_REPLAY_ZONE="${ZMAX_REPLAY_ZONE:-}" \
  -e ZMAX_REPLAY_CHUNK="${ZMAX_REPLAY_CHUNK:-}" \
  -e ZMAX_REPLAY_BUDGET_X="${ZMAX_REPLAY_BUDGET_X:-}" \
  -e ZMAX_REPLAY_CMD="${ZMAX_REPLAY_CMD:-}" \
  -e ZMAX_REPLAY_TRAJ="${ZMAX_REPLAY_TRAJ:-}" \
  -e ZMAX_RT_TRAJ="${ZMAX_RT_TRAJ:-}" \
  -e ZMAX_MOVE_TYPE="${ZMAX_MOVE_TYPE:-}" \
  -e ZMAX_NO_EXPAND="${ZMAX_NO_EXPAND:-}" \
  -e ZMAX_PTS_FROM="${ZMAX_PTS_FROM:-}" \
  -e ZMAX_PTS_TO="${ZMAX_PTS_TO:-}" \
  -e ZMAX_REPLAY_FAST="${ZMAX_REPLAY_FAST:-}" \
  -e ZMAX_REPLAY_RESUME="${ZMAX_REPLAY_RESUME:-}" \
  -e ZMAX_SEG_NAME="${ZMAX_SEG_NAME:-}" \
  -e ZMAX_SEG_SPEED="${ZMAX_SEG_SPEED:-}" \
  -e ZMAX_SEG_TRAJ="${ZMAX_SEG_TRAJ:-}" \
  -e ZMAX_SEG_STATES="${ZMAX_SEG_STATES:-}" \
  -e ZMAX_SEG_MAXDEG="${ZMAX_SEG_MAXDEG:-}" \
  -e ZMAX_SEG_MAXMM="${ZMAX_SEG_MAXMM:-}" \
  -e ZMAX_BOX_ZMAX="${ZMAX_BOX_ZMAX:-}" \
  -e ZMAX_REPLAY_BATCH="${ZMAX_REPLAY_BATCH:-}" \
  -e ZMAX_REPLAY_RESUME="${ZMAX_REPLAY_RESUME:-}" \
  -e ZMAX_ROT_IN_PLACE="${ZMAX_ROT_IN_PLACE:-}" \
  -e ZMAX_RT_I0="${ZMAX_RT_I0:-}" \
  -e ZMAX_RT_I1="${ZMAX_RT_I1:-}" \
  -e ZMAX_RT_RATE="${ZMAX_RT_RATE:-}" \
  -e ZMAX_RT_MAXDEG="${ZMAX_RT_MAXDEG:-}" \
  -e ZMAX_RT_LOGDIR="${ZMAX_RT_LOGDIR:-}" \
  -e ZMAX_RT_VMAX="${ZMAX_RT_VMAX:-}" \
  -e ZMAX_RT_MODE="${ZMAX_RT_MODE:-}" \
  -e ZMAX_RT_BUDGET="${ZMAX_RT_BUDGET:-}" \
  -e ZMAX_RT_AMAX="${ZMAX_RT_AMAX:-}" \
  -e ZMAX_RT_BUDGET2="${ZMAX_RT_BUDGET2:-}" \
  -e ZMAX_RT_MEAS="${ZMAX_RT_MEAS:-}" \
  -e ZMAX_RT_ALIGN_TOL="${ZMAX_RT_ALIGN_TOL:-}" \
  -e ZMAX_RT_SMOOTH="${ZMAX_RT_SMOOTH:-}" \
  -e ZMAX_RT_COLLISION="${ZMAX_RT_COLLISION:-}" \
  -e ZMAX_RT_SECS="${ZMAX_RT_SECS:-}" \
  -e ZMAX_RT_STATE="${ZMAX_RT_STATE:-}" \
  -e ZMAX_RT_NO_STOPLOOP="${ZMAX_RT_NO_STOPLOOP:-}" \
  -e ZMAX_RT_TLIM="${ZMAX_RT_TLIM:-}" \
  -e ZMAX_RT_FILTER="${ZMAX_RT_FILTER:-}" \
  -e ZMAX_RT_LAG="${ZMAX_RT_LAG:-}" \
  -e ZMAX_PP_I0="${ZMAX_PP_I0:-}" \
  -e ZMAX_PP_I1="${ZMAX_PP_I1:-}" \
  -e ZMAX_PP_SPEED="${ZMAX_PP_SPEED:-}" \
  -e ZMAX_PP_DWELL="${ZMAX_PP_DWELL:-}" \
  -e ZMAX_PP_CHUNK="${ZMAX_PP_CHUNK:-}" \
  -e ZMAX_PP_TMO="${ZMAX_PP_TMO:-}" \
  -e ZMAX_PP_TOL="${ZMAX_PP_TOL:-}" \
  -e ZMAX_PP_ABORT="${ZMAX_PP_ABORT:-}" \
  -e ZMAX_PP_TRAJ="${ZMAX_PP_TRAJ:-}" \
  -e ZMAX_PP_STOPS="${ZMAX_PP_STOPS:-}" \
  -e ZMAX_PP_SLOW="${ZMAX_PP_SLOW:-}" \
  -e ZMAX_REC_RATE="${ZMAX_REC_RATE:-}" \
  -e ZMAX_REC_SECS="${ZMAX_REC_SECS:-}" \
  -e ZMAX_REC_DIR="${ZMAX_REC_DIR:-}" \
  -e ZMAX_RT_HOLD_AT="${ZMAX_RT_HOLD_AT:-}" \
  -e ZMAX_RT_HOLD_MS="${ZMAX_RT_HOLD_MS:-}" \
  -e ZMAX_RT_LOAD="${ZMAX_RT_LOAD:-}" \
  -e ZMAX_RT_HOLD_TICKS="${ZMAX_RT_HOLD_TICKS:-}" \
  -e ZMAX_RT_HOLD_AT="${ZMAX_RT_HOLD_AT:-}" \
  -e ZMAX_RT_HOLD_MS="${ZMAX_RT_HOLD_MS:-}" \
  -e ZMAX_RT_TOL="${ZMAX_RT_TOL:-}" \
  -e ZMAX_RT_INTERVAL="${ZMAX_RT_INTERVAL:-}" \
  -e ZMAX_RT_DRY="${ZMAX_RT_DRY:-}" \
  -v "$SDK_DIR":/sdk \
  -v "$REPO_TOOLS":/repo:ro \
  -w /sdk "$IMAGE" python3 "/repo/$SCRIPT" "$@"
