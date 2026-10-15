#!/usr/bin/env bash
# 一次性重启 → 摆盘/插拔各抓图 + 量像素 + 核日志 (盒定位/光模块尺寸/插拔专属图层 三处修复)
cd /home/ubuntu/zmax || exit 1
export DISPLAY=:0
PY=gui-venv311/bin/python

echo "── ① 重启控制台 (载入三处修复) ──"
unset QT_QPA_PLATFORM
bash tools/studio_ctl.sh restart --force 2>&1 | tail -2
for i in $(seq 1 30); do wmctrl -l 2>/dev/null | grep -q "XSpace ZMAX" && { echo "   就绪 ($((i*10))s)"; break; }; sleep 10; done
sleep 20

echo "── ② 打开(摆盘) ──"
$PY tools/ss_task_bind.py --activate TASK-06-TRAY >/dev/null 2>&1
$PY tools/ss_scene_switch.py --task TASK-06-TRAY 2>&1 | tail -1
echo open_all > /tmp/zmax_nav_cmd
sleep 28
W=$(wmctrl -l | grep "3D场景" | awk '{print $1}' | head -1)
echo "   3D窗=$W"
[ -n "$W" ] && xdotool windowactivate --sync "$W" && sleep 2 && scrot -u /tmp/fix_tray.png && echo "   抓 /tmp/fix_tray.png"

echo "── ③ 切插拔 ──"
$PY tools/ss_task_bind.py --activate TASK-01-FW >/dev/null 2>&1
$PY tools/ss_scene_switch.py --task TASK-01-FW 2>&1 | tail -1
sleep 16
W=$(wmctrl -l | grep "3D场景" | awk '{print $1}' | head -1)
[ -n "$W" ] && xdotool windowactivate --sync "$W" && sleep 2 && scrot -u /tmp/fix_fw.png && echo "   抓 /tmp/fix_fw.png"

echo "── ④ 日志: 三处修复是否生效 ──"
L=$(ls -t /tmp/studio_launch_*.log | head -1)
echo "   日志: $L"
grep -aE "\[3D场景\]" "$L" | tail -8

echo "── ⑤ 像素核对 (盒↔孔口 / 盘件金 饱和度) ──"
$PY - <<'PY'
import cv2, numpy as np
for nm,p in (("插拔", "/tmp/fix_fw.png"), ("摆盘", "/tmp/fix_tray.png")):
    im=cv2.imread(p)
    if im is None: print("   %s 图缺" % nm); continue
    hsv=cv2.cvtColor(im,cv2.COLOR_BGR2HSV)
    h,s,v=hsv[:,:,0].astype(int),hsv[:,:,1].astype(int),hsv[:,:,2].astype(int)
    gs=((h>=15)&(h<=35)&(s>=120)&(v>=120)); pg=((h>=15)&(h<=35)&(s>=30)&(s<120)&(v>=170))
    print("   %s: 饱和金 %d px · 淡金 %d px · 淡/饱和=%.2f" % (nm, int(gs.sum()), int(pg.sum()), pg.sum()/max(1,gs.sum())))
    # 红盒 (shaded 会变暗) → 用 H 判红: h<8 或 >172 且饱和高
    red=(((h<=8)|(h>=172))&(s>=120)&(v>=90)); ys,xs=np.where(red)
    if len(xs): print("      红盒像素 %d bbox x[%d..%d] y[%d..%d]" % (len(xs), xs.min(), xs.max(), ys.min(), ys.max()))
PY
