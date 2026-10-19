#!/usr/bin/env bash
# 归档 v5.50.746 增补 (20261019 夜间) → ~/zmax/zmax_data/release_5.50.746_20261019_expo
#   本轮主题: ① 表面 AOI 真降曝光 48000→5000us(显示压高光回退默认关) ② 流形引擎几何完备性(切投影有效·度规势证伪)
#   口径沿用 archive_release_5_50_746.sh: 代码 + 数据快照 + 证据 + MANIFEST + sha256sums
set -u
REPO=/home/ubuntu/zmax
VER=5.50.746
DST=$HOME/zmax/zmax_data/release_${VER}_$(date +%Y%m%d)_expo
mkdir -p "$DST"/{tools,gui,src,data,evidence,logs,docs}
cd "$REPO" || exit 1

echo "=== ① 本轮改动的代码 ==="
cp -f tools/cam_live_stream.py \
      tools/aoi_surface_expo_sweep.py tools/aoi_surface_set_expo.py \
      tools/mk_surface_expo_why.py tools/mk_surface_expo_ab.py tools/mk_surface_now.py \
      tools/mk_deglare_levels.py tools/mk_deglare_ab_image.py \
      tools/verify_manifold_geometry.py tools/ab_engine_geometry.py tools/diag_metric_phi.py \
      tools/diag_annot_vlm.py tools/diag_vlm_raw.py \
      tools/archive_release_5_50_746_expo.sh "$DST/tools/" 2>/dev/null
mkdir -p "$DST/src/manifold"
cp -f src/lerobot/manifold/manifold_engine.py "$DST/src/manifold/" 2>/dev/null
# 🆕 L2 光学质量检测节点 + 10083 表面旁路 (2026-10-19 老倪)
mkdir -p "$DST/src/l2_aoi"
cp -f src/lerobot/policies/yolo_3d/surface_optical.py "$DST/src/l2_aoi/" 2>/dev/null
cp -f src/lerobot/middleware/nodes/n_inspection.py "$DST/src/l2_aoi/" 2>/dev/null
cp -f src/lerobot/engineering/nodes/library.py "$DST/src/l2_aoi/" 2>/dev/null
cp -f tools/verify_aoi_surface_node.py tools/mk_surface_judge_rect.py tools/mk_surface_judge_two.py \
      tools/mk_surface_judge.py tools/aoi_surface_rect.py "$DST/tools/" 2>/dev/null
cp -f data/database/zmax/sources/canvas/state_space_obs.json "$DST/data/" 2>/dev/null
cp -f VERSION.md "$DST/docs/"

echo "=== ② 数据快照 (曝光对比图 / 死白定位 / 引擎A/B) ==="
mkdir -p "$DST/data/shots"
cp -f data/deliver/surface_*.png data/deliver/*deglare*.png "$DST/data/shots/" 2>/dev/null
cp -f data/deliver/surface_expo_ab.json data/deliver/surface_expo_why.json "$DST/data/" 2>/dev/null
cp -f reports/ab_engine_geometry.json "$DST/data/" 2>/dev/null
cp -f docs/eval/流形引擎几何完备性_20261019.md \
      "docs/eval/550A_全量pipeline_度规约束与分层_2026-10-19.md" "$DST/docs/" 2>/dev/null

echo "=== ③ 证据 (实测数字) ==="
{
  echo "# v$VER 增补实测证据 ($(date '+%F %T'))"
  echo
  echo "## 表面相机 10083 真降曝光 (工控机 POST /exposure, 落盘 surface_exposure.json)"
  echo "- 生效值: us=5000 / gain=1.8   (本轮起点 48000; 产线默认 80000)"
  echo "- gain 全程未动 (1.8)"
  echo
  echo "| 曝光us | mean | p90 | 死白>=250 | 暗部<25 |"
  echo "|---|---|---|---|---|"
  echo "| 48000 (原) | 103.9 | 179 | 5.18% | 0.4% |"
  echo "| 35000 | 78.7 | 130 | 4.61% | 4.4% |"
  echo "| 25000 | 59.0 | 92 | 3.96% | 14.7% |"
  echo "| 18000 | 44.8 | 66 | 3.54% | 29.2% |"
  echo "| 12000 | 32.5 | 43 | 3.25% | 58.8% |"
  echo "| 8000 | 23.9 | 28 | 2.76% | 82.5% |"
  echo "| **5000 (现)** | **16.3** | **17** | **0.82%** | **94.7%** |"
  echo
  echo "## 两条硬结论"
  echo "- 死白不是整体过曝: 曝光降 90% (48000→5000), 死白 5.18%→0.82%; 但 48000→18000 只降 1.64 个点,"
  echo "  剩下的是局部镜面反光 (最大连通域 bbox x1031~1714 y0~1281, 233891px, 占死白 90%), 靠曝光压不干净"
  echo "- 判据与曝光的关系分两段: 48000/25000/18000/12000 四档 judge_ok=False 但理由**逐字相同**"
  echo "  (两法估角不一致: 掩膜 19.69° vs 直线 0°) ⇒ 与曝光无关, 属工件姿态/取景;"
  echo "  8000/5000 两档变成「亮条上边缘点太少(195/197)」 ⇒ 曝光压到过曝亮条消失, 表面厚度判据失去几何基础"
  echo
  echo "## 流形引擎几何完备性 (tools/verify_manifold_geometry.py)"
  echo "- 自检 11/11 PASS (初版 3/8 失败, 5 条是判据自身写错: round(phi,6) 精度 / sphere 弧长上界 π 非 π/2 /"
  echo "  descent=-grad 又取一次负 / 用度规势模式去测切投影开关 / 混合势分段)"
  echo "- su2 切空间投影: 旧版法向泄漏 70.5% (随机点) / 50.5% (真轨迹 k=150)"
  echo
  echo "| 目标距离 | A 基线 | B +度规势 | C +切投影 | D 都开 |"
  echo "|---|---|---|---|---|"
  echo "| k=5 | cos 0.9965 · 漏3.2% | 1.0000 · 0% | **1.0000 · 0%** | 1.0000 · 0% |"
  echo "| k=30 | cos 0.9707 · 漏13.1% | 0.9284 · 3.4% | **1.0000 · 0%** | 0.9200 · 0% |"
  echo "| k=150 | cos 0.8036 · 漏50.5% | 0.4090 · 15.5% | **1.0000 · 0%** | 0.4600 · 0% |"
  echo
  echo "- 切投影: 收敛拍数/单调率与基线**完全一致**(5.2/20.8/37.4 拍, 单调率 1.000) ⇒ 只提方向质量, 无额外代价"
  echo "- 度规势被证伪: 逐点诊断 c∈[0.001,0.999] 方向 cos=1.0000 (胜欧氏 0.707~0.9997), 但 c→0 时 ‖grad‖ 塌到 5.9e-05"
  echo "  (Fubini-Study 的 arccos|⟨p,q⟩| 尖点); project 的 bounded_rotvec(gain=2.0) 把远距离状态推到近 π 死角 ⇒ k=150 大量点踩驻点"
  echo "- 数学根因: 欧氏势的切空间梯度 ∝ −(g−c·p), 精确等于测地方向 ⇒ 「欧氏势+切投影」已是方向意义最优, 度规在此指标无提升空间"
  echo
  echo "## L2 光学质量检测节点 · 10083 表面旁路 (2026-10-19 老倪)"
  echo "- 节点: ssaoi 🔍 光学质量检测 · layer 由空 → **L2** (模块真源 LAYER / DB mw_node / 画布 JSON params 三处一致)"
  echo "- 旁路: 跑在 **4060 本机**, 只读 GET 10083 /picture?kind=origin&grab=1, 不部署不改产线不抢独占"
  echo "- 实现: src/lerobot/policies/yolo_3d/surface_optical.py::SurfaceOpticalQuality"
  echo "        → tools/aoi_surface_rect.py::surface_judge (与交付判据图同一实现)"
  echo "- 判据图口径: 长边水平(长边在 x) · 保留整块(expand 纳回暗头, expand_px 单列) · 零拉伸(no_stretch=输出尺寸==裁剪尺寸)"
  echo "- 实测 (5000us): 模块摆正 1282x188 · 长宽比 6.819 · 倾角 -69.79° · 矩形度 0.833 · expand_px=[154,0] · no_stretch=True"
  echo "- 🔴 **ROI 口径 (本轮最值钱的一条)**: 判决必须看**摆正后模块 ROI**, 不能看整帧 mean ——"
  echo "  同一帧: 整帧 mean=16.25 / 死白 0.82% / 暗部 94.7% (**看着全黑**),"
  echo "  而模块 mean=153.97 / 死白 **16.70%** / 清晰度 60.9 (**本身严重过曝**); 黑背景把整帧均值拉低 ⇒ 拿整帧判会得出反向结论"
  echo "- 话题: 表面光学.* 共 13 个 (可用/取像体检/整帧{均值,死白,暗部,清晰度}/模块{均值,清晰度,长宽比}/倾角/矩形度/水平/曝光us)"
  echo "- 自检 tools/verify_aoi_surface_node.py **10/10 PASS** (含 10083 不可达时优雅降级)"
  echo
  echo "## 闸门默认状态 (未改动, 零回归)"
  echo "- ZMAX_MANIFOLD_SU2_TANGENT 默认关 (实测有效, 待真机 A/B 后决定)"
  echo "- ZMAX_MANIFOLD_PHI_METRIC 默认关 (实测有害, 保持研究用)"
  echo "- ZMAX_SURFACE_DEGLARE 默认关 (本轮从 1 改 0: 老倪「别变暗, 要调节曝光」)"
  echo "- ZMAX_L2_GATE=0 · ZMAX_SKILL_FF=0"
} > "$DST/evidence/measured_$(date +%Y%m%d).md"

echo "=== ④ MANIFEST ==="
{
  echo "# Z-MAX v$VER 增补归档 ($(date '+%F %T'))"
  echo
  echo "主题: 表面 AOI 真降曝光 48000→5000us (显示压高光回退默认关) · 流形引擎几何完备性 (切投影有效 / 度规势证伪)"
  echo
  echo "## 改动"
  echo "- tools/cam_live_stream.py          _SURFACE_DEGLARE 默认 1→0 (画面如实反映相机曝光); knee/top 做成 env 可调"
  echo "- tools/aoi_surface_expo_sweep.py   逐档 POST 真写曝光 → 抓两帧 → 量 mean/p90/死白/暗部"
  echo "- tools/aoi_surface_set_expo.py     设单档曝光 + 自动跑判据验证 (POST /capture_detect → 轮询 /last_result)"
  echo "- tools/mk_surface_expo_why.py      死白连通域定位 (块数/面积/bbox/九宫格分布) + 标红可视化"
  echo "- tools/mk_surface_expo_ab.py       两档曝光 A/B, 各抓帧各验判据, 并排对比图"
  echo "- tools/mk_surface_now.py           当前曝光实拍图 (带 mean/p90/死白/暗部 标注)"
  echo "- tools/mk_deglare_levels.py        显示压高光多档对比 (含 160/130/110/90 四档)"
  echo "- src/lerobot/manifold/manifold_engine.py  su2 切空间投影 + 度规势(含近远混合) + 两开关, 默认关"
  echo "- tools/verify_manifold_geometry.py 8→11 条零回归判据, 全 PASS"
  echo "- tools/ab_engine_geometry.py       引擎真身四臂 A/B (基线/度规势/切投影/都开) × 三档目标距离"
  echo "- tools/diag_metric_phi.py          度规势在哪一档 c 失效的逐点诊断"
  echo "- 版本号未变: 仍 $VER (老倪本轮未指定新号)"
  echo
  echo "## 目录"
  echo "- tools/ : 本轮代码 ; src/manifold/ : 引擎"
  echo "- data/ : surface_expo_ab.json + surface_expo_why.json + ab_engine_geometry.json + shots/(全部对比图)"
  echo "- evidence/measured_$(date +%Y%m%d).md : 三张实测表 (曝光七档 / 死白归因 / 引擎四臂)"
  echo "- docs/ : VERSION.md + 流形引擎几何完备性 + 550A 全量 pipeline 报告"
  echo
  echo "## 已知缺口"
  echo "- 5000us 下表面判据无几何基础 (亮条消失), 厚度检测不可用 ⇒ 只适合看图"
  echo "- 死白残留 0.82% 是镜面反光, 软件不可压, 需现场改光源角度/加偏振片"
  echo "- 切投影未接在役引擎 (ss_engine_loop), 真机 A/B 未跑"
} > "$DST/MANIFEST.md"

cd "$DST" && find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt
echo
echo "== 归档完成: $DST"
du -sh "$DST" 2>/dev/null | sed 's/^/   /'
echo "   文件 $(find "$DST" -type f | wc -l) 个, 校验 $(wc -l < sha256sums.txt) 行"
echo "== sha256 验收 =="
sha256sum -c sha256sums.txt 2>&1 | grep -c ": OK" | sed 's/^/   OK /'
sha256sum -c sha256sums.txt 2>&1 | grep -v ": OK" | head -3
