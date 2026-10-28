#!/usr/bin/env bash
# 归档 v5.50.757 本轮产物 (3DGS 采集轨迹自主动作化 + PSNR 同协议口径)
#   产物: ~/zmax_data/release_sync_<YYYYMMDD>_v5.50.757
#   口径沿用 5.50.756: 只拷本轮改动的代码 + 唯一依据快照 + 证据 + MANIFEST + sha256
set -u
REPO=/home/ubuntu/zmax
STAGE=$HOME/.hermes/cache/scratch/rel757
VER=5.50.757
DST=$HOME/zmax_data/release_sync_$(date +%Y%m%d)_v${VER}
mkdir -p "$DST"/{tools,gui,src,data,evidence,logs,docs,remote/orin,remote/intel,scripts}
cd "$REPO" || exit 1

echo "=== ① 本轮改动的代码 ==="
cp -f tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py "$DST/gui/" 2>/dev/null
cp -f src/lerobot/ops/docs_sync.py "$DST/src/" 2>/dev/null
cp -f tools/ci/integrity_check.py tools/bump_version.py tools/archive_release_5_50_757.sh "$DST/tools/" 2>/dev/null
cp -f VERSION.md "$DST/docs/"

echo "=== ② 本轮新增脚本 (轨迹设计/执行/对照) ==="
cp -f "$STAGE"/../plan_orbit3.py "$STAGE"/../geom_check.py "$STAGE"/../run_orbit_orin.sh \
      "$STAGE"/../chain_proto25.sh "$STAGE"/../ab_orbit.sh "$STAGE"/../see_scene.py "$DST/scripts/" 2>/dev/null
cp -f "$STAGE"/../live_mon.py "$STAGE"/../chain_ab.sh "$DST/scripts/" 2>/dev/null

echo "=== ③ 唯一依据快照 (config 是软链, 必须显式拷) ==="
mkdir -p "$DST/data/config"
cp -a config/calib "$DST/data/config/" 2>/dev/null
cp -a config/platform "$DST/data/config/" 2>/dev/null
cp -f zmax_data/models/handeye_state.json "$DST/data/" 2>/dev/null
cp -f zmax_data/models/real_cam_calib.json "$DST/data/" 2>/dev/null
cp -f "$STAGE"/intel/real_cam_calib_undist.json "$DST/data/" 2>/dev/null
cp -f "$STAGE"/orin/d405_intr.json "$DST/data/" 2>/dev/null
cp -f zmax_data/zmax_engineering.db "$DST/data/" 2>/dev/null
cp -f zmax_data/zmax_space.proj "$DST/data/" 2>/dev/null

echo "=== ④ 远端产物 (Orin 相机链 / Intel 训练链) ==="
cp -a "$STAGE"/orin/. "$DST/remote/orin/" 2>/dev/null
cp -a "$STAGE"/intel/. "$DST/remote/intel/" 2>/dev/null

echo "=== ⑤ 日志 ==="
cp -f "$STAGE"/orin/orbit_run3.log "$DST/logs/" 2>/dev/null
cp -f "$STAGE"/intel/remote/rel/*.log "$DST/logs/" 2>/dev/null
cp -f "$STAGE"/intel/sessions.jsonl "$DST/logs/" 2>/dev/null

echo "=== ⑥ 证据 (实测数字) ==="
cat > "$DST/evidence/measured_20261025.md" <<'EOM'
# v5.50.757 实测证据 · 2026-10-25

## 一、机械臂自主轨迹（绕标定板，恒定 z 纯平移）

| 项 | 实测 |
|---|---|
| 路点 | 19 个（径向外退 2 + 绕弧 ±40° 每 8° 共 16 + 退回原位 1） |
| 末端总路程 | 719 mm；相机实际扫过 ≈ 859 mm |
| z | **0.430300 全程不变**（首个路点至末个路点逐位相同） |
| 姿态 | 四元数一个字节不改（纯平移，不触发 50102/50113） |
| 到位精度 | 19/19 路点 `success=True`，偏差 **0.00 mm**（判据：<2mm 连续 1.5s） |
| 总用时 | 46 s（实际 5.4 mm/s，`speed` 参数不按比例） |
| 净空自检 | 全部 PASS，最差 **67.1 mm**（末端↔检测设备）；相机包络最低 z=0.311 与检测设备箱顶 0.34 在 X 向隔 342 mm |
| 收尾状态 | `power=on · operation=idle · has_error=False` |

早前两趟（同弧线，速度 200）：16 路点 / 243 mm / 37 s / 偏差 0.00 mm ×16。

## 二、采集（真机 D405，相机端去畸变）

| 项 | 实测 |
|---|---|
| 会话 | 20261024_205020_5f33 |
| 帧 | **202 帧彩色 + 202 帧深度**（深度失败 0） |
| 位姿跨度 | 0.302 m（门限 0.1 ✓） |
| 清晰度 | p10 221 / 中位 273 / p90 302（拉普拉斯方差） |
| 转角 | rot_deg = 0.0（本趟刻意不转姿态） |
| 数据包 | 45,426,661 B |

相机链：Orin `d405_hub.py` 单进程独占相机 → 相机端 `getOptimalNewCameraMatrix alpha=0` 去畸变（彩色线性 / 深度最近邻）→ 只编一次 → Intel 订 ROS2 CompressedImage。

| 项 | 实测 |
|---|---|
| Intel 侧订阅 | 彩色 9.09 Hz / 57 KB · 深度 8.43 Hz / 168 KB |
| 帧龄 | img_age 0.07 s · depth_age 0.01 s |
| 深度 | 有效率 79%，中心 415 mm |
| 吞吐分解 | 只取帧+对齐 26.5 fps → +深度 raw 7.5 fps → +彩色 raw 3.0 fps → 生产话题 3.0 fps（停订户不变 ⇒ 瓶颈在 Orin 发布端） |
| 采集环实速 | **1.3~2.5 帧/秒**（配置 10 Hz；每帧 3 次 HTTP + 清晰度 + 写盘） |
| 速度参数 | speed=200 ⇒ 6.6 mm/s；speed=33 ⇒ 5.4 mm/s（**低速段不按比例**） |

## 三、PSNR 同协议对照（random 初始化 · 留出连续 25% = 8 段留 2 段）

| 数据 | 留出段 | 留出 PSNR | 训练视角 | 间隙 | 高斯 | 耗时 |
|---|---|---|---|---|---|---|
| 旧 635 帧（手动走位） | 89 帧 / 142.3° | **10.41 dB** | 13.38 | 2.97 | 104,239 | 1038 s |
| 新 202 帧（绕板弧线） | 39 帧 / 0.3 m | **15.18 dB** | 17.86 | 2.68 | 107,190 | 1354 s |
| 差 | — | **+4.77 dB** | +4.48 | −0.29 | — | — |

留出−训练间隙几乎不变（2.97→2.68）⇒ 提升来自**成像一致性**（去畸变只编一次 + 匀速无拖影 + 平视），不是外推能力。

## 四、depth 初始化：增益随帧数（不是一句话能结案）

| 数据 / 初始化 | 留出 PSNR | 高斯 | 耗时 |
|---|---|---|---|
| 202 帧 · depth | **15.26 dB** | 280,452 | 528 s |
| 202 帧 · random | 14.65 dB | 102,125 | 1332.6 s |
| 635 帧 · depth | 13.34 dB | 402,383 | 586 s |
| 635 帧 · random | 13.74 dB | 107,034 | 724 s |

少帧（202）时 depth **+0.61 dB / 快 2.5×**；多帧（635）时 **−0.40 dB**。⇒ 帧数稀时 geometry 才真进模型。

## 五、留出协议纪律（本轮踩出的坑）

默认「8 段留 1 段」在两种数据上难度不同：旧数据切出 47 帧/73.6°（整段角度缺失=外推），
新数据切出 21 帧/0.1 m（前后都有邻居=插值）⇒ **同数据集不同留出协议也不可比**，跨数据集更不可比。
同协议对照必须固定 init + holdout-blocks/holdout-keep + steps 三项。
EOM

echo "=== ⑦ MANIFEST ==="
cat > "$DST/MANIFEST.md" <<'EOM'
# release v5.50.757 · 2026-10-25

## 主题
3DGS 采集轨迹自主动作化（机械臂自跑恒定 z 纯平移弧线绕标定板拍一圈）+ PSNR 同协议口径（连续 25% 留出）

## 改动清单
- `tools/gui/{studio,update_checker,version_sync}.py` + `src/lerobot/ops/docs_sync.py` + `tools/ci/integrity_check.py`：版本号 5.50.757
- `VERSION.md`：新增表首行
- `scripts/`：本轮新增的轨迹设计/净空自检/执行器/对照链（plan_orbit3 · geom_check · orbit_exec · run_orbit_orin · chain_proto25 · ab_orbit · see_scene · live_mon · chain_ab）
- `remote/orin/`：`d405_hub.py`（相机唯一持有者 + 相机端去畸变）、`traj_orbit_v3.json`（19 路点）、`orbit_run3.log`、`d405_intr.json`
- `remote/intel/`：`gs_train.py`（block 留出 + 25% 协议）、`gs_autocap_daemon.py`（深度落盘 + 质量指标 + 增量 frames.jsonl）、`gs_ros_bridge.py`（compressed 图像 + depth）、`real_cam_calib_undist.json`、四次训练 `job.json`/`train_report.json`/`cameras.json`

## 目录
| 目录 | 内容 |
|---|---|
| tools/ gui/ src/ docs/ | 版本号相关代码与 VERSION.md |
| scripts/ | 本轮新增脚本（轨迹/执行/对照/取证） |
| data/ | 唯一依据快照（config/calib + config/platform + handeye_state + real_cam_calib(_undist) + d405_intr + 工程库 + space.proj） |
| remote/orin/ · remote/intel/ | 两台远端机器的实际在役代码与训练产物 |
| evidence/ | measured_20261025.md（全部实测数字） |
| logs/ | 轨迹执行日志 + 四组训练日志 + sessions.jsonl |
EOM

echo "=== ⑧ sha256 ==="
cd "$DST" && find . -type f ! -name sha256sums.txt ! -name MANIFEST.md -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt
echo "文件数: $(find . -type f | wc -l)  体积: $(du -sh . | cut -f1)"
sha256sum -c sha256sums.txt --quiet && echo "✅ sha256 全部 OK"
echo "归档 → $DST"
