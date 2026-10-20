#!/usr/bin/env bash
# USB RealSense D435 独占小服务 (8796) 启停 —— 单进程持有设备, AR 服务只代理
set -u
cd /home/ubuntu/zmax || exit 1
PY=/home/ubuntu/zmax/gui-venv311/bin/python
PIDF=/tmp/rs_service.pid
LOG=/tmp/rs_service.log
cmd=${1:-status}

running() {
  [ -f "$PIDF" ] || return 1
  local p; p=$(cat "$PIDF" 2>/dev/null)
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}

case "$cmd" in
  start)
    if running; then echo "已在运行 (pid $(cat $PIDF))"; exit 0; fi
    nohup "$PY" tools/rs_service.py --port 8789 >> "$LOG" 2>&1 &
    echo $! > "$PIDF"
    for i in $(seq 1 40); do
      code=$(curl -s -o /tmp/rs_health.json -w '%{http_code}' --max-time 2 http://127.0.0.1:8789/health 2>/dev/null)
      if [ "$code" = "200" ] && grep -q '"zmax-rs"' /tmp/rs_health.json 2>/dev/null; then
        echo "✅ 8789 已应答 · $(cat /tmp/rs_health.json)"; exit 0
      fi
      sleep 0.25
    done
    echo "❌ 起不来, 看 $LOG"; tail -5 "$LOG"; exit 1;;
  stop)
    if running; then kill "$(cat $PIDF)"; sleep 1; echo "已停"; else echo "没在跑"; fi
    rm -f "$PIDF";;
  restart)
    "$0" stop >/dev/null 2>&1; sleep 1; "$0" start;;
  status)
    if running; then
      echo "运行中 (pid $(cat $PIDF))"
      curl -s --max-time 4 http://127.0.0.1:8789/health; echo
    else echo "未运行"; fi;;
  *) echo "用法: $0 start|stop|restart|status"; exit 2;;
esac
