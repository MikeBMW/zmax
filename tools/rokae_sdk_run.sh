#!/usr/bin/env bash
# rokae_sdk_run.sh — 本机(4060) 独立 SDK 直连控制的唯一入口。
#
# 口径(2026-10-07 老倪现场指令): 「不要改变 orin 原来的任何服务。你可以直接调用SDK，但要独立实现」
#   · 全程**不碰 Orin**: 不读不写 Orin 的文件/单元/服务, 不前不后依赖它的 ROS/DDS/驱动栈
#   · 走厂家 xCoreSDK(x86_64) 直连控制器 192.168.23.160; SDK 是 cpython-310 ⇒ 必须容器里跑
#   · 脚本本体在**仓库**里(tools/rokae/sdk_ctl.py), 以只读方式挂进容器 ⇒ 无副本漂移
#   · 只挂 ~/zmax_data/rokae_sdk(服务端 SDK + 采样落盘 + 证据目录), -w /sdk 因为 SDK 要写 logs/
#
# 用法:
#   bash tools/rokae_sdk_run.sh state                      # 只读: 电源/状态/模式/报警/位姿/关节
#   bash tools/rokae_sdk_run.sh pose
#   bash tools/rokae_sdk_run.sh move-rel --dz 1.0 --speed 5   # 相对运动(mm, 姿态不变)
#   bash tools/rokae_sdk_run.sh stop | reset
set -euo pipefail

SDK_DIR="${ZMAX_SDK_DIR:-/home/ubuntu/zmax_data/rokae_sdk}"
REPO_TOOLS="$(cd "$(dirname "$0")" && pwd)/rokae"
IMAGE="${ZMAX_SDK_IMAGE:-ros:humble-ros-base}"

if [ ! -d "$SDK_DIR/xcoresdk_python" ]; then
  echo "⛔ 找不到 SDK: $SDK_DIR/xcoresdk_python (先从 Orin 拷一份, 见技能 rokae-direct-control)" >&2
  exit 2
fi

exec sudo docker run --rm --network host \
  -e ZMAX_HOST_TS="$(date +%s)" \
  -e ZMAX_ROBOT_IP="${ZMAX_ROBOT_IP:-192.168.23.160}" \
  -v "$SDK_DIR":/sdk \
  -v "$REPO_TOOLS":/repo:ro \
  -w /sdk "$IMAGE" python3 /repo/sdk_ctl.py "$@"
