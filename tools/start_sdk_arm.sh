#!/usr/bin/env bash
# start_sdk_arm.sh — 起/停/看 本机 SDK 直连动作链 (纯新增件; **不碰 Orin, 不碰老服务/老页面**)
#
# 组成:
#   ① 容器 zmax-sdk-arm-agent: 常驻, 持一条 xCoreSDK 会话 → 直连控制器 192.168.23.160
#      脚本 tools/rokae/sdk_agent.py (仓库, 只读挂载) + 控制层 tools/rokae/sdk_ctl.py
#   ② 主机服务 tools/sdk_motion_service.py (端口 8798): 极简点动页 + JSON 接口
# 用法: bash tools/start_sdk_arm.sh [--check|--stop]
set -uo pipefail
REPO=/home/ubuntu/zmax
SDK_DIR="/home/ubuntu/zmax/zmax_data/rokae_sdk"
IMAGE=ros:humble-ros-base
NAME=zmax-sdk-arm-agent
PORT="${ZMAX_ARM_PORT:-8798}"
PY="$REPO/gui-venv311/bin/python"
LOG="$HOME/zmax/zmax_data/sdk_motion_service.log"

running() { sudo docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$NAME"; }
listening() { ss -ltn 2>/dev/null | grep -q ":$PORT "; }

case "${1:-}" in
  --stop)
    echo "① 停容器 $NAME"; sudo docker rm -f "$NAME" >/dev/null 2>&1 || true
    echo "② 停服务(端口 $PORT)"
    for d in /proc/[0-9]*; do
      [ -r "$d/cmdline" ] || continue
      tr '\0' ' ' < "$d/cmdline" 2>/dev/null | grep -q "tools/sdk_motion_service.py" && {
        p=$(basename "$d"); [ "$p" = "$$" ] && continue; kill -TERM "$p" 2>/dev/null && echo "   killed $p"; }
    done
    sleep 1; echo "③ 状态: 容器=$(running && echo up || echo down) 端口$PORT=$(listening && echo 在听 || echo 无)"
    exit 0 ;;
esac

echo "① 容器代理"
if running; then
  echo "   已在跑: $NAME"
else
  sudo docker rm -f "$NAME" >/dev/null 2>&1 || true
  sudo docker run -d --name "$NAME" --restart unless-stopped --network host \
    -e ZMAX_ROBOT_IP="${ZMAX_ROBOT_IP:-192.168.23.160}" \
    -v "$SDK_DIR":/sdk -v "$REPO/tools/rokae":/repo:ro -w /sdk \
    "$IMAGE" python3 -u /repo/sdk_agent.py >/dev/null
  echo "   已起: $NAME (日志: sudo docker logs $NAME)"
fi
sleep 3

echo "② 主机服务 (: $PORT)"
if listening; then
  echo "   已在听 $PORT"
else
  # 完全脱离: 新会话(setsid) + 三个 fd 全重定向, 避免被调用方的进程组/管道回收
  ( cd "$REPO" && setsid "$PY" -u tools/sdk_motion_service.py >> "$LOG" 2>&1 < /dev/null & )
  sleep 2
fi

echo "③ 自检"
echo -n "   容器: "; running && echo up || echo down
echo -n "   FIFO: "; [ -p "$SDK_DIR/cmd_arm.fifo" ] && echo "在 ($SDK_DIR/cmd_arm.fifo)" || echo "缺"
echo -n "   端口: "; listening && echo "$PORT 在听" || echo "未监听"
echo "   心跳: $(curl -s -m 4 "http://127.0.0.1:$PORT/state" | head -c 220)"
echo
echo "页面: http://10.163.146.78:$PORT/  (本机调试 http://127.0.0.1:$PORT/)"
echo "授权: bash tools/sdk_arm_auth.sh --ttl 1800 --uses 30 --by \"老倪(现场)\""
