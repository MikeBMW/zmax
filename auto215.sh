#!/usr/bin/env bash
# 自动把 215 点走完: 每一批等 running=false 再发下一批, 直到 cursor>=215
# 用途: 老倪「继续到215个点」。逐点串行, 不并发, 每批 40 点。
set -u
API=http://127.0.0.1:8797/api/arm/step_traj
SPEED=${SPEED:-20}
BATCH=${BATCH:-40}
TOTAL=215
LOG=/home/intel/zmax_550c/zmax_data/rokae_sdk/auto215.log

st() { curl -s --max-time 8 "$API/status" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get('running'),d.get('cursor') or 0,d.get('done') or 0,(d.get('ok_all') if d.get('ok_all') is not None else ''),(d.get('why') or ''))
except Exception:
    print('ERR 0 0  ')
"; }

echo "$(date '+%F %T') auto215 start speed=$SPEED batch=$BATCH" >> $LOG

while :; do
  R=$(st); RUN=$(echo $R | cut -d' ' -f1); CUR=$(echo $R | cut -d' ' -f2)
  [ "$RUN" = "ERR" ] && { echo "$(date '+%F %T') status 读失败, 等 10s" >> $LOG; sleep 10; continue; }

  if [ "$RUN" = "True" ]; then
    sleep 6
    continue
  fi

  # running=false: 看游标
  if [ "$CUR" -ge "$TOTAL" ]; then
    echo "$(date '+%F %T') DONE cursor=$CUR/215  $R" >> $LOG
    break
  fi

  N=$BATCH
  REST=$((TOTAL - CUR))
  [ "$REST" -lt "$N" ] && N=$REST
  RESP=$(curl -s --max-time 15 -X POST "$API" -H "Content-Type: application/json" \
         -d "{\"n\":$N,\"start\":$CUR,\"speed\":$SPEED,\"dry\":false}")
  echo "$(date '+%F %T') send start=$CUR n=$N -> $(echo $RESP | head -c 160)" >> $LOG
  echo "$RESP" | grep -q '"started": true' || { echo "$(date '+%F %T') 派单被拒, 等 15s 重试" >> $LOG; sleep 15; }
  sleep 8
done

echo "$(date '+%F %T') auto215 end" >> $LOG
