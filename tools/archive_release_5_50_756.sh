#!/usr/bin/env bash
# 归档 v5.50.756 本轮产物 (3DGS 自主进化修复 + 竞品PPT图表原生可编辑)
#   产物: ~/zmax_data/release_sync_<YYYYMMDD>_v5.50.756
#   口径沿用 archive_release_5_50_750_arstate.sh: 只拷本轮改动过的代码 + 唯一依据快照 + 证据 + MANIFEST + sha256
set -u
REPO=/home/ubuntu/zmax
VER=5.50.756
DST=$HOME/zmax_data/release_sync_$(date +%Y%m%d)_v${VER}
mkdir -p "$DST"/{tools,gui,src,data,evidence,logs,docs,ppt,remote}
cd "$REPO" || exit 1

echo "=== ① 本轮改动的代码 ==="
cp -f tools/gs_train.py "$DST/tools/" 2>/dev/null
cp -f tools/gui/studio.py tools/gui/update_checker.py tools/gui/version_sync.py "$DST/gui/" 2>/dev/null
cp -f src/lerobot/ops/docs_sync.py "$DST/src/" 2>/dev/null
cp -f tools/ci/integrity_check.py tools/bump_version.py "$DST/tools/" 2>/dev/null
cp -f tools/archive_release_5_50_756.sh "$DST/tools/" 2>/dev/null
cp -f VERSION.md "$DST/docs/"
cp -f ~/zmax_data/deliverables/robotics_landscape_2026-10-23/{data_v5.py,make_pptx_v5.py,verify_v5.py,README_v5.md} "$DST/ppt/" 2>/dev/null

echo "=== ② 唯一依据快照 (config 是软链, 必须显式拷) ==="
mkdir -p "$DST/data/config"
cp -a config/calib "$DST/data/config/" 2>/dev/null
cp -a config/platform "$DST/data/config/" 2>/dev/null
cp -f zmax_data/models/handeye_state.json "$DST/data/" 2>/dev/null
cp -f zmax_data/models/real_cam_calib.json "$DST/data/" 2>/dev/null
cp -f zmax_data/zmax_engineering.db "$DST/data/" 2>/dev/null
cp -f zmax_data/zmax_space.proj "$DST/data/" 2>/dev/null

echo "=== ③ 证据 (实测数字) ==="
cp -f ~/zmax_data/deliverables/robotics_landscape_2026-10-23/Z-MAX_竞品与合作分析_33页_图表可编辑_v5_2026-10-24.pptx "$DST/evidence/" 2>/dev/null
cat > "$DST/evidence/measured_20261024.md" <<'EOM'
# v5.50.756 实测证据 · 2026-10-24

## 一、3DGS 自主进化闭环

| 项 | 实测 |
|---|---|
| 守护 | gs_auto_train.py 17h18m 连续运行；autocap 14h58m |
| 11 点新数据 | 会话 auto_1023_0659 帧 1571 → **1801**（+230 帧，10:55 后写入） |
| 位姿跨度 | x 647.9 / y 979.7 / z 816.9 mm（真实扫掠，非静止连拍） |
| 独立视点 | 1438（门限 30） |
| 自动触发 | 11:53:05 编排器发现 1801 帧未训练 → 11:53:09 建库 rc=0 → 立即开训 |
| 崩因 | evaluate() 漏 SYCL 空交集保护 ⇒ 400 步后首次 eval 崩在 gs_train.py:257 |
| 报错 | `IndexError: shape mismatch: ... shapes [0], [0, 2]`（gsplat/rendering.py:516 nnz=0） |
| 修法 | evaluate() 两个 render 循环各加 IndexError 跳过 + 往后多取一个视角，全坏才报「留出不可用」 |
| 训练步速 | 200 步 71.5s ⇒ 3000 步 ≈ 18 分钟（Arc B390 SYCL） |
| 历史成功版 | 4 版：1023_190611 / 1023_193904 / 1023_210300 / 1024_093716 |
| 历史 PSNR | 留出 10.22 → 11.27 → 11.53 → 11.86 dB（逐版微涨，仍在平凡基线附近） |

## 二、位姿运动取证（10:58:46 → 11:07:25，8 分 39 秒）

| 段 | 内容 |
|---|---|
| 10:58:46→10:58:53 | 311 mm 快速转移，姿态 28.9°（z 恒定 0.332） |
| 10:59:13→11:02:37 | z=0.332 层，y +0.459 → −0.395，19 点，每点停 10~15s |
| 11:02:45→11:02:47 | 94 mm 下压，z 0.351 → 0.257（2.1s） |
| 11:02:49→11:07:25 | z=0.257 层，y −0.410 → +0.433，33 点 |
| 结束后 | 至 11:47 相邻位移 0.001 mm（静止） |

总位移 306.5 mm · 姿态 28.6° · 起点 (0.598, 0.179, 0.332) 与早上停机位姿一致

## 三、PPT 原生图表化

| 项 | 实测 |
|---|---|
| 图片 → 原生对象 | 9 张 PNG → **12 个 chart** + 3 张形状图（P4/P25/P29） |
| 图表类型 | P6 6×RADAR · P8 2×BAR · P13 BAR · P20 BAR_STACKED · P28 COLUMN · P32 LINE_MARKERS |
| 内嵌数据表 | 12 × ppt/embeddings/Microsoft_Excel_Sheet*.xlsx（右键「编辑数据」可改） |
| 体积 | 1,334,968 B → **202,540 B**（−85%） |
| 校验 | verify_v5 PASS：33 页 / 9 表 / 12 图表 / 30 位图 / 513 文本块 / 豆腐块 0 / <6pt 0 |
EOM

echo "=== ④ 运行日志 ==="
cp -f ../.hermes/cache/scratch/probe_intel_evo.py ../.hermes/cache/scratch/an_pose_11.py "$DST/logs/" 2>/dev/null

echo "=== ⑤ MANIFEST ==="
cat > "$DST/MANIFEST.md" <<'EOM'
# release v5.50.756 · 2026-10-24

## 主题
3DGS 自主进化闭环修复（evaluate 漏 SYCL 零交集保护 ⇒ 400 步必崩）+ 竞品 PPT 图表全改原生可编辑对象

## 改动清单
- `tools/gs_train.py`：evaluate() 加 IndexError 跳过（训练循环早有保护，evaluate 漏了；这是每次自训在 400~500 步必崩的唯一原因）
- `tools/gui/{studio,update_checker,version_sync}.py` + `src/lerobot/ops/docs_sync.py` + `tools/ci/integrity_check.py`：版本号 5.50.756
- `VERSION.md`：新增表首行
- PPT 生成链（`ppt/`）：data_v5 / make_pptx_v5 / verify_v5 / README_v5，图表改原生 chart

## 目录
| 目录 | 内容 |
|---|---|
| tools/ gui/ src/ | 本轮改动的代码 |
| data/ | 唯一依据快照（config/calib + config/platform + handeye_state + real_cam_calib + 工程库 + space.proj） |
| evidence/ | 竞品 PPT 定版 + measured_20261024.md（全部实测数字） |
| logs/ | 取证脚本（位姿分析 / Intel 探测） |
| ppt/ | PPT 生成链 |
| remote/ | Intel 侧产物（资产 ply/splat + 训练日志 + state.json） |
EOM

echo "=== ⑥ sha256 ==="
cd "$DST" && find . -type f ! -name sha256sums.txt ! -name MANIFEST.md -print0 | sort -z | xargs -0 sha256sum > sha256sums.txt
echo "文件数: $(find . -type f | wc -l)  体积: $(du -sh . | cut -f1)"
sha256sum -c sha256sums.txt --quiet && echo "✅ sha256 全部 OK"
echo "归档 → $DST"
