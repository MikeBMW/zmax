#!/usr/bin/env bash
# 给工位总览闸门打开「手机远程操作」(2026-10-01 老倪: 「要实现手机远程操作」)
#   · 只加 --allow-ctl 一个开关: 闸门额外放行 /room 页 + POST /ctl/arm · /ctl/move · /ctl/gs_map
#   · 口令仍然必需; 真动仍要 8793 的两步确认 + 10 分钟自动失效; 每次控制 POST 进闸门日志
#   · 想关: 再跑 tools/station_gate_remote_ctl.sh off
set -eu
MODE="${1:-on}"
U=/etc/systemd/system/zmax-station-gate.service
BASE="/home/ubuntu/zmax/gui-venv311/bin/python /home/ubuntu/zmax/tools/tunnel_proxy.py --port 8893 --upstream 127.0.0.1:8793 --token zmax-live --mode station"
if [ "$MODE" = "off" ]; then
  EXEC="$BASE"
  echo "  · 关掉远程操作(回到公网只读)"
else
  EXEC="$BASE --allow-ctl"
  echo "  · 打开远程操作: /room + POST /ctl/arm · /ctl/move · /ctl/gs_map"
fi
sudo cp "$U" "${U}.bak_$(date +%Y%m%d_%H%M%S)"
sudo python3 - "$U" "$EXEC" <<'PY'
import sys, re
path, exec_line = sys.argv[1], sys.argv[2]
s = open(path, encoding="utf-8").read()
s = re.sub(r"^ExecStart=.*$", "ExecStart=" + exec_line, s, count=1, flags=re.M)
s = re.sub(r"^Description=.*$",
           "Description=Z-MAX 工位总览闸门 (8793 -> 8893; 只读画面 + 远程操作开关见 ExecStart)",
           s, count=1, flags=re.M)
open(path, "w", encoding="utf-8").write(s)
print("  已写:", [l for l in s.splitlines() if l.startswith("ExecStart")][0][:150])
PY
sudo systemctl daemon-reload
sudo systemctl restart zmax-station-gate.service
sleep 2
systemctl is-active zmax-station-gate.service
tail -4 /var/log/zmax-station-gate.log 2>/dev/null | sed 's/^/  /'
