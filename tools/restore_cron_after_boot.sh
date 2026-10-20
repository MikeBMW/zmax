#!/bin/bash
# 开机后恢复 2026-10-20 关机时暂停的 14 条定时任务
# 用法: bash tools/restore_cron_after_boot.sh
set -e
BAK=/tmp/crontab_before_shutdown_20261020.txt
[ -f "$BAK" ] || { echo "❌ 备份不存在: $BAK"; exit 1; }
crontab "$BAK"
echo "✓ crontab 已恢复 ($(crontab -l | grep -vcE '^#|^$') 条活跃)"
# 服务
for u in sam3-seg ss-bypass ss-local-infer ss-yolo-bypass aoi-feishu-push zmax-mapping zmax-net-optimize \
         zmax-dds-ss zmax-dds-agg zmax-dds-pub zmax-engdb zmax-traj-ar zmax-traj-pub zmax-traj-rec \
         zmax-station-gate zmax-ss-engine-loop zmax-ss-trace-pub zmax-ss-skill-dispatch zmax-torque-bus \
         zmax-gravity-pub zmax-hil-bridge zmax-agent-hub zmax-ctl-stop zmax-proxy zmax-web-agent-bridge \
         zmax-dataspaces-loop zmax-dataspaces-probe zmax-ss3d-live-push zmax-studio-mem-guard \
         zmax-moveit-plan-req zmax-tunnel-proxy zmax-tunnel-lhr zmax-ecs-ov zmax-ecs-station; do
  systemctl is-enabled "$u" >/dev/null 2>&1 && sudo -S -p '' systemctl start "$u" 2>/dev/null && echo "  ✓ $u"
done
