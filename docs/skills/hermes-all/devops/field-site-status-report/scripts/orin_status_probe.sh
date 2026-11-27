#!/bin/bash
# 现场只读体检 —— 不启停服务、不碰相机、不触发拍照、不下发任何动作
# 本机侧:
#   scp -P 22022 <本文件> tashan@39.102.211.79:/tmp/ && ssh -p 22022 tashan@39.102.211.79 'bash /tmp/orin_status_probe.sh'
# 或免落盘:
#   ssh orin 'bash -s' < scripts/orin_status_probe.sh
# 为什么要单独一个文件: 塞进 ssh 引号里, $t / 引号 / 多行 for 会被吃坏; 循环里 printf 与 ros2 输出会互相插行。
export ROS_DOMAIN_ID=0             # 产线栈一律 domain 0; 用 23 只能看到 /rosout
source /opt/ros/humble/setup.bash 2>/dev/null

hr(){ echo; echo "===== $* ====="; }

echo '=== 1.主机'
hostname; uptime -p; date '+%F %T %Z'
echo "load: $(cut -d' ' -f1-3 /proc/loadavg)"
free -m | awk '/Mem:/{printf "mem %s/%s MB\n",$3,$2}'
df -h / /home 2>/dev/null | awk 'NR>1{printf "disk %s %s/%s (%s)\n",$6,$3,$2,$5}'
for z in /sys/class/thermal/thermal_zone*/temp; do t=$(cat "$z" 2>/dev/null); [ -n "$t" ] && echo "temp $(basename "$(dirname "$z")"): $((t/1000))C"; done | head -4
head -1 /etc/nv_tegra_release 2>/dev/null

echo '=== 2.网络'
ip -brief addr | grep -v '^lo'
ip route show | head -6
echo "多播: $(ip route get 239.255.0.1 2>/dev/null | head -1)"
echo '   ↑ 必须是产线网卡; 落在 WiFi 说明上网口抢了 DDS 发现多播'
for h in 192.168.23.1 192.168.23.23 192.168.23.70 192.168.23.160; do
  r=$(ping -c1 -W1 "$h" 2>/dev/null | grep -o 'time=[0-9.]*' | head -1)
  echo "ping $h: ${r:-无响应}"
done
curl -s -m8 -o /dev/null -w '出网 baidu %{http_code} %{time_total}s\n' https://www.baidu.com/ 2>/dev/null

echo '=== 3.单元 / 进程 / 端口'
systemctl list-units --type=service --state=running --no-legend 2>/dev/null | awk '{print $1}' | grep -Ei 'zmax|orin|gripper|robot|motion|realsense|ss_|dds'
echo '--- 关键进程'
ps -eo pid,etime,pcpu,args --sort=-pcpu | grep -E 'robot_driver|gripper_driver|motion|orin_gateway|ss_infer|realsense|hmi_v1|tunnel|uplink|sdk_bridge' | grep -v grep | cut -c1-120 | head -12
echo '--- 监听端口'
ss -ltn | awk 'NR>1{print $4}' | sort -u | head -20

echo '=== 4.USB / 设备'
lsusb 2>/dev/null | grep -Ei 'realtek|intel|realsense|can|ftdi|honeywell|artery'
ls /dev/video* 2>/dev/null | tr '\n' ' '; echo
ls -l /dev/serial/by-id/ 2>/dev/null | awk '{print $9, $11}' | head -6

echo '=== 5.ROS (domain 0)'
ros2 daemon stop >/dev/null 2>&1; sleep 2          # 老 daemon 会缓存上一个网络的图
timeout 15 ros2 node list > /tmp/_orin_nodes 2>/dev/null
echo "节点: $(wc -l < /tmp/_orin_nodes) 个"; sed 's/^/  /' /tmp/_orin_nodes | head -25
for t in /real_joint_states /robot/joint_states /robot/force_torque /gripper_pos /motion/active_states \
         /realsense/color/image_raw /robot/tcp_pose /robot_status /barcode_scanner/status /tower_light/status; do
  pubs=$(timeout 8 ros2 topic info "$t" 2>/dev/null | grep -m1 'Publisher count' | grep -o '[0-9]\+')
  rate=$(timeout 6 ros2 topic hz "$t" 2>/dev/null | grep -m1 'average rate' | sed 's/average rate: //')
  # 话题在列表里 ≠ 有人在发: pubs=0 / rate 空 = 驱动没起
  printf '%-30s pubs=%-3s rate=%s\n' "$t" "${pubs:-?}" "${rate:-无}"
done

echo '=== 6.机械臂真值 (SDK 直桥 39061, 不依赖 ROS 栈)'
curl -s -m5 http://127.0.0.1:39061/health; echo
a=$(curl -s -m5 http://127.0.0.1:39061/status); sleep 5; b=$(curl -s -m5 http://127.0.0.1:39061/status)
python3 - "$a" "$b" <<'PY' 2>/dev/null || echo '(39061 未应答/未起)'
import json,sys
A=json.loads(sys.argv[1]); B=json.loads(sys.argv[2])
a,b=A.get("status",{}),B.get("status",{})
print("conn_ts", a.get("conn_ts"), "<- 连接时刻, 不是采样时刻; 两次相同≠数据旧")
jp,jp2=a.get("jointPos") or [],b.get("jointPos") or []
if jp: print("joints deg:", [round(x*57.2958,2) for x in jp])
if jp and jp2: print("dJoint(5s,deg):", [round((y-x)*57.2958,4) for x,y in zip(jp,jp2)])
ta,tb=a.get("jointTorque") or [],b.get("jointTorque") or []
if ta and tb: print("dTorque:", [round(y-x,4) for x,y in zip(ta,tb)], "<- 有抖动=真在采样")
fl=a.get("flangeInBase") or []
if len(fl)>=6: print("flange mm:", [round(v*1000,1) for v in fl[:3]], "rpy deg:", [round(v*57.2958,1) for v in fl[3:]])
print("power:", a.get("powerState"), "mode:", a.get("operateMode"), "vel:", a.get("jointVel"))
PY

echo '=== 7.外部服务 (从本机出发)'
for u in http://192.168.23.23:10082/storage http://192.168.23.23:10082/last_result \
         http://192.168.23.23:10083/storage http://192.168.23.23:10083/last_result \
         http://192.168.23.70:8800/health http://127.0.0.1:8765/health http://127.0.0.1:8090/; do
  printf '%-46s' "$u"
  timeout 5 curl -s -m5 -o /tmp/_p.json -w '%{http_code} ' "$u" 2>/dev/null || printf '连接失败 '
  head -c 120 /tmp/_p.json 2>/dev/null; echo; rm -f /tmp/_p.json
done

echo '=== 8.数据留存 / 遥测'
ls -ld --time-style=+%F_%T /home/tashan/.zmax/mcap 2>/dev/null || echo 'mcap 目录不存在 = 录制没开'
ls -1t /home/tashan/.zmax/mcap 2>/dev/null | head -3
journalctl -u zmax-orin-uplink -n 2 --no-pager 2>/dev/null | tail -2