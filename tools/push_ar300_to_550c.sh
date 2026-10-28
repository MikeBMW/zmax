#!/usr/bin/env bash
# 🚀 AR 300UPH 增量迁移: 本机 4060 (550A/550B 工程) → Intel 550C (/home/intel/zmax_550c)
#
# 只推**增量**: 画布 / 四类配置 / 元任务 / 工单 / 两个新节点实现 + 注册表
# 不推权重 (Intel 已部署), 不推整仓 3.3G, 不碰 Intel 的 active_product=550C
#
# 用法: bash tools/push_ar300_to_550c.sh [--dry]
set -uo pipefail

SRC=/home/ubuntu/zmax
DST=intel@192.168.23.70:/home/intel/zmax_550c
DRY=""
[ "${1:-}" = "--dry" ] && DRY="--dry-run"

# 清单: 相对 $SRC 的路径 (缺失的会跳过并提示)
LIST=(
  "data/database/zmax/config_meta.json"
  "data/database/zmax/sources/config/ss_task_binding.json"
  "data/database/zmax/sources/config/tasks/tasks.json"
  "data/database/zmax/sources/config/tasks/ar_meta_tasks.json"
  "data/database/zmax/sources/config/platform/zmax_perf_spec.json"
  "data/database/zmax/sources/config/platform/zmax_platform.json"
  "data/database/zmax/sources/canvas/state_space_obs.json"
  "models/active_models.json"
  "flows/scenes_5jobs.json"
  "config/orders/BS_SCN-07-AOI.json"
  "src/lerobot/engineering/nodes/plan_long_impl.py"
  "src/lerobot/engineering/nodes/uph_tact_impl.py"
  "src/lerobot/engineering/nodes/library.py"
  "src/lerobot/middleware/node_names.json"
  "src/lerobot/middleware/nodes/n_longplan.py"
  "src/lerobot/middleware/nodes/n_uph.py"
  "zmax_data/runtime/traj/sim_insert.json"
  "data/database/zmax/zmax_engineering.db"
  "tools/ss_canvas_loop.py"
  "tools/ss_meta_task_ar.py"
  "tools/ar300_config.py"
  "tools/ar300_workorder.py"
)

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
miss=0
for f in "${LIST[@]}"; do
  if [ -e "$SRC/$f" ]; then
    printf '%s\n' "$f" >> "$TMP"
  else
    echo "⚠️ 本机缺: $f"; miss=$((miss+1))
  fi
done
echo "清单: $(wc -l < "$TMP") 个文件 (缺 $miss)"

# 目录不存在则先建 (rsync --files-from 需要目标父目录)
rsync -az --files-from="$TMP" $DRY "$SRC/" "$DST/"
RC=$?
echo "rsync rc=$RC"

if [ -n "$DRY" ]; then echo "(dry-run 结束, 未真正写入)"; exit $RC; fi

echo "════ 550C 侧回读校验"
ssh -o BatchMode=yes intel@192.168.23.70 'cd /home/intel/zmax_550c || exit 1
python3 - <<"PY"
import json, os
def j(p):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception as e: return {"__err__": str(e)}
R = []
cv = j("data/database/zmax/sources/canvas/state_space_obs.json")
R.append(("画布 94 节点 / 214 连线", "%d / %d" % (len(cv.get("nodes") or []), len(cv.get("links") or [])) if "nodes" in cv else str(cv)[:60]))
ids = {n["id"] for n in (cv.get("nodes") or [])}
R.append(("画布含 ssplan/ssuph", "ssplan" in ids and "ssuph" in ids))
tk = j("data/database/zmax/sources/config/tasks/tasks.json")
t7 = [x for x in (tk.get("tasks") or []) if x.get("task_id") == "TASK-07-AOI"]
R.append(("TASK-07-AOI 有 meta_tasks", len((t7[0].get("meta_tasks") or [])) if t7 else 0))
am = j("data/database/zmax/sources/config/tasks/ar_meta_tasks.json")
R.append(("ar_meta_tasks 校验标记", am.get("verified")))
cm = j("data/database/zmax/config_meta.json")
R.append(("功能数 (77)", len(cm.get("functions") or {})))
pf = j("data/database/zmax/sources/config/platform/zmax_perf_spec.json")
e = [g for g in (pf.get("groups") or []) if g.get("gid") == "E"]
R.append(("perf E 组含 perf.UPH_target", any(m.get("id") == "perf.UPH_target" for m in (e[0].get("metrics") or [])) if e else False))
wo = j("config/orders/BS_SCN-07-AOI.json")
R.append(("工单 ar_300uph.uph_target", (wo.get("ar_300uph") or {}).get("uph_target")))
bl = j("src/lerobot/middleware/node_names.json")
R.append(("node_names ssplan/ssuph", (bl.get("ssplan"), bl.get("ssuph"))))
ok = 0
for k, v in R:
    good = v not in (None, False, "", 0, []) and "__err__" not in str(v)
    ok += bool(good)
    print(("  ✅ " if good else "  ❌ ") + "%-28s %s" % (k, v))
print("  档位: " + str(j("config/platform/zmax_product.json").get("active_product")))
print("回归: %d/%d" % (ok, len(R)))
PY'
