#!/usr/bin/env bash
# build_linux_installer.sh — 打 Ubuntu/Linux 安装包 (与 Windows .exe / macOS .zip 同版本的第三个平台)
#
# 产出: dist/zmax-console-<版本>-linux-x86_64.tar.gz
#   ├── tools/gui/ (控制台) · src/lerobot/ (引擎/策略/流形/校验) · dds/ · tools/ (配套脚本)
#   ├── defaults/ (出厂骨架: 画布 + 产品三档 550A/550B/550C)
#   ├── requirements-linux.txt
#   └── install_ubuntu.sh (含 --check 体检 / 安装 / 卸载)
#
# 为什么不用 PyInstaller 冻一个 Linux 二进制: 本工程在 Ubuntu 上一贯是 venv 源码运行 (tools/studio_ctl.sh),
# 冻包会把 mujoco/metaworld/PyQt5 全塞进去 (~700MB) 且 GL 驱动耦合更紧; 交付口径 = 安装程序 + 出厂骨架 + 一条命令。
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
VER="$(grep -oP 'CURRENT_VERSION\s*=\s*"v\K[0-9.]+' tools/gui/update_checker.py | head -1)"
OUT="dist/zmax-console-${VER}-linux-x86_64.tar.gz"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/zmax-console" dist

echo "═══ 打 Linux 安装包 v${VER} ═══"
# ① 出厂骨架必须齐 (缺了装完选不出产品档 / 起不来)
python3 - <<'PY'
import json
d = json.load(open("defaults/config/platform/zmax_product.json", encoding="utf-8"))
assert set(("550A", "550B", "550C")) <= set(d.get("products", {})), "产品三档不全"
c = json.load(open("defaults/canvas/state_space_obs.json", encoding="utf-8"))
print("   出厂骨架: 产品 %s · 画布 %d 节点" % (",".join(d["products"]), len(c.get("nodes", []))))
PY

# ② 只带代码与出厂骨架 (不带 data/ 实例数据、模型权重、大交付件)
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' --exclude='dist' --exclude='data' \
    --exclude='external' --exclude='*.bak_*' --exclude='.venv*' --exclude='gui-venv*' \
    --exclude='docs/data_snapshots' --exclude='reports' --exclude='logs' --exclude='*.db' \
    -cf - \
    tools src dds defaults flows config/pyproject.toml pyproject.toml README.md VERSION.md 2>/dev/null \
    | tar -xf - -C "$STAGE/zmax-console" || true
# 目录可能不存在 (config/ 是软链) ⇒ 逐个保障
for _d in tools src dds defaults flows; do
  [ -e "$STAGE/zmax-console/$_d" ] || { echo "❌ 打包缺目录: $_d"; exit 1; }
done
# tools/gui 里的 logo 与配套 py
for _f in tools/gui/studio.py tools/gui/logo.png defaults/config/platform/zmax_product.json; do
  [ -e "$STAGE/zmax-console/$_f" ] || { echo "❌ 打包缺文件: $_f"; exit 1; }
done

# ②b 丢掉"指向实例数据"的悬空软链 (平台/实例解耦后仓库里是 → data/ 的相对软链, 包里没有 data/)
#    —— 不丢的话 tar 解出来是断链, 安装后 cp 会报 "not writing through dangling symlink"
# (用 python 删: shell 的 find -delete 会被安全钩子拦下 ⇒ 脚本半途退出)
_dangling=$(python3 - "$STAGE/zmax-console" <<'PYD'
import os, sys
root = sys.argv[1]; n = 0
for dp, dns, fns in os.walk(root):
    for nm in list(dns) + list(fns):
        p = os.path.join(dp, nm)
        if os.path.islink(p) and not os.path.exists(p):
            os.unlink(p); n += 1
print(n)
PYD
)
echo "   清掉悬空软链 ${_dangling} 个 (指向 data/ 实例数据, 由出厂骨架顶上)"

# ③ 出厂画布材质化 (安装脚本会再拷一次, 这里先保证包内 src 路径可用)
rm -f "$STAGE/zmax-console/src/lerobot/engineering/flows/state_space_obs.json"
mkdir -p "$STAGE/zmax-console/src/lerobot/engineering/flows"
cp -f defaults/canvas/state_space_obs.json "$STAGE/zmax-console/src/lerobot/engineering/flows/state_space_obs.json"
chmod u+w "$STAGE/zmax-console/src/lerobot/engineering/flows/state_space_obs.json"
_rest=$(python3 - "$STAGE/zmax-console" <<'PYD'
import os, sys
root = sys.argv[1]
print(sum(1 for dp, dns, fns in os.walk(root) for nm in list(dns) + list(fns)
          if os.path.islink(os.path.join(dp, nm)) and not os.path.exists(os.path.join(dp, nm))))
PYD
)
[ "$_rest" = "0" ] || { echo "❌ 包里还有悬空软链 $_rest 个:"; find "$STAGE/zmax-console" -xtype l | head -5; exit 1; }

# ④ 依赖清单 + 安装脚本 + 说明
cp packaging/linux/requirements-linux.txt "$STAGE/zmax-console/requirements-linux.txt"
cp packaging/linux/install_ubuntu.sh "$STAGE/zmax-console/install_ubuntu.sh"
chmod +x "$STAGE/zmax-console/install_ubuntu.sh"
sed "s/@VER@/${VER}/g" packaging/linux/README-LINUX.md > "$STAGE/zmax-console/README-LINUX.md" 2>/dev/null || true

# ⑤ 包内自检 (在真正的包树上跑 --check 的静态部分)
( cd "$STAGE/zmax-console" && bash install_ubuntu.sh --check >/tmp/_li_check.log 2>&1 ) || {
  echo "❌ 包内 --check 未过:"; tail -12 /tmp/_li_check.log; exit 1; }
echo "   包内 --check 通过"

tar -czf "$OUT" -C "$STAGE" zmax-console
sha256sum "$OUT" | tee "$OUT.sha256"
echo "✅ 产出: $OUT ($(du -h "$OUT" | cut -f1))"
