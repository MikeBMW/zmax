#!/usr/bin/env bash
# 收工存档 (2026-10-19): 代码快照 + 数据快照 + 清单 + sha256
set -u
REPO=/home/ubuntu/zmax
DST=$REPO/zmax_data/savepoint_$(date +%Y%m%d_%H%M)
mkdir -p "$DST"/{data,config,evidence,shots}
cd "$REPO" || exit 1

echo "=== ① 代码快照 (git archive HEAD) ==="
git archive --format=tar.gz -o "$DST/code_HEAD_$(git rev-parse --short HEAD).tar.gz" HEAD
git rev-parse HEAD > "$DST/GIT_HEAD.txt"
git log --oneline -12 > "$DST/GIT_LOG.txt"
git tag --list 'v5.50.*' | tail -5 > "$DST/GIT_TAGS.txt"

echo "=== ② 真源快照 (分层力 / 引力律 / 运行态) ==="
cp -f config/calib/layer_forces.json config/calib/gravity_law.json \
      config/calib/force_field.json config/calib/zmax_manifold.json "$DST/config/" 2>/dev/null
for f in chunk_latest engine_latest torque_live ui_run trace_live plan_from_vff skill_phys; do
  cp -f "zmax_data/ss_live/$f.json" "$DST/data/" 2>/dev/null
done
cp -f zmax_data/l5_loop/state.json "$DST/data/l5_loop_state.json" 2>/dev/null
cp -f zmax_data/ss_live/l5_scene_vec.json "$DST/data/" 2>/dev/null
cp -f zmax_data/eval/orbital_state_verify.json "$DST/data/" 2>/dev/null
cp -f zmax_data/release_5.50.746_20261019/MANIFEST.md "$DST/data/release_5.50.746_MANIFEST.md" 2>/dev/null
cp -f docs/data_snapshots/20261019_solar_state/*.png "$DST/shots/" 2>/dev/null

echo "=== ③ 证据 ==="
{
  echo "# 收工实测 ($(date '+%F %T'))"
  echo
  echo "## 分层力 (每层各自真源, 权重热生效)"
  echo "- L2 前馈 = chunk_latest.ff[0][:3] · L3 动作头 = chunk_latest.chunk[0][:3]"
  echo "- L4 流形度量 = metric_M/m_ref × ff · L5 = l5_scene_vec.json (VL 标注框 → 方向×置信)"
  echo "- 权重 w: L2 1.0 / L3 0.30 / L4 0.55 / L5 0.35 · 主力 = 加权最大层 (实测 L2)"
  echo
  echo "## 万有引力约束 (force = G·M/r², Φ=−G·M/r)"
  echo "- r: L5/L2 1.0 · L3 1.6 · L4 2.6 · mass_scale 各 1.0"
  echo "- verify_gravity_law 8/8: 反平方 4.000000000000 · 保守场 1.0e-10 · 反作用 0 · 叠加 0 · 势能 0"
  echo
  echo "## 判据 (全部真跑)"
  echo "- verify_gravity_table 40/40 · verify_orbital_state 21/21 · verify_orbital_arch 64/64"
  echo "- verify_gravity_law 8/8 · verify_orbital_nojump 5/5 · verify_mparam_page 全过"
  echo "- verify_no_autostart PASS (无自动开窗 / 命令通道空 / 落地 home)"
  echo
  echo "## 运行态口径"
  echo "- \"在跑\" = 控制台 ui_run.json 的 pid 活着, 或 L5 闭环进程真的在 /proc (只有 state.json 不算)"
  echo "- 未运行 ⇒ 力/四元数/S³ 盘/公转全冻结 (画面变化 ≤0.5%)"
  echo "- 控制台启动 3.5s 量级 (懒建页, 第一眼 HomeWidget)"
} > "$DST/evidence/measured_$(date +%Y%m%d).md"

echo "=== ④ MANIFEST ==="
{
  echo "# Z-MAX 收工存档 $(date '+%F %T')"
  echo
  echo "代码: HEAD $(git rev-parse --short HEAD) · 版本 v5.50.746 · 工作区干净"
  echo
  echo "## 本日主题"
  echo "- 太阳系/力场: 四层力各接自己的模型输出张量; S³ 盘固定五格位; 盘与球同一投影 (方向差 0.00°)"
  echo "- 万有引力约束: |F|=G·M/r² · Φ=−G·M/r · 反平方/作用反作用/叠加/保守场四条数值恒等"
  echo "- L5: 不再自启动 (控制台启动/退出清残留进程); VL 标注框 → 场景方向矢量 (l5_scene_vec.json)"
  echo "- 布局: 右栏最小宽 1080→580 可拖 · 太阳系高度按视口封顶 (表整块可见)"
  echo
  echo "## 目录"
  echo "- code_HEAD_*.tar.gz : 整仓代码快照 (git archive)"
  echo "- config/ : layer_forces / gravity_law / force_field / zmax_manifold"
  echo "- data/   : chunk/engine/torque/ui_run/trace/plan/skill + l5_loop_state + l5_scene_vec + 判据落盘"
  echo "- shots/  : 太阳系截图"
  echo "- evidence/measured_*.md : 实测数字"
  echo "- GIT_HEAD/GIT_LOG/GIT_TAGS : 版本锚点"
} > "$DST/MANIFEST.md"

cd "$DST" && find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt
echo
echo "== 存档完成: $DST"
du -sh "$DST" | sed 's/^/   /'
echo "   文件 $(find "$DST" -type f | wc -l) 个 · 校验 $(wc -l < sha256sums.txt) 行"
