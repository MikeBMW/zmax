#!/bin/bash
# 清掉可能卡住的轨迹执行进程与锁 (2026-10-25: traj_exec 卡住时会一直占着 flock,
# 后续点击全被"已有另一个 traj_exec 正在执行"拒掉, 表现就是"点了没反应")
cd /home/ubuntu/zmax || exit 1
for p in $(pgrep -f "tools/traj_exec"); do
  echo "kill $p"
  kill -9 "$p" 2>/dev/null
done
rm -f zmax_data/runtime/traj/traj_exec.lock
rm -f zmax_data/runtime/traj/traj_state.json
echo "清理完成; 剩余=$(pgrep -cf 'tools/traj_exec' || true)"
