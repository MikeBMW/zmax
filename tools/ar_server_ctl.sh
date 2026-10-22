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
    # 🔴 坑(2026-10-22 实测): 本服务是 ForkingMixIn(每请求 fork 一个子进程), 子进程会继承监听 fd。
    #   只 kill 一次 → 残留子进程仍占着 8797, 新进程 bind 失败(errno 98), 但脚本还 curl 到旧进程 200
    #   ⇒ 报"started"而实际跑的是**旧代码**('改了页面还是老内容' 就是这么来的)。
    #   所以: 循环 kill + 兜底 SIGKILL, 直到连续两次扫描都为空。
    _empty=0
    for i in $(seq 1 40); do
      pids=$(_port_pids)
      if [ -z "$pids" ]; then _empty=$((_empty+1)); [ "$_empty" -ge 2 ] && { echo "  端口 $PORT 已释放 (${i}s)"; break; }; else _empty=0; fi
      for pid in $pids; do kill "$pid" 2>/dev/null; done
      [ "$i" -ge 6 ] && for pid in $pids; do kill -9 "$pid" 2>/dev/null; done
      sleep 0.5
    done
    # 再扫一遍进程组残留(子进程 ppid 指向老父进程时也能收)
    _left=$(_port_pids)
    [ -n "$_left" ] && echo "  ⚠ 仍有 pid 占用: $_left (已尝试 SIGKILL)"
    ;;
  start)
    if _port_busy; then echo "  ✗ 端口 $PORT 还被占用 ($(_port_pids | tr '\n' ' ')) ⇒ 先 stop; 不在这里假装启动成功"; exit 1; fi
    _PRE=$(_port_pids)
    cd "$REPO/tools" || exit 2
    AR_PORT=$PORT setsid nohup "$PY" "$REPO/tools/tcp_ar_server.py" >>"$LOG" 2>&1 </dev/null &
    for i in $(seq 1 40); do
      _c=$(curl -s -o /dev/null -m 2 -w '%{http_code}' "http://127.0.0.1:$PORT/api/cams" || echo 000)
      if [ "$_c" = "200" ]; then
        # 断言: 应答的那个 pid 必须是新起的, 不能是 stop 前的残留
        _now=$(_port_pids)
        _stale=""
        for x in $_now; do case " $_PRE " in *" $x "*) _stale="$x";; esac; done
        if [ -n "$_stale" ]; then echo "  ✗ 应答的是旧进程 $_stale ⇒ 新进程没起来(bind 失败?), 看 $LOG"; exit 1; fi
        echo "  started: 端口 $PORT 已应答 (${i}s) pid=$(echo $_now) · log $LOG"; break
      fi
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
