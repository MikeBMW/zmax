#!/usr/bin/env bash
# 重启控制台 → 待就绪 → 统一打开 → **单独切场景**(插拔↔摆盘) → 核 3D 窗是否跟随 + 是否换 episode 真源
cd /home/ubuntu/zmax || exit 1
export DISPLAY=:0
PY=gui-venv311/bin/python
LOG_BEFORE=$(ls -t /tmp/studio_launch_*.log 2>/dev/null | head -1)

echo "── ① 重启控制台 (载入 3D 场景跟随/换 episode 的新码) ──"
unset QT_QPA_PLATFORM
bash tools/studio_ctl.sh restart --force 2>&1 | tail -2

echo "── ② 等窗口就绪 (最多 8 分钟) ──"
for i in $(seq 1 48); do
  wmctrl -l 2>/dev/null | grep -q "XSpace Studio" && { echo "   就绪 (第 $((i*10))s)"; break; }
  sleep 10
done
sleep 20

echo "── ③ 统一打开 (摆盘) ──"
$PY tools/ss_task_bind.py --activate TASK-06-TRAY 2>&1 | tail -1
$PY tools/ss_scene_switch.py --task TASK-06-TRAY 2>&1 | tail -1
echo open_all > /tmp/zmax_nav_cmd
sleep 30
wmctrl -l | grep -E "3D场景|信号分析" || echo "   ⚠️ 窗未出现"

echo "── ④ **单独切场景** 摆盘 → 插拔 (不按启动按钮) ──"
$PY tools/ss_scene_switch.py --task TASK-01-FW 2>&1 | tail -1
sleep 14; wmctrl -l | grep "3D场景"
echo "── ⑤ 再单独切回 摆盘 ──"
$PY tools/ss_scene_switch.py --task TASK-06-TRAY 2>&1 | tail -1
sleep 14; wmctrl -l | grep "3D场景"

echo "── ⑥ 3D 窗日志 (跟随 + 装载) ──"
LOG=$(ls -t /tmp/studio_launch_*.log 2>/dev/null | head -1)
echo "   日志: $LOG"
grep -aE "\[3D场景\]" "$LOG" | tail -8

echo "── ⑦ 抓摆盘态 3D 窗 + 计数 ──"
W=$(wmctrl -l | grep "3D场景" | awk '{print $1}' | head -1)
xdotool windowactivate --sync "$W"; sleep 1.5
scrot -u /tmp/3d_after_fix.png
$PY - <<'PY'
import cv2
im=cv2.imread('/tmp/3d_after_fix.png')
print("   图:", None if im is None else im.shape)
if im is not None:
    b,g,r=im[:,:,0].astype(int),im[:,:,1].astype(int),im[:,:,2].astype(int)
    print("   轨迹线色(89,166,255)像素: %d" % int(((abs(r-89)<=26)&(abs(g-166)<=26)&(abs(b-255)<=26)).sum()))
PY
