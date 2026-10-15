#!/usr/bin/env bash
# 等控制台就绪 → 统一打开(3D+信号) → 场景 摆盘↔插拔↔摆盘 各抓一张 3D 窗图 → 核 3D 窗到底装了哪条 episode
cd /home/ubuntu/zmax || exit 1
PY=gui-venv311/bin/python
export DISPLAY=:0
DISP="env DISPLAY=:0"

echo "── ① 等控制台就绪 (最多 9 分钟) ──"
for i in $(seq 1 54); do
  PID=$(ss -ltnp 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1)
  N=$(wmctrl -l 2>/dev/null | grep -c "XSpace ZMAX")
  if [ "$N" -ge 1 ]; then echo "   控制台窗口已出现 (第 $((i*10))s, pid=${PID:-?})"; break; fi
  sleep 10
done
sleep 15

echo "── ② 统一打开工程/信号/场景 (摆盘) ──"
$PY tools/ss_task_bind.py --activate TASK-06-TRAY 2>&1 | tail -1
$PY tools/ss_scene_switch.py --task TASK-06-TRAY 2>&1 | tail -1
echo open_all > /tmp/zmax_nav_cmd
sleep 25
$DISP wmctrl -l | grep -E "3D场景|信号分析" || echo "   ⚠️ 3D/信号窗还没出现"

shot () {   # $1=名字
  W=$($DISP wmctrl -l | grep "3D场景" | awk '{print $1}' | head -1)
  [ -z "$W" ] && { echo "   ⚠️ 3D 窗不在"; return; }
  $DISP bash -c "xdotool windowactivate --sync $W; sleep 1.2; scrot -u /tmp/3d_$1.png"
  echo "   抓图 /tmp/3d_$1.png  (窗标题: $($DISP wmctrl -l | grep -oP '3D场景.*' | head -1))"
}

echo "── ③ 场景 摆盘 → 抓图 ──"
shot tray1
echo "── ④ 切插拔 → 抓图 ──"
$PY tools/ss_scene_switch.py --task TASK-01-FW 2>&1 | tail -1
$PY tools/ss_task_bind.py --activate TASK-01-FW 2>&1 | tail -1
sleep 8; shot fw
echo "── ⑤ 切回摆盘 → 抓图 ──"
$PY tools/ss_scene_switch.py --task TASK-06-TRAY 2>&1 | tail -1
$PY tools/ss_task_bind.py --activate TASK-06-TRAY 2>&1 | tail -1
sleep 8; shot tray2

echo "── ⑥ 控制台日志里 3D 场景 episode 装载记录 (修好后才会有) ──"
LOG=$(ls -t logs/studio*.log /tmp/zmax_studio*.log /tmp/studio*.log 2>/dev/null | head -1)
echo "   日志: ${LOG:-未找到}"
[ -n "$LOG" ] && grep -aE "\[3D场景\]|装载|SS-TRAY-PLACE|SS-EPI-CORNER" "$LOG" | tail -8
echo "── ⑦ 两张摆盘图是否相同(应与插拔图不同) ──"
$PY - <<'PY'
import cv2, numpy as np, os
def rd(p):
    return cv2.imread(p) if os.path.isfile(p) else None
a,b,c = rd('/tmp/3d_tray1.png'), rd('/tmp/3d_fw.png'), rd('/tmp/3d_tray2.png')
def diff(x,y):
    if x is None or y is None: return 'n/a'
    if x.shape != y.shape: return 'size不同'
    return int((np.abs(x.astype(int)-y.astype(int)).sum(2) > 25).sum())
print('   摆盘1 vs 插拔 差异像素:', diff(a,b))
print('   摆盘2 vs 插拔 差异像素:', diff(c,b))
print('   摆盘1 vs 摆盘2 差异像素:', diff(a,c))
PY
