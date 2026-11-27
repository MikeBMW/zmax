#!/bin/bash
# 最小改动版: 只把执行器里的服务名 /gripper_driver → /gripper_srv(驱动真实名字), 不动字符串结构
set -u
cd /home/ubuntu/zmax
SSH="ssh -o BatchMode=yes -o ConnectTimeout=8 tashan@192.168.23.66"
WS=/home/tashan/0810/tashan_robot_so_20260924_142706_0cabfde_aarch64/install/setup.bash
ENVX="export ROS_DOMAIN_ID=0 FASTDDS_BUILTIN_TRANSPORTS=UDPv4 ROS_LOCALHOST_ONLY=0;"
READ="timeout 10 ros2 topic echo --once /gripper_pos std_msgs/msg/Float32 2>/dev/null | grep data"

echo "① 执行器现状(应仍在跑, 用旧名):"
ps -eo pid,etime,cmd | grep 'tools/l2_daemon.py' | grep -v grep | cut -c1-90 | sed 's/^/   /'
echo "   代码里 /gripper_driver 处数: $(grep -c '/gripper_driver' tools/l2_daemon.py) · 行号: $(grep -n '/gripper_driver' tools/l2_daemon.py | cut -d: -f1 | tr '\n' ' ')"

echo
echo "② 最小改动(纯名字替换):"
cp tools/l2_daemon.py zmax_data/backups/l2_daemon.py.$(date +%Y%m%d_%H%M%S)b.bak
python3 - <<'EOF'
p='/home/ubuntu/zmax/tools/l2_daemon.py'
s=open(p,encoding='utf-8').read()
n=s.count('/gripper_driver')
s=s.replace('/gripper_driver','/gripper_srv')
open(p,'w',encoding='utf-8').write(s)
print('   替换 %d 处 → 现在 /gripper_srv=%d 处, /gripper_driver=%d 处'%(n,s.count('/gripper_srv'),s.count('/gripper_driver')))
EOF
if gui-venv311/bin/python -m py_compile tools/l2_daemon.py; then
  echo "   语法 ✅"
else
  echo "   语法 ❌ 回滚"; cp $(ls -t zmax_data/backups/l2_daemon.py.*b.bak | head -1) tools/l2_daemon.py; exit 1
fi

echo
echo "③ 重启执行器(抓现环境原样拉起):"
PID=$(pgrep -f 'tools/l2_daemon.py' | head -1)
if [ -n "${PID:-}" ]; then
  tr '\0' '\n' < /proc/$PID/environ 2>/dev/null | grep -E '^(ZMAX_|ROS_|FASTDDS|RMW_)' > /tmp/l2d_env.txt || true
  echo "   抓到环境 $(wc -l < /tmp/l2d_env.txt) 条 · 守护进程: $(ps -eo pid,cmd | grep -iE 'keepalive' | grep -v grep | wc -l) 个"
  kill "$PID" && echo "   kill $PID"
fi
sleep 10
if ! pgrep -f 'tools/l2_daemon.py' >/dev/null; then
  echo "   无守护 ⇒ 按抓到环境子启"
  ( set -a; . /tmp/l2d_env.txt 2>/dev/null; set +a; setsid nohup gui-venv311/bin/python tools/l2_daemon.py >> zmax_data/l2_daemon_stdout.log 2>&1 < /dev/null & )
  sleep 12
fi
echo "   执行器 pid: $(pgrep -f 'tools/l2_daemon.py' | head -1)"

echo
echo "④ 验收: 走页面同一条通道点 L2.grip_close(真值应仍在 0.0 闭合处, 关键看回执有没有 curr_pos)"
curl -s --max-time 45 -X POST http://127.0.0.1:8793/ctl/move -H 'Content-Type: application/json' \
  -d '{"skill":"L2.grip_close","arm":1}' | head -c 420 | sed 's/^/   回执: /'
echo
sleep 10
echo "   --- 执行器最近 8 行 ---"
tail -8 zmax_data/l2_daemon_stdout.log | cut -c1-180 | sed 's/^/   /'
echo "   --- 夹爪真值 ---"
for i in 1 2; do printf "   [%d] " $i; timeout 40 $SSH "source /opt/ros/humble/setup.bash; source $WS; $ENVX $READ" 2>/dev/null | tr '\n' ' '; echo; sleep 2; done