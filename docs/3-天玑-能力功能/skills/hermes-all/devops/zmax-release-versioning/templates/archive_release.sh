#!/usr/bin/env bash
# Z-MAX 小版本归档模板 —— 复制成 tools/archive_release_<VER>.sh, 只改 VER / BASE / MANIFEST 主题
#
# 为什么这样写:
#   · code 清单**由上一版 tag 现场算**(git diff), 不手写 —— 手写必漏文件, 而 sha256 照样全绿
#   · diff 里混着 Hermes 技能/记忆同步提交 ⇒ 必须 skip, 否则 code/ 里全是技能库
#   · config/ 是软链且不在 git ⇒ 参数真源只能显式 cp
#   · 常驻服务 log 是 GB 级 ⇒ 只留尾部, 否则归档从几十 MB 涨到几百 MB
#   · sha256sums 最后生成且排除自己, 否则 -c 必 FAIL
set -uo pipefail
VER=5.50.000          # ← 改
BASE=v5.50.000        # ← 改: 上一版 tag
DATE=$(date +%Y%m%d)
REPO=/home/ubuntu/zmax
DST=$REPO/zmax_data/release_${VER}_${DATE}
rm -rf "$DST"; mkdir -p "$DST"/{code,data,logs,evidence}
cd "$REPO" || exit 1

# ── ① 代码: 上一版 tag 之后真改过的文件 ──────────────────────────────────────
git diff --name-only "$BASE"..HEAD | while IFS= read -r f; do
  [ -f "$f" ] || continue
  case "$f" in
    *"hermes-all"*|*"/memory/"*|*.code-workspace) continue ;;   # 技能/记忆同步, 非产品代码
  esac
  mkdir -p "$DST/code/$(dirname "$f")"
  cp -L "$f" "$DST/code/$f"        # -L 解引用软链(打包红线)
done
echo "code 文件数: $(find "$DST/code" -type f | wc -l)"

# ── ② 数据: 参数真源(软链) + 画布 + 点位 + 本轮真源 json ────────────────────
mkdir -p "$DST/data/config" "$DST/data/canvas" "$DST/data/points"
[ -d config/calib ]    && cp -rL config/calib    "$DST/data/config/" 2>/dev/null
[ -d config/platform ] && cp -rL config/platform "$DST/data/config/" 2>/dev/null
cp -f data/database/zmax/sources/canvas/state_space_obs.json "$DST/data/canvas/" 2>/dev/null
cp -f reports/aoi_points/*.json "$DST/data/points/" 2>/dev/null
# ↑ 本轮还有别的真源(回放修正表/进化台账)就各自再开子目录, 别塞进 canvas
echo "data 文件数: $(find "$DST/data" -type f | wc -l)  体积: $(du -sh "$DST/data" | cut -f1)"

# ── ③ 日志尾 ───────────────────────────────────────────────────────────────
for L in /var/log/zmax-*.log; do
  [ -f "$L" ] && tail -n 4000 "$L" > "$DST/logs/$(basename "$L").tail.log"
done
echo "logs 文件数: $(find "$DST/logs" -type f | wc -l)"

# ── ④ 实测证据(只写数字; heredoc 分隔符必须与内层不同) ─────────────────────
{ echo "# v$VER 实测证据 ($DATE)"; echo; echo '```'
  ./gui-venv311/bin/python - <<'PYEV' 2>&1 | head -40
import json, glob
for p in sorted(glob.glob('reports/*.json'))[:5]:
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception:
        continue
    print(p, {k: d[k] for k in list(d)[:4]})
PYEV
  echo '```'
} > "$DST/evidence/measured_${DATE}.md"
echo "evidence: $(wc -l < "$DST/evidence/measured_${DATE}.md") 行 —— 必须 sed -n 回读确认有数字"

# ── ⑤ MANIFEST ─────────────────────────────────────────────────────────────
cat > "$DST/MANIFEST.md" <<EOF
# Z-MAX v$VER 归档 ($DATE)

主题: <一句话>

## 本轮改动
- <逐条: 文件 + 做了什么 + 实测数字>

## 目录
- code/   引用 $BASE 之后真改过的产品代码(技能/记忆同步已剔除)
- data/   参数真源(calib+platform) · 画布真源 · 点位台账 · 本轮真源 json
- logs/   常驻服务日志**仅尾部 4000 行**
- evidence/measured_$DATE.md  实测数字

## 验收
\`sha256sum -c sha256sums.txt\` 全 OK
EOF

# ── ⑥ sha256(排除清单自身) ────────────────────────────────────────────────
cd "$DST" || exit 1
find . -type f ! -name sha256sums.txt | sort | xargs sha256sum > sha256sums.txt
sha256sum -c sha256sums.txt --quiet && echo "sha256 全 OK"
echo "文件数: $(find . -type f ! -name sha256sums.txt | wc -l)  体积: $(du -sh . | cut -f1)"
echo "归档: $DST"
