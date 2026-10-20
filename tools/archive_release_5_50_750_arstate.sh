#!/usr/bin/env bash
# 归档 v5.50.750 本轮产物 (AR 场景接真机: 位姿/六维力/机器人状态机 + 信号分析收口与字号)
#   产物: ~/zmax/zmax_data/release_sync_<YYYYMMDD>_v5.50.750
#   口径沿用 archive_release_5_50_746.sh: 只拷本轮改动过的代码 + 真源快照 + 证据 + MANIFEST + sha256
set -u
REPO=/home/ubuntu/zmax
VER=5.50.750
DST=$HOME/zmax/zmax_data/release_sync_$(date +%Y%m%d)_v${VER}
mkdir -p "$DST"/{tools,gui,src,web,data,evidence,logs,docs}
cd "$REPO" || exit 1

echo "=== ① 本轮改动的代码 ==="
cp -f tools/ar_aoi_bus.py tools/robot_state.py tools/tcp_ar_server.py \
      tools/verify_ar_force_signals.py tools/verify_sig_space_sync.py \
      tools/restore_cron_after_boot.sh tools/archive_release_5_50_750_arstate.sh "$DST/tools/" 2>/dev/null
mkdir -p "$DST/tools/rokae"
cp -f tools/rokae/ft_direct_sampler.py "$DST/tools/rokae/" 2>/dev/null
cp -f tools/gui/canoe_graphic.py tools/gui/dds_canoe.py "$DST/gui/" 2>/dev/null
cp -f tools/web/tcp-ar.html "$DST/web/" 2>/dev/null
cp -f VERSION.md "$DST/docs/"

echo "=== ② 真源快照 (config 是软链, 必须显式拷) ==="
cp -f config/topics/ar_aoi_signals.json "$DST/data/" 2>/dev/null
cp -f zmax_data/ar_live/ar_aoi_live.json "$DST/data/" 2>/dev/null
cp -f zmax_data/rokae_sdk/tcp_out/state.json "$DST/data/tcp_state.json" 2>/dev/null
cp -f zmax_data/rokae_sdk/tcp_out/latest.json "$DST/data/tcp_latest.json" 2>/dev/null
cp -f zmax_data/rokae_sdk/ft_out/latest.json "$DST/data/ft_latest.json" 2>/dev/null
cp -f zmax_data/ss_live/skill_dispatch.json "$DST/data/" 2>/dev/null
cp -f zmax_data/ss_live/skill_gate.json "$DST/data/" 2>/dev/null
cp -f zmax_data/ss_live/engine_latest.json "$DST/data/" 2>/dev/null
cp -f zmax_data/dataspace/live.json "$DST/data/dataspace_live.json" 2>/dev/null

echo "=== ③ 运行日志 ==="
cp -f /tmp/tcp_ar_server.log "$DST/logs/" 2>/dev/null
cp -f /tmp/ar_aoi_bus.log "$DST/logs/" 2>/dev/null

echo "=== ④ 证据 (只写实测数字) ==="
{
  echo "# v$VER 实测证据 ($(date '+%F %T'))"
  echo
  echo "主题: AR 场景接上真机 —— 末端位姿 x/y/z + 插拔侧向力(真机六维力) + 机器人状态机(是否在插拔)"
  echo "      信号分析收口到 10 条主要信号/字体放大; 选场景即切波形; 数据空间与信号分析同源"
  echo
  echo "## 真机量 (全部来自真实机器人, 无仿真/无平台自算冒充)"
  echo "- 末端位姿: ar_aoi_live.末端.x/y/z = 0.6865 / 0.2282 / 0.2780 m (tcp_out/latest.json, 珞石 xCoreSDK 直采)"
  echo "- 侧向力口径: hypot(fy,fz) 基座系; 工具系算出的值视为错量直接拒用"
  echo "- 换算自检 --selftest: 合成 3-4-5 直角 7/7 PASS (侧向合力 5.0 · 轴向=fx · 工具系拒用 · 陈旧不写 · 报错不写 · 无文件不写)"
  echo "- 力的实时性: ft_out/latest.json 帧龄 > 1s ⇒ 不写任何力键, 值列显示「未接」, meta 写原因 (不用 0 冒充)"
  echo "- 当前真实状态: 控制器 192.168.23.160 不可达 (产线网卡不在位) ⇒ 力三条未接; 状态帧龄 13886s"
  echo
  echo "## 机器人状态机 (真源 tools/robot_state.py)"
  echo "- 实测输出: 🤖 未连接 · 手动 · 阶段 抬起 · 非插拔 · 任务 TASK-01-FW · 状态帧龄 13886.2s"
  echo "- 阶段真源: ss_live/skill_dispatch.json 写龄 0.02s (每拍写) → 备路 skill_gate.json"
  echo "- 状态码 0=未连接 / 1=急停报警 / 2=未上电 / 3=手动 / 4=自动待机 / 5=自动运行"
  echo "- 报警数 10 (state.json n_err_recent, 今日 08:15 急停未恢复)"
  echo "- 插拔判定 = 当前阶段 ∈ {插入,拔出,插拔} 或 执行技能含 insert/pull; 阶段拿不到才写「未知」"
  echo
  echo "## 信号分析收口 (老倪: 不要那么多信号, 不要超过 10 个)"
  echo "- 默认 🎯 主要信号 10 条: 末端 x/y/z + 帧龄 + 轴向力 + 侧向力 + 力帧龄 + 机器人.插拔中/状态_码/运动中"
  echo "- 树默认 1 个根 (当前场景), 全量视图 391 行 (取消勾选即回, 数据一条没删)"
  echo "- 字号: 树/按钮/日志 13px→16px, 表头/小标 12px→14px, 名字列 minWidth 460→560; 实测行文字高 23px"
  echo
  echo "## 场景切换即切波形 (老倪: 选了 AR 右侧还是绿色插拔信号)"
  echo "- 实测 切插拔 ⇒ 树上只剩插拔一个根, 波形里 AR 信号 0 条"
  echo "- 实测 切回 AR ⇒ 自动重新勾上 AR 信号 6 条 (力的 3 条未接不勾), sstrace 曲线已撤, 只剩 AR 根"
  echo "- 实测 模拟数据源变 AR (不点窗口) ⇒ _tick 2s 探针触发, 波形自动切成 AR 6 条"
  echo
  echo "## 数据空间 ↔ 信号分析 同源"
  echo "- DDS 侧本来就同源: 都读 zmax_data/dataspace/{live.json,trace.jsonl,busdb.json} (28 话题)"
  echo "- 新增「🥽 AR 场景 · 文件通道 101 条」顶层组: 位姿行 x 686.5 · y 228.2 · z 278.0 mm (与 ar_aoi_live.json 同值)"
  echo "- 状态机行: 未连接 · 阶段 抬起 · 非插拔 · 报警 10"
  echo
  echo "## AR 页面 (8797)"
  echo "- /api/robot_state 实测 ok:true · code:0 · stage:转移 · inserting:false"
  echo "- 真浏览器读 DOM #tRob = \"🤖 未连接 · 阶段 接近 · 非插拔\" (1s 轮询; 插拔中置绿/急停置红)"
  echo
  echo "## 判据"
  echo "- tools/verify_ar_force_signals.py: PASS (AR 根 #8957e5 · x/y/z 真值 · 力四行「未接」非 0 · 主要信号 ≤10 · 场景切换 · 数据源跟随)"
  echo "- tools/verify_sig_space_sync.py: PASS (数据空间 AR 组 · 位姿同值 · 状态机可读 · 树 16px/行高 23px · DDS 同一文件)"
  echo "- tools/rokae/ft_direct_sampler.py --selftest: 7/7 PASS"
} > "$DST/evidence/measured_$(date +%Y%m%d).md"

echo "=== ⑤ MANIFEST ==="
{
  echo "# v$VER 产物归档 ($(date '+%F %T'))"
  echo
  echo "主题: AR 场景接上真机 —— 末端位姿 x/y/z + 插拔侧向力(真机六维力) + 机器人状态机(是否在插拔);"
  echo "      信号分析主要信号收口(≤10)+字号放大+选场景即切; 数据空间与信号分析同源"
  echo
  echo "## 本轮改动"
  echo '```'
  echo "tools/robot_state.py           新增 · 机器人状态机单一真源 (state/latest/阶段/任务 → code 0..5 + 是否插拔)"
  echo "tools/rokae/ft_direct_sampler.py 新增 · 只读真机六维力采样 (xCoreSDK getEndTorque, 不调 fcStart/不下发运动)"
  echo "tools/ar_aoi_bus.py            新增 末端.轴向力/侧向力/侧向力y/z/力帧龄 + 机器人.* 6 条; real_force 元信息; 陈旧保护"
  echo "tools/tcp_ar_server.py         新增 /api/robot_state (只读代发)"
  echo "tools/web/tcp-ar.html          顶部 chip: 🤖 状态 · 阶段 · 是否插拔 (1s 轮询, 插拔置绿/急停置红)"
  echo "tools/gui/canoe_graphic.py     主要信号模式 ≤10 + 按场景收口 + 场景切换即切波形 + 字号 16px/14px"
  echo "tools/gui/dds_canoe.py         数据空间挂 AR 文件通道组 (位姿/力/状态机三行汇总), 与信号分析同源"
  echo "tools/verify_ar_force_signals.py 判据: 真起信号分析窗口 (含 --selftest)"
  echo "tools/verify_sig_space_sync.py   判据: 两个窗口同源 + 字号"
  echo "tools/restore_cron_after_boot.sh 开机恢复 cron/服务 (本次上电用)"
  echo '```'
  echo
  echo "## 目录"
  echo "- tools/ gui/ web/ : 本轮改动过的代码 (只拷改过的, 不是整仓)"
  echo "- data/ : 真源快照 —— ar_aoi_signals.json(注册表) · ar_aoi_live.json(AR 总线) · tcp_state/tcp_latest(控制器三查+位姿)"
  echo "          ft_latest(六维力) · skill_dispatch/skill_gate/engine_latest(阶段与任务) · dataspace_live(DDS 话题质量)"
  echo "- evidence/ : 实测数字 (只写数字, 不写排查过程)"
  echo "- logs/ : tcp_ar_server.log / ar_aoi_bus.log"
  echo "- docs/ : VERSION.md"
  echo
  echo "## 未关项"
  echo "- 控制器 192.168.23.160 / Orin 192.168.23.66 不可达 (产线网卡不在位) ⇒ 力三条、运动中 未接; 接上采样器即出数"
  echo "- 插拔判定依赖 ss_live/skill_dispatch.json 的阶段名; 阶段名新增同义词时要同步 robot_state.INSERT_STAGES"
} > "$DST/MANIFEST.md"

echo "=== ⑥ sha256 ==="
cd "$DST" || exit 1
find . -type f ! -name sha256sums.txt | sort | xargs sha256sum > sha256sums.txt
echo
echo "归档目录: $DST"
echo "文件数: $(find . -type f | wc -l) · 体积: $(du -sh . | cut -f1)"
echo
echo "=== 验收 sha256sum -c ==="
sha256sum -c sha256sums.txt 2>&1 | tail -3
echo "OK 行数: $(sha256sum -c sha256sums.txt 2>/dev/null | grep -c ': OK$') · FAIL 行数: $(sha256sum -c sha256sums.txt 2>/dev/null | grep -vc ': OK$')"
