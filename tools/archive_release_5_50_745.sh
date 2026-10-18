#!/usr/bin/env bash
# 归档 v5.50.745 产物 → ~/zmax/zmax_data/release_5.50.745_YYYYMMDD
#   本轮主题: 臂相机上的 tool1 坐标系(原点=模块头顶中心) / 绿框钉死+不拉长 / 光模块放回槽位(反向复现抓取)
#   沿用 archive_release_5_50_741.sh 口径: 代码 + 真源快照 + 数据 + 证据 + 文档, 末尾 MANIFEST.md + sha256sums.txt
set -u
REPO=/home/ubuntu/zmax
VER=5.50.745
DST=$HOME/zmax/zmax_data/release_${VER}_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,gui,src,data,evidence,logs,docs}
cd "$REPO" || exit 1

echo "=== ① 本轮改动的代码 ==="
cp -f tools/tcp_ar_server.py tools/opt_box3d.py tools/freeze_mod3d.py tools/draw_tool_frame.py \
      tools/place_back.py tools/place_back_finish.py \
      tools/calib_from_arm.py tools/calib_from_module.py tools/calib_flow.py tools/calib_arm_solve.py \
      tools/archive_release_5_50_745.sh "$DST/tools/" 2>/dev/null
cp -f tools/web/tcp-ar.html "$DST/gui/"
cp -f tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py "$DST/gui/" 2>/dev/null
cp -f src/lerobot/ops/docs_sync.py "$DST/src/" 2>/dev/null
cp -f tools/ci/integrity_check.py "$DST/tools/" 2>/dev/null
cp -f VERSION.md "$DST/docs/"

echo "=== ② 数据快照 (模块几何真值 / 放回位 / 标定采集) ==="
cp -f zmax_data/ar_rs/grasp_ref.json zmax_data/ar_rs/module_calib_ref.json "$DST/data/" 2>/dev/null
cp -f data/skills/l2_atomic/taught_points.json "$DST/data/" 2>/dev/null
cp -f zmax_data/calib_d435/flow/poses.json "$DST/data/d435_flow_poses.json" 2>/dev/null
cp -f /dev/shm/mod3_freeze.json "$DST/data/mod3_freeze.json" 2>/dev/null
cp -f /tmp/place_back2.log "$DST/logs/place_back_motion.log" 2>/dev/null
cp -f /tmp/place_finish.log "$DST/logs/place_back_finish.log" 2>/dev/null
cp -f /tmp/calib_flow4.log "$DST/logs/d435_flow_capture.log" 2>/dev/null
cp -f /tmp/calib_arm3.log "$DST/logs/d435_arm_silhouette.log" 2>/dev/null

echo "=== ③ 证据 (实测数字) ==="
{
  echo "# v$VER 实测证据 ($(date '+%F %T'))"
  echo
  echo "## tool1 坐标系(臂相机)"
  echo "- 原点(对齐标注框中心) (332.7,30.4) px; 手眼原始投影 (332.9,41.8) px; 差 11.5px≈5mm ⇒ align_shift_px=(-0.23,-11.49)"
  echo "- 三轴 60mm 端点像素: X1780 / Y1750 / Z1291; 相机系 z=217.7mm; /toolframe.jpg HTTP 200 960x1280 134KB"
  echo
  echo "## 绿框钉死"
  echo "- 连续 5 次采样框 [316.1,0.1,349.3,60.6] 完全一致; 画面帧龄 0.08~0.14s 照常刷新"
  echo
  echo "## 光模块放回槽位(本次实测)"
  echo "- 姿态: 32.4° 分 9 步(4°/步) → 终态姿态差 0.00°; 位移 111mm 分 4 步(35mm/步) → 位置差 1.0mm"
  echo "- 松爪指令: {'skill':'L2.grip_open'}; 夹爪真值 合住 174 / 张开 >700"
  echo "- 库内已记: taught_points.mod_slot_return (0.6533,0.2107,0.2202) / mod_slot_approach (0.6466,0.2056,0.1105)"
  echo
  echo "## 已知未完成(D435 外参)"
  echo "- 四种自动路线全试: 模块当靶标(YOLO 在 D435 上对静态杂物 conf 0.20~0.28 假检出, 两个差 110mm 的 TCP 投到同一像素) /"
  echo "  臂轮廓最远点(RMS 209px, f=-3.7, 臂被画幅顶部裁掉) / 纯平移光流(需 5 位姿, 现场只凑到 4 个) / 圆点板+ArUco(未找到可用靶标)"
  echo "- 光流采集: 4 位姿 (610,305,300)(610,225,300)(610,225,260)(610,305,260) 已落盘, 未解算成功"
  echo "- 运动被拒口径: 50023/50002 超程、50102/50120 奇异、PowerState.estop ⇒ ABORT、x≥625 撞检测设备外扩区"
} > "$DST/evidence/measured_$(date +%Y%m%d).md"

echo "=== ④ MANIFEST ==="
{
  echo "# Z-MAX v$VER 归档 ($(date '+%F %T'))"
  echo
  echo "主题: tool1 坐标系看得见 · 模块框不漂不拉长 · 模块放得回槽位"
  echo
  echo "## 改动"
  echo "- tools/tcp_ar_server.py     /api/toolframe + /toolframe.jpg(臂相机画 tool1 三轴, align=box 对齐标注头顶中心)"
  echo "- tools/draw_tool_frame.py   离线复算 tool1 投影(手眼矩阵取逆 + 米→毫米)"
  echo "- tools/opt_box3d.py         位置闸(跳变>max(60px,1.5×对角)沿用上次框) + 模板只许 YOLO 生成 + 竖向硬夹"
  echo "- tools/freeze_mod3d.py      绿框钉死(--freeze/--clear)"
  echo "- tools/web/tcp-ar.html      『▣ tool1系』按钮 + D435 假检出警告 + 双缓冲"
  echo "- tools/place_back.py        反向复现抓取位姿放回模块(姿态≤4°/步, 位移≤35mm/步, 逐步前置检查)"
  echo "- tools/place_back_finish.py 真松爪({'skill':'L2.grip_open'})+沿 -tool1x 退出"
  echo "- tools/calib_flow.py        纯平移光流解固定相机外参(未成功, 数据留档)"
  echo "- tools/calib_from_arm.py / calib_from_module.py / calib_arm_solve.py  帧差分轮廓路线(证伪留档)"
  echo "- 版本号 5.50.741 → $VER"
  echo
  echo "## 目录"
  echo "- tools/ gui/ src/ : 本轮代码"
  echo "- data/ : 模块几何真值(module_calib_ref.json) + 放回位点(taught_points) + D435 光流位姿 + 绿框冻结值"
  echo "- logs/ : 放回运动/松爪/标定采集日志"
  echo "- evidence/measured_$(date +%Y%m%d).md : 全部实测数字"
  echo "- docs/VERSION.md"
} > "$DST/MANIFEST.md"

cd "$DST" && find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt
echo
echo "== 归档完成: $DST"
du -sh "$DST" 2>/dev/null | sed 's/^/   /'
echo "   文件 $(find "$DST" -type f | wc -l) 个, 校验 $(wc -l < sha256sums.txt) 行"
