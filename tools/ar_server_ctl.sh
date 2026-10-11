#!/usr/bin/env bash
# AR 服务 (8797 · tools/tcp_ar_server.py) 起/停/重启/看
# 用法: bash tools/ar_server_ctl.sh start|stop|restart|status
# 🔴 坑(已实测): **只按监听端口找 pid, 绝不按进程名 ps|grep** —— 按名匹配会把我自己这条命令行也杀掉
#   (命令行里出现该脚本名就自杀: exit -15 SIGTERM)。同理再起会撞 "Address already in use", 必须等端口真释放。
set -u
REPO=/home/ubuntu/zmax
PY=$REPO/gui-venv311/bin/python
PORT=${AR_PORT:-8797}
LOG=/tmp/tcp_ar_server.log

_port_pids() { ss -ltnp 2>/dev/null | awk -v p=":$PORT" '$4 ~ p {print $NF}' | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u; }
_port_busy() { [ -n "$(_port_pids)" ]; }

case "${1:-status}" in
  stop)
    for pid in $(_port_pids); do echo "  kill $pid (端口 $PORT)"; kill "$pid" 2>/dev/null; done
    for i in $(seq 1 30); do
      _port_busy || { echo "  端口 $PORT 已释放 (等待 ${i}s)"; break; }
      sleep 1
    done
    ;;
  start)
    if _port_busy; then echo "  端口 $PORT 还被占用 ⇒ 先 stop"; exit 0; fi
    cd "$REPO/tools" || exit 2
    AR_PORT=$PORT setsid nohup "$PY" "$REPO/tools/tcp_ar_server.py" >>"$LOG" 2>&1 </dev/null &
    for i in $(seq 1 40); do
      _c=$(curl -s -o /dev/null -m 2 -w '%{http_code}' "http://127.0.0.1:$PORT/api/cams" || echo 000)
      [ "$_c" = "200" ] && { echo "  started: 端口 $PORT 已应答 (${i}s) · log $LOG"; break; }
      sleep 1
    done
    ;;
  restart) bash "$0" stop; bash "$0" start ;;
  status)
    printf "  端口 %s 监听: %s\n" "$PORT" "$(_port_pids | tr '\n' ' ')"
    printf "  /api/cams: "; curl -s -o /dev/null -m 3 -w '%{http_code}\n' "http://127.0.0.1:$PORT/api/cams"
    ;;
  *) echo "用法: bash tools/ar_server_ctl.sh start|stop|restart|status"; exit 1 ;;
esac
