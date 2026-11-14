#!/usr/bin/env bash
# Intel 上位姿中继: Orin SDK 桥(经 ssh 隧道 39071) → Intel 的 tcp_out/latest.json
# 与 4060 上的 zmax-pose-relay.service 同一份脚本、同一口径, 只改 OUT 路径
set -e
mkdir -p /home/intel/zmax/zmax_data/rokae_sdk/tcp_out

sudo tee /etc/systemd/system/zmax-pose-relay.service >/dev/null <<'UNIT'
[Unit]
Description=Z-MAX 位姿真值中继 (Orin SDK 桥 -> latest.json) [Intel]
After=network-online.target

[Service]
Environment=ZMAX_BRIDGE_URL=http://127.0.0.1:39071
Environment=ZMAX_POSE_OUT=/home/intel/zmax/zmax_data/rokae_sdk/tcp_out/latest.json
Environment=ZMAX_POSE_RELAY_HZ=10
WorkingDirectory=/home/intel/zmax
ExecStart=/usr/bin/python3 /home/intel/zmax/tools/orin_pose_relay.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now zmax-pose-relay >/dev/null 2>&1
sleep 4
echo "服务: $(systemctl is-active zmax-pose-relay)"
echo "落盘: $(stat -c '%s bytes  %y' /home/intel/zmax/zmax_data/rokae_sdk/tcp_out/latest.json 2>/dev/null | cut -c1-60)"
python3 - <<'PY'
import json, time
p = "/home/intel/zmax/zmax_data/rokae_sdk/tcp_out/latest.json"
d = json.load(open(p))
age = time.time() - float(d.get("ts", 0))
print("位姿: x=%.2f y=%.2f z=%.2f mm  rx=%.2f ry=%.2f rz=%.2f deg" % (
    d["x"], d["y"] if False else d["y"], d["z"], d["rx"], d["ry"], d["rz"]))
print("帧龄: %.2fs  来源: %s" % (age, d.get("src")))
print("关节: %s" % ["%.1f" % v for v in (d.get("joint") or [])[:6]])
PY
