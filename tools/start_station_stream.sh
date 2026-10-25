#!/bin/bash
# 🛰 工位总览/叠加 推流服务 —— 稳定启动器 (2026-09-28)
#
# 为什么需要它: 控制台两个按钮(🛰工位总览 / 🧩场景叠加)起来的那条命令**设备号写死**过
#   (--local-dev 2 --local2-dev 0), 现场后果实测:
#     · /dev/video2 = 笔记本相机的 GREY(IR) 路 ⇒ 画面近黑(mean≈6/255) —— 老倪:「笔记本内置摄像头太黑了」
#     · /dev/video0 = 笔记本**彩色**路, 却被当成 MAXHUB ⇒ 两格串线 —— 老倪:「MAXHUB 的跟笔记本串线了」
#   本脚本一律按 **卡名+能力** 解析设备(tools/cam_dev_resolve.py), 换号/换机/重启都不会再错。
#
# 用法:
#   bash tools/start_station_stream.sh          # 换号重启(先停旧, 再按解析结果起新)
#   bash tools/start_station_stream.sh --check  # 只看: 当前进程用的哪两路 + 两格实测
set -u
ROOT=/home/ubuntu/zmax
PY="$ROOT/gui-venv311/bin/python"
PORT=8791
STATION=8793
LOG=/tmp/zmax_scene_overlay.log
ORIN_HOST="${ZMAX_ORIN_HOST:-tashan@192.168.23.66}"; ORIN_HOST="${ORIN_HOST##*@}"

_ld=$("$PY" "$ROOT/tools/cam_dev_resolve.py" 2>/dev/null | sed -n 's/^LOCAL=//p');  [ -n "$_ld" ] || _ld=0
_l2=$("$PY" "$ROOT/tools/cam_dev_resolve.py" 2>/dev/null | sed -n 's/^LOCAL2=//p'); [ -n "$_l2" ] || _l2=-1
_lu=$("$PY" "$ROOT/tools/cam_dev_resolve.py" 2>/dev/null | sed -n 's/^USB=//p');   [ -n "$_lu" ] || _lu=-1
[ "$_l2" = "$_ld" ] && _l2=-1        # 绝不把两路指到同一台设备(独占会打不开)

# ── 🎥 2026-10-17: 笔记本那一路的开关 —— 由页面落盘的 cam_local_src.json 决定 ─────────
#   kind=off ⇒ **完全不打开笔记本摄像头**（老倪要用内置摄像头开微信; Z-MAX 不能再独占 /dev/video0）。
#   背景: 配置落盘为 usb 但 USB 相机不在位时, cam_live_stream 会「退回内置」(不黑屏的设计)
#   ⇒ 结果是把笔记本内置摄像头一直占着。off 就是显式关掉这一路, 页面点 [内置]/[USB] 可随时开回。
_src_kind=$(python3 -c "import json;print(json.load(open('$ROOT/zmax_data/cam_local_src.json')).get('kind','builtin'))" 2>/dev/null || echo builtin)
LOCAL_ARGS=(--local-dev "$_ld" --local2-dev "$_l2")
# ── 🌐 远程模式: 中央相机不在本机(没有第二台 USB 相机)时, 吃 Orin 推到 ECS 中转的帧 ──────
#   链路: Orin 跑 tools/orin_cam_uplink.py → POST /api/relay/cam/push?cam=central
#         本机读 https://datadrive.world/api/snapshot/central
#   2026-10-25 老倪远程: 厂内相机只有经 Orin 的公网出口才拿得到, 本机没有产线网卡。
RELAY_CAM="${ZMAX_CAM_RELAY:-https://datadrive.world/api/snapshot}"
CENTRAL_URL="${ZMAX_CENTRAL_CAM_URL:-http://127.0.0.1:8812/snap.jpg}"
if [ "$_l2" -lt 0 ] && [ "$_src_kind" != "off" ]; then
  # ① 优先: 550C(Intel) 的中央相机, 经 zmax-intel-cam-tunnel 转到本机 8812
  if curl -s -m 3 -o /dev/null "$CENTRAL_URL" 2>/dev/null; then
    LOCAL_ARGS=(--local-dev "$_ld" --local2-url "$CENTRAL_URL" --local2-label "🎥 中央相机" --local2-fps 10)
    echo "  · 中央相机: 走 550C 隧道 $CENTRAL_URL"
  elif curl -s -m 3 -o /dev/null "$RELAY_CAM/central" 2>/dev/null; then
    # ② 兜底: ECS 中转里 Orin 推到 central 的帧
    LOCAL_ARGS=(--local-dev "$_ld" --local2-url "$RELAY_CAM/central" --local2-label "🎥 中央相机" --local2-fps 10)
    echo "  · 中央相机: 550C 隧道不通 → 吃 ECS 中转 $RELAY_CAM/central"
  else
    echo "  · 中央相机: 550C 隧道与 ECS 中转都没有帧 ⇒ 这一格会是空"
  fi
fi
if [ "$_src_kind" = "off" ]; then
  LOCAL_ARGS=(--no-local --no-local2)
  echo "  ⏸ 笔记本那一路: 已关闭 (cam_local_src.json kind=off)"
  echo "     ⇒ 不打开本机摄像头, 内置摄像头留给微信/会议软件 (页面点 [内置]/[USB] 可开回)"
fi

_pid_by_port() { ss -tlnp 2>/dev/null | sed -n "s/.*:${1} .*pid=\\([0-9]*\\).*/\\1/p" | head -1; }

if [ "${1:-}" = "--check" ]; then
  p=$(_pid_by_port $PORT)
  echo "=== 当前推流进程 ==="
  [ -n "$p" ] && ps -o pid,etimes,cmd -p "$p" --no-headers | cut -c1-220 | sed 's/^/  /' || echo "  (8791 没在监听)"
  echo "=== 解析结果 (此刻硬件) ==="
  python3 "$ROOT/tools/cam_dev_resolve.py" --json 2>/dev/null | sed -n '1,12p' | sed 's/^/  /'
  echo "=== 笔记本这一路当前源 (服务端真值) ==="
  curl -s -m 6 "http://127.0.0.1:$PORT/cam/src" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print('  · 当前: %s → /dev/video%s %s'%(d.get('kind'),d.get('dev'),d.get('name') or ''));[print('  · 可选: %s → /dev/video%s %s'%(o['kind'],o['dev'],o['name'])) for o in d.get('options',[])]" 2>/dev/null
  echo "=== 两格实测(真实取帧) ==="
  curl -s -m 12 "http://127.0.0.1:$PORT/stats" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);[print('  %-8s %-40s frames=%s'%(k,d[k].get('label',''),d[k].get('frames_served'))) for k in ('local','local2') if k in d]" 2>/dev/null
  exit 0
fi

p=$(_pid_by_port $PORT)
if [ -n "$p" ]; then echo "  · 停旧推流 pid=$p (按端口找, 不用 pkill 名字 —— 会杀到自己)"; kill "$p"; sleep 3; fi

cd "$ROOT" || exit 1
echo "  · 相机映射: 笔记本彩色 /dev/video$_ld · MAXHUB 顶视 $([ "$_l2" -ge 0 ] && echo "/dev/video$_l2" || echo '(未找到)')"
echo "  · 笔记本这一路可选: 内置 /dev/video$_ld · USB $([ "$_lu" -ge 0 ] && echo "/dev/video$_lu" || echo '(没插/不在位)')" \
     "  ← 页面 [内置|USB] 按钮可随时切 (选择落盘, 重启后仍是它)"
# ── 2026-09-29 根治: 先抬 fd 上限 + 清掉从父进程继承来的 fd 表 ────────────────
# 事故: 22:47 那个实例"一出生 fd 表就是满的"(日志第 15 行即 Errno 24) —— 它继承了
#       父进程的 1024 个 fd + 1024 的软上限, 于是连 accept 都做不了, 整个服务僵死 7 小时。
#       这里 ulimit 抬上限, closerange 丢弃 3 号以上的继承 fd, setrlimit 顶到硬上限。
ulimit -n 65535 2>/dev/null || ulimit -n 4096 2>/dev/null || true
# ── 手臂相机源: 产线网直连优先, 本机不在产线网时走 ECS 隧道本地口 18792 ─────────
#   直连: http://192.168.23.66:8792/frame.jpg (Orin rs_fast_node)
#   隧道: zmax-orin-arm-fwd.service (ssh -L 18792 -> Orin 8792, 走 39.102.211.79:22022)
ARM_URL="http://$ORIN_HOST:8792/frame.jpg"
if ! curl -s -m 2 -o /dev/null "http://$ORIN_HOST:8792/frame.jpg" 2>/dev/null; then
  if curl -s -m 2 -o /dev/null "http://127.0.0.1:18792/frame.jpg" 2>/dev/null; then
    ARM_URL="http://127.0.0.1:18792/frame.jpg"
    echo "  · 手臂源: 产线网 $ORIN_HOST:8792 不通 → 改走 ECS 隧道 127.0.0.1:18792"
  else
    # 🌐 远程兜底: 产线与隧道都不通 ⇒ 吃 Orin 推到 ECS 中转的臂相机帧
    #   (Orin 跑 tools/orin_cam_uplink.py → POST /api/relay/cam/push?cam=arm)
    if curl -s -m 3 -o /dev/null "$RELAY_CAM/arm" 2>/dev/null; then
      ARM_URL="http://127.0.0.1:18792/frame.jpg,$RELAY_CAM/arm"
      echo "  · 手臂源: 产线/隧道都不通 → 追加 ECS 中转 $RELAY_CAM/arm (需 Orin 推帧)"
    else
      echo "  · 手臂源: 产线网/隧道/ECS 中转都没有帧 ⇒ 这一路会是空"
    fi
  fi
else
  echo "  · 手臂源: 产线网直连 http://$ORIN_HOST:8792/frame.jpg"
fi
# ── AOI 工控机地址: 直连优先, 不在产线网时用隧道本地口 10082/10083 ──────────────
#   隧道单元: zmax-orin-aoi-fwd.service (ssh -L 10082/10083 -> 192.168.23.23 经 Orin)
if curl -s -m 2 -o /dev/null "http://192.168.23.23:10082/storage" 2>/dev/null; then
  echo "  · AOI 源: 产线网直连 192.168.23.23:10082/10083"
elif curl -s -m 2 -o /dev/null "http://127.0.0.1:10082/storage" 2>/dev/null; then
  export ZMAX_AOI_HOST=127.0.0.1
  echo "  · AOI 源: 产线网不通 → 改走隧道 127.0.0.1:10082/10083 (ZMAX_AOI_HOST=127.0.0.1)"
else
  echo "  · AOI 源: 直连与隧道都不通 (zmax-orin-aoi-fwd 没起?) ⇒ 金手指/表面两格会是空"
fi
nohup "$PY" -c 'import os,sys,resource
try:
  _s,_h=resource.getrlimit(resource.RLIMIT_NOFILE)
  resource.setrlimit(resource.RLIMIT_NOFILE,(_h,_h))
except Exception:
  pass
os.closerange(3,65536)
os.execv(sys.argv[1], sys.argv[1:])' "$PY" tools/cam_live_stream.py --port $PORT --quality 72 --fps 30 \
  --arm-http "$ARM_URL" --arm-fps 30 \
  "${LOCAL_ARGS[@]}" \
  --depth-fps 4 --aoi-fps 0.25 --ctl-motion --station-port $STATION \
  --overlay --overlay-src all --overlay-fps 10 >> "$LOG" 2>&1 &

for i in $(seq 1 20); do
  curl -s -m 3 -o /dev/null "http://127.0.0.1:$PORT/stats" && break
  sleep 1
done
sleep 2
echo "  · 复核:"
curl -s -o /dev/null -w "    8793/station → %{http_code}\n" -m 8 "http://127.0.0.1:$STATION/station"
curl -s -m 8 "http://127.0.0.1:$PORT/stats" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);[print('    %-8s %s'%(k,d[k].get('label',''))) for k in ('local','local2','arm') if k in d]" 2>/dev/null
echo "  页面: http://10.163.146.78:$STATION/station"
