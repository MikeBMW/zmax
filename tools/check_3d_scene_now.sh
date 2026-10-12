#!/usr/bin/env bash
cd /home/ubuntu/zmax || exit 1
export DISPLAY=:0
PY=gui-venv311/bin/python
shot () {  # $1 = 名字
  W=$(wmctrl -l | grep "3D场景" | awk '{print $1}' | head -1)
  [ -z "$W" ] && { echo "   ⚠️ 3D 窗不在"; return 1; }
  xdotool windowactivate --sync "$W"; sleep 1.5
  scrot -u "/tmp/3d_$1.png"
  echo "   抓 /tmp/3d_$1.png · 标题: $(wmctrl -l | grep -oP '3D场景[^ ]*( · [^ ]+)?' | head -1)"
}
echo "── ① 现场景抓图 ──"
wmctrl -l | grep "3D场景"; shot now
echo "── ② 切插拔 → 抓 ──"
$PY tools/ss_task_bind.py --activate TASK-01-FW >/dev/null 2>&1
$PY tools/ss_scene_switch.py --task TASK-01-FW 2>&1 | tail -1
sleep 10; wmctrl -l | grep "3D场景"; shot fw
echo "── ③ 切回摆盘 → 抓 ──"
$PY tools/ss_task_bind.py --activate TASK-06-TRAY >/dev/null 2>&1
$PY tools/ss_scene_switch.py --task TASK-06-TRAY 2>&1 | tail -1
sleep 10; wmctrl -l | grep "3D场景"; shot tray
echo "── ④ 图差 + 轨迹线色像素 (轨迹层是 (0.35,0.65,1.0) 蓝) ──"
$PY - <<'PY'
import cv2, numpy as np, os, glob
def rd(p): return cv2.imread(p) if os.path.isfile(p) else None
def d(x,y):
    if x is None or y is None: return 'n/a'
    if x.shape!=y.shape: return 'size不同'
    return int((np.abs(x.astype(int)-y.astype(int)).sum(2)>25).sum())
fs={os.path.basename(p):rd(p) for p in sorted(glob.glob('/tmp/3d_*.png'))}
print("   图:", list(fs))
for k,img in fs.items():
    if img is None: continue
    b,g,r=img[:,:,0].astype(int),img[:,:,1].astype(int),img[:,:,2].astype(int)   # BGR
    m=((abs(r-89)<=26)&(abs(g-166)<=26)&(abs(b-255)<=26))
    print("   %-16s 轨迹线色像素 %5d  (尺寸 %s)" % (k, int(m.sum()), img.shape))
for a in fs:
    for b2 in fs:
        if a<b2 and fs[a] is not None: print("   %-16s vs %-16s → 差异像素 %s" % (a,b2,d(fs[a],fs[b2])))
PY
