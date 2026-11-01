#!/usr/bin/env bash
# 安全停建图: 只杀 gs_map_run / gs_capture(按显式 pid), 不碰 l2_daemon / 安全层 / 相机
set -u
cd /home/ubuntu/zmax

echo "=== 0) 杀前清点 ==="
mapfile -t GP < <(pgrep -f 'tools/gs_map_run\.py' || true)
mapfile -t CP < <(pgrep -f 'tools/gs_capture\.py' || true)
D=$(pgrep -f 'tools/l2_daemon\.py' | head -1 || true)
echo "  gs_map_run  : ${GP[*]:-无}"
echo "  gs_capture  : ${CP[*]:-无}"
echo "  l2_daemon(必须活着): ${D:-无}"

echo
echo "=== 1) 停建图 ==="
for p in "${GP[@]:-}" "${CP[@]:-}"; do
  [ -n "${p:-}" ] || continue
  kill "$p" 2>/dev/null && echo "  已 kill $p" || echo "  kill $p 失败/已退"
done
sleep 2
for p in "${GP[@]:-}" "${CP[@]:-}"; do
  [ -n "${p:-}" ] || continue
  if kill -0 "$p" 2>/dev/null; then kill -9 "$p" 2>/dev/null && echo "  强杀 $p"; fi
done
sleep 1

echo
echo "=== 2) 杀后核验 ==="
pgrep -af 'gs_map_run\.py|gs_capture\.py' | cut -c1-100 | sed 's/^/  残留: /' || true
pgrep -f 'tools/gs_map_run\.py' >/dev/null && echo "  ❌ 还有建图进程" || echo "  ✅ 建图已停"
pgrep -f 'tools/l2_daemon\.py' >/dev/null && echo "  ✅ 执行器还活着" || echo "  ❌ 执行器没了(要拉回!)"

echo
echo "=== 3) 臂/控制器现状 ==="
gui-venv311/bin/python - <<'PY'
import json, os, time, sys
sys.path.insert(0, "/home/ubuntu/zmax/tools/rokae")
import l2_transport_sdk as T
a = T.read_pose()
print("  TCP=(%.4f, %.4f, %.4f) 帧龄%.2fs" % (*a["pos"], a["age"]))
print("  quat=[%s]" % " ".join("%.4f" % v for v in a["quat"]))
time.sleep(5)
b = T.read_pose()
import math
d = math.sqrt(sum((b["pos"][i] - a["pos"][i]) ** 2 for i in range(3))) * 1000
print("  5秒位移 %.1fmm %s" % (d, "(代理里那条动作在收尾, 会自己停)" if d > 0.5 else "(已停)"))
AG = os.path.expanduser("~/zmax/zmax_data/rokae_sdk")
fd = os.open(AG + "/cmd_arm.fifo", os.O_WRONLY | os.O_NONBLOCK)
os.write(fd, b'{"cmd":"state","tag":"post-stop"}\n')
os.close(fd)
time.sleep(1.2)
o = json.load(open(AG + "/tcp_out/agent_result.json", encoding="utf-8")).get("out") or {}
print("  state=%s" % json.dumps(o.get("state"), ensure_ascii=False))
print("  alarms=%s" % json.dumps(o.get("alarms"), ensure_ascii=False))
PY

echo
echo "=== 4) 状态文件改成已停(免得页面以为还在跑) ==="
python3 - <<'PY'
import json, os, time
p = os.path.expanduser("~/zmax/zmax_data/gs_map/status.json")
d = json.load(open(p, encoding="utf-8"))
d["running"] = False
d["step"] = "stopped-by-operator"
d["status_line"] = "⏹ 已停(改成 1000 速 + 修 space1/2 姿态后重启)"
d.setdefault("log", []).append("[%s] ⏹ 手动停止: 准备提速到 1000 并修 space1/2 姿态" % time.strftime("%H:%M:%S"))
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("  status.running=%s step=%s" % (d["running"], d["step"]))
PY
