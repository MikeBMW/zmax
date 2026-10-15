#!/usr/bin/env bash
# install_ubuntu.sh — Z-MAX Console · Ubuntu / Linux 安装程序 (v5.50.735, 2026-10-15)
#
# 用法:
#   bash install_ubuntu.sh --check          # 只体检 (不装任何东西) —— 交付前/上机前先跑这个
#   bash install_ubuntu.sh                  # 安装到 ~/.local/share/zmax (venv + 桌面图标 + zmax-console 命令)
#   bash install_ubuntu.sh --prefix /opt/zmax
#   bash install_ubuntu.sh --uninstall
#
# 口径:
#   · 装的是**源码运行版** (Ubuntu 上本工程一直这么跑: python venv + PyQt5 + tools/gui/studio.py)。
#     没有 GPU 也能跑 (纯 CPU 仿真); 有 NVIDIA 卡时自动用系统驱动。
#   · 出厂骨架随包: defaults/canvas (画布) + defaults/config/platform/zmax_product.json (产品三档 550A/550B/550C)
#     ⇒ 全新安装就能选产品档, 不需要实例数据包。
#   · 真机/实例数据 (data/) 不进包: 装机后用工程数据包 + tools/instance_init.py 接。
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"          # 包内 app 根
PREFIX="${HOME}/.local/share/zmax"
PY="${PYTHON:-python3}"
DO_CHECK=0; DO_UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --check) DO_CHECK=1 ;;
    --uninstall) DO_UNINSTALL=1 ;;
    --prefix) PREFIX="$2"; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
  shift
done

_ok=0; _bad=0
say()  { printf '   %s\n' "$*"; }
pass() { _ok=$((_ok+1));  printf '   ✅ %s\n' "$*"; }
fail() { _bad=$((_bad+1)); printf '   ❌ %s\n' "$*"; }

echo "═══ Z-MAX Console · Ubuntu 安装体检 ═══"
say "包目录: ${SRC}"
say "安装前缀: ${PREFIX}"

echo "[1/6] 运行环境"
_pyv="$($PY -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo none)"
if [ "$_pyv" = none ]; then fail "找不到 $PY (先 apt install python3 python3-venv python3-pip)"; else
  case "$_pyv" in
    3.1[0-9]|3.[2-9][0-9]) pass "python ${_pyv}";;
    *) fail "python ${_pyv} 太旧 (要 ≥3.10)";;
  esac
fi
if $PY -c 'import venv' 2>/dev/null; then pass "venv 模块在"; else fail "缺 python3-venv"; fi
if command -v pip3 >/dev/null 2>&1 || $PY -m pip --version >/dev/null 2>&1; then pass "pip 在"; else fail "缺 pip"; fi

echo "[2/6] 图形环境 (PyQt5 需要)"
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then pass "有显示服务 (DISPLAY/WAYLAND_DISPLAY)"; else
  say "⚠️ 无 DISPLAY: 只在纯命令行用 (远程旁路/无界面模式); 要开图形界面请在有桌面的会话里跑"
fi
_miss=""
for _lib in libGL.so.1 libxkbcommon.so.0 libEGL.so.1; do
  ldconfig -p 2>/dev/null | grep -q "$_lib" || _miss="$_miss $_lib"
done
if [ -z "$_miss" ]; then pass "系统图形库齐 (libGL/libEGL/libxkbcommon)"; else
  fail "缺系统库:${_miss} ⇒ sudo apt install -y libgl1 libegl1 libxkbcommon0 libxcb-xinerama0 libxcb-cursor0"
fi

echo "[3/6] 包里该有的东西"
for _f in tools/gui/studio.py defaults/config/platform/zmax_product.json defaults/canvas/state_space_obs.json \
          requirements-linux.txt dds/zmax_node.py src/lerobot/policies/left_right/state_space/physics_constraints.py; do
  if [ -e "${SRC}/${_f}" ]; then pass "${_f}"; else fail "缺 ${_f} (包不完整)"; fi
done
if [ -f "${SRC}/defaults/config/platform/zmax_product.json" ]; then
  _prods="$($PY - <<'PY' 2>/dev/null || echo ""
import json;d=json.load(open("defaults/config/platform/zmax_product.json"));print(",".join(d.get("products",{})))
PY
)"
  case "$_prods" in *550A*550B*550C*) pass "产品三档在: ${_prods}";; *) fail "产品档不全: ${_prods}";; esac
fi

echo "[4/6] 磁盘与内存"
_avail_kb=$(df -Pk "$(dirname "$PREFIX")" 2>/dev/null | awk 'NR==2{print $4}')
if [ -n "${_avail_kb:-}" ] && [ "$_avail_kb" -gt 3145728 ]; then pass "可用磁盘 $((_avail_kb/1024/1024)) GB (>3GB)"; else
  fail "磁盘不足 (venv+deps 约需 3GB): ${_avail_kb:-?} KB"
fi
_mem_mb=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
if [ "${_mem_mb:-0}" -ge 3800 ]; then pass "内存 ${_mem_mb} MB"; else
  say "⚠️ 内存 ${_mem_mb} MB 偏小 (建议 ≥4GB); 仿真+GUI 同时开会吃紧"
fi

echo "[5/6] 可选加速"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  pass "NVIDIA 卡: $(nvidia-smi -L | head -1)"
else
  say "⚠️ 无 NVIDIA 卡/驱动 ⇒ 走 CPU (仿真与检测仍可跑, 训练类功能不可用)"
fi
if command -v docker >/dev/null 2>&1; then pass "docker 在 (可选: 容器化部署)"; else say "○ docker 不在 (非必需)"; fi

echo "[6/6] 结论"
if [ "$_bad" -gt 0 ]; then
  printf '\n⛔ 体检未过: %d 项要处理 (上面标 ❌ 的), 处理完重跑 --check\n' "$_bad"
  exit 1
fi
printf '\n✅ 体检通过 (%d 项)\n' "$_ok"

if [ "$DO_CHECK" = "1" ]; then
  echo "(--check 模式: 未安装; 去掉 --check 即真装)"
  exit 0
fi

if [ "$DO_UNINSTALL" = "1" ]; then
  rm -rf "$PREFIX" "${HOME}/.local/bin/zmax-console" "${HOME}/.local/share/applications/zmax-console.desktop"
  echo "已卸载 ${PREFIX} (工程数据 data/ 不动)"
  exit 0
fi

echo "═══ 开始安装 → ${PREFIX} ═══"
mkdir -p "${PREFIX}/app" "${PREFIX}/venv"
# ① 拷代码 (不要 __pycache__ / .git / data)
( cd "$SRC" && tar --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' --exclude='data' -cf - . ) \
  | ( cd "${PREFIX}/app" && tar -xf - )
echo "   ✅ 代码就位: ${PREFIX}/app"
# ② venv + 依赖
[ -x "${PREFIX}/venv/bin/python" ] || $PY -m venv "${PREFIX}/venv"
"${PREFIX}/venv/bin/python" -m pip install -q --upgrade pip
echo "   … 装依赖 (首次 3~10 分钟, 分量最大的是一堆 mujoco/metaworld 依赖)"
"${PREFIX}/venv/bin/python" -m pip install -q -r "${SRC}/requirements-linux.txt"
echo "   ✅ 依赖装好"
# ③ 材质化出厂骨架 (实例数据包不在包里)
mkdir -p "${PREFIX}/app/src/lerobot/engineering/flows"
cp -f "${PREFIX}/app/defaults/canvas/state_space_obs.json" \
      "${PREFIX}/app/src/lerobot/engineering/flows/state_space_obs.json"
echo "   ✅ 出厂画布就位 (全新安装即可启动)"
# ④ 启动器 + 桌面项
mkdir -p "${HOME}/.local/bin" "${HOME}/.local/share/applications"
cat > "${HOME}/.local/bin/zmax-console" <<EOF
#!/usr/bin/env bash
cd ${PREFIX}/app/tools/gui && exec ${PREFIX}/venv/bin/python studio.py "\$@"
EOF
chmod +x "${HOME}/.local/bin/zmax-console"
cat > "${HOME}/.local/share/applications/zmax-console.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Z-MAX Console
Comment=XSpace ZMAX 状态空间控制台
Exec=${HOME}/.local/bin/zmax-console
Terminal=false
Categories=Development;Science;
EOF
echo "   ✅ 命令 zmax-console + 桌面图标就位"
echo
echo "装好了。启动: zmax-console      (或点桌面图标 Z-MAX Console)"
echo "接真实工程数据: tar 解开工程数据包 → tools/instance_init.py --link → tools/engineering_db.py build"
echo "产品档 (550A/550B/550C): 配置中心「产品配置」页切, 真源 defaults/config/platform/zmax_product.json"
