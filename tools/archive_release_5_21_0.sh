#!/usr/bin/env bash
# 归档 v5.21.0 产物 → ~/zmax/zmax_data/release_5.21.0_YYYYMMDD
#   本轮主题: 配置中心 VEH.6 + 任务/工单/配置三合一收口 (一个状态空间工程承载全部任务)
#   ① MCD 描述(MCD-2MC) + 参数注册表        ② 模型×工程契约求交匹配矩阵
#   ③ 工单 Build Sheet ×5 (上下料 8 段 25 条) ④ 任务配置 5 条 (工艺步骤+desc/力/坐标)
#   ⑤ 任务×状态空间工程绑定 (段→节点机械推导 / 6 档位 / 一个工程多任务)
#   ⑥ 配置落到画布节点「标定诊断测量·主参数M」(改名 + 7 段挂载)  ⑦ 结构指纹修死循环
#   ⑧ GUI: VEH.6 新页 + 返回主窗口 + 任务表列 + 节点写入按钮    ⑨ 操作面 CLI
# 约定沿用 archive_release_5_15_36.sh: 代码 + 真源快照 + 证据 + 文档 + 画布备份, 末尾 MANIFEST.md + sha256sums.txt
set -u
REPO=/home/ubuntu/zmax
DST=$HOME/zmax/zmax_data/release_5.21.0_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,gui,src,config,canvas,docs,evidence,reports}
cd "$REPO" || exit 1

echo "=== ① 本轮新增/改动的代码 ==="
cp -f tools/mcd_build.py tools/model_site_match.py tools/build_sheet.py tools/task_build.py \
      tools/config_center.py tools/ss_task_bind.py tools/ss_node_sync.py \
      tools/bump_version.py tools/canvas_add_manifold_calib.py tools/archive_release_5_21_0.sh \
      "$DST/tools/" 2>/dev/null
cp -f tools/gui/veh6_config_page.py tools/gui/studio.py tools/gui/update_checker.py \
      tools/gui/docs_sync.py tools/gui/version_sync.py "$DST/gui/" 2>/dev/null
cp -f src/lerobot/engineering/nodes/library.py "$DST/src/" 2>/dev/null
ls "$DST/tools" | wc -l | sed 's/^/  tools 文件: /'
ls "$DST/gui" | wc -l | sed 's/^/  gui 文件: /'

echo "=== ② 配置真源快照 (生成物是真源, 必须带) ==="
mkdir -p "$DST/config/mcd" "$DST/config/tasks" "$DST/config/orders" "$DST/config/calib"
cp -f config/mcd/zmax_mcd.json config/mcd/param_registry.json config/mcd/match_matrix.json "$DST/config/mcd/" 2>/dev/null
cp -f config/tasks/tasks.json "$DST/config/tasks/" 2>/dev/null
cp -f config/orders/BS_*.json "$DST/config/orders/" 2>/dev/null
cp -f config/ss_task_binding.json "$DST/config/" 2>/dev/null
cp -f config/calib/zmax_manifold.json config/calib/zmax_calib.json "$DST/config/calib/" 2>/dev/null
find "$DST/config" -type f | wc -l | sed 's/^/  配置真源文件: /'

echo "=== ③ 画布真源 + 最近备份 (改名的回滚面) ==="
cp -f src/lerobot/engineering/flows/state_space_obs.json "$DST/canvas/" 2>/dev/null
ls -t src/lerobot/engineering/flows/_archive/*cfg_node_sync*.json 2>/dev/null | head -1 | while read -r f; do
  cp -f "$f" "$DST/canvas/$(basename "$f")"
done
ls -1 "$DST/canvas" | sed 's/^/  /'

echo "=== ④ 工程文件 (.zmaxproj, 控制台可直接加载) ==="
cp -f reports/projects/SS_主工程_任务配置.zmaxproj "$DST/reports/" 2>/dev/null
ls -l "$DST/reports/" | tail -1 | awk '{print "  工程文件:", $5, "bytes"}'

echo "=== ⑤ 实测证据 ==="
cp -f reports/release_v5.21.0_evidence.txt "$DST/evidence/" 2>/dev/null
cp -f reports/projects/SS_主工程_任务配置.zmaxproj "$DST/evidence/工程文件.should_load_ok" 2>/dev/null
ls "$DST/evidence" | sed 's/^/  /'

echo "=== ⑥ 文档 ==="
cp -f VERSION.md "$DST/docs/" 2>/dev/null
cp -f docs/design/manifold_mcd_master_param_M_20261009.md \
      docs/design/veh6_config_center_mcd_20261009.md \
      docs/design/veh6_config_center_operation_20261009.md \
      docs/design/veh6_task_config_20261009.md \
      docs/design/model_zoo_config_matching_20261009.md \
      docs/design/robot_build_sheet_loading_unloading_20261009.md \
      docs/design/ss_task_binding_20261009.md "$DST/docs/" 2>/dev/null
ls "$DST/docs" | wc -l | sed 's/^/  文档: /'

echo "=== ⑦ MANIFEST + sha256 ==="
cd "$DST" || exit 1
{
  echo "# v5.21.0 归档 MANIFEST ($(date '+%F %T %Z'))"
  echo
  echo "- 仓库: MikeBMW/zmax @ $(cd "$REPO" && git rev-parse --short HEAD) (main)"
  echo "- 主题: 配置中心 VEH.6 + 任务/工单/配置三合一收口 (一个状态空间工程承载全部任务)"
  echo "- 画布: 89 节点 / 184 连线 · 节点 n_calib_mani 改名「🧮 标定诊断测量 · 主参数 M」并挂 7 段配置"
  echo "- 工程文件: reports/SS_主工程_任务配置.zmaxproj (schema zmax.statespace.project/1, 5 任务)"
  echo "- 交互入口: 控制台 → VEH.6 配置中心 (默认「📋 任务配置」) · 顶栏「← 返回主窗口」"
  echo "- 操作面: python3 tools/config_center.py {overview,node,node write,tasks,task,bind,activate,project,check}"
  echo
  echo "## 文件清单"
  find . -type f ! -name MANIFEST.md ! -name sha256sums.txt -printf "%s\t%p\n" | sort -k2 \
    | awk -F'\t' '{printf "- %s (%.0f B)\n", $2, $1}'
  echo
  echo "## sha256"
  echo "见 sha256sums.txt"
} > MANIFEST.md
rm -f sha256sums.txt
find . -type f ! -name MANIFEST.md ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt

echo "归档: $DST · 文件 $(find "$DST" -type f | wc -l) · 大小 $(du -sh "$DST" | cut -f1) · sha256 $(wc -l < sha256sums.txt) 条"
