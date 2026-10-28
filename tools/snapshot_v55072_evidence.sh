#!/usr/bin/env bash
# 采集本轮 (v5.50.71→v5.50.72) 现场数据 → docs/data_snapshots/20261015_visual_evidence_caliber/
# 只读取证: 帧/阈值表/大屏 fullflow 段/飞书消息 id/链路状态。不写业务文件。
set -u
cd /home/ubuntu/zmax
DST=docs/data_snapshots/20261015_visual_evidence_caliber
mkdir -p "$DST"

# ① 链路状态 (产线是否可达)
{
  echo "# 链路状态 $(date '+%F %T')"
  echo "## 网卡"; ip -br addr show 2>/dev/null | grep -E 'enx|192\.168\.23' || echo "(无 192.168.23.x 地址)"
  echo "## ping AOI 192.168.23.23"; ping -c 2 -W 2 192.168.23.23 2>&1 | tail -2
  echo "## ping Orin 192.168.23.66"; ping -c 2 -W 2 192.168.23.66 2>&1 | tail -2
  echo "## AOI TCP 10082/10083"
  for p in 10082 10083; do printf '  %s ' "$p"; timeout 5 bash -c "</dev/tcp/192.168.23.23/$p" 2>&1 && echo 通 || echo 不通; done
} > "$DST/link_status.txt" 2>&1

# ② 本机帧可用性 + 在役 YOLO 阈值响应表
gui-venv311/bin/python tools/probe_frames_local.py > "$DST/frames_local.txt" 2>&1
gui-venv311/bin/python tools/yolo_threshold_response.py --img http://127.0.0.1:8791/snapshot/local2.jpg \
  > "$DST/yolo_threshold_local2.txt" 2>&1
gui-venv311/bin/python tools/yolo_threshold_response.py --dir zmax_data/eval_frames/live_1014_230655 --limit 4 \
  > "$DST/yolo_threshold_evalframes.txt" 2>&1

# ③ 大屏 fullflow 段 (7 任务闭环结果唯一依据)
gui-venv311/bin/python - <<'PY' > "$DST/dashboard_fullflow.json" 2>&1
import json
d = json.load(open('zmax_data/datapush/dashboard.json'))
print(json.dumps({"schema": d.get("schema"), "generated_at": d.get("generated_at"),
                  "version": d.get("version"), "fullflow": d.get("fullflow")}, ensure_ascii=False, indent=1))
PY

# ④ 元任务预测 topic 唯一依据 (信号分析可见性)
gui-venv311/bin/python - <<'PY' > "$DST/signal_analysis_meta_pred.json" 2>&1
import json, time
live = json.load(open('zmax_data/dataspace/live.json'))
tp = live.get('topics') or {}
v = tp.get('ss_meta_pred') or {}
print(json.dumps({"live_mtime": time.strftime('%F %T', time.localtime(__import__('os').path.getmtime('zmax_data/dataspace/live.json'))),
                  "mode": live.get("mode"), "n_topics": len(tp), "ss_meta_pred": v}, ensure_ascii=False, indent=1))
PY

ls -la "$DST" | tail -8
