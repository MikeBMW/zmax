#!/bin/bash
# 老倪: 「你自己开回金手指点1」
# 手法: 位置不动、只把姿态对齐到点1(ΔB=-15.65°) → 再重试 MoveL。
# 为什么这样: 控制器对"带 15.9° 姿态差 + 96mm 平移"的 MoveL 返 rc=6/CHECK;
#            原地只转轴(零平移)是最小风险的一类动作, 且不违反台账规则 A(没用分段绕过平移路径)。
set -u
cd /home/ubuntu/zmax
PY=gui-venv311/bin/python
L=zmax_data/l2_daemon_stdout.log

echo "═══ 0) 起始真值 ═══"
$PY - <<'EOF'
import sys,math,json; sys.path.insert(0,'/home/ubuntu/zmax/tools/rokae')
import l2_transport_sdk as T
c=T.read_pose(); print("   臂 (%.4f,%.4f,%.4f) abc=[%.3f,%.3f,%.3f] 帧龄%.2fs"%(*c['pos'],*[math.degrees(x) for x in c['rpy']],c['age']))
EOF

echo
echo "═══ 1) 绕 B 轴 −16°(位置不动) ═══"
echo "   下发..."
curl -s --max-time 30 -X POST http://127.0.0.1:8793/ctl/move \
  -H 'Content-Type: application/json' \
  -d '{"skill":"L2.rot_b_neg","deg":16,"speed":8,"arm":1}' | head -c 400 | sed 's/^/   回执: /'
echo
for i in $(seq 1 12); do
  sleep 8
  R=$($PY - <<'EOF'
import sys,math; sys.path.insert(0,'/home/ubuntu/zmax/tools/rokae')
import l2_transport_sdk as T
c=T.read_pose(); print("%.4f %.4f %.4f %.3f %.3f %.3f"%(c['pos'][0],c['pos'][1],c['pos'][2],*[math.degrees(x) for x in c['rpy']]))
EOF
)
  echo "   [$((i*8))s] $R"
  B=$(echo "$R" | awk '{print $5}')
  if awk -v b="$B" 'BEGIN{exit !(b < 4.0)}'; then echo "   ↳ B 已接近目标 2.2° ⇒ 停等"; break; fi
done

echo
echo "═══ 2) 重试点1(单条 MoveL, 不切段) ═══"
curl -s --max-time 40 -X POST http://127.0.0.1:8793/ctl/move \
  -H 'Content-Type: application/json' \
  -d '{"skill":"L2.goto_gold_pt1","speed":8,"arm":1}' | head -c 400 | sed 's/^/   回执: /'
echo
echo "   等 25s 看执行器真值..."
sleep 25
tail -8 "$L" | grep -aE "目标 L2.goto|已下发|SDK 腿|到位|❌|✅" | cut -c1-175 | sed 's/^/   /'

echo
echo "═══ 3) 结局真值 ═══"
$PY - <<'EOF'
import sys,math,time; sys.path.insert(0,'/home/ubuntu/zmax/tools/rokae')
import l2_transport_sdk as T
a=T.read_pose(); p0=list(a['pos']); time.sleep(3); b=T.read_pose()
T1=(0.596737,0.142622,0.641536)
print("   %s (%.4f,%.4f,%.4f) → (%.4f,%.4f,%.4f) · %.2fmm/s"%(
  time.strftime('%H:%M:%S'),*p0,*b['pos'],math.dist(p0,b['pos'])/3*1000))
print("   距点1 %.1fmm · 帧龄%.2fs"%(math.dist(T1,b['pos'])*1000,b['age']))
EOF
