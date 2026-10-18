#!/bin/bash
# 停跟随 + 重启 SDK 腿容器 (写脚本里跑, 避免 pkill -f 匹配到自己这条命令行)
set -u
cd /home/ubuntu/zmax
# 只杀 python 进程 —— 否则 pgrep -f 会匹配到调用本脚本的那条 bash 命令行, 把自己杀掉
for p in $(pgrep -f "bridge_follow_live[.]py"); do
  c=$(cat /proc/$p/comm 2>/dev/null)
  case "$c" in python|python3) kill -TERM "$p" 2>/dev/null;; esac
done
sleep 1
python3 - <<'PY'
import json, os
FIFO = "/home/ubuntu/zmax/zmax_data/rokae_sdk/cmd_arm.fifo"
try:
    fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
    os.write(fd, (json.dumps({"cmd": "follow", "on": False}) + "\n").encode())
    os.close(fd)
    print("follow off 已发")
except OSError as e:
    print("FIFO:", e)
PY
sudo docker restart zmax-sdk-arm-agent >/dev/null 2>&1
sleep 12
sudo docker ps --format '{{.Names}} {{.Status}}' | grep sdk-arm
python3 -c "
import json,time,os
p='/home/ubuntu/zmax/zmax_data/rokae_sdk/tcp_out/agent_heartbeat.json'
d=json.load(open(p))
print('pose=',[round(x,4) for x in (d.get('pose') or {}).get('tcp',[])],'age=%.1fs'%(time.time()-os.path.getmtime(p)))"
