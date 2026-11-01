#!/usr/bin/env bash
# 急停后第一时间: ①停建图(只杀建图进程) ②抓臂/控制器/报警/日志 现场
set -u
cd /home/ubuntu/zmax

echo "=== ① 停建图(防它继续试发) ==="
mapfile -t GP < <(pgrep -f 'tools/gs_map_run\.py' || true)
mapfile -t CP < <(pgrep -f 'tools/gs_capture\.py' || true)
for p in "${GP[@]:-}" "${CP[@]:-}"; do
  [ -n "${p:-}" ] || continue
  kill "$p" 2>/dev/null && echo "  已 kill $p"
  sleep 1
  kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null && echo "  强杀 $p"
done
pgrep -f 'tools/gs_map_run\.py' >/dev/null && echo "  ❌ 仍有建图进程" || echo "  ✅ 建图已停"
pgrep -f 'tools/l2_daemon\.py' >/dev/null && echo "  ✅ 执行器还在(不杀它)" || echo "  ⚠️ 执行器不在"

echo
echo "=== ② 状态文件(跑到哪一步) ==="
python3 -c "
import json,os
try:
    d=json.load(open(os.path.expanduser('~/zmax/zmax_data/gs_map/status.json'),encoding='utf-8'))
    print('  running=%s step=%s session=%s'%(d.get('running'),d.get('step'),(d.get('session') or '')[-24:]))
    print('  status_line=%s'%str(d.get('status_line'))[:140])
    for ln in (d.get('log') or [])[-8:]: print('    %s'%str(ln)[:170])
except Exception as e: print('  读不到:',e)
"

echo
echo "=== ③ 臂位姿 + 控制器/急停状态 + 全部报警 ==="
gui-venv311/bin/python - <<'PY'
import json, os, time, sys
sys.path.insert(0, "/home/ubuntu/zmax/tools/rokae")
import l2_transport_sdk as T
a = T.read_pose()
print("  TCP=(%.4f, %.4f, %.4f)  帧龄%.2fs" % (*a["pos"], a["age"]))
print("  quat=[%s]  rpy_deg=[%s]" % (" ".join("%.4f" % v for v in a["quat"]), " ".join("%.2f" % v for v in a["rpy"])))
AG = os.path.expanduser("~/zmax/zmax_data/rokae_sdk")
fd = os.open(AG + "/cmd_arm.fifo", os.O_WRONLY | os.O_NONBLOCK)
os.write(fd, b'{"cmd":"state","tag":"post-estop"}\n')
os.close(fd)
time.sleep(1.5)
d = json.load(open(AG + "/tcp_out/agent_result.json", encoding="utf-8"))
o = d.get("out") or {}
print("  state  = %s" % json.dumps(o.get("state"), ensure_ascii=False))
print("  alarms = %s" % json.dumps(o.get("alarms"), ensure_ascii=False))
print("  pose   = %s" % json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in (o.get("pose") or {}).items() if k != "joints"}, ensure_ascii=False)[:260])
print("  joints = %s" % json.dumps([round(v, 4) for v in ((o.get("pose") or {}).get("joints") or [])], ensure_ascii=False))
time.sleep(4)
b = T.read_pose()
import math
dd = math.sqrt(sum((b["pos"][i] - a["pos"][i]) ** 2 for i in range(3))) * 1000
print("  4 秒位移 %.1fmm %s" % (dd, "(静止)" if dd < 0.5 else "(⚠️ 还在动!)"))
PY

echo
echo "=== ④ 执行器日志尾部(最后一次下发/失败原因) ==="
tail -16 ~/zmax/zmax_data/l2_daemon_stdout.log | cut -c1-215 | sed 's/^/  /'

echo
echo "=== ⑤ 建图 run.log 尾部 ==="
tail -10 ~/zmax/zmax_data/gs_map/run.log 2>/dev/null | cut -c1-190 | sed 's/^/  /'
echo "  现在: $(date '+%F %T')"
