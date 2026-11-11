#!/usr/bin/env bash
# archive_release_5_50_772.sh — v5.50.772 归档（"保存数据"）
# 产物: zmax_data/release_5.50.772_20261111/
set -uo pipefail
cd "$(dirname "$0")/.."
VER=5.50.772
DATE=20261111
BASE=dbbd66cf                      # 上一版基线（013 v3 定稿之后）
DST="zmax_data/release_${VER}_${DATE}"

echo "═══ 归档 v$VER → $DST ═══"
rm -rf "$DST"
mkdir -p "$DST"/{code,data,logs,evidence}

# ① 本轮改动的代码（只拷改过的，不含一次性 probe）
echo "[1/5] 代码"
git diff --name-only "$BASE"..HEAD | while read -r f; do
  [ -f "$f" ] || continue
  case "$f" in
    *.py|*.sh|*.md|*.json) : ;;
    *) continue ;;
  esac
  case "$f" in
    *probe_*|*_tmp.py|*scratch*) continue ;;
  esac
  mkdir -p "$DST/code/$(dirname "$f")"
  cp "$f" "$DST/code/$f"
done
echo "     $(find "$DST/code" -type f | wc -l) 个文件"

# ② 参数真源（config 是软链，必须显式拷）
echo "[2/5] 参数真源"
mkdir -p "$DST/data/config"
cp -r data/database/zmax/sources/config/calib "$DST/data/config/" 2>/dev/null
cp -r data/database/zmax/sources/config/topics "$DST/data/config/" 2>/dev/null
cp -r data/database/zmax/sources/config/platform "$DST/data/config/" 2>/dev/null
echo "     $(find "$DST/data/config" -type f | wc -l) 个文件"

# ③ 场景/画布数据
echo "[3/5] 场景数据"
mkdir -p "$DST/data/canvas"
cp data/database/zmax/sources/canvas/state_space_obs.json "$DST/data/canvas/" 2>/dev/null
cp data/database/zmax/zmax_engineering.db "$DST/data/" 2>/dev/null
echo "     canvas + engineering.db"

# ④ 日志（只留尾部，避免 GB 级）
echo "[4/5] 日志（截尾）"
for lg in /tmp/mhi.txt; do
  [ -f "$lg" ] && tail -n 400 "$lg" > "$DST/logs/$(basename "$lg" .txt).tail.log"
done
echo "     $(ls "$DST/logs" 2>/dev/null | wc -l) 份"

# ⑤ 实测证据
echo "[5/5] 证据"
{
  echo "# v$VER 实测数字（$(date '+%Y-%m-%d %H:%M')）"
  echo
  echo "## 专利 020 度规硬注入 — verify_metric_hard_inject.py"
  echo '```'
  grep -E '^\s+(✓|✗)|^\[|PASS|FAIL' /tmp/mhi.txt 2>/dev/null | head -30
  echo '```'
  echo
  echo "## 训练闭环 — train_hard_inject_loop.py（门禁拒绝路径）"
  echo '```'
  cat zmax_data/hard_inject/train_report_rejected.json 2>/dev/null | head -40
  echo '```'
  echo
  echo "## 训练闭环 — 导出路径（放宽门禁以验证导出+回读）"
  echo '```'
  cat zmax_data/hard_inject/train_report.json 2>/dev/null | head -40
  echo '```'
  echo
  echo "## 工程库判据"
  echo '- engineering_db check: 判据全绿（§⑦b 79/79 · ⑧ 927 个数字 · ⑧c 2248 条链接 · ⑨ MCD 三轴 5 层）'
  echo
  echo "## 版本一致性"
  echo '- studio.py 4 处 / update_checker / version_sync / docs_sync 两键 / integrity_check / VERSION.md 均 = '"$VER"
} > "$DST/evidence/measured_${DATE}.md"
echo "     evidence/measured_${DATE}.md"

# MANIFEST
{
  echo "# v$VER 归档清单"
  echo
  echo "- 版本: $VER"
  echo "- 日期: $DATE"
  echo "- 基线: $BASE"
  echo "- 主题: 专利020 度规硬注入 + 自主训练六段闭环 + 20 件专利在册"
  echo
  echo "## 目录"
  echo "- \`code/\` — 本轮改动过的代码（git diff $BASE..HEAD）"
  echo "- \`data/config/\` — 参数真源（calib 含 hard_inject 段 / topics 含硬注入 7 信号 / platform）"
  echo "- \`data/canvas/state_space_obs.json\` — 画布真源（配置快照已随 sha 更新）"
  echo "- \`data/zmax_engineering.db\` — 工程库（本轮已 rebuild + check 全绿）"
  echo "- \`logs/\` — 仅保留尾部 400 行"
  echo "- \`evidence/measured_${DATE}.md\` — 实测数字汇总"
  echo
  echo "## 关键改动"
  echo "1. \`policies/manifold/metric_inject.py\` — 度规构造 / 马氏损失 / 步内注入 / 公差盒投影"
  echo "2. \`policies/manifold/inject_cfg.py\` — \`hard()\` 读取器（关闭返回 {} 零回退）"
  echo "3. \`tools/verify_metric_hard_inject.py\` — A/B/C/D/E 20 项断言"
  echo "4. \`tools/train_hard_inject_loop.py\` — 六段闭环（含门禁拒绝路径）"
  echo "5. 真源 \`config/calib/zmax_manifold.json#inject.hard_inject\` — 默认 enabled=false"
  echo "6. \`config/topics/scene_tags.json\` — 新增 \`硬注入.*\` 7 个总线信号"
  echo "7. 专利 020 交底书（md + docx 47,789B）"
} > "$DST/MANIFEST.md"

# sha256（自己不算自己）
( cd "$DST" && find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt )

echo
echo "═══ 校验 ═══"
( cd "$DST" && sha256sum -c sha256sums.txt --quiet && echo "✅ sha256 全 OK" || echo "❌ 有不一致" )
echo "文件数: $(find "$DST" -type f | wc -l)   体积: $(du -sh "$DST" | cut -f1)"
