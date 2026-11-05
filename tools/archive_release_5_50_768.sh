#!/usr/bin/env bash
# 归档 v5.50.768 本轮产物 (算力实测 + 55D 端侧部署 + BOM 三档成本 + 手册 M4)
#   产物: ~/zmax_data/release_sync_<YYYYMMDD>_v5.50.768
#   口径: 只拷本轮改动的代码 + 真源快照 + 交付件 + 证据 + MANIFEST + sha256
set -u
REPO=/home/ubuntu/zmax
DATA=/home/ubuntu/zmax_data
VER=5.50.768
DST=$DATA/release_sync_$(date +%Y%m%d)_v${VER}
mkdir -p "$DST"/{tools,web,gui,src,data,evidence,logs,docs,deliverables,scripts}
cd "$REPO" || exit 1

echo "=== ① 版本号文件 (六处) ==="
cp -f tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py "$DST/gui/"
cp -f src/lerobot/ops/docs_sync.py "$DST/src/"
cp -f tools/ci/integrity_check.py tools/bump_version.py "$DST/tools/"
cp -f VERSION.md "$DST/docs/"

echo "=== ② 本轮代码: 算力实测与成本 ==="
cp -f tools/bench_compute.py tools/bench_torch_550a.py tools/compute_report.py \
      tools/bom_cost.py "$DST/tools/" 2>/dev/null
echo "=== ③ 本轮代码: 55D / SE(3) / 手册 ==="
cp -f src/lerobot/policies/left_right/state_space/unified_state55.py \
      src/lerobot/policies/left_right/state_space/perception.py "$DST/src/" 2>/dev/null
cp -f src/lerobot/manifold/se3_pose_head.py src/lerobot/manifold/manifold_engine.py "$DST/src/" 2>/dev/null
cp -f tools/deck_m4.py tools/deck_55d_revise.py tools/verify_state55.py \
      tools/verify_se3_engine.py tools/se3_pose_provider.py tools/se3_pose_head_train.py \
      tools/ss_wiring_audit.py tools/ss_engine_loop.py "$DST/tools/" 2>/dev/null
echo "=== ④ 本轮代码: AR 进化 ==="
cp -f tools/ar_mujoco_clutter.py tools/ar_hard_holdout.py tools/ar_yolo_train_eval.py \
      tools/evolve_ar_world.py tools/ar_mujoco_dataset.py "$DST/tools/" 2>/dev/null

echo "=== ⑤ 真源快照 (config 软链 → data) ==="
if [ -d data/database/zmax/sources/config ]; then
  mkdir -p "$DST/data/config"
  cp -a data/database/zmax/sources/config/. "$DST/data/config/" 2>/dev/null
fi
for f in zmax_data/ss_live/engine_latest.json zmax_data/ar_evolve/ledger.json \
         data/database/zmax/sources/canvas/state_space_obs.json; do
  [ -f "$f" ] && cp -f "$f" "$DST/data/" 2>/dev/null
done
mkdir -p "$DST/data/compute"
cp -f reports/compute/*.json reports/compute/*.md "$DST/data/compute/" 2>/dev/null

echo "=== ⑥ 交付件 ==="
cp -f "zmax_data/deliverables/20261105/Z-MAX以世界模型为核心的状态空间工程_5.50.D-M4.pptx" \
      "zmax_data/deliverables/20261105/Z-MAX以世界模型为核心的状态空间工程_5.50.D-M3.pptx" \
      "$DST/deliverables/" 2>/dev/null

echo "=== ⑦ 证据 (只写数字) ==="
{
  echo "# v5.50.768 实测数字 (仅数字, 无过程)"
  echo
  echo "## 算力 (本机实测 mean of N)"
  echo '| 组件 | 550A 4060 | 550C NPU | 550C iGPU | 550C CPU |'
  echo '|---|---:|---:|---:|---:|'
  echo '| YOLO 640 | 9.04 ms | 2.90 ms | 2.19 ms | 98~144 ms |'
  echo '| INTACT 编码 | — | 2.73 ms | 1.79 ms | 48~116 ms |'
  echo '| INTACT 预测 | — | 1.19 ms | 1.46 ms | 2.19 ms |'
  echo '| SAM3 编码 | 733~1141 ms | 2872 ms | 474 ms | >170 s |'
  echo '| SmolVLM2-500M | 768 ms/帧 | — | — | — |'
  echo '| 流形引擎 1 步 | 0.84 ms | 0.99 ms | — | 0.99 ms |'
  echo
  echo "- 入拍链合计 **8.33 ms / 100 ms ⇒ 占空 8.3%**, 余量 91.7 ms"
  echo "- 550A 显存在役并发 **5932 / 8188 MiB**; Qwen2.5-VL-3B (7.1GB) 实测 OOM"
  echo "- SE(3) 头实链: 真值帧龄 0.09 s · quat_norm 1.000000029 · 6维ξ→群指数 0.62 ms"
  echo
  echo "## BOM (2026 参考价中值, 万元)"
  echo '| 档位 | 550C | Thor T5000 | 目标 | 550C 余量 |'
  echo '|---|---:|---:|---:|---:|'
  echo '| 精细操作(双臂) | 25.75 | 27.15 | 30 | +4.25 |'
  echo '| 集出版(单臂) | 15.90 | 17.30 | 22 | +6.10 |'
  echo '| 专家版(双臂) | 36.85 | 38.25 | 35 | −1.85 |'
  echo
  echo "- 回本 0.55 / 0.70 / 0.64 年 (314·180·314 件/h, 8000h, 稼动 85%)"
  echo "- 专家版降本: 六维力只装插入臂 → 33.65 万"
  echo
  echo "## 55D 验收"
  echo "- 550A verify_state55: 七组判据 PASS"
  echo "- 550C verify_state55: 布局/融合/扩展隔离/43vs55/引擎口径/兼容 PASS (测地线+SLERP 因无 torch 标 skipped)"
} > "$DST/evidence/measured_$(date +%Y%m%d).md"

echo "=== ⑧ 日志 ==="
[ -f /var/log/zmax-ss-engine.log ] && sudo -n cp -f /var/log/zmax-ss-engine.log "$DST/logs/" 2>/dev/null
[ -f /tmp/ss_canvas_loop.log ] && cp -f /tmp/ss_canvas_loop.log "$DST/logs/" 2>/dev/null
cp -f tools/archive_release_5_50_768.sh "$DST/scripts/"

echo "=== ⑨ MANIFEST ==="
{
  echo "# v${VER} 归档 MANIFEST"
  echo
  echo "生成: $(date '+%F %T')  ·  仓库 HEAD: $(git rev-parse --short HEAD)  ·  分支: $(git branch --show-current)"
  echo
  echo "## 主题"
  echo "算力实测(550A/550C 三个计算单元) + 550C 55D 端侧部署 + BOM 三档成本分析 + 手册 M4(299 页)。"
  echo "根因: 100ms 拍预算原先只有架构说法、没有实测数字; 成本档位与目标 30/22/35 万从未对账。"
  echo
  echo "## 目录"
  echo "- \`tools/\` \`gui/\` \`src/\` — 本轮改动过的代码 (非整仓)"
  echo "- \`data/\` — 真源快照: config(标定/平台) + engine_latest + ar 进化台账 + 画布状态 + compute/*.json"
  echo "- \`deliverables/\` — 手册 M3 / M4 pptx"
  echo "- \`evidence/\` — 实测数字汇总 (算力/BOM/验收)"
  echo "- \`logs/\` — 引擎与画布运行日志"
  echo "- \`scripts/\` — 本归档脚本"
  echo
  echo "## 关键结论文件"
  echo "- \`data/compute/COMPUTE_REPORT.md\` — 入拍 8.33ms 与三件只能异步的依据"
  echo "- \`data/compute/BOM_COST.md\` — 三档 BOM 与回本, 专家版超 5% 的降本路径"
  echo "- \`evidence/measured_$(date +%Y%m%d).md\` — 一页看完的数字"
} > "$DST/MANIFEST.md"

echo "=== ⑩ sha256 ==="
cd "$DST" || exit 1
find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt
FILES=$(find . -type f | wc -l); SIZE=$(du -sh . | cut -f1)
echo "文件数 $FILES · 体积 $SIZE"
sha256sum -c sha256sums.txt --quiet && echo "sha256 全 OK" || echo "❌ sha256 FAIL"
echo "归档: $DST"
