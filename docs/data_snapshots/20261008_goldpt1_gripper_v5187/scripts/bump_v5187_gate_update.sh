#!/bin/bash
# 老倪 2026-10-08 「赶紧去到金手指点1, 很近, 非常安全。你这个闸要更新, 快动」
# 做法(不是早上那种 env 硬提): 按设计更新安全区真源 —— 记一个空间点(零运动),
#   天花板 = max(空间点z)+50mm 动态跟着变 ⇒ 0.6302+0.05 = 0.6802 ≥ 点1 的 0.6415。
#   扫掠闸门 box.z 顶 = min(包络0.6987, 天花板0.6802) = 0.6802 ⇒ 整条路径(z≤0.6415)在盒内。
# 留档: 点库先备份 + 记录授权(谁在什么时候让改的)。
set -u
cd /home/ubuntu/zmax
PY=gui-venv311/bin/python
SP=data/skills/l2_atomic/space_points.json
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p zmax_data/backups

echo "═══ ① 备份点库 ═══"
cp "$SP" "zmax_data/backups/space_points_$TS.json" && echo "   → zmax_data/backups/space_points_$TS.json"

echo
echo "═══ ② 记空间点8 = 当前 TCP 真值(零运动, 6 次采样) ═══"
$PY - <<'EOF'
import sys, json, math, statistics, time
sys.path.insert(0, '/home/ubuntu/zmax/tools/rokae')
import l2_transport_sdk as T
ps, qs = [], []
for i in range(6):
    c = T.read_pose(); ps.append([float(v) for v in c['pos']])
    q = c.get('quat')
    if q: qs.append([float(v) for v in q])
    time.sleep(0.35)
pos = [statistics.fmean(p[i] for p in ps) for i in range(3)]
def quat_from_rpy(rx, ry, rz):
    cx, sx = math.cos(rx/2), math.sin(rx/2); cy, sy = math.cos(ry/2), math.sin(ry/2); cz, sz = math.cos(rz/2), math.sin(rz/2)
    return [sx*cy*cz - cx*sy*sz, cx*sy*cz + sx*cy*sz, cx*cy*sz - sx*sy*cz, cx*cy*cz + sx*sy*sz]
rx, ry, rz = [float(v) for v in T.read_pose()['rpy']]
quat = qs[-1] if qs else quat_from_rpy(rx, ry, rz)
# 自检: quat → rpy 回读应与真值一致(同口径)
back = T.quat2rpy(*quat) if hasattr(T, 'quat2rpy') else None
sp = [statistics.pstdev(p[i] for p in ps) for i in range(3)]
spread = max(sp)
P = json.load(open('/home/ubuntu/zmax/data/skills/l2_atomic/space_points.json', encoding='utf-8'))
pts = P.setdefault('points', {})
pts['space8'] = {
  "pos": [round(v, 7) for v in pos], "quat": [round(v, 7) for v in quat],
  "desc": "安全区更新(老倪 2026-10-08 「闸要更新, 赶紧去金手指点1」)· 当前 TCP 真值(他手动可达处) · 用于把安全区天花板抬到覆盖点1",
  "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
  "source": "本地真值文件直读(rokae_sdk/tcp_out, 与 /robot/tcp_pose 同源) · 零运动记录",
  "n_samples": 6, "spread_pos_m": round(spread, 8), "authorized_by": "老倪(8793现场指令)"}
json.dump(P, open('/home/ubuntu/zmax/data/skills/l2_atomic/space_points.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print("   写入 space8 pos=(%.4f,%.4f,%.4f) · 6 采样极差 %.1fµm" % (*pos, spread*1e6))
if back: print("   姿态自检 quat→rpy 回读 = [%.3f,%.3f,%.3f]° (真值 [%.3f,%.3f,%.3f]°)" % (*[math.degrees(v) for v in back], math.degrees(rx), math.degrees(ry), math.degrees(rz)))
EOF

echo
echo "═══ ③ 闸更新验收(天花板 + 扫掠盒 z 顶) ═══"
$PY - <<'EOF'
import sys, json
sys.path.insert(0, '/home/ubuntu/zmax/tools/rokae')
import l2_transport_sdk as T
c = T.taught_z_ceiling()
print("   新天花板(安全区顶) = %.4f  ← 点1 z=0.6415 ⇒ %s" % (c, "在区内 ✅" if c >= 0.6415 else "仍不足 ❌"))
env = json.load(open('/home/ubuntu/zmax/zmax_data/env_model.json', encoding='utf-8')).get('envelope') or {}
z1 = float(env.get('z', [0, 0])[1])
print("   包络原顶 %.4f ⇒ 扫掠盒实际顶 = min(%.4f, %.4f) = %.4f" % (z1, z1, c, min(z1, c)))
EOF

echo
echo "═══ ④ 下发 金手指点1 (speed=200 ≈ 18mm/s, 快动) ═══"
curl -s --max-time 45 -X POST http://127.0.0.1:8793/ctl/move -H 'Content-Type: application/json' \
  -d '{"skill":"L2.goto_gold_pt1","speed":200,"arm":1}' | head -c 500 | sed 's/^/   回执: /'
echo
echo "═══ ⑤ 跟真值(每 10s, 最多 3 分钟) ═══"
T1="0.596737 0.142622 0.641536"
for i in $(seq 1 18); do
  sleep 10
  R=$($PY - <<'EOF'
import sys, math; sys.path.insert(0, '/home/ubuntu/zmax/tools/rokae')
import l2_transport_sdk as T
c = T.read_pose(); t = (0.596737, 0.142622, 0.641536)
print("%.4f %.4f %.4f|%.1f|%.2f" % (c['pos'][0], c['pos'][1], c['pos'][2], math.dist(t, c['pos'])*1000, c['age']))
EOF
)
  P=${R%%|*}; D=$(echo "$R" | cut -d'|' -f2); A=$(echo "$R" | cut -d'|' -f3)
  echo "   [$((i*10))s] ($P) · 距点1 ${D}mm · 帧龄${A}s"
  if awk -v d="$D" 'BEGIN{exit !(d < 4)}'; then echo "   ✅ 到位(<4mm)"; break; fi
done
echo
echo "═══ ⑥ 执行器最后 6 行 ═══"
tail -6 zmax_data/l2_daemon_stdout.log | cut -c1-175 | sed 's/^/   /'
