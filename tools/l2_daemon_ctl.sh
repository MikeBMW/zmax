#!/usr/bin/env bash
# L2 常驻执行器 启停 (FIFO: zmax_data/l2_cmd.fifo)
#   症状 "执行器 FIFO 无法打开([Errno 6])" = FIFO 文件在、**没人读** ⇒ 守护进程没跑。
#   本脚本只负责把守护进程拉起来并自证(有 reader + 日志无异常); 不发任何运动指令。
set -u
cd /home/ubuntu/zmax || exit 1
PY=/home/ubuntu/zmax/gui-venv311/bin/python
FIFO=/home/ubuntu/zmax/zmax_data/l2_cmd.fifo
LOG=/tmp/l2_daemon.out
PIDF=/tmp/l2_daemon.pid

# 按 /proc/cmdline 找真进程 (禁 pgrep -f 名字: 会匹配到本脚本自己的命令行)
find_pid() {
  for p in /proc/[0-9]*; do
    c=$( { tr '\0' ' ' < "$p/cmdline"; } 2>/dev/null ) || continue   # 进程刚退出会有 No such file, 忽略
    case "$c" in
      *python*[l]2_daemon.py*) echo "${p#/proc/}"; return 0;;
    esac
  done
  return 1
}

has_reader() {   # FIFO 上有没有读端: 只认「该 pid 的 fd 里挂着这条 fifo」(/proc fdinfo 的 flags 在带 O_NONBLOCK 时会误判方向)
  local pid; pid=$(find_pid) || return 1
  for f in /proc/$pid/fd/*; do
    [ "$(readlink "$f" 2>/dev/null)" = "$FIFO" ] && return 0
  done
  return 1
}

case "${1:-status}" in
  start)
    if pid=$(find_pid); then echo "已在跑 (pid $pid)"; exit 0; fi
    [ -p "$FIFO" ] || { mkfifo "$FIFO"; echo "补建 FIFO: $FIFO"; }
    nohup "$PY" -u tools/l2_daemon.py > "$LOG" 2>&1 &
    echo $! > "$PIDF"
    for i in $(seq 1 40); do
      if pid=$(find_pid); then
        if has_reader; then echo "✅ L2 执行器已起 (pid $pid, FIFO 有 reader) · 日志 $LOG"; exit 0; fi
      fi
      sleep 0.5
    done
    echo "❌ 没起来或 FIFO 没 reader · 日志尾:"; tail -20 "$LOG"; exit 1;;
  stop)
    if pid=$(find_pid); then kill "$pid"; sleep 1; echo "已停 (pid $pid)"; else echo "没在跑"; fi;;
  restart) "$0" stop >/dev/null 2>&1; sleep 1; "$0" start;;
  status)
    if pid=$(find_pid); then
      echo "运行中 pid $pid · FIFO reader: $(has_reader && echo 有 || echo 无)"
      echo "日志尾:"; tail -5 "$LOG" 2>/dev/null
    else echo "未运行 (FIFO 文件存在也没用: 没有读端 ⇒ 写入报 Errno 6)"; fi;;
  *) echo "用法: $0 start|stop|restart|status"; exit 2;;
esac
