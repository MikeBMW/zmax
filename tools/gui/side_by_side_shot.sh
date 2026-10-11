#!/usr/bin/env bash
# 并排摆: 3D 场景窗(左) + 信号窗口(右), 控制台先最小化 (只为出一张"两边时刻对得上"的取证图)
set -u
export DISPLAY=:0
CONSOLE=0x01e0057e
SS3D=0x01e00597
GW=0x02a00006
xdotool windowminimize $CONSOLE 2>/dev/null
sleep 1
wmctrl -i -r $SS3D -e 0,40,200,1300,900
sleep 1
wmctrl -i -r $GW -e 0,1380,200,1560,1050
sleep 1
wmctrl -i -a $SS3D; sleep 1; wmctrl -i -a $GW; sleep 2
scrot -o /tmp/side_by_side.png
sleep 1
wmctrl -i -a $CONSOLE
echo "saved /tmp/side_by_side.png"
for w in $SS3D $GW; do xdotool getwindowgeometry $w 2>/dev/null | sed -n '2,3p'; echo "--"; done
