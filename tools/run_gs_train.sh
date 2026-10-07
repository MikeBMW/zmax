#!/usr/bin/env bash
# 3DGS 训练环境包装器 — 必须用它跑 gs_train.py / gs_dataset.py, 否则 gsplat 的 CUDA 扩展
# 载不到 (报 `'NoneType' object has no attribute 'CameraModelType'`, 真因是 JIT 编译失败被吞)。
#
# 本机情况 (2026-10-01 实测, 由 rebuild_cuda_shim.sh 建立):
#   · 系统 nvcc 私有头与 API 头版本不齐 (legacy cuda_fp16.h 是 13.3 / API 头是 12.4)
#     ⇒ 直接 JIT 编不过; /home/ubuntu/zmax/toolchains/cuda-shim = nvcc 全套 + 12.4 API 头 + legacy 私有头合并
#   · 4060 Laptop = sm_89; gcc 13 需 CUDAHOSTCXX 指到 shim 的 g++
# 用法: tools/run_gs_train.sh --data <数据集> --out <输出> [--steps N ...]
set -euo pipefail
S=/home/ubuntu/zmax/toolchains/cuda-shim
if [ ! -x "$S/bin/nvcc" ]; then
  echo "⛔ CUDA shim 不在位: $S (先跑 /home/ubuntu/zmax/zmax_data/rebuild_cuda_shim.sh)"; exit 3
fi
export CUDA_HOME="$S"
export PATH="$S/bin:/home/ubuntu/zmax/venvs/gs-venv/bin:$PATH"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.9}"
export CC="$S/bin/gcc"
export CXX="$S/bin/g++"
export CUDAHOSTCXX="$S/bin/g++"
exec /home/ubuntu/zmax/venvs/gs-venv/bin/python "$(dirname "$0")/gs_train.py" "$@"
