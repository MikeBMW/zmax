#!/usr/bin/env bash
# Intel 550C 无人值守看护: 服务死/训练卡/对称进化停/磁盘低 ⇒ 自己拉起来, 不请示
LOG=/home/intel/evolve/watchdog.log
say(){ echo "$(date -Is) $*" >> "$LOG"; }
cmd(){ systemctl "$@" >/dev/null 2>&1; }

# ① YOLO 进化
systemctl is-active --quiet zmax-evolve-intel || { say "evolve 不在 -> restart"; cmd restart zmax-evolve-intel; }
H=$(curl -s --max-time 5 http://127.0.0.1:8810/health)
if [ -z "$H" ]; then
  say "health 空 -> restart evolve"; cmd restart zmax-evolve-intel
else
  PH=$(printf '%s' "$H" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("phase",""))' 2>/dev/null)
  AGE=$(( $(date +%s) - $(stat -c %Y /home/intel/evolve/evolve.log 2>/dev/null || echo 0) ))
  case "$PH" in
    training*) ;;
    *) [ "$AGE" -gt 900 ] && { say "log 陈旧 ${AGE}s phase=$PH -> restart"; cmd restart zmax-evolve-intel; } ;;
  esac
fi

# ② 对称性引擎进化
systemctl is-active --quiet zmax-symmetry-evolve || { say "sym-evolve 不在 -> restart"; cmd restart zmax-symmetry-evolve; }
SL=/home/intel/evolve/symmetry_ledger.jsonl
if [ -f "$SL" ]; then
  A2=$(( $(date +%s) - $(stat -c %Y "$SL") ))
  [ "$A2" -gt 1800 ] && { say "sym ledger 陈旧 ${A2}s -> restart"; cmd restart zmax-symmetry-evolve; }
else
  say "sym ledger 缺失 -> restart"; cmd restart zmax-symmetry-evolve
fi

# ③ 磁盘红线 (训练产物全在 /home)
AVAIL=$(df -BG --output=avail /home | tail -1 | tr -dc '0-9')
[ -n "$AVAIL" ] && [ "$AVAIL" -lt 15 ] && say "磁盘余量 ${AVAIL}G < 15G (红线)"

# ④ 日志体量 (超 400MB 就保留尾部 80MB, 防写满盘)
SZ=$(stat -c %s /home/intel/evolve/evolve.log 2>/dev/null || echo 0)
if [ "$SZ" -gt 400000000 ]; then
  say "evolve.log ${SZ}B -> 截尾"
  tail -c 80000000 /home/intel/evolve/evolve.log > /tmp/evlog.tail 2>/dev/null && cat /tmp/evlog.tail > /home/intel/evolve/evolve.log
  rm -f /tmp/evlog.tail
fi
say "ok phase=${PH:-?} disk=${AVAIL:-?}G"
