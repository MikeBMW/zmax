#!/bin/bash
# 停掉流式跟随 (只杀 python 进程, 不匹配本脚本自己的命令行)
set -u
cd /home/ubuntu/zmax
for p in $(pgrep -f "bridge_follow_live[.]py"); do
  c=$(cat /proc/$p/comm 2>/dev/null)
  case "$c" in python|python3) kill -TERM "$p" 2>/dev/null && echo "killed $p";; esac
done
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
sleep 1
python3 -c "
import json
s=json.load(open('/home/ubuntu/zmax/zmax_data/rokae_sdk/follow/status.json'))
print('follow 线程 on=%s n=%s why=%s'%(s.get('on'),s.get('n'),str(s.get('why'))[:40]))"
