#!/usr/bin/env bash
# 清掉占着 /tmp/zmax_start.lock 的孤儿 ss_canvas_loop(父进程=init, 无调试器)
set -u
for P in $(pgrep -f 'tools/ss_canvas_loop.py' 2>/dev/null); do
  PP=$(awk '{print $4}' /proc/$P/stat 2>/dev/null)
  if [ "$PP" = "1" ]; then
    echo "kill 孤儿 canvas pid=$P (父=init)"
    kill -TERM "$P" 2>/dev/null; sleep 1
    kill -KILL "$P" 2>/dev/null
  else
    echo "跳过 pid=$P (父=$PP, 不是孤儿)"
  fi
done
sleep 1
if [ -e /tmp/zmax_start.lock ] && ! fuser /tmp/zmax_start.lock >/dev/null 2>&1; then
  rm -f /tmp/zmax_start.lock; echo "陈旧锁文件已删"
fi
if fuser /tmp/zmax_start.lock >/dev/null 2>&1; then
  echo "锁仍被占用: $(sudo fuser /tmp/zmax_start.lock 2>&1 | tr -s ' ')"
else
  echo "启动锁已释放 ✅"
fi
