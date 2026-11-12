#!/bin/bash
# offline_evolve.sh — 断网/离场的自主进化执行器 (2026-11-12)
#
# 用法:
#   bash tools/offline_evolve.sh --rounds 1 --n 24 --clutter 6 --epochs 1        # 冒烟
#   bash tools/offline_evolve.sh --rounds 4 --n 400 --clutter 6 --epochs 30      # 正式跑
#
# 它做四件事:
#   1) 建/复用沙箱根 (默认 /tmp/evo_offline): 软链 src/tools/models/gui-venv311, 独立的 zmax_data
#      —— 离线自进化绝不写现场台账 (zmax_data/ar_evolve/ledger.json)
#   2) 在 `unshare -n` 里跑 (只有 lo 且 DOWN): 现场没了、外网没了、连本机 127.0.0.1 都没有
#   3) 留出集缺失就先本地造 (mujoco, 无网)
#   4) 设备默认 CPU (不跟现场在跑的训练抢 8G 显存); 有卡时 ZMAX_TRAIN_DEVICE=0
#
# 判据不变: 主判据 hard 留出集 mAP50-95, mAP50 只做不回退护栏。
set -u
R=${ZMAX_OFFLINE_ROOT:-/tmp/evo_offline}
SRC=${ZMAX_SRC:-/home/ubuntu/zmax}
PY=$SRC/gui-venv311/bin/python
DEV=${ZMAX_TRAIN_DEVICE:-cpu}
ARGS="$@"

# 1) 沙箱
mkdir -p "$R/zmax_data/ar_evolve" "$R/zmax_data/ar_mujoco"
for d in src tools models external config; do [ -e "$R/$d" ] || ln -s "$SRC/$d" "$R/$d"; done
[ -e "$R/gui-venv311" ] || ln -s "$SRC/gui-venv311" "$R/gui-venv311"

# 现场快照里的真机帧也带进沙箱 (只读引用, 不进判据)
SNAP=$(ls -dt "$SRC"/zmax_data/site_snapshot/*/ 2>/dev/null | head -1)
[ -n "$SNAP" ] && ln -sfn "$SNAP" "$R/zmax_data/site_snapshot"

INNER=$(mktemp /tmp/offline_evolve_XXXX.sh)
cat > "$INNER" <<EOS
set -e
export ZMAX_ROOT=$R HOME=/home/ubuntu PYTHONUNBUFFERED=1 ZMAX_TRAIN_DEVICE=$DEV
export OFFLINE_SNAPSHOT=${SNAP:-none}
cd $SRC
ip -br addr | grep -qE '^eth|^enp|^wlan' && { echo "❌ 还有网卡, 不算离线"; exit 8; }
curl -s -m2 http://1.1.1.1 >/dev/null 2>&1 && { echo "❌ 还有外网, 不算离线"; exit 8; }
echo "✔ 离线自证: 无外网 / 无本机回环 (只有 lo DOWN)"
# 留出集: 缺哪个造哪个
for spec in "holdout_hard 24 16 31337" "holdout_clutter 24 6 9001"; do
  set -- \$spec; d=\$1; n=\$2; c=\$3; s=\$4
  [ -f $R/zmax_data/ar_evolve/\$d/data.yaml ] || \\
    $PY tools/ar_mujoco_clutter.py --gen --n \$n --clutter \$c --seed \$s --out $R/zmax_data/ar_evolve/\$d | tail -1
done
[ -f $R/zmax_data/ar_mujoco/holdout/data.yaml ] || \\
  $PY tools/ar_mujoco_clutter.py --gen --n 16 --clutter 0 --seed 1 --out $R/zmax_data/ar_mujoco/holdout | tail -1
echo "留出集就绪: hard/\$(ls $R/zmax_data/ar_evolve/holdout_hard/images | wc -l) 张 · hc/\$(ls $R/zmax_data/ar_evolve/holdout_clutter/images | wc -l) 张"
echo "--- 进化开始 (\$ARGS) ---"
$PY tools/evolve_ar_world.py \$ARGS 2>&1 | grep -avE '^(\\s+)?[0-9]+/[0-9]+' | tail -30
EOS
chmod +x "$INNER"

sudo unshare -n bash "$INNER"
rc=$?
rm -f "$INNER"
echo "--- 台账 ---"
$PY - <<'PYEOF'
import json, glob, os
p = os.environ.get("ZMAX_OFFLINE_ROOT", "/tmp/evo_offline") + "/zmax_data/ar_evolve/ledger.json"
if not os.path.isfile(p):
    print("无台账 (第一轮还没落)"); raise SystemExit
d = json.load(open(p))
g = d.get("generations", [])
print("代数=%d 采纳=%d best=%s" % (len(g), sum(1 for x in g if x.get("accepted")), d.get("best")))
if g:
    x = g[-1]
    ev = (x.get("stages", {}).get("train_eval", {}) or {})
    print("末代 gen=%s accepted=%s reason=%s" % (x.get("gen"), x.get("accepted"), str(x.get("reason"))[:90]))
PYEOF
exit $rc
