#!/usr/bin/env bash
# 归档 v5.50.741 产物 → ~/zmax/zmax_data/release_5.50.741_YYYYMMDD
#   本轮主题: AR 三维视图看得到真机实际走过的轨迹(橙色) / 视图上下颠倒修正 / 清除轨迹真清
#             / 桥接改"整轮一条多点路径"(平顺) + 严格串行不叠队 + 模板防衰减 + 越界自动重锚定
#   沿用 archive_release_5_41_0.sh 口径: 代码 + 真源快照 + 数据 + 证据 + 文档, 末尾 MANIFEST.md + sha256sums.txt
set -u
REPO=/home/ubuntu/zmax
DST=$HOME/zmax/zmax_data/release_5.50.741_$(date +%Y%m%d)
mkdir -p "$DST"/{tools,gui,src,data,evidence,logs,docs}
cd "$REPO" || exit 1

echo "=== ① 本轮改动的代码 ==="
cp -f tools/bridge_episode_path.py tools/bridge_path_recorder.py \
      tools/capture_truth_template.py tools/tcp_ar_server.py \
      tools/archive_release_5_50_741.sh "$DST/tools/" 2>/dev/null
cp -f tools/bridge_stage_move_async.py tools/bridge_stage_path.py tools/stop_all_bridge.sh "$DST/tools/" 2>/dev/null
cp -f tools/web/tcp-ar.html "$DST/gui/"
cp -f tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py "$DST/gui/" 2>/dev/null
cp -f src/lerobot/ops/docs_sync.py "$DST/src/" 2>/dev/null
cp -f tools/ci/integrity_check.py "$DST/tools/" 2>/dev/null
cp -f VERSION.md "$DST/docs/"

echo "=== ② 数据快照 (模板 / 真机轨迹 / 跟随日志) ==="
cp -f zmax_data/ss_live/episode_template_truth.json zmax_data/ss_live/episode_template.json \
      zmax_data/ss_live/bridge_real_path.json "$DST/data/" 2>/dev/null
cp -f zmax_data/ss_live/bridge_episode_path.jsonl "$DST/data/" 2>/dev/null
cp -f /tmp/ep15.log "$DST/logs/ep15_bridge_follow.log" 2>/dev/null
cp -f /tmp/ep14.log "$DST/logs/ep14_bridge_follow.log" 2>/dev/null
cp -f /tmp/rec2.log  "$DST/logs/recorder.log" 2>/dev/null

echo "=== ③ 证据 (实测数字) ==="
{
  echo "# v5.50.741 实测证据 ($(date '+%F %T'))"
  echo
  echo "## 网络实时性 (到控制器 192.168.23.160, 网卡 enx00e04c0c32a0 1Gb 全双工)"
  echo "- ping 20 包: 0% 丢包, RTT 0.098/0.141/0.288ms, mdev 0.046ms, 零收发错误"
  echo "- 命令往返 (写FIFO→拿到SDK回执): 10.7/10.7/10.8/11.0/10.7 ms ⇒ 均 11ms, 抖动 ±0.3ms"
  echo
  echo "## 平顺 (整轮一条多点路径, 一次 moveStart)"
  echo "- 批量路径初测: 10 点 × 5mm = 50mm, 用时 2.8s, 残差 0.0mm ⇒ 一口气走完, 中间不停"
  echo "- 整轮回放: 50 点 / 32mm / 4.3s@7.4mm/s, 50 点 / 40mm / 15.2s@2.6mm/s 两档都连续走完"
  echo
  echo "## 幅度 (老倪要求: 小、不要走远)"
  echo "- 仿真真值一轮 42s: 路径 696mm, X 270 / Y 78 / Z 142 mm (摆盘 SS-TRAY-PLACE)"
  echo "- 真机: --max-path 40mm 硬上限, 实测 15s 累计行走 44.5mm (2.9mm/s), 净位移 (-26.1,+1.5,+20.0)mm"
  echo
  echo "## 叠队教训"
  echo "- 同时排队两条 path ⇒ 越走越快越走远, 包络闸被顶穿 (实测 12s 行程 X54.7/Y0/Z53.0mm, 峰 70mm/s)"
  echo "- 连拒 150 轮: 手动挪位后手臂落在旧包络外 0.9mm, 腿回报 rc=4 扫掠越界, 旧代码拿旧锚点死磕"
  echo "- 前置条件不满足: OperateMode.manual / OperationState.jogging ⇒ rc=3 全拒"
  echo
  echo "## AR 三维视图"
  echo "- 改正前 up 向量 fwd×R ⇒ U=(0,0,-1) 朝下: 台面点 v=316, 台面上方 0.2m 点 v=396 (高的更低=颠倒)"
  echo "- 改正后 up = R×fwd ⇒ U=(0.32,-0.41,0.85): 台面点 v=317, 上方点 v=237 (高的在高处)"
  echo "- 画布像素复核: 网格 mean_v=303 (下半), 橙色真机轨迹 mean_v=183 (上半) ⇒ 轨迹在地平面之上"
  echo "- 真机轨迹: 715 点 / 820.4mm, 10Hz 实测采样; 画布橙色像素 329 个 ⇒ 确实画出来了"
  echo "- 清除轨迹实测: 清除后立刻 real=0 点; 5s 后只剩清除后新点 (原来只清仿真 trace, 橙色不动)"
} > "$DST/evidence/measured_20261018.md"

echo "=== ④ MANIFEST ==="
{
  echo "# Z-MAX v5.50.741 归档 ($(date '+%F %T'))"
  echo
  echo "主题: 真机跟随「看得见、走得平、不跑远」"
  echo
  echo "## 改动"
  echo "- tools/bridge_episode_path.py   整轮一条多点路径 + 严格串行(等回执) + --max-path 硬上限 + 越界自动重锚定"
  echo "- tools/bridge_path_recorder.py  10Hz 录实测 TCP → zmax_data/ss_live/bridge_real_path.json"
  echo "- tools/capture_truth_template.py 从仿真真值录一轮模板(696mm/42s)"
  echo "- tools/tcp_ar_server.py         /api/traj 增加 real 序列; /api/traj/clear 同清真机轨迹并通知录制器"
  echo "- tools/web/tcp-ar.html          3D 橙色真机轨迹管道 + 相机 up 修正(地平线不再上天) + 图例"
  echo "- 版本号 5.50.740 → 5.50.741"
  echo
  echo "## 目录"
  echo "- tools/ gui/ src/ : 本轮代码"
  echo "- data/ : 轨迹模板 + 真机实测轨迹 + 跟随日志(jsonl)"
  echo "- logs/ : 跟随/录制运行日志"
  echo "- evidence/measured_20261018.md : 全部实测数字"
  echo "- docs/VERSION.md"
} > "$DST/MANIFEST.md"

cd "$DST" && find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt
echo
echo "== 归档完成: $DST"
du -sh "$DST" 2>/dev/null | sed 's/^/   /'
echo "   文件 $(find "$DST" -type f | wc -l) 个, 校验 $(wc -l < sha256sums.txt) 行"
