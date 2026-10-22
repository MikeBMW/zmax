# Intel Arc B390 XPU 打通记录（2026-10-22）

## 结论

**torch XPU 在 Intel Arc B390 上跑通了，ultralytics 也能用。**
**但 gsplat（3DGS）用不上 —— gsplat 1.5.3 没有 SYCL 后端实现。**

## 怎么打通的

外网只有 ~50KB/s（4060 和 Intel 都一样）。关键手法：**分段并发下载**。

`download.pytorch.org` 的 CDN 边缘缓存不一致：
- 前段 6.6 MB/s（有缓存）
- 后段 574 B/s（要回源）

单线程下载 677MB 要 170 分钟。**分 16 段独立 curl 并发**后几十秒就下完。

脚本：`~/.hermes/cache/scratch/dl_xpu_torch.sh`（分段 + 重试 + 大小校验 + 合并）

## 装的包

| 包 | 大小 | 来源 | 说明 |
|---|---|---|---|
| torch 2.7.1+xpu | 677 MB | download.pytorch.org/whl/xpu | 分段并发下 |
| intel-pti 1.2.0 | 1.8 MB | pypi.org | 提供 libpti_view.so |
| intel-sycl-rt 2026.2.0 | 165 MB | pypi.org | 提供 SYCL_HOME，gsplat 要找它 |
| ultralytics 8.4.126 | 8.3 MB | 4060 gui-venv311 直传 | 纯 Python，跨版本兼容 |

## 踩过的坑（都修了）

1. **`libpti_view.so.0.10: cannot open shared object file`**
   `intel-pti` 装的是 `libpti_view.so.1`，但 torch 要 `.so.0.10`（旧 soname）。
   修：`ln -sfn libpti_view.so.1 libpti_view.so.0.10`（同族 ABI 兼容，实测可用）。
   全路径：`~/train_venv/lib/libpti_view.so.0.10`

2. **`cv2.imshow` / `cv2.IMREAD_COLOR` 不存在**
   软链 `cv2` 时把整个 `dist-packages` 目录链过去了，形成空壳（7 个私有属性、`__file__=None`）。
   修：系统 cv2 是**单文件 `.so`**，要链那个文件：
   `ln -sfn /usr/lib/python3/dist-packages/cv2.cpython-312-x86_64-linux-gnu.so $SP/cv2.cpython-312-x86_64-linux-gnu.so`

3. **`data.yaml` 里写死 4060 绝对路径**
   `path: /home/ubuntu/zmax/zmax_data/full_train/peg_insert` → Intel 上必须改成本机路径。

4. **matplotlib 跨 Python 版本不能用（C 扩展 ABI）**
   `ImportError: cannot import name '_c_internal_utils' from partially initialized module 'matplotlib'`
   matplotlib 从 `gui-venv311`（Python 3.11）传的，Intel venv 是 3.12。
   `_c_internal_utils` 是编译好的 `.so`，ABI 不兼容。
   **纯 Python 包**（ultralytics、requests、yaml）可以跨版本，
   **带 C 扩展的**（matplotlib、pandas、numpy、cv2）必须匹配版本。
   修：从 4060 的 `gs-venv`（Python 3.12）传 matplotlib，不要从 gui-venv311 传。

5. **torch 2.7 强依赖 CUDA 库**
   即使是 CPU 用途，`torch/__init__.py` 也会加载 `nvidia/*/lib/*.so`。
   必须把整个 `nvidia/`（3.7G）和 `cusparselt`（227M，**不在 nvidia/ 下，是独立包**）一起传。
   缺 `libcusparseLt.so.0` 就是漏了 cusparselt。

## 验证证据

```
torch: 2.7.1+xpu
xpu available: True
xpu count: 1
device: Intel(R) Arc(TM) B390 GPU
XPU 矩阵乘: (300, 300) ok

ultralytics 8.4.126
```

## gsplat 为什么不行（硬结论，别再试了）

`gsplat/cuda/_backend.py` 第 169 行：

```python
if cuda_toolkit_available():        # 只查 nvcc / CUDA_HOME
    ... 编译 ...
else:
    Console().print("gsplat: No CUDA toolkit found. gsplat will be disabled.")
```

**没有 SYCL 分支。** 第 95 行那个 `_jit_compile(..., with_sycl=None)` 只是为了避免
torch 2.7 新 API 报 TypeError 的兼容处理，**不是真用 SYCL 编译**。

即使装了 `intel-sycl-rt` 让 gsplat 找到 SYCL_HOME（"No CUDA toolkit" 警告会消失），
`cuda_toolkit_available()` 仍返回 False，`_C` 仍是 None，
`rasterization` 照样报 `'NoneType' object has no attribute 'CameraModelType'`。

而且 gsplat 的 kernel 是 CUDA C++ 源码（`.cu`），SYCL 编译器也编不了。

**结论：3DGS 训练只能在 4060。** Intel 的定位是采集 + SfM + CPU 推理 + YOLO XPU 训练。

## 环境

```
~/train_venv   6.5G  (torch 2.7.1+xpu + gsplat 1.5.3 + ultralytics 8.4.126 + 依赖)
~/train_data/peg_insert/  18,900 train / 2,100 val / 3 类(hand/peg/hole)
~/zmax_map/models/yolov8n.pt  6.3M
```

跑任何东西都要带：
```bash
export LD_LIBRARY_PATH=$HOME/train_venv/lib:$LD_LIBRARY_PATH
```
（否则找不到 libpti_view.so.0.10）
