#!/usr/bin/env bash
# 等 cooldown 后把 v6(对称性指导进化) 换上并重启, 不打断正在跑的这一代
set -u
LOG=/home/intel/evolve/apply_v6.log
T=/home/intel/zmax_map/tools
echo "wait-cooldown start $(date -Is)" >> "$LOG"
for i in $(seq 1 3240); do
  PH=$(curl -s --max-time 3 http://127.0.0.1:8810/health 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("phase",""))' 2>/dev/null)
  case "$PH" in
    cooldown*)
      cp "$T/zmax_evolve_intel.py" "$T/zmax_evolve_intel.py.bak_v5_$(date +%m%d_%H%M)"
      cp "$T/zmax_evolve_intel_v6.py" "$T/zmax_evolve_intel.py"
      systemctl restart zmax-evolve-intel
      sleep 6
      echo "applied $(date -Is) phase=$PH" >> "$LOG"
      curl -s --max-time 3 http://127.0.0.1:8810/health >> "$LOG" 2>/dev/null; echo >> "$LOG"
      exit 0
      ;;
  esac
  if [ $((i % 60)) -eq 0 ]; then echo "waiting $i phase=${PH:-?} $(date -Is)" >> "$LOG"; fi
  sleep 10
done
echo "timeout (4h) waiting cooldown" >> "$LOG"
exit 1
