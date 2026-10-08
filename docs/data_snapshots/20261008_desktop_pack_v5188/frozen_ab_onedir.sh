#!/usr/bin/env bash
# 冻结 A/B 取证 (本地, onedir 最小探针 —— 与 CI onefile 同口径的"冻结语义":
#   sys.frozen=True / sys._MEIPASS=<包内> / --add-data 落在 _MEIPASS/src/...)。
#   A) 带 src/lerobot/engineering → 探针 rc=0 (工程包可达, 151 条节点逻辑 + 画布真源在位)
#   B) 不带 (= 老倪手上那个坏包)  → rc=1 且错误与现场同源 "No module named 'lerobot'"
# 说明: 本机 gui-venv311 带 torch/ultralytics, onefile 会超 4GB 上限 → 用 onedir 验证导入机制;
#       真 exe/app 的端到端由 CI 的冻结核验 (--engine-selftest 已扩到 GUI 导入链) 判。
set -u
REPO=/home/ubuntu/zmax
PY=("$REPO/gui-venv311/bin/python" -m PyInstaller)
PROBE=/home/ubuntu/.hermes/cache/scratch/probe_frozen_node_logic.py
OUT=/home/ubuntu/.hermes/cache/scratch/frozen_ab
rm -rf "$OUT"; mkdir -p "$OUT"

build() {   # $1=名字  $2=1 带工程包
  local name="$1" withpkg="$2" extra=()
  [ "$withpkg" = "1" ] && extra=(--add-data "$REPO/src/lerobot/engineering:src/lerobot/engineering")
  echo "--- 构建 $name (engineering=$withpkg) ---"
  "${PY[@]}" --noconfirm --paths "$REPO/tools/gui" "${extra[@]}" \
    --distpath "$OUT/dist_$name" --workpath "$OUT/build_$name" --specpath "$OUT/build_$name" \
    --name "$name" "$PROBE" > "$OUT/${name}_build.log" 2>&1
  echo "    pyinstaller rc=$?"
}

run() {     # $1=名字
  local name="$1"
  local exe="$OUT/dist_$name/$name/$name"
  echo "    运行 $exe"
  "$exe" > "$OUT/${name}_selftest.json" 2>&1
  local rc=$?
  echo "    探针 rc=$rc"
  sed 's/^/      /' "$OUT/${name}_selftest.json"
  return $rc
}

build ZMAX_Probe_Eng 1
run   ZMAX_Probe_Eng;  R1=$?
echo
build ZMAX_Probe_NoEng 0
run   ZMAX_Probe_NoEng; R2=$?
echo
echo "================ 结论 ================"
echo "A(带工程包) rc=$R1   B(不带) rc=$R2"
if [ "$R1" = "0" ] && [ "$R2" != "0" ]; then
  echo "✅ A/B 成立: 带包→通过; 不带包→复现老倪现象 (根因确认 + 核验有牙)"
else
  echo "❌ A/B 不成立 — 需复查"
fi
