#!/bin/bash
# migrate_550c_phase1.sh — 550C 服务迁移 Phase 1 (无硬件依赖的核心服务)
# 生成时间: 2026-10-25  目标: Intel 端侧主节点
set -u
UNIT_DIR="$HOME/.zmax_migrated_units"
PHASE1="zmax-engdb zmax-ss-engine-loop zmax-ss-skill-dispatch zmax-ss-trace-pub
        zmax-ss3d-live-push zmax-gravity-pub zmax-traj-ar zmax-traj-pub zmax-traj-rec
        zmax-dashboard zmax-agent-hub zmax-web-agent-bridge zmax-fw-render
        zmax-mapping zmax-hil-bridge zmax-dataspaces-loop zmax-dataspaces-probe
        zmax-symmetry-adopt zmax-dds-agg zmax-dds-pub zmax-dds-ss zmax-moveit-plan-req"

echo "=== 安装 unit ==="
ok=0; miss=0
for u in $PHASE1; do
  f="$UNIT_DIR/$u.service"
  if [ -f "$f" ]; then
    sudo cp "$f" /etc/systemd/system/ && ok=$((ok+1))
  else
    echo "  ⚠ 缺 unit: $u"; miss=$((miss+1))
  fi
done
echo "  已安装 $ok 个, 缺失 $miss 个"
sudo systemctl daemon-reload

echo
echo "=== 逐个启动 (enable --now) ==="
for u in $PHASE1; do
  [ -f "/etc/systemd/system/$u.service" ] || continue
  sudo systemctl enable --now "$u" >/dev/null 2>&1
  st=$(systemctl is-active "$u" 2>/dev/null)
  printf "  %-34s %s\n" "$u" "$st"
done

echo
echo "=== 验收 A: 进程/端口 ==="
sleep 3
for u in $PHASE1; do
  [ -f "/etc/systemd/system/$u.service" ] || continue
  st=$(systemctl is-active "$u" 2>/dev/null)
  pid=$(systemctl show -p MainPID --value "$u" 2>/dev/null)
  port=$(sudo ss -ltnp 2>/dev/null | grep "pid=$pid," | grep -oE ':[0-9]{4,5} ' | head -1 | tr -d ': ')
  printf "  %-34s %-8s pid=%-8s port=%s\n" "$u" "$st" "${pid:-—}" "${port:-—}"
done

echo
echo "=== 验收 B: 失败项日志 (只打有错的) ==="
for u in $PHASE1; do
  [ -f "/etc/systemd/system/$u.service" ] || continue
  if [ "$(systemctl is-active "$u" 2>/dev/null)" != "active" ]; then
    echo "--- $u"
    sudo journalctl -u "$u" -n 6 --no-pager 2>/dev/null | tail -6
  fi
done
