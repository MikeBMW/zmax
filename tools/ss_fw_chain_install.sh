#!/usr/bin/env bash
# 装/重装「插拔场景空间智能链」两个系统单元 (真源 = 仓库 tools/systemd/)
#   ① zmax-fw-render.service      渲染帧服务 8799
#   ② zmax-ss-engine-loop.service 引擎回路 (VLM 编码 + 多层管线)
# 注意: 必须先把散跑的裸进程停掉 (systemd Restart=always 会抢着重启成旧档)
set -eu
R=/home/ubuntu/zmax
sudo cp -f "$R/tools/systemd/zmax-fw-render.service" /etc/systemd/system/
sudo cp -f "$R/tools/systemd/zmax-ss-engine-loop.service" /etc/systemd/system/
sudo cp -f "$R/tools/systemd/zmax-ss-trace-pub.service" /etc/systemd/system/
sudo systemctl daemon-reload
# 停散跑的 (用 [x] 断自身匹配)
for pat in '[f]w_render_server\.py --port 8799' '[s]s_engine_loop\.py run' '[s]s_fw_trace_pub\.py'; do
  pids=$(pgrep -f "$pat" 2>/dev/null | tr '\n' ' ') || true
  [ -n "${pids:-}" ] && { echo "停散跑: $pids"; sudo kill $pids 2>/dev/null || true; sleep 2; }
done
sudo systemctl enable zmax-fw-render.service zmax-ss-engine-loop.service zmax-ss-trace-pub.service >/dev/null 2>&1 || true
sudo systemctl restart zmax-fw-render.service
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8799/frame.png || echo 000)
  [ "$code" = "200" ] && { echo "✅ 渲染帧服务就绪 (${i}×0.5s)"; break; }
  sleep 0.5
done
sudo systemctl restart zmax-ss-engine-loop.service
sudo systemctl restart zmax-ss-trace-pub.service
sleep 8
echo "--- 单元状态 ---"
systemctl is-active zmax-fw-render.service zmax-ss-engine-loop.service zmax-ss-trace-pub.service
echo "--- 引擎真值 ---"
"$R/gui-venv311/bin/python" - <<'PYEOF'
import json, os, time
p = "/home/ubuntu/zmax/zmax_data/ss_live/engine_latest.json"
e = json.load(open(p, encoding="utf-8"))
print("帧龄 %.1fs · cycle %s · task %s · 编码器 %s · 管线 %s(calls %s)"
      % (time.time() - os.path.getmtime(p), e.get("cycle"), e.get("task_id"),
         e.get("encoder"), e.get("pipe_on"), e.get("pipe_calls")))
print("z_source: %s" % e.get("z_source"))
PYEOF
