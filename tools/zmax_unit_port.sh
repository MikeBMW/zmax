#!/usr/bin/env bash
# zmax_unit_port.sh —— 把 550C 侧同步过来的 systemd unit 适配到本机
#
# 背景：550C 的 unit 里写死了 /home/intel/*、User=intel。
#   直接拷到本机（无 intel 用户）会导致 status=217/USER，
#   服务静默起不来（2026-11-27 踩过：8797 轨迹台、zmax-agent-hub 等 66 个）。
#
# 用法:
#   zmax_unit_port.sh check    只报告，不改（默认）
#   zmax_unit_port.sh apply    备份 + 改写 + daemon-reload
#
# 安全: apply 前把原文件备份到 /root/zmax_unit_bak_<ts>/；只改 unit，不动 drop-in。
set -uo pipefail
MODE=${1:-check}
TS=$(date +%Y%m%d_%H%M%S)
BAK=/root/zmax_unit_bak_$TS
SRC=/etc/systemd/system
TMP=$(mktemp -d)

# 路径映射：550C(Intel) -> 本机(Ubuntu)
map_file() {
  python3 - "$1" "$2" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
MAP = [
    ("/home/intel/zmax_550c", "/home/ubuntu/zmax"),
    ("/home/intel/zmax_map", "/home/ubuntu/zmax"),
    ("/home/intel/gsxpu-venv", "/home/ubuntu/zmax/gui-venv311"),
    ("/home/intel/train_venv", "/home/ubuntu/zmax/venvs/lerobot-venv"),
    ("/home/intel/aoi_evo/.venv", "/home/ubuntu/zmax/gui-venv311"),
    ("/home/intel/openvino_2026.1_env", "/home/ubuntu/zmax/gui-venv311"),
    ("/home/intel/zmax_550a", "/home/ubuntu/zmax"),
    ("/home/intel", "/home/ubuntu"),
]
t = open(src, encoding="utf-8", errors="replace").read()
for a, b in MAP:
    t = t.replace(a, b)
t = t.replace("User=intel", "User=ubuntu").replace("Group=intel", "Group=ubuntu")
open(dst, "w").write(t)
PY
}

changed=0; missing=0
for f in $SRC/zmax*.service; do
  [ -e "$f" ] || continue
  grep -q '/home/intel\|User=intel' "$f" 2>/dev/null || continue
  b=$(basename "$f")
  map_file "$f" "$TMP/$b"
  exe=$(grep -m1 '^ExecStart=' "$TMP/$b" | sed 's/^ExecStart=-\{0,1\}//' | awk '{print $1}')
  if [ -n "$exe" ] && [ ! -e "$exe" ] && ! command -v "$exe" >/dev/null 2>&1; then
    printf '  MISS  %-34s %s\n' "$b" "$exe"; missing=$((missing+1))
  else
    printf '  OK    %-34s %s\n' "$b" "$exe"
  fi
  changed=$((changed+1))
done

echo "[unit-port] 需要适配: $changed 个 (ExecStart 缺失 $missing 个)"

if [ "$MODE" = "apply" ] && [ "$changed" -gt 0 ]; then
  sudo mkdir -p "$BAK"
  for f in $SRC/zmax*.service; do
    grep -q '/home/intel\|User=intel' "$f" 2>/dev/null || continue
    sudo cp -a "$f" "$BAK/"
  done
  sudo cp "$TMP"/zmax*.service "$SRC/"
  sudo systemctl daemon-reload
  echo "[unit-port] 已改写 $changed 个, 备份在 $BAK, daemon-reload 完成"
  echo "[unit-port] 注意: 运行中的进程不会自动换, 需要重启对应服务才生效"
fi
rm -rf "$TMP"
