#!/usr/bin/env bash
# 把 550C 上某个 3DGS 训练任务拉到本机 → 8793 的 3DGS 窗口就能看到 (latest 自动变)
#
# 用法: bash tools/publish_gs_job.sh <job_id> [资产名]
#   例: bash tools/publish_gs_job.sh 20261026_085249_d06f05 drag_20261026_083549
#
# 为什么要有它: 550C 训练完只把产物留在自己盘上; 8793(cam_live_stream) 读的是
#   本机 ~/zmax/zmax_data/gs_assets/<名>/gs.splat, 所以要显式拉回来一次。
#   链路走 ECS 三跳 (笔记本不在现场局域网时也能用)。
set -euo pipefail

JOB="${1:?用法: publish_gs_job.sh <job_id> [资产名]}"
NAME="${2:-$JOB}"
HOST="intel@192.168.23.70"
PROXY="bash /home/ubuntu/zmax/zmax_data/runtime/proxy_via_ecs_orin.sh %h %p"
OUT="/home/intel/gs_train_service_intel/jobs/${JOB}/out"
DST="${HOME}/zmax/zmax_data/gs_assets/${NAME}"

mkdir -p "${DST}"
scp -q -o BatchMode=yes -o ProxyCommand="${PROXY}" \
    "${HOST}:${OUT}/gs.splat" "${DST}/gs.splat"
scp -q -o BatchMode=yes -o ProxyCommand="${PROXY}" \
    "${HOST}:${OUT}/train_report.json" "${DST}/train_report.json"
# 留出视角的渲染图当预览(有就拉, 没有不报错)
scp -q -o BatchMode=yes -o ProxyCommand="${PROXY}" \
    "${HOST}:${OUT}/renders/holdout_00.png" "${DST}/preview.png" 2>/dev/null || true

echo "已落盘: ${DST}"
ls -l "${DST}"
echo "--- 8793 资产清单(最新在前) ---"
curl -s -m 8 http://127.0.0.1:8793/gs/list | head -c 600
echo
