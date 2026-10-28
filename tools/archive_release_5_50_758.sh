#!/usr/bin/env bash
# 归档 v5.50.758 本轮产物 (市场分析 1000 台口径 + 2027 模型分层策略 + ar3d 4 孔交替/UPH 浮层)
#   产物: ~/zmax_data/release_sync_<YYYYMMDD>_v5.50.758
#   口径沿用 5.50.757: 只拷本轮改动的代码 + 唯一依据快照 + 交付件 + 证据 + MANIFEST + sha256
set -u
REPO=/home/ubuntu/zmax
DATA=/home/ubuntu/zmax_data
VER=5.50.758
DST=$DATA/release_sync_$(date +%Y%m%d)_v${VER}
mkdir -p "$DST"/{tools,web,gui,src,data,evidence,logs,docs,deliverables,scripts}
cd "$REPO" || exit 1

echo "=== ① 版本号文件（5.50.758 六处） ==="
cp -f tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py "$DST/gui/"
cp -f src/lerobot/ops/docs_sync.py "$DST/src/"
cp -f tools/ci/integrity_check.py tools/bump_version.py tools/archive_release_5_50_758.sh "$DST/tools/"
cp -f VERSION.md "$DST/docs/"

echo "=== ② 本轮代码（ar3d 节拍/相机检测 + 市场与定价模型） ==="
cp -f tools/sim_insert_plan.py tools/refresh_sim_insert.sh "$DST/tools/"
cp -f tools/web/tcp-ar.html "$DST/web/"
cp -f tools/market_analysis_20261027.py tools/pricing_model_20261027.py \
      tools/make_pricing_deck_20261027.py tools/check_deck_layout.py "$DST/tools/"
cp -f tools/archive_release_5_50_758.sh "$DST/scripts/"

echo "=== ③ 唯一依据快照（config 是软链，必须显式拷） ==="
mkdir -p "$DST/data/config"
cp -a config/calib "$DST/data/config/" 2>/dev/null
cp -a config/platform "$DST/data/config/" 2>/dev/null
mkdir -p "$DST/data/traj"
for f in sim_insert.json sim_insert_plan.json; do
  cp -f "zmax_data/runtime/traj/$f" "$DST/data/traj/" 2>/dev/null
done
cp -f zmax_data/reports/market_20261027/metrics_market.json "$DST/data/" 2>/dev/null
cp -f zmax_data/zmax_engineering.db "$DST/data/" 2>/dev/null
cp -f zmax_data/zmax_space.proj "$DST/data/" 2>/dev/null

echo "=== ④ 交付件（市场 PPT + 2027 模型规划，含 pdf/图/数字唯一依据） ==="
cp -a "$DATA"/deliverables/sp_module_market_2026-10-27 "$DST/deliverables/" 2>/dev/null
cp -a "$DATA"/deliverables/model_plan_2027 "$DST/deliverables/" 2>/dev/null

echo "=== ⑤ 日志 ==="
cp -f /tmp/traj_ar.log "$DST/logs/" 2>/dev/null
journalctl -u zmax-traj-ar --no-pager -n 200 > "$DST/logs/zmax-traj-ar.journal" 2>/dev/null

echo "=== ⑥ 证据（实测数字） ==="
cat > "$DST/evidence/measured_20261027.md" <<'EOM'
# v5.50.758 实测证据 · 2026-10-27

## 一、ar3d 节拍（唯一依据 /api/sim_insert）

| 项 | 实测 |
|---|---|
| loop | **45.872 s / 4 件** ⇒ 313.9 件/h（管理口径 300） |
| 单件节拍 | **11.468 s/件**（右臂末端 625.6 mm/s，不与总时间对标） |
| 段数 / 单批 | 392 段 · 14 件 · 159.43 s |
| 4 孔位 | y = 228 / 168 / 108 / 48（pitch −60，全在检测柜内 x 711.7~843.7） |
| 检测 | 金手指 0.8 s + 侧面 4×0.5 s（拔除后 AOI，插着不检） |
| 良率 | 99.2%（1/125 NG，确定性推进） |

## 二、市场模型（1000 台口径，reports/market_20261027/metrics_market.json）

| 项 | 实测 |
|---|---|
| 量价四档（20/50/100/200 台·年） | 总成本 23.68 / 19.19 / 16.78 / 14.52 万；BOM 18.78 / 16.18 / 14.55 / 12.80 万 |
| 三包 | A 29.8/26.8/24.8/21.8 万 · B 42.8/39.8/36.8/31.8 万 · C 0.12 元/只 |
| 单只成本（200 台档） | **0.026 元/只**（11.468 s/件 ⇒ 112.5 万只/年） |
| 五年计划 | 40/120/220/300/320 台（累计 1000）· 收入 3.21 亿 · 毛利 1.44 亿 |
| 三方各得 | **4,816 万**（硬件/软件/运营 1:1:1） |

## 三、PPT 自检（两套交付件）

| 交付件 | 页数 | PROBLEMS | RENDERED | EDGE_PROBLEMS | 墨密度 |
|---|---|---|---|---|---|
| 市场分析与三方分成 | 20 | 0 | 20 | 0 | 7.7%~38.5% |
| 2027 模型产品规划 | 13 | 0 | 13 | 0 | 8.4%~38.6% |

## 四、模型分层锚点（写进策略稿的数字）

| 项 | 实测 |
|---|---|
| 全链每帧 | 20~35 ms（L5 0.1 / L2 8~18 / L4 10~25 / L3 0.01 ms） |
| 收口闸 | 151 次否决 / 33 帧 |
| 预测「下一帧」 | 持久基线 0.00042 vs MOE 0.0121（29×）/ dense 0.0167（40×），52,212 帧 |
| 流形引擎 | 0.056 ms/帧 · 约束违例 1.1e-16 |
| INTACT | 稳态 101 ms · 冷启 6.7 s |
| 能力特征 | 23 条（Z700 10 在役 / Z100 13 规划） |
EOM

echo "=== ⑦ MANIFEST ==="
cat > "$DST/MANIFEST.md" <<'EOM'
# v5.50.758 归档 · 2026-10-27

## 主题
市场分析改「人力替代口径」（1000 台 / 100 场景 × 10 台 / 200 台·年）并重算三方 1:1:1；
新增 2027 模型产品分层策略（L5/L4/L3/L2 · H-JEPA 事件靶 · 三刀解耦 · 配置中心）；
ar3d 4 孔交替插拔 + 双相机 AOI + UPH 浮层/中键平移。

## 目录
- `gui/ src/ tools/ web/` 本轮改动的代码（studio 三处显示 + update_checker + version_sync + docs_sync + integrity_check）
- `web/tcp-ar.html` 构建 r50（4 孔 / UPH 300 浮层 / 中键平移 panOff / 真机臂分离）
- `tools/sim_insert_plan.py` 节拍唯一依据（loop 45.872 s / 4 件 · 625.6 mm/s · 检测 0.8/0.5 s）
- `tools/market_analysis_20261027.py` 市场模型（DISC 量价折扣 / PLATFORM 200 台年 / 五年 1000 台）
- `data/config/` 标定与平台唯一依据全量（calib + platform）
- `data/traj/` sim_insert.json + sim_insert_plan.json（节拍与段表唯一依据）
- `data/metrics_market.json` 市场模型输出（唯一数字唯一依据）
- `deliverables/` 两套交付件（市场 20 页 / 模型规划 13 页，含 pdf、逐页 png、figs、data.json、脚本）
- `evidence/measured_20261027.md` 实测数字
- `sha256sums.txt` 全量校验
EOM

echo "=== ⑧ sha256 + 自校验 ==="
cd "$DST" || exit 1
find . -type f ! -name sha256sums.txt | sort | xargs sha256sum > sha256sums.txt
sha256sum -c sha256sums.txt --quiet && echo "✅ sha256 全 OK"
echo "files=$(find . -type f | wc -l)  size=$(du -sh . | cut -f1)  dst=$DST"
