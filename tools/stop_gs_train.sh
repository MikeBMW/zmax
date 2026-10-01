#!/usr/bin/env bash
# 停 3DGS 训练进程 —— 必须独立成脚本执行。
# 踩过的坑: 内联 pkill -f "gs_train.py ..." 时, 模式串会匹配到自己这条命令的 cmdline,
# 把自己的 shell 一起杀掉(exit -15)。这里用 pgrep 先取 pid, 排除自身与父进程。
set -u
SELF=$$
for p in $(pgrep -f gs_train.py); do
  [ "$p" = "$SELF" ] && continue
  [ "$p" = "$PPID" ] && continue
  echo "kill $p: $(tr '\0' ' ' < /proc/$p/cmdline 2>/dev/null | cut -c1-90)"
  kill "$p" 2>/dev/null
done
sleep 2
echo "剩余 gs_train 进程: $(pgrep -fc gs_train.py || echo 0)"
