#!/bin/bash
# 安装 studio.py 内存看门狗 (systemd timer, 每 2 分钟) — 2026-10-18 OOM 事故后加
set -e
cat > /etc/systemd/system/zmax-studio-mem-guard.service <<'EOF'
[Unit]
Description=Z-MAX studio.py 内存看门狗 (单实例>8GB 或孤儿>2GB ⇒ SIGTERM)
After=multi-user.target

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/zmax
Environment=STUDIO_MAX_GB=8
Environment=STUDIO_ORPHAN_GB=2
Environment=STUDIO_TOTAL_GB=12
ExecStart=/usr/bin/python3 /home/ubuntu/zmax/tools/studio_mem_guard.py --enforce
StandardOutput=append:/home/ubuntu/zmax/zmax_data/ops/studio_guard.log
StandardError=append:/home/ubuntu/zmax/zmax_data/ops/studio_guard.log
EOF

cat > /etc/systemd/system/zmax-studio-mem-guard.timer <<'EOF'
[Unit]
Description=每 2 分钟检查 studio.py 内存 (防整机 OOM)

[Timer]
OnBootSec=3min
OnUnitActiveSec=2min
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF

mkdir -p /home/ubuntu/zmax/zmax_data/ops
systemctl daemon-reload
systemctl enable --now zmax-studio-mem-guard.timer
systemctl start zmax-studio-mem-guard.service
sleep 2
echo "--- timer 状态 ---"
systemctl is-active zmax-studio-mem-guard.timer
systemctl list-timers zmax-studio-mem-guard.timer --no-pager | head -3
echo "--- 首次运行结果 ---"
tail -3 /home/ubuntu/zmax/zmax_data/ops/studio_guard.log 2>/dev/null || echo "(无输出=正常)"
