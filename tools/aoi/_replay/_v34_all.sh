#!/bin/bash
# Run one module over all reference sequences, each in its own process.
# usage: _v34_all.sh <mod.py> <outdir>
PY=/home/ubuntu/.hermes/cache/scratch/aoi310/bin/python
REPLAY=/home/ubuntu/zmax/tools/aoi/_replay
S=/home/ubuntu/.hermes/cache/scratch
MOD=$1
OUT=$2
mkdir -p "$OUT"
run() {  # name  glob
  echo "############################## $1"
  $PY "$REPLAY/_v34_run.py" "$MOD" "$2" 2>&1 | grep -vE "^$"
}
{
run l3        "$S/aoi_l3_frames"
run pt2       "$S/pt2_frames/*.png"
run frozen    "$S/aoi_frozen"
run frozen2   "$S/aoi_frozen2"
run frozen3   "$S/aoi_frozen3"
run frozen4   "$S/aoi_frozen4"
run liveF     "$S/liveF[0-9].png"
run live18    "$S/aoi_live_frames"
} > "$OUT/_all.txt" 2>&1
echo "wrote $OUT/_all.txt"
grep -E "^(MOD|NSEQ)" "$OUT/_all.txt"
