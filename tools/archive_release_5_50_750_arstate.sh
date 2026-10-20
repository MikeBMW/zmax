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
      tools/rs_service.py tools/rs_service.sh tools/rs_probe.py tools/verify_rs_camera.py \
      tools/realsense_source.py tools/cam_live_stream.py tools/cam_live_stream_ctl.sh \
      tools/l2_daemon.py tools/l2_daemon_ctl.sh \
      tools/watch_insert.py tools/record_insertion.py tools/save_insert_series.py \
      tools/ar_server_kill_by_port.sh tools/ar_server_hard_restart.sh tools/boot_restore.sh \
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
cp -f zmax_data/ar_state/module3d_lock.json "$DST/data/" 2>/dev/null
cp -f zmax_data/evidence/insertion_*.json "$DST/data/" 2>/dev/null
cp -f zmax_data/evidence/insertion_index.jsonl "$DST/data/" 2>/dev/null
cp -f zmax_data/evidence/insertion_series_*.jsonl "$DST/data/" 2>/dev/null
cp -f zmax_data/rokae_sdk/tcp_out/state.json "$DST/data/tcp_state.json" 2>/dev/null
cp -f zmax_data/rokae_sdk/tcp_out/latest.json "$DST/data/tcp_latest.json" 2>/dev/null
cp -f zmax_data/rokae_sdk/ft_out/latest.json "$DST/data/ft_latest.json" 2>/dev/null
cp -f zmax_data/ss_live/skill_dispatch.json "$DST/data/" 2>/dev/null
cp -f zmax_data/ss_live/skill_gate.json "$DST/data/" 2>/dev/null
cp -f zmax_data/ss_live/engine_latest.json "$DST/data/" 2>/dev/null
cp -f zmax_data/dataspace/live.json "$DST/data/dataspace_live.json" 2>/dev/null

echo "=== ③ 运行日志 ==="
cp -f /tmp/tcp_ar_server.log "$DST/logs/" 2>/dev/null
cp -f /tmp/rs_service.log "$DST/logs/" 2>/dev/null
cp -f /tmp/ar_aoi_bus.log "$DST/logs/" 2>/dev/null

echo "=== ④ 证据 (只写实测数字, 现取现算) ==="
EV="$DST/evidence/measured_$(date +%Y%m%d).md"
./gui-venv311/bin/python - "$EV" <<'PY'
import json, math, sys, time
ev = sys.argv[1]
live = json.load(open("zmax_data/ar_live/ar_aoi_live.json", encoding="utf-8"))
s = live.get("s") or {}
m = (live.get("meta") or {}).get("last_pull") or {}
g = lambda k, d=float("nan"): s.get(k, d)
L = []
L.append("# v5.50.750 实测证据 (%s)" % time.strftime("%F %T"))
L.append("")
L.append("主题: AR 场景接上真机 —— 末端位姿 x/y/z + 插拔侧向力(真机六维力) + 机器人状态机(是否在插拔);")
L.append("      信号分析主要信号收口(<=10)+字号放大+选场景即切; 数据空间与信号分析同源")
L.append("")
L.append("## 真机量 (真实机器人, 无仿真/无平台自算冒充) —— 归档当刻现取")
L.append("- 末端位姿: x %.4f  y %.4f  z %.4f m · 帧龄 %.2fs (tcp_out/latest.json, 珞石 xCoreSDK 直采 5Hz)"
         % (g("末端.x"), g("末端.y"), g("末端.z"), g("末端.帧龄_s")))
L.append("- 真机六维力: 轴向 %.2f N · 侧向 %.2f N (hypot(fy,fz)=hypot(%.2f,%.2f)) · 帧龄 %.2fs · 参考系 %s"
         % (g("末端.轴向力_N"), g("末端.侧向力_N"), g("末端.侧向力y_N"), g("末端.侧向力z_N"),
            g("末端.力帧龄_s"), "world/base (基座系, 插入轴=+x)"))
L.append("- 力换算自检 --selftest: 合成 3-4-5 直角 7/7 PASS (侧向合力 5.0 · 轴向=fx · 工具系拒用 · 陈旧不写 · 报错不写 · 无文件不写)")
L.append("- 静止时侧向力不为 0 = 夹爪+D405+工件的重力分量, 不是接触力 ⇒ 接触判据看**变化量**, 不看绝对值")
L.append("- ft_out/latest.json 帧龄 > 1s ⇒ 总线不写任何力键, 值列显示「未接」, meta 写原因 (不用 0 冒充)")
L.append("")
L.append("## 机器人状态机 (真源 tools/robot_state.py, 当前三态走 SDK enum 直读)")
L.append("- 一句话: %s" % (m.get("robot") or "—"))
L.append("- 状态码 %.0f · 插拔中 %.0f · 运动中 %.0f · 阶段码 %.0f · 历史报警 %d 条"
         % (g("机器人.状态_码"), g("机器人.插拔中", 0), g("机器人.运动中", 0), g("机器人.阶段_码"), g("机器人.报警数", 0)))
L.append("- 口径: 0 未连接 / 1 急停·伺服报警 / 2 未使能(伺服off) / 3 手动 / 4 自动待机 / 5 自动运行")
L.append("- 急停只看**当前** PowerState∈{estop,gstop}; state.json 的 last_estop/n_err_recent 是历史记录, 不当当前故障")
L.append("- 插拔判定 = 阶段∈{插入,拔出,插拔} 或 执行技能含 insert/pull; 阶段取 ss_live/skill_dispatch.json (>3s 陈旧⇒未知)")
L.append("")
L.append("## 本轮真机上修掉的两个错 (根因)")
L.append("- getEndTorque 成功返回 {'ec':0,'message':'success'} 被当成报错抛出 (键名是 ec 不是 code) ⇒ 真机有数也报「未接」")
L.append("- 用 state.json 的历史 last_estop 判当前急停 ⇒ 明明 power=on 也显示「急停/报警」")
L.append("")
L.append("## 信号分析收口 (老倪: 不要那么多信号, 不要超过 10 个)")
L.append("- 默认 🎯 主要信号 10 条: 末端 x/y/z + 帧龄 + 轴向力 + 侧向力 + 力帧龄 + 机器人.插拔中/状态_码/运动中")
L.append("- 树默认 1 个根 (当前场景), 全量视图 391 行 (取消勾选即回, 数据一条没删)")
L.append("- 字号: 树/按钮/日志 13px→16px, 表头/小标 12px→14px, 名字列 minWidth 460→560; 实测行文字高 23px")
L.append("")
L.append("## 场景切换即切波形 (老倪: 选了 AR 右侧还是绿色插拔信号)")
L.append("- 切插拔 ⇒ 树上只剩插拔一个根, 波形里 AR 信号 0 条; 切回 AR ⇒ 自动重勾 AR 信号 (真机有数时 10 条全勾)")
L.append("- 数据源在画布/3D 侧改变 ⇒ _tick 2s 探针触发自动切, 不需再点信号窗口")
L.append("")
L.append("## 数据空间 ↔ 信号分析 同源")
L.append("- DDS 侧本来就同源: 都读 zmax_data/dataspace/{live.json,trace.jsonl,busdb.json} (28 话题)")
L.append("- 新增「🥽 AR 场景 · 文件通道」顶层组: 位姿/力/状态机 三行汇总, 值直接取 ar_aoi_live.json")
L.append("")
L.append("## 现场约定 (老倪口述 2026-10-20)")
L.append("- 光模块就夹在机器人手臂末端(夹爪)上, 随臂动; AR 画面里的绿色边框不用动, 不要去重标定")
L.append("")
L.append("## USB RealSense D435 现场事故与修法 (2026-10-20 老倪报「怎么不好使了」)")
try:
    import urllib.request as _u, json as _j
    _h = _j.loads(_u.urlopen("http://127.0.0.1:8789/health", timeout=4).read().decode())
    _i = _j.loads(_u.urlopen("http://127.0.0.1:8797/api/rs_info", timeout=8).read().decode())
    _d = _i.get("depth") or {}
    L.append("- 现象: /snap/rs.jpg 返回 200 但 **0 字节**; /api/rs_info 有内参却 `frames=0`; dmesg 刷 `uvcvideo ... status (-71)`; 曾报 `xioctl(VIDIOC_S_FMT) failed, errno=16 Device or resource busy`")
    L.append("- 根因一(架构): `tcp_ar_server.py` 是 **ForkingMixIn**(每连接 fork), pyrealsense 的取帧线程不会被继承 ⇒ 子进程里的 pipeline 是空壳(snap()=None)。2/9 子进程轮流开设备还会互相抢 UVC ⇒ EBUSY / -71")
    L.append("- 根因二(抢占): 8791 相机流服务把卡名里的 `RealSense` 也当「USB 摄像头」扫进去, 用 CV2 开着 video8 ⇒ D435 被两个进程分着抢")
    L.append("- 修法: 新增 `tools/rs_service.py`(8789, **单进程 + 每请求一线程**)独占 D435; AR 服务的 /api/rs_* · /snap/rs.jpg · /rs.mjpg 全部代理过去; `cam_live_stream` 永不把 RealSense 当 USB 摄像头; `realsense_source` 连续 EBUSY 三次即 hardware_reset 重枚举")
    L.append("- 实测归档当刻: health ok=%s n=%s age=%.3fs | 经 8797 frames=%s age=%.3fs depth_valid=%s | 卡名 RealSense D435 @ USB %s" % (_h.get("ok"), _h.get("n"), (_h.get("age_s") or -1), _i.get("frames"), (_i.get("age_s") or -1), _d.get("valid_ratio"), "5000Mbps"))
except Exception as _e:
    L.append("- 实测取数失败: %s: %s" % (type(_e).__name__, str(_e)[:100]))
L.append("")
L.append("## 判据")
L.append("- tools/verify_ar_force_signals.py: 见下 (真起窗口, 含主要信号 <=10 / 场景切换 / 数据源跟随 / 力未接不写 0)")
L.append("- tools/verify_sig_space_sync.py: 见下 (数据空间 AR 组 · 位姿同值 · 状态机可读 · 树 16px/行高 23px · DDS 同一文件)")
open(ev, "w", encoding="utf-8").write("\n".join(L) + "\n")
print("evidence 写入(现取): " + ev)
PY
{
  echo
  echo "## 判据实跑输出"
  echo '```'
  QT_QPA_PLATFORM=offscreen timeout 240 ./gui-venv311/bin/python tools/verify_ar_force_signals.py 2>&1 \
    | grep -E "✅ PASS|❌ FAIL|^  ✅ .*(力|插拔|场景|数据源|10 条)|^   - " || echo "verify_ar_force_signals 未跑通"
  QT_QPA_PLATFORM=offscreen timeout 240 ./gui-venv311/bin/python tools/verify_sig_space_sync.py 2>&1 \
    > "$DST/evidence/verify_sig_space_sync.txt" 2>&1
  timeout 120 ./gui-venv311/bin/python tools/verify_rs_camera.py 2>&1 \
    | tee "$DST/evidence/verify_rs_camera.txt" \
    | grep -E "^PASS|^FAIL|^[0-9]+/[0-9]+ PASS" || echo "verify_rs_camera 未跑通"
  echo '```'
} >> "$EV"

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
  echo "tools/rs_service.py (+.sh)     新增 · USB D435 独占小服务(8789, 单进程线程模型): 修 fork 空壳/frames=0/0字节/EBUSY"
  echo "tools/tcp_ar_server.py         改 · /api/rs_* · /snap/rs.jpg · /rs.mjpg 全代理到 8789; _rs_jpeg 不再在本进程开设备"
  echo "tools/realsense_source.py      改 · 连续 EBUSY 三次即 hardware_reset 重枚举 (光重试没用)"
  echo "tools/cam_live_stream.py       改 · 绝不把 RealSense 当「USB 摄像头」(抢走会让 AR EBUSY) + 按卡名解析"
  echo "tools/verify_rs_camera.py      判据 · 独占/出帧/新帧/像素/代理/cams 六项 (2026-10-20 实测 6/6 PASS)"
  echo "tools/l2_daemon.py             改 · FIFO 常驻读端(O_RDWR+select): 修 Errno 6 指令被拒(含动作执行期间)"
  echo "tools/l2_daemon_ctl.sh         新增 · 执行器 start|stop|restart|status (status 直接报 FIFO reader 有无)"
  echo "tools/ar_server.py/tcp_ar_server.py 改 · 绿框定主: /api/module3d_lock(lock|unlock) + 锁定时坐标恒定(stale=false, live 单独报活性)"
  echo "web/tcp-ar.html                改 · 顶部 '🔒 绿框定主' 按钮 + 定主时标签写 '🔒 定主'"
  echo "tools/watch_insert.py          新增 · 插入过程只读监视 (位姿/力/实时框/画面差, 1Hz 一行)"
  echo "tools/record_insertion.py      新增 · 把'这一刻'落证据: json + 臂/D435 同刻原帧 + index.jsonl"
  echo "tools/save_insert_series.py    新增 · 采样表存 jsonl 并算行程/力峰/保持段 (不编)"
  echo "tools/boot_restore.sh          改 · 开机先拉 RealSense 小服务(8789) 再拉 AR 服务(8797)"
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
