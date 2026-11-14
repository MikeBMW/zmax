#!/usr/bin/env bash
# Intel 上建立到 Orin 的硬件桥隧道(39071 -> Orin 39061), 与 4060 上那条一模一样
pkill -f 'L 127.0.0.1:39071' 2>/dev/null
sleep 1
setsid nohup ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=10 -o ServerAliveCountMax=3 -o TCPKeepAlive=yes -o ConnectTimeout=20 \
  -L 127.0.0.1:39071:127.0.0.1:39061 \
  tashan@192.168.23.66 >/tmp/tun39071.log 2>&1 < /dev/null &
sleep 3
echo "监听: $(ss -ltn 2>/dev/null | grep -c 39071)"
echo "位姿: $(curl -s -m 5 http://127.0.0.1:39071/status | head -c 220)"
