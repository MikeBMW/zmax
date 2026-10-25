#!/bin/bash
# 重启 AR 服务 (8797) —— 只杀监听 8797 的那个 python, 不用 pkill -f 匹配
# (踩过: `pkill -f 'ssh.*18795'` 把执行它的 shell 自己杀了)
set -u
cd /home/ubuntu/zmax || exit 1
# 🔴 踩过两次:
#  ① 用 `pkill -f 'ssh.*18795'` 把执行它的 shell 自己杀了
#  ② 只 kill `ss` 里的**第一个** pid —— tcp_ar_server.py 是 ForkingMixIn,
#     父+多个 fork 子进程**共享同一个监听 socket**, ss 会列出 6 个 pid。
#     只杀一个 ⇒ 旧代码还在服务, 症状是"改了代码行为没变"(实测 map 轨迹还是 7 点)。
mapfile -t PIDS < <(ss -ltnp 2>/dev/null | grep ':8797' | grep -oP 'pid=\K[0-9]+' | sort -u)
if [ ${#PIDS[@]} -gt 0 ]; then
  echo "停 8797: ${#PIDS[@]} 个进程 (${PIDS[*]})"
  kill "${PIDS[@]}" 2>/dev/null
  for _ in $(seq 1 25); do
    sleep 0.3
    ss -ltnp 2>/dev/null | grep -q ':8797' || break
  done
  if ss -ltnp 2>/dev/null | grep -q ':8797'; then
    echo "普通 kill 没清干净, 补 -9"
    mapfile -t LEFT < <(ss -ltnp 2>/dev/null | grep ':8797' | grep -oP 'pid=\K[0-9]+' | sort -u)
    [ ${#LEFT[@]} -gt 0 ] && kill -9 "${LEFT[@]}" 2>/dev/null
    sleep 1.5
  fi
else
  echo "8797 当前没在监听"
fi
if ss -ltnp 2>/dev/null | grep -q ':8797'; then
  echo "⛔ 8797 还被占着, 不启动新的"; ss -ltnp 2>/dev/null | grep ':8797'; exit 1
fi
mkdir -p zmax_data/logs
nohup ./gui-venv311/bin/python tools/tcp_ar_server.py \
  >> zmax_data/logs/tcp_ar_server.log 2>&1 &
echo "新 pid=$!"
for _ in $(seq 1 30); do
  sleep 0.5
  ss -ltnp 2>/dev/null | grep -q ':8797' && { echo "8797 起来了"; break; }
done
ss -ltnp 2>/dev/null | grep ':8797' || echo "⚠ 8797 没起来, 看 zmax_data/logs/tcp_ar_server.log"
