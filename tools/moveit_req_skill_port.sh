#!/bin/bash
# 2026-10-18: MoveIt 请求器改为「技能口给目标」— 段由引擎发布的 skill_gate.json 提供;
# 段陈旧/引擎没跑 ⇒ _stage_of 返回 None ⇒ 自动退回人工示教点 slot7 (原行为, 不中断可用性)。
set -e
cat > /etc/systemd/system/zmax-moveit-plan-req.service.d/override.conf <<'EOF'
[Service]
# 🎯 目标来源: --auto 读 ss_live/skill_gate.json 的当前段 (原子技能口算目标位姿)
#    段真值超过 SS_GATE_MAX_AGE 秒 ⇒ 打印帧龄并退回 --to 示教点 (绝不猜)
Environment=SS_GATE_MAX_AGE=10.0
ExecStart=
ExecStart=/usr/bin/python3 /home/ubuntu/zmax/tools/moveit_plan_req.py --auto --to slot7 --watch --interval 1.0
EOF
# 保留最近 2000 行 req.log (原来已 20MB, 每秒一行会无限涨)
mkdir -p /etc/systemd/system/zmax-moveit-plan-req.service.d
systemctl daemon-reload
systemctl restart zmax-moveit-plan-req.service
sleep 4
systemctl is-active zmax-moveit-plan-req.service
tail -3 /home/ubuntu/zmax/zmax_data/runtime/moveit_plan/req.log
