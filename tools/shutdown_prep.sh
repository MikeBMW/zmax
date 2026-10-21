#!/bin/bash
# 关机前收口: 停训练/编排器/常驻服务, 但不动 intel 与 Orin
set -u
echo "== 停训练 (SIGTERM, 让其落盘) =="
for pat in "tools/joint_train_all.py" "tools/fullflow_tasks7.py" "lerobot.scripts.lerobot_train"; do
  pids=$(pgrep -f "$pat" | grep -v $$ || true)
  [ -n "$pids" ] && { echo "  kill $pat -> $pids"; kill $pids 2>/dev/null; }
done
sleep 8
echo "== 复查残留 =="
pgrep -af "joint_train_all|fullflow_tasks7|lerobot_train|collect_simreal" | grep -v "bash -c\|pgrep" | head -5
echo "== 停本机常驻服务 =="
for s in zmax-studio.service sam3-seg.service; do
  st=$(systemctl --user is-active $s 2>/dev/null)
  if [ "$st" = "active" ]; then systemctl --user stop $s && echo "  stopped $s"; else echo "  $s 已是 $st"; fi
done
echo "== GPU/内存 =="
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader
free -g | head -2
