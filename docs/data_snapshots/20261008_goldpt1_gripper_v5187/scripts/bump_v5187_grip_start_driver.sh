#!/bin/bash
# 老倪: 「关闭夹抓, 还是不好使, 修」→ ① 在 Orin 拉起 gripper_driver ② 用执行器同口径发闭合 ③ 读真值验收
set -u
SSH="ssh -o BatchMode=yes -o ConnectTimeout=8 tashan@192.168.23.66"
WS=/home/tashan/0810/tashan_robot_so_20260924_142706_0cabfde_aarch64/install/setup.bash
PRE="source /opt/ros/humble/setup.bash; source $WS; export ROS_DOMAIN_ID=0 FASTDDS_BUILTIN_TRANSPORTS=UDPv4 ROS_LOCALHOST_ONLY=0;"

echo "═══ ⓪ 顺带看臂到点1了没 ═══"
gui-venv311/bin/python - <<'EOF'
import sys, math; sys.path.insert(0, '/home/ubuntu/zmax/tools/rokae')
import l2_transport_sdk as T
c = T.read_pose(); t = (0.596737, 0.142622, 0.641536)
print("   臂 (%.4f,%.4f,%.4f) · 距点1 %.1fmm · 帧龄%.2fs" % (*c['pos'], math.dist(t, c['pos'])*1000, c['age']))
EOF

echo
echo "═══ ① 拉起 gripper_driver(常驻, 脱 ssh) ═══"
timeout 60 $SSH "$PRE mkdir -p /home/tashan/.zmax/logs; setsid nohup ros2 run gripper gripper_driver > /home/tashan/.zmax/logs/gripper_driver.log 2>&1 < /dev/null & sleep 6; echo '--- 进程 ---'; ps -eo pid,etime,cmd | grep -i gripper_driver | grep -v grep | head -3; echo '--- 日志前 8 行 ---'; head -8 /home/tashan/.zmax/logs/gripper_driver.log 2>/dev/null" 2>&1 | sed 's/^/   /'

echo
echo "═══ ② 等它就绪(最多 40s) ═══"
for i in $(seq 1 8); do
  sleep 5
  S=$(timeout 40 $SSH "$PRE timeout 12 ros2 service list 2>/dev/null | grep -c gripper" 2>/dev/null | tr -d ' \r')
  P=$(timeout 40 $SSH "$PRE timeout 12 ros2 topic list 2>/dev/null | grep -c gripper_pos" 2>/dev/null | tr -d ' \r')
  echo "   [$((i*5))s] gripper 服务=$S · gripper_pos 话题=$P"
  if [ "${S:-0}" -ge 1 ] && [ "${P:-0}" -ge 1 ]; then echo "   ✅ 已就绪"; break; fi
done

echo
echo "═══ ③ 闭合(执行器原式: pos=0.0 · force=40 · 其余保持) ═══"
timeout 90 $SSH "$PRE timeout 60 ros2 service call /gripper_driver interfaces/srv/GripperSrv '{target_pos: 0.0, target_speed: -1.0, target_force: 40, target_acc: -1.0, target_push_length: -1.0, target_push_speed: -1.0}'" 2>&1 | head -12 | sed 's/^/   /'

echo
echo "═══ ④ 真值验收 /gripper_pos(连续 4 次) ═══"
for i in 1 2 3 4; do
  printf "   [%d] " $i
  timeout 30 $SSH "$PRE timeout 10 ros2 topic echo --once /gripper_pos 2>/dev/null" 2>/dev/null | head -3 | tr '\n' ' '
  echo
  sleep 2
done
echo "   口径: 空爪≈21 / 夹住模块≈185"
