==============================================================
 Intel Intel 训练环境 — 来源与限制（别重复踩坑）
==============================================================

本目录（~/train_venv）里的 torch / gsplat 是【从 4060 局域网直传】来的，
不是 pip 装的。

为什么不是 pip：
  · 外网带宽只有 ~50 KB/s（4060 也一样，不是 Intel 的问题）
  · 清华镜像 https://pypi.tuna.tsinghua.edu.cn/simple 拉不到 torch:
      ERROR: Could not find a version that satisfies the requirement torch
             (from versions: none)
  · download.pytorch.org 下 840MB 后卡死不动
  ⇒ 下 2.5GB 的 XPU 版 torch 需要 14 小时，不可行

实际做法（已成功，实测 83 MB/s）：
  从 4060 的 /home/ubuntu/zmax/venvs/gs-venv/lib/python3.12/site-packages/
  用 rsync 直传：
    torch 2.7.1+cu128        1.9 G
    nvidia (CUDA 运行库)     3.7 G   ← torch 2.7 的 __init__ 强制加载这些 .so
    cusparselt               227 M   ← 不在 nvidia/ 下, 单独一个包
    gsplat 1.5.3              26 M
    82 个依赖包              886 M
  numpy / PIL / cv2 / scipy 用软链指向系统包（/usr/lib/python3/dist-packages）

现在能做什么：
  ✅ torch CPU 任务（推理、预处理、小模型）
  ✅ 单目 SfM（tools/mapping/mono_sfm.py，纯 OpenCV）
  ✅ 采集图像+位姿（zmax-gs-autocap）
  ❌ 3DGS 训练

为什么 3DGS 训练不行：
  gsplat import 时打印：No CUDA toolkit found. gsplat will be disabled.
  → _C = None → rasterization 报
    'NoneType' object has no attribute 'CameraModelType'

  gsplat/cuda/_backend.py:95/103 确认有 SYCL 路径（torch>=2.7 支持 SYCL），
  即 Intel Arc 架构上支持。但需要 icpx/dpcpp 编译器：

    /opt/intel/oneapi/ 里只有 redist/ （运行时: libsycl.so.8、
    Level Zero 驱动 libze_intel_gpu.so / libze_intel_npu.so 都在）
    **没有 compiler/ 目录** —— 编译器根本没装

  装 intel-oneapi-compiler-dpcpp-cpp 要 1~2 GB，外网 50KB/s 下不动。

要真让 Intel 训 3DGS 的唯一路径：
  1. 拿到 intel-oneapi-compiler-dpcpp-cpp 安装包（U盘 / 内网软件源）
  2. source /opt/intel/oneapi/setvars.sh
  3. 用 SYCL 重编 gsplat（或装 gsplat 的 SYCL wheel）
  4. gs_train.py 会自动走 xpu 分支（它本来就写了 CUDA→XPU→CPU 降级）

当前生产分工（已验证，别改）：
  Intel  zmax-gs-autocap :8806  采集 + 判定 + 送训
  4060   zmax-gs-train   :8804  3DGS 训练（CUDA，3.9 秒/趟）

磁盘：本机 44G / 937G
==============================================================
