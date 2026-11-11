#!/usr/bin/env bash
# 本机 AOI 镜像服务 —— 起停/体检 (旁路 AOI 检测用, 不碰工控机)
#
#   bash tools/aoi_local_service.sh start|stop|status|log gold|surface|both
#
# 默认帧源 remote:192.168.23.23 (工控机在跑时取它的原图)。停机时用:
#   ZMAX_AOI_LOCAL_GOLD_SRC=push    ZMAX_AOI_LOCAL_SURFACE_SRC=push   再 POST /frame 推帧
#   或 file:<图> / dir:<目录> / cam:http://127.0.0.1:8797/snap/gold.jpg
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv-aoi310/bin/python"
RUN="$ROOT/src/lerobot/policies/aoi/service/run.py"
DATA="${ZMAX_AOI_LOCAL_DATA:-$HOME/zmax/zmax_data/aoi_local}"
mkdir -p "$DATA"

port_of() { case "$1" in gold) echo 20082;; surface) echo 20083;; esac; }

pidfile() { echo "$DATA/$1.pid"; }
logfile() { echo "/tmp/aoi_local_$1.log"; }

start_one() {
  local k="$1" p; p="$(port_of "$k")"
  if curl -s -m 2 -o /dev/null "http://127.0.0.1:$p/health"; then
    echo "[$k] 已在跑 (:$p)"; return 0
  fi
  [ -x "$VENV" ] || { echo "缺解释器 $VENV —— uv pip install --python $VENV numpy==1.26.4 opencv-python==4.10.0.84 flask"; return 1; }
  nohup "$VENV" "$RUN" --kind "$k" --port "$p" >"$(logfile "$k")" 2>&1 &
  echo $! >"$(pidfile "$k")"
  for i in $(seq 1 40); do
    curl -s -m 1 -o /dev/null "http://127.0.0.1:$p/health" && { echo "[$k] 起好 pid=$(cat "$(pidfile "$k")") :$p 源=$(curl -s -m 2 "http://127.0.0.1:$p/source" | head -c 120)"; return 0; }
    sleep 0.3
  done
  echo "[$k] 起不来, 看 $(logfile "$k")"; return 1
}

stop_one() {
  local k="$1" f; f="$(pidfile "$k")"
  if [ -f "$f" ]; then
    local pid; pid="$(cat "$f")"
    kill "$pid" 2>/dev/null && echo "[$k] 停 pid=$pid"
    rm -f "$f"
  else
    local p; p="$(port_of "$k")"
    local pid; pid="$(ss -ltnp 2>/dev/null | awk -v P=":$p" '$4 ~ P {print $NF}' | grep -oP 'pid=\K[0-9]+' | head -1)"
    [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null && echo "[$k] 停 pid=$pid (按端口找到)"
  fi
}

status_one() {
  local k="$1" p; p="$(port_of "$k")"
  if curl -s -m 3 "http://127.0.0.1:$p/health" >/tmp/_aoi_h.json; then
    echo "[$k] UP :$p $(head -c 200 /tmp/_aoi_h.json)"
  else
    echo "[$k] DOWN :$p"
  fi
}

cmd="${1:-status}"; what="${2:-both}"
[ "$what" = "both" ] && targets="gold surface" || targets="$what"
for k in $targets; do
  case "$cmd" in
    start) start_one "$k" ;;
    stop) stop_one "$k" ;;
    status) status_one "$k" ;;
    log) echo "== $(logfile "$k") =="; tail -n 20 "$(logfile "$k")" 2>/dev/null ;;
    *) echo "用法: $0 start|stop|status|log gold|surface|both"; exit 2 ;;
  esac
done
