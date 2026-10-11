#!/usr/bin/env bash
# 真机取证: 在 3D 场景窗里把进度条拖到 3 个不同位置, 看实时监控的竖线 x / 场景时刻是否同步跟着变
set -u
export DISPLAY=:0
SS=$(wmctrl -l | grep "3D场景" | awk '{print $1}')
GW=$(wmctrl -l | grep -i "Graphic" | awk '{print $1}')
[ -z "$SS" ] && { echo "3D 场景窗没开"; exit 3; }
wmctrl -i -r $SS -e 0,40,200,1300,900; sleep 1
wmctrl -i -r $GW -e 0,1380,200,1560,1050; sleep 1
wmctrl -i -a $GW; sleep 1; wmctrl -i -a $SS; sleep 1
eval $(xdotool getwindowgeometry --shell $SS)
WX=$X; WY=$Y; WW=$WIDTH; WH=$HEIGHT
Y=$(( WY + WH - 42 ))          # 刚测出来的进度条所在行
echo "=== 依次点进度条: 20% → 70% → 30% ==="
for fx in 20 70 30; do
  xdotool mousemove $(( WX + WW * fx / 100 )) $Y click 1
  sleep 2.6
  echo "--- 点 ${fx}% 之后 ---"
  python3 -c "
import json,time
d=json.load(open('/home/ubuntu/zmax/zmax_data/ss_live/trace_live.json'))
print('  3D 侧: 帧 %s/%s · 场景时刻 %.3fs · 🕒 %s' % (d.get('帧'),d.get('总帧'),float(d.get('时间_s') or -1), time.strftime('%H:%M:%S',time.localtime(d.get('ts',0)))))"
  grep "SELFCHECK t=" /tmp/gw_watch.log | tail -1 | sed 's/^/  波形侧: /'
done
echo
echo "=== 波形侧完整轨迹 (每 2s 一行, 看竖线x/场景时刻是否随我点的位置左右走) ==="
grep "SELFCHECK t=" /tmp/gw_watch.log | tail -14
