#!/bin/bash
# legs_watchdog.sh —— 保 18822/39071 这两个命门端口"始终在听"
#
# 实测 2026-10-25: 经 ECS 的这条连接会被对端周期性踢 ("Connection closed by remote host"),
# 而 systemd 的 Restart 有间隔 ⇒ 有几十秒到几分钟的空窗, 期间所有 Intel/Orin 操作都失败,
# 表现成"550C 连不上""SAM3 传不过去"。用 20s 一次的巡看把空窗压到 <20s。
# 判据只看端口在不在听(不看 ssh 交互, 免得自己制造连接压力):
set -u
UNIT=zmax-orin-legs
need="18822 39071"

missing=""
for p in $need; do
  ss -ltn "sport = :$p" 2>/dev/null | grep -q LISTEN || missing="$missing $p"
done

if [ -n "$missing" ]; then
  echo "$(date '+%H:%M:%S') 端口缺:$missing ⇒ 重启 $UNIT"
  systemctl reset-failed $UNIT >/dev/null 2>&1
  systemctl restart $UNIT
  sleep 6
  still=""
  for p in $need; do
    ss -ltn "sport = :$p" 2>/dev/null | grep -q LISTEN || still="$still $p"
  done
  [ -n "$still" ] && echo "$(date '+%H:%M:%S') ⚠️ 重启后仍缺:$still (可能需要人看 ECS/Orin)"
  exit 0
fi
exit 0
