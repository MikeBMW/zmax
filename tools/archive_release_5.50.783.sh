#!/usr/bin/env bash
# 归档 v5.50.783 (「保存数据」) —— 六维卡拉比-丘切面固化
# 口径: 代码只拷本轮改过的(product, 滤掉 skills/memory 同步噪声); data/ 手工列清单
#       (data/ 与 zmax_data/ 都在 .gitignore, commit 保存不了这些); 日志只留尾部。
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
VER=5.50.783
BASE=v5.50.782
TS=$(date +%Y%m%d_%H%M)
DST="zmax_data/release_${VER}_${TS}"
rm -rf "$DST"; mkdir -p "$DST"/{code,data,logs,evidence}

echo "== ① code (git diff $BASE..HEAD, 滤掉技能/记忆同步噪声)"
git diff --name-only "$BASE"..HEAD \
  | grep -vE '(skills/hermes-all/|/memory/|\.usage\.json|\.code-workspace|configs/generated_)' \
  > /tmp/rel_code_list.txt
n=0
while IFS= read -r f; do
  [ -f "$f" ] || continue
  mkdir -p "$DST/code/$(dirname "$f")"
  cp -a "$f" "$DST/code/$f" && n=$((n+1))
done < /tmp/rel_code_list.txt
echo "   code 文件数: $n"

echo "== ② data (画布/引擎落盘/服务配置 —— 这些 git 存不了)"
mkdir -p "$DST/data"
for f in \
  data/database/zmax/sources/canvas/state_space_obs.json \
  flows/state_space_obs.json \
  config/ss_task_binding.json \
  deploy/systemd/zmax-cy-slice.service \
  zmax_data/ss_live/mani10_live.json \
  zmax_data/ss_live/mani_flow_live.json \
  zmax_data/ss_live/skill_gate.json ; do
  [ -f "$f" ] || { echo "   ⚠ 缺: $f"; continue; }
  mkdir -p "$DST/data/$(dirname "$f")"
  cp -a "$f" "$DST/data/$f"
done
[ -f zmax_data/ss_live/engine_gate.jsonl ] && tail -n 500 zmax_data/ss_live/engine_gate.jsonl \
  > "$DST/data/zmax_data/ss_live/engine_gate.tail.jsonl"

echo "== ③ logs (只留尾部, 常驻服务日志是 GB 级)"
tail -n 800 /tmp/studio_launch.log > "$DST/logs/studio_launch.tail.log" 2>/dev/null || true
sudo tail -n 300 /var/log/zmax-cy-slice.log > "$DST/logs/zmax-cy-slice.tail.log" 2>/dev/null || true

echo "== ④ 生成 MANIFEST / sha256"
{
  echo "# 归档 v$VER — 六维卡拉比-丘切面固化 ($(date '+%F %H:%M'))"
  echo
  echo "## 主题"
  echo "把「六维卡拉比-丘流形切面(孔洞=亏格g=6)」从一次性脚本固化成标准服务: 数学自证 + 8810 systemd 服务 + 交互页 + 画布双击内嵌窗。"
  echo
  echo "## 本轮代码 ($BASE..HEAD, 已滤技能/记忆同步)"
  sed 's/^/  - /' /tmp/rel_code_list.txt
  echo
  echo "## 目录"
  echo "  code/     本轮改动源码 (只拷改过的)"
  echo "  data/     画布真源 + 引擎落盘 + 服务 unit + 绑定清单 (git 不跟踪)"
  echo "  logs/     启动/服务日志尾部"
  echo "  evidence/ 实测数字"
  echo
  echo "## 说明"
  echo "  - data/ 与 zmax_data/ 在 .gitignore 内, 故用本目录归档, 不靠 commit。"
  echo "  - 日志仅保留尾部行数 (studio 800 / cy-slice 300)。"
  echo "  - 画布真源以 data/database/zmax/sources/canvas/state_space_obs.json 为准, flows/ 为判据侧同步副本。"
} > "$DST/MANIFEST.md"

# ⚠️ 清单必须在归档目录内用相对路径生成, 否则 sha256sum -c 会按“仓库根+相对路径”找文件 → 全 FAIL
( cd "$DST" && find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt )
echo "== ⑤ 校验"
( cd "$DST" && sha256sum -c --quiet sha256sums.txt && echo "   sha256 全 OK" )
echo "== 完成: $DST"
find "$DST" -type f | wc -l | sed 's/^/   文件数: /'
du -sh "$DST" | sed 's/^/   体积:   /'
