#!/usr/bin/env bash
# 重启工位相机流服务 (8791 取图/统计 + 8793 工位总览, 同一进程) —— 老倪 2026-10-22
#   🔴 现场: 8797/ar 与 8793/station 里「机器人相机」那格没有画面。
#      根因: 服务是用 --arm-http http://192.168.23.66:8792/frame.jpg 起的, 而本机只有 WiFi
#      10.163.146.78/23, **没有 192.168.23.0/24 路由** ⇒ 直连必 No route to host ⇒ arm 那一路 0 帧;
#      Orin 侧相机其实是活的 (ssh 转发口 127.0.0.1:18792 自报 age≈0.1s, 累计百万帧)。
#   ⇒ 本次重启: 保留直连地址作首选, 再加 ZMAX_ARM_HTTP_FALLBACK=127.0.0.1:18792 自动切换。
#   用法: bash tools/restart_cam_stream.sh [--dry]
set -u
cd /home/ubuntu/zmax || exit 1
LOG=/tmp/cam_live_stream.log
PY=/home/ubuntu/zmax/gui-venv311/bin/python
DRY=0
[ "${1:-}" = "--dry" ] && DRY=1

# 按端口找 pid (禁 ps|grep 名 —— 会把自己杀掉)
PID=$(ss -ltnp 2>/dev/null | grep -oP '(?<=:8791 ).*?pid=\K[0-9]+' | head -1)
if [ -z "${PID:-}" ]; then
    PID=$(ss -ltnp 2>/dev/null | awk '/:8791 /{print $0}' | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
fi
echo "[$(date '+%F %T')] 现有 8791 pid=${PID:-无}"

if [ "$DRY" = "1" ]; then
    echo "dry-run: 将 TERM ${PID:-无} 并用下列命令重启:"
    echo "  $PY tools/cam_live_stream.py --port 8791 --quality 72 --fps 30 --arm-http http://192.168.23.66:8792/frame.jpg --arm-fps 30 --local-dev 0 --local2-dev -1 --depth-fps 4 --aoi-fps 0.25"
    exit 0
fi

if [ -n "${PID:-}" ]; then
    kill -TERM "$PID" 2>/dev/null
    for _ in $(seq 1 30); do
        kill -0 "$PID" 2>/dev/null || break
        sleep 0.2
    done
    kill -0 "$PID" 2>/dev/null && { echo "⚠ TERM 后仍在, 升级 KILL"; kill -KILL "$PID" 2>/dev/null; sleep 0.5; }
fi

export ZMAX_ARM_HTTP_FALLBACK="${ZMAX_ARM_HTTP_FALLBACK:-http://127.0.0.1:18792/frame.jpg}"
# AOI 两路 (金手指/表面) 同源问题: 默认源是 192.168.23.23:10082/10083, 本机同样没路由;
#   实际有一条 ssh 转发 127.0.0.1:10082/10083 → 产线 AOI (实测 /region 200 · /picture 110KB 真图)
export ZMAX_AOI_HOST="${ZMAX_AOI_HOST:-127.0.0.1}"
nohup "$PY" tools/cam_live_stream.py \
    --port 8791 --quality 72 --fps 30 \
    --arm-http http://192.168.23.66:8792/frame.jpg --arm-fps 30 \
    --local-dev 0 --local2-dev -1 --depth-fps 4 --aoi-fps 0.25 \
    >> "$LOG" 2>&1 &
NEW=$!
echo "[$(date '+%F %T')] 新 pid=$NEW · 日志 $LOG · 臂源回退=$ZMAX_ARM_HTTP_FALLBACK · AOI 源=$ZMAX_AOI_HOST"

# 等就绪: 8791 /stats 里 arm.online=true 且 frames_served 在涨
for i in $(seq 1 40); do
    sleep 0.5
    S=$(curl -s --max-time 2 http://127.0.0.1:8791/stats 2>/dev/null)
    [ -z "$S" ] && continue
    A=$(printf '%s' "$S" | "$PY" -c 'import sys,json;
try:
 d=json.load(sys.stdin); a=d.get("arm") or {}
 print(("1" if a.get("online") else "0")+" %s %s %s"%(a.get("frames_served"),a.get("age_s"),a.get("src_url") or "-"))
except Exception: print("0 - - -")' 2>/dev/null)
    case "$A" in
      1*) echo "[$(date '+%F %T')] ✅ arm 就绪: $A"; break ;;
      *)  [ "$i" = "40" ] && echo "[$(date '+%F %T')] ⚠ 120s 后 arm 仍未出帧: $A (看 $LOG)" ;;
    esac
done
curl -s --max-time 3 -o /dev/null -w '8793/station=%{http_code}\n' http://127.0.0.1:8793/station
