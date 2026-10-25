#!/bin/bash
# wait_ports_free.sh <port...> —— 等到这些本地端口不再被占(最多等 $WAIT_MAX 秒, 默认 20)
#
# 为什么需要: 常驻 ssh 隧道重启时, 上一个进程还没退出, 新进程就 bind 同一个 -L 端口 ⇒
#   "bind [127.0.0.1]:18822: Address already in use" ⇒ ExitOnForwardFailure 让它立刻退出 ⇒
#   systemd 再拉 ⇒ 又撞 ⇒ 实测 zmax-orin-intel-fwd 重启计数冲到 7, 期间 550C/AOI/相机全断。
#   在 ExecStart 之前等一下, 就把这个重启风暴消掉(网络本身没坏)。
set -u
WAIT_MAX="${WAIT_MAX:-20}"
deadline=$(( $(date +%s) + WAIT_MAX ))
while :; do
  busy=""
  for p in "$@"; do
    if ss -ltn "sport = :$p" 2>/dev/null | grep -q LISTEN; then busy="$busy $p"; fi
  done
  [ -z "$busy" ] && exit 0
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "⚠️ 等不到端口释放:$busy (继续启动, 让 ssh 自己报)"
    exit 0
  fi
  sleep 1
done
