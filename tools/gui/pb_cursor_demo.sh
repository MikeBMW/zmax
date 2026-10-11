#!/usr/bin/env bash
# 现场取证: 拖 3D 场景的播放进度条 ⇒ 实时监控页的竖线时刻是否跟着变
set -u
export DISPLAY=:0
cd /home/ubuntu/zmax
ZK=zmax_data/ss_live/trace_live.json
frame_now() { python3 -c "
import json,sys
try:
    d=json.load(open('$ZK'))
    print('%s %s %.3f' % (d.get('帧'), d.get('总帧'), float(d.get('时间_s') or -1)))
except Exception as e:
    print('ERR', e)"; }

fnum() { python3 -c "import json
try:
    print(json.load(open('$ZK')).get('帧'))
except Exception:
    print('ERR')" 2>/dev/null; }

GW=$(wmctrl -l | grep -i "Graphic" | awk '{print $1}')
SS=$(wmctrl -l | grep "3D场景" | awk '{print $1}')
echo "gw=$GW ss3d=$SS"
[ -z "$SS" ] && { echo "3D 场景窗没开"; exit 3; }
wmctrl -i -r $SS -e 0,40,200,1300,900
wmctrl -i -r $GW -e 0,1380,200,1560,1050
wmctrl -i -a $GW; sleep 1; wmctrl -i -a $SS; sleep 1
eval $(xdotool getwindowgeometry --shell $SS)
WX=$X; WY=$Y; WW=$WIDTH; WH=$HEIGHT
BEFORE_F=$(fnum); before=$(frame_now); echo "拖动前: 帧=$BEFORE_F / $before"
# 在窗口最下面一条上扫几个 y, 找那条进度条 (点一下帧号会跳到对应位置)
for fy in 42 34 28 22 16 10; do
  YY=$(( WY + WH - fy ))
  for fx in 35 55 70; do
    XX=$(( WX + WW * fx / 100 ))
    xdotool mousemove $XX $YY click 1
    sleep 0.8
    NOW_F=$(fnum)
    if [ "$NOW_F" != "$BEFORE_F" ] && [ "$NOW_F" != "ERR" ]; then
      echo "  ✓ 命中进度条: 点(${fx}%, 底-${fy}px) → 帧 $BEFORE_F → $NOW_F"
      FOUND=1; break 2
    fi
  done
  echo "  (底-${fy}px 不是进度条)"
done
sleep 1.2
after=$(frame_now); echo "拖动后: $after"
scrot -o /tmp/pb_demo.png
python3 - <<'EOF'
from PIL import Image
im=Image.open('/tmp/pb_demo.png')
im.crop((1380,200,2940,520)).resize((3120,640), Image.LANCZOS).save('/tmp/pb_status.png')
im.crop((40,200,1340,1100)).save('/tmp/pb_3d.png')
EOF
echo "=== 波形页状态行 ==="
tesseract /tmp/pb_status.png stdout -l chi_sim+eng --psm 6 2>/dev/null | grep -E "3D 播放|数据时刻|场景" | head -3
echo "=== 3D 场景窗 ==="
tesseract /tmp/pb_3d.png stdout -l chi_sim+eng --psm 6 2>/dev/null | grep -E "快照时刻|场景时刻" | head -3
