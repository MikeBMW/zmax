#!/bin/bash
# edge_intel_probe.sh — Intel 端侧 (550C) 只读体检
# 用法(本机无产线网口时):
#   sshpass -p <pw> ssh -o StrictHostKeyChecking=no -J orin intel@192.168.23.70 'bash -s' < edge_intel_probe.sh
# 只读: 不启停单元、不改参数、不动相机; 只打 /health 与 /pipeline/stats。
set -u
BASE=${EDGE_BASE:-http://127.0.0.1:8800}
DELTA=${DELTA:-10}

wrap(){ # wrap '<json>' 'a.b.c'  -> 打一个字段, 缺则 NA
  python3 -c '
import json,sys
node=json.loads(sys.argv[1])
for k in sys.argv[2].split("."):
    node=node.get(k) if isinstance(node,dict) else None
    if node is None: print("NA"); raise SystemExit
print(json.dumps(node,ensure_ascii=False) if isinstance(node,(dict,list)) else node)
' "$1" "$2"
}

delta(){ python3 -c 'import sys
try:
    a,b,t=int(sys.argv[1]),int(sys.argv[2]),float(sys.argv[3]); print("%d (+%.0f/s)"%(b-a,(b-a)/t))
except Exception: print("NA(不可解析或未涨)")' "$1" "$2" "$3"; }

echo "===== HOST ====="
hostname; uname -r; uptime -p; date "+%F %T %Z"
echo "load: $(cut -d' ' -f1-3 /proc/loadavg)"
echo "cpu_threads: $(nproc)"
grep -m1 'model name' /proc/cpuinfo | cut -d: -f2
free -m | awk 'NR==1||NR==2'
df -h / | tail -1
echo "governor: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null)  cur_khz: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null)"
for z in /sys/class/thermal/thermal_zone*/temp; do [ -r "$z" ] || continue; t=$(cat "$z"); echo "temp $(basename "$(dirname "$z")")=$((t/1000))C"; done | sort -u | head -6

echo "===== ACCEL ====="
ls -l /dev/accel* /dev/dri/render* 2>/dev/null
lsmod | grep -E '^(xe|i915|intel_vpu)' | awk '{print $1, $2}'
dmesg 2>/dev/null | grep -iE 'intel_vpu|Firmware: intel/vpu' | tail -3

echo "===== UNITS ====="
for u in zmax-edge.service zmax-edge-pipeline.service; do
  echo "--- $u"
  systemctl show "$u" -p ActiveState,SubState,ExecMainStartTimestamp,NRestarts,MainPID --no-pager 2>/dev/null
  systemctl cat "$u" 2>/dev/null | grep -E 'StandardOutput|ExecStart' | sed 's/^/    /'
done
echo "--- failed"; systemctl --failed --no-legend --no-pager 2>/dev/null | head -5

echo "===== NET & PORTS ====="
echo "ip: $(ip -br addr | awk '{print $1"="$3}' | tr '\n' ' ')"
echo "can_dev: $(ls /sys/class/net | grep -c '^can')"
ss -ltnp 2>/dev/null | awk 'NR==1||/LISTEN/' | head -15

echo "===== /health ====="
H0=$(curl -s -m 4 "$BASE/health")
if [ -z "$H0" ]; then echo "NO RESPONSE from $BASE/health"; else
  echo "$H0" | python3 -m json.tool 2>/dev/null | head -45
fi

echo "===== /pipeline/stats (真在推理的唯一证据) ====="
S0=$(curl -s -m 4 "$BASE/pipeline/stats")
if [ -z "$S0" ]; then echo "NO RESPONSE from $BASE/pipeline/stats (流水线未起?)"; else
  echo "T0: NPU=$(wrap "$S0" devices.NPU.n)  GPU=$(wrap "$S0" devices.GPU.n)  --- sleep ${DELTA}s ---"
  sleep "$DELTA"
  S1=$(curl -s -m 4 "$BASE/pipeline/stats")
  echo "NPU Δ: $(delta "$(wrap "$S0" devices.NPU.n)" "$(wrap "$S1" devices.NPU.n)" "$DELTA")  fps=$(wrap "$S1" devices.NPU.fps)  avg_ms=$(wrap "$S1" devices.NPU.avg_ms)  duty=$(wrap "$S1" devices.NPU.duty_pct)"
  echo "GPU Δ: $(delta "$(wrap "$S0" devices.GPU.n)" "$(wrap "$S1" devices.GPU.n)" "$DELTA")  fps=$(wrap "$S1" devices.GPU.fps)  avg_ms=$(wrap "$S1" devices.GPU.avg_ms)  duty=$(wrap "$S1" devices.GPU.duty_pct)"
  echo "models: NPU=$(wrap "$S1" devices.NPU.models)  GPU=$(wrap "$S1" devices.GPU.models)"
  echo "src: $(wrap "$S1" devices.NPU.src) | $(wrap "$S1" devices.GPU.src)"
  echo "     ^ 固定 jpg 名/zeros = 合成满载自测: fps 只是能力上限, 不是产线吞吐"
  echo "err: $(wrap "$S1" devices.NPU.err) / $(wrap "$S1" devices.GPU.err)"
fi
if [ -n "$H0" ]; then echo "HTTP 业务口: n_req=$(wrap "$H0" n_req)  last_req_age_s=$(wrap "$H0" infer.last_req_age_s)  (大 age = 没业务在调; 内部 pipeline 不走 HTTP)"; fi

echo "===== LOG (journal 常为空: unit 用 StandardOutput=append) ====="
journalctl -u zmax-edge --no-pager -n 5 2>/dev/null | tail -5
LOG=$(systemctl cat zmax-edge.service 2>/dev/null | sed -n 's/.*StandardOutput=append:\(.*\)/\1/p' | head -1)
if [ -n "${LOG:-}" ]; then echo "--- tail $LOG"; tail -n 12 "$LOG" 2>/dev/null; fi

echo "===== PROFILE FILES (端侧通常没有) ====="
ls /home/*/zmax/config/platform/zmax_product.json 2>/dev/null || echo "zmax_product.json: 无 (档位真源只在工程机)"
echo "===== END ====="
