#!/usr/bin/env bash
# 在 Intel 550C 上部署「画布节点常驻循环」, 白名单 = ssplan (长程元任务编排器)
# 目的: 工厂侧 550C 也能由元任务驱动 (写 ar_cmd.json → 供 AR 页/执行链读), 真机零指令
set -uo pipefail
H=intel@192.168.23.70
D=/home/intel/zmax_550c

echo "① 推 ss_canvas_loop.py"
rsync -az /home/ubuntu/zmax/tools/ss_canvas_loop.py $H:$D/tools/ || exit 1

echo "② 建 systemd 单元 (Intel 侧)"
ssh -o BatchMode=yes $H 'sudo tee /etc/systemd/system/zmax-ss-canvas-loop.service >/dev/null <<"EOF"
[Unit]
Description=Z-MAX 550C 状态空间画布常驻循环 (白名单 ssplan · 元任务驱动 · 真机零指令)
After=network.target

[Service]
Type=simple
User=intel
WorkingDirectory=/home/intel/zmax_550c
Environment=ZMAX_CANVAS_ONLY=ssplan
Environment=ZMAX_UPH_AR_PUB=0
Environment=ZMAX_SS_LIVE=/home/intel/zmax_550c/zmax_data/ss_live
ExecStart=/home/intel/gsxpu-venv/bin/python /home/intel/zmax_550c/tools/ss_canvas_loop.py run --hz 10
Restart=always
RestartSec=5
StandardOutput=append:/home/intel/zmax_550c/zmax_data/logs/ss_canvas_loop.log
StandardError=append:/home/intel/zmax_550c/zmax_data/logs/ss_canvas_loop.log

[Install]
WantedBy=multi-user.target
EOF
sudo mkdir -p /home/intel/zmax_550c/zmax_data/logs /home/intel/zmax_550c/zmax_data/ss_live
sudo systemctl daemon-reload && sudo systemctl enable --now zmax-ss-canvas-loop 2>&1 | tail -2
sleep 6
echo "③ 状态: $(systemctl is-active zmax-ss-canvas-loop)"
echo "④ 回读 ar_cmd.json:"
python3 - <<"PY"
import json, os, time
p = "/home/intel/zmax_550c/zmax_data/ss_live/ar_cmd.json"
if not os.path.exists(p):
    print("  ❌ 未生成", p); raise SystemExit(1)
d = json.load(open(p, encoding="utf-8"))
age = time.time() - os.path.getmtime(p)
print("  文件龄 %.2fs | seq=%s | kind=%s | mt=%s %s (%s/%s) batch=%s | task=%s"
      % (age, d.get("seq"), d.get("kind"), d.get("mt_id"), d.get("mt_name"),
         d.get("mt_i"), d.get("mt_n"), d.get("batch"), d.get("task_id")))
ok = bool(d.get("mt_id")) and age < 5
print("  判据: 元任务字段齐 + 帧龄<5s → %s" % ("✅ 通过" if ok else "❌ 未通过"))
raise SystemExit(0 if ok else 1)
PY
echo "⑤ 日志尾:"
tail -3 /home/intel/zmax_550c/zmax_data/logs/ss_canvas_loop.log 2>/dev/null
'
echo "rc=$?"
