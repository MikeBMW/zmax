#!/usr/bin/env bash
# 修飞书网关"抖动": systemd 单元无限重启(exit 75/TEMPFAIL), 因为主机上已有一个
# 不由 systemd 托管的 gateway 进程("launched by profile 'default'") ⇒ 单元起来就说
# "already serves profile default — nothing to start" 然后退出, Restart=always 再拉,
# restart counter 一路涨(2026-10-07 实测 2110 次)。功能上飞书是通的, 但单元永远不是 active,
# 一旦那个野进程死掉就没人拉 ⇒ 归位: 停单元 → 杀掉野进程 → 起单元(由 systemd 托管)。
# 写成脚本的原因: 内联 `pgrep -f <含 gateway 字样的模式>` 会匹配到执行它的 shell 自己 ⇒ 自杀。
set -u
say(){ echo "[$(date +%H:%M:%S)] $*"; }

say "① 找不由 systemd 托管的 gateway 进程"
P=$(pgrep -f 'hermes_cli.main gateway run' | head -1)
if [ -z "${P:-}" ]; then
  say "   没有野进程, 直接起单元"; systemctl start hermes-gateway; sleep 6
  systemctl is-active hermes-gateway; exit 0
fi
say "   野进程 pid=$P (父 $(ps -o ppid= -p "$P" 2>/dev/null | tr -d ' '))"

say "② 停单元(止住重启风暴)"
systemctl stop hermes-gateway; sleep 2

say "③ 结束野进程, 把托管权交给 systemd"
kill "$P" 2>/dev/null; sleep 8
pgrep -f 'hermes_cli.main gateway run' >/dev/null && { say "   仍在? 强杀"; pkill -f 'hermes_cli.main gateway run'; sleep 4; }

say "④ 起单元"
systemctl start hermes-gateway; sleep 8

say "── 核验 ──"
printf "  unit: %s\n" "$(systemctl is-active hermes-gateway)"
printf "  MainPID: %s\n" "$(systemctl show -p MainPID --value hermes-gateway 2>/dev/null)"
printf "  socket: %s\n" "$([ -S /tmp/hermes-gateway.sock ] && echo 在 || echo 缺)"
journalctl -u hermes-gateway -n 8 --no-pager 2>/dev/null | tail -5 | cut -c1-130
say "完成"
