#!/usr/bin/env bash
# 归档 v5.50.746 产物 → ~/zmax/zmax_data/release_5.50.746_YYYYMMDD
#   本轮主题: 分层力 L2~L5 各接自己的模型输出张量 + 权重热生效 + 表/太阳系不再被挤掉
#   沿用 archive_release_5_50_745.sh 口径: 代码 + 真源快照 + 证据 + 文档, 末尾 MANIFEST.md + sha256sums.txt
set -u
REPO=/home/ubuntu/zmax
VER=5.50.746
DST=$HOME/zmax/zmax_data/release_${VER}_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,gui,src,data,evidence,logs,docs}
cd "$REPO" || exit 1

echo "=== ① 本轮改动的代码 ==="
cp -f tools/layer_forces.py tools/ar_l5_understand.py tools/tdrive_bus.py \
      tools/verify_gravity_table.py tools/verify_orbital_state.py tools/verify_orbital_arch.py \
      tools/verify_orbital_nojump.py tools/verify_mparam_page.py \
      tools/archive_release_5_50_746.sh "$DST/tools/" 2>/dev/null
cp -f tools/gui/gravity_table.py tools/gui/orbital_arch.py tools/gui/model_tree.py \
      tools/gui/simulink_module.py tools/gui/ss_dreamview.py \
      tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py "$DST/gui/" 2>/dev/null
cp -f src/lerobot/ops/docs_sync.py "$DST/src/" 2>/dev/null
cp -f tools/ci/integrity_check.py "$DST/tools/" 2>/dev/null
cp -f config/calib/layer_forces.json config/calib/force_field.json "$DST/data/" 2>/dev/null
cp -f VERSION.md "$DST/docs/"

echo "=== ② 数据快照 (分层力真源 / 判据落盘 / 太阳系截图) ==="
cp -f zmax_data/ss_live/chunk_latest.json "$DST/data/" 2>/dev/null
cp -f zmax_data/ss_live/engine_latest.json zmax_data/ss_live/torque_live.json "$DST/data/" 2>/dev/null
cp -f zmax_data/ss_live/ui_run.json zmax_data/ss_live/trace_live.json "$DST/data/" 2>/dev/null
cp -f zmax_data/eval/orbital_state_verify.json "$DST/data/" 2>/dev/null
mkdir -p "$DST/data/solar_shots"
cp -f docs/data_snapshots/20261019_solar_state/*.png "$DST/data/solar_shots/" 2>/dev/null

echo "=== ③ 证据 (实测数字) ==="
{
  echo "# v$VER 实测证据 ($(date '+%F %T'))"
  echo
  echo "## 分层力 L2~L5 (每层读它自己的模型输出)"
  echo "- L2 前馈 u_ff   = chunk_latest.ff[0][:3]     实测 |F| 0.047 m/s  ← 主力"
  echo "- L3 动作头      = chunk_latest.chunk[0][:3]  实测 |F| 0.038 m/s"
  echo "- L4 流形度量    = metric_M/m_ref × ff        实测 |F| 0.026 m/s (metric_M 3.643)"
  echo "- L5 VL 场景理解 = l5_scene_vec.json           当前无真源 ⇒ 格子写「缺 L5」, 不拿 prior 回放冒充"
  echo "- 权重 w = L2 1.0 / L3 0.45 / L4 0.55 / L5 0.35 (config/calib/layer_forces.json, 热生效)"
  echo "- 主力判定: 加权后模长最大那层 ⇒ 实测稳定为 L2(前馈); 太阳系 L2 分力笔宽 3.2 vs 其它 1.7"
  echo
  echo "## 表/太阳系布局 (右栏 1067 宽)"
  echo "- 1067x1120: 太阳系 454 / 表 547, 表底 y=1086 (页高 1120) ⇒ 合力(列)行可见"
  echo "- 1200x1120: 太阳系 493 / 表 493, 表底 y=1086"
  echo "- 1067x860 : 太阳系 300 / 表 547, 表底 y=826"
  echo "- 根因: 太阳系高度按 max(520, 0.46×宽) 抬到 520, 与表 586 相加超视口 ⇒ 表被推到视口外(只剩表头)"
  echo
  echo "## q合 闪烁 (悬停提示条压在读数上)"
  echo "- 18 帧 (160ms/帧) q合 区域墨量 162~387 波动; 逐字比对: 第二行被「拖动=旋转 · 滚轮=缩放…」整条盖住"
  echo "- 修法: setToolTip 去重 + 未击中球体不弹提示条; 实测 6 次鼠标移动 → setToolTip 只调用 1 次(空文本)"
  echo
  echo "## 判据"
  echo "- verify_gravity_table 40/40 · verify_orbital_state 21/21 · verify_orbital_arch 64/64"
  echo "- verify_orbital_nojump 5/5 · verify_mparam_page 全过"
  echo "- 控制台启动 3.65s (懒建页 + 空闲建页)"
} > "$DST/evidence/measured_$(date +%Y%m%d).md"

echo "=== ④ MANIFEST ==="
{
  echo "# Z-MAX v$VER 归档 ($(date '+%F %T'))"
  echo
  echo "主题: 分层力 L2~L5 各接自己的模型输出张量 · 权重热生效 · 表与太阳系同屏不再互相挤掉"
  echo
  echo "## 改动"
  echo "- tools/layer_forces.py        分层力核心: L2=前馈 ff / L3=动作头 chunk / L4=度量 M×ff / L5=VL 场景矢量; 权重+换算系数读 config"
  echo "- tools/gui/gravity_table.py   活源之后压分层力 (每层它自己的真源), 缺层清空写「缺 Lx」; 不再二次乘 α; 主力=加权最大层"
  echo "- tools/gui/orbital_arch.py    未运行全冻结 · 同拍 reload · S³ 表盘数字/对数射线 · q̂ 行(提示条去重不再遮读数)"
  echo "- tools/gui/model_tree.py      太阳系高度先按「视口−表整块−页头」封顶 (表不再被挤到视口外)"
  echo "- tools/ar_l5_understand.py    VL 每理解一帧把最大目标框偏移折成方向矢量写 ss_live/l5_scene_vec.json (L5 真源钩子)"
  echo "- tools/gui/simulink_module.py ui_run 发布 cap_level · 无 3D 窗口时由控制台发布 trace_live"
  echo "- tools/tdrive_bus.py          τ = M·(−∇Φ + α·u_ff), apply_to_tau 默认关闭"
  echo "- tools/verify_*.py            判据口径随新分层力更新 (R3/P2/Q1/W1/W2)"
  echo "- 版本号 5.50.745 → $VER"
  echo
  echo "## 目录"
  echo "- tools/ gui/ src/ : 本轮代码"
  echo "- data/ : layer_forces.json(权重) + force_field.json + chunk/engine/torque/ui_run/trace 快照 + 判据落盘 + solar_shots/(太阳系截图)"
  echo "- evidence/measured_$(date +%Y%m%d).md : 全部实测数字"
  echo "- docs/VERSION.md"
  echo
  echo "## 已知缺口"
  echo "- L5 没有持续的场景矢量真源 (VL 只按需跑; 相机 arm 目前无帧) ⇒ 界面标「缺 L5」"
  echo "- L3 当前产出者是「测地线规划 + ridge 解码」, 不是 DiT action head 前向"
  echo "- 姿态四元数无真源 (tcp_pose rx/ry/rz=None); 界面显示的是力/方向四元数"
} > "$DST/MANIFEST.md"

cd "$DST" && find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt
echo
echo "== 归档完成: $DST"
du -sh "$DST" 2>/dev/null | sed 's/^/   /'
echo "   文件 $(find "$DST" -type f | wc -l) 个, 校验 $(wc -l < sha256sums.txt) 行"
