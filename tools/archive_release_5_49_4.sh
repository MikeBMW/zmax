#!/usr/bin/env bash
# 小版本迭代 v5.49.4 归档 — 3D 场景渲染修正 (2026-10-12 老倪现场两条)
#   主题: ① 摆盘光模块"拿起来变长/透明/位置偏/放下消失" ② 插拔夹具孔口不可见(看着像错位)
#   约定沿用 archive_release_5_49_3.sh: 代码 + 唯一依据快照 + 证据 + 文档, 末尾 MANIFEST.md + sha256sums.txt
set -u
REPO=/home/ubuntu/zmax
VER=5.49.4
DST=$HOME/zmax/zmax_data/release_${VER}_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,gui,config,canvas,evidence,reports,docs}
cd "$REPO" || exit 1

echo "=== ⓪ 版本号 $VER ==="
cat > /tmp/rel_${VER}.md <<'EOF'
## v5.49.4 — 3D 场景渲染修正 (小版本迭代)

老倪现场两条: 「点击插拔却跳到摆盘; 摆盘光模块本来短小, 拿起来后变长+透明长方体」→ 追加:
「夹具/孔座 与插入终点横向偏差; 拿起的光模块与渲染的有位置偏差; 放下后又消失」

1. 场景按钮被看门狗扳回 (回归): 按钮只切窗口、未写画布数据源 ⇒ 跟随看门狗 2s 后扳回。
   修: 按钮改走 `_switch_scene_manual()` = 先 `write_canvas_scene()`(复用 tools/ss_scene_switch.py::switch)
   再切窗口 + 8s 独占期。实测: 写画布=插拔 → 10s/24s 后标题仍「3D场景 · 插拔场景」。
2. 拿起来"变长": 摆盘臂上件被整件隐藏(旧逻辑怕与料盘 3 件重复) ⇒ 拿起时露出插拔的 200mm 那根。
   修: 摆盘也画臂上件, 尺寸按摆盘件唯一依据 52×20×12mm (`sim_scene_def._tray_layout`)。
3. "透明长方体": 盘件原为无光照平涂 (shader=None, 单色+线框穿面) ⇒ 金色件改 shader='shaded'。
   实测: 单色平涂像素 72 → 含明暗面 15893 (明暗占比≈100%)。
4. 拿起件与渲染件"位置偏差"30mm: 摆盘 episode 的 meta 无 `peg_head_off`, 代码静默套用插拔默认
   [-0.13,0,-0.01] ⇒ 偏移 -0.13/2+0.035 = -30mm。修: 缺字段 ⇒ 偏移 0 (该 episode 的 peg 即件中心)。
5. "放下后消失": 放好的件没留在 tray盘 槽位。修: 按 episode「完成」真值帧 [798/1723/2654] 点亮槽位件。
6. 插拔"夹具与插入终点横向偏差": 数值上齐 (盒心 y=0.6833 vs 终点 y=0.6834, 差 0.1mm);
   逐像素复核发现 **孔口全图 0px 不可见** (纯深色方口画在深色盒体上) + 插入终点在盒面内侧 35mm 被盒体挡死
   ⇒ 看着像错位。修: 孔口加**亮青边框**(朝相机 +X 面, 相机 x=+1.3 已核) + 插入终点绿框**穿透显示**。
7. 摆盘 tray盘 槽位线框按件半长放大 r=0.012→0.027 (24mm 框装不下 52mm 件 = "盘太小"来源之一)。
8. 老倪定规矩: 双击启动图标 → **只落配置中心, 不自动开 3D/信号/画布**, 先检查任务配置再点「🚀 启动工程」。
   真根因: /tmp/zmax_nav_cmd 残留上一轮命令 ⇒ 新进程(去重表空)一建好界面就执行 ⇒ 看着像"3D 自己开起来"。
   修: launch_studio.sh 启动前清空命令通道 + unset 全部 ZMAX_AUTO_*; studio.py 启动段预先固定该规矩。
   判据: tools/verify_no_autostart.py PASS (启动后 45s 无 3D/信号窗; 命令通道空; 落配置中心)。
9. 配置中心配置数据 → 状态空间「标定诊断测量 · 主参数 M」节点: 新唯一依据模块
   src/lerobot/engineering/config_import.py (8 唯一依据 + 工程库 + 工单 → 写回节点 cfg_*), 节点运行真加载;
   右键「打开源码」直达导入函数 (params.source+source_symbol ⇒ code -g config_import.py:94);
   画布写口改唯一依据 data/database/zmax/sources/canvas/。判据 verify_node_cfg_import.py ✅ 15/15 PASS。
10. 主参数 M = 度量张量 g_ij(x) = M·G_ij(x) (det G=1): src/lerobot/manifold/metric_field.py
   (Γ/曲率/梯度/测地线全数值; 单位行列式 ⇒ 尺度与形状可分开标定) + 节点真跑报几何量
   + 写盘闸门 (原始形状须严格正定)。判据 verify_metric_main_param.py ✅ 23/23 PASS。

取证工具: tools/verify_v2_look.py (两场景抓图量像素) · tools/verify_mouth_align.py (孔口↔插入终点
唯一颜色反查, 换算 mm) · tools/qa_3d_pixels.py · 放大 3D 窗用 `xdotool windowsize` (无需重启即可取证)。
EOF
gui-venv311/bin/python tools/bump_version.py --to "$VER" --summary-file /tmp/rel_${VER}.md \
  || echo "   (版本已是 v$VER, 跳过 bump — 归档仍继续)"

echo "=== ① 本轮改动的代码 (逐文件拷贝) ==="
cp -f tools/gui/ss_dreamview.py tools/gui/studio.py tools/gui/update_checker.py "$DST/gui/" 2>/dev/null
cp -f tools/gui/veh6_config_page.py tools/verify_zmax_open_flow.py tools/verify_node_cfg_import.py \
      src/lerobot/engineering/config_import.py src/lerobot/engineering/nodes/library.py \
      src/lerobot/manifold/metric_field.py tools/zmax_params.py tools/verify_metric_main_param.py \
      src/lerobot/manifold/health.py src/lerobot/manifold/engine_loop.py tools/sil_test_engine.py \
      tools/verify_engine_loop.py tools/config_to_M.py tools/verify_config_to_M.py \
      tools/engine_bus_publish.py tools/feishu_send_file.py \
      tools/gui/launch_studio.sh tools/verify_no_autostart.py \
      tools/sim_scene_def.py tools/tray_live_publish.py tools/tray_plan_3parts.py \
      tools/verify_v2_look.py tools/verify_mouth_align.py tools/qa_3d_pixels.py tools/cmp_3d_fix.py \
      tools/verify_3d_scene_episode.sh tools/check_3d_scene_now.sh tools/verify_3d_follow.sh \
      tools/archive_release_${VER/./_}.sh "$DST/tools/" 2>/dev/null
ls "$DST/gui" | sed 's/^/  gui: /'; ls "$DST/tools" | sed 's/^/  tool: /'
echo "  编译: $(gui-venv311/bin/python -m py_compile tools/gui/ss_dreamview.py tools/sim_scene_def.py && echo OK)"

mkdir -p "$DST/src/lerobot/engineering/nodes"
cp -f src/lerobot/engineering/config_import.py "$DST/src/lerobot/engineering/" 2>/dev/null
mkdir -p "$DST/src/lerobot/manifold"
cp -f src/lerobot/manifold/metric_field.py src/lerobot/manifold/health.py src/lerobot/manifold/engine_loop.py "$DST/src/lerobot/manifold/" 2>/dev/null
cp -f config/calib/zmax_manifold.json "$DST/config/" 2>/dev/null
cp -f src/lerobot/engineering/nodes/library.py "$DST/src/lerobot/engineering/nodes/" 2>/dev/null

echo "=== ② 唯一依据快照 (场景/画布/信号色标) ==="
cp -f data/scene/scenes/SS-TRAY-PLACE/objects3d.json "$DST/config/tray_objects3d.json" 2>/dev/null
cp -f data/scene/scenes/SS-EPI-CORNER/objects3d.json "$DST/config/fw_objects3d.json" 2>/dev/null
cp -fL data/database/zmax/sources/canvas/state_space_obs.json "$DST/canvas/state_space_obs.json" 2>/dev/null
cp -f data/database/zmax/zmax_space.proj "$DST/canvas/" 2>/dev/null
cp -f data/database/zmax/zmax_engineering.db "$DST/canvas/" 2>/dev/null
cp -f src/lerobot/engineering/flows/state_space_obs.json "$DST/canvas/state_space_obs__src_copy.json" 2>/dev/null
mkdir -p "$DST/config/topics"; cp -f config/topics/scene_tags.json "$DST/config/topics/" 2>/dev/null
echo "   画布 md5: $(md5sum flows/state_space_obs.json 2>/dev/null | cut -d' ' -f1)"

echo "=== ③ 本轮证据 (真跑 episode + 截图 + 版本核对) ==="
cp -f reports/tray_place_latest.mp4 reports/tray_plan_3parts.json "$DST/reports/" 2>/dev/null
cp -f reports/tray_place_latest.npz "$DST/reports/" 2>/dev/null
for f in /tmp/v4_fw.png /tmp/v5_fw.png /tmp/v2_tray.png /tmp/grasp_tray.png; do
  [ -f "$f" ] && cp -f "$f" "$DST/evidence/$(basename "$f")"
done
gui-venv311/bin/python tools/verify_version_sync.py --offline > "$DST/evidence/verify_version_sync.txt" 2>&1 || true
tail -2 "$DST/evidence/verify_version_sync.txt" | sed 's/^/  /'
{ echo "version_repo: $(grep -m1 -oP 'CURRENT_VERSION = \K.*' tools/gui/update_checker.py)";
  echo "git_head: $(git rev-parse --short HEAD 2>/dev/null)";
  echo "git_tag: $(git describe --tags --always 2>/dev/null)";
  echo "canvas_md5: $(md5sum flows/state_space_obs.json | cut -d' ' -f1)";
  echo "scene_tags_md5: $(md5sum config/topics/scene_tags.json | cut -d' ' -f1)";
  echo "ss_dreamview: $(sha256sum tools/gui/ss_dreamview.py | cut -c1-16) ($(wc -c < tools/gui/ss_dreamview.py) 字节)"; } \
  > "$DST/evidence/refs.txt"
sed 's/^/  /' "$DST/evidence/refs.txt"

echo "=== ④ 文档 ==="
cp -f VERSION.md "$DST/docs/" 2>/dev/null
cp -f docs/skills/hermes-all/software-development/zmax-console/references/config-sheet-and-scene-colors.md \
      "$DST/docs/zmax-console-config-sheet-and-scene-colors.md" 2>/dev/null

mkdir -p "$DST/deliverables"
cp -f docs/deliverables/*.md "$DST/deliverables/" 2>/dev/null

cp -f reports/sil_engine_*.json "$DST/reports/" 2>/dev/null
echo "=== ⑤ MANIFEST + sha256 ==="
( cd "$DST" && find . -type f ! -name sha256sums.txt ! -name MANIFEST.md -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt )
{ echo "# 归档 v$VER — 3D 场景渲染修正 (摆盘件/孔口可见/场景按钮不再被扳回)";
  echo; echo "生成: $(date '+%F %T')  源: $REPO  HEAD: $(git rev-parse --short HEAD 2>/dev/null)";
  echo; echo "## 目录"; echo '```'; ls -1 "$DST"; echo '```';
  echo; echo "## 校验"; echo 'sha256sum -c sha256sums.txt  (本目录内)'; } > "$DST/MANIFEST.md"
echo
echo "✅ 归档完成: $DST"
echo "   文件 $(find "$DST" -type f | wc -l) 个 · 大小 $(du -sh "$DST" | cut -f1)"
echo "   核验: (cd $DST && sha256sum -c sha256sums.txt | grep -c OK) 个 OK"
