---
name: intel-xpu-yolo-training
description: Use when Intel Arc XPU 上跑 YOLO 训练报错或要自主进化.
version: 1.0.0
author: zmax-agent
license: MIT
metadata:
  hermes:
    tags: [intel, xpu, arc, yolo, ultralytics, autonomous-evolution]
    related_skills: [gpu-training-load-guard, yolo-3d-perception-chain, disk-redline-guard]
---

# Intel XPU YOLO 训练与自主进化

在 Intel Arc 核显（如 B390）上用 torch XPU 跑 ultralytics YOLO 训练，并建立
「训练→评估→择优」的自主进化闭环。**3DGS 不行**（gsplat 无 SYCL 后端），YOLO 可以。

## When to Use

- 要在 Intel 核显/Arc GPU 上跑 YOLO 训练，或在 Intel 上建立自主进化闭环。
- 训练启动后静默死掉 / 卡在预处理 / `No labels found in train.cache`。
- 报 `IGC: Internal Compiler Error` 或 `The program was built for 1 devices`。
- 报 `cannot import name '_c_internal_utils'` / `No module named 'matplotlib'`。
- 要判断训练是真在算还是空转（GPU 占用读不到时）。

## 开工前的三层体检

训练跑不起来时按这个顺序查，别一上来就调参：

```bash
# 1. XPU 真的在?
python -c "import torch; print(torch.__version__, torch.xpu.is_available(), torch.xpu.get_device_name(0))"

# 2. torchvision 能 import? (NMS 靠它绕 IGC 崩溃)
python -c "import torchvision; import torch; print(torchvision.__version__); print(torchvision.ops.nms(torch.tensor([[0.,0.,10.,10.],[1.,1.,9.,9.]]), torch.tensor([0.9,0.8]), 0.5))"

# 3. 数据集是真文件还是坏链 —— 最高频的「训练卡住」真因
find ~/train_data/xxx/images/train -maxdepth 1 -type f | wc -l   # 真文件数
find ~/train_data/xxx/images/train -maxdepth 1 -type l | wc -l   # 软链数
```

**第 3 项最容易漏**：`ls | wc -l` 显示 18,900 张，实际可能是 18,900 个
指向源机器路径的坏符号链接，真文件 0 张。表象是训练启动后静默死掉、
`No labels found in .../train.cache`、或预处理后无任何 epoch 输出。

## 传输数据集必须 `-L`

```bash
rsync -aLz --info=progress2 -e "sshpass -p PW ssh -o StrictHostKeyChecking=no" \
  /src/peg_insert/ user@host:~/train_data/peg_insert/
```

不加 `-L` 会把软链本身传过去，指向的还是源机器路径 ⇒ 目标机器全是坏链。
传完必须验 `-type f` 数量，别只看 `ls | wc -l`。

## matplotlib 用桩，不要硬装

Python 3.12 环境里通常没有 cp312 版 matplotlib；从 py3.11 机器拷过去会报
`cannot import name '_c_internal_utils'` / `_cext`，因为 C 扩展 ABI 不兼容。

写一个最小桩（`tools/mpl_stub.py`）塞进 `sys.path`，只提供 ultralytics
import 期真正用到的东西：

- `matplotlib.font_manager` 的 `findSystemFonts`（**必须返回 `[]`**，不是空模块）
- `pyplot` 的 `close/subplots/savefig/figure/imshow` 全部 no-op
- `use()` / `rcParams`

**桩不能太万能**：用 `__getattr__` 返回通用对象会让 `inspect` 崩溃。
只暴露确定的属性。

**守护进程自己也要 import 桩** —— 在 systemd 服务里单独 `ExecStartPre` 里
import 一次没用，主进程照样在 `get_dataset` 就崩。

## 两个必然踩的坑

### NMS 崩在 Intel IGC 编译器

```
warning: module got recompiled from IR because provided native binary is incompatible
IGC: Internal Compiler Error: Termination request sent to the program
RuntimeError: The program was built for 1 devices
```

`ultralytics/utils/nms.py` 里 `TorchNMS.nms` 的 XPU kernel 会触发 IGC 崩溃。
解法是让 torchvision 可用 —— 它会走 CPU 版 NMS：

```bash
pip install --no-deps --no-index torchvision-0.22.0+xpu-cp312-cp312-linux_x86_64.whl
```

torchvision 的 XPU wheel 只有 2MB。版本必须和 torch 配套（torch 2.7.x ↔ tv 0.22.0）。

### 视觉干扰读不到 GPU 占用

`/sys/class/drm/card0/device/gpu_busy_percent` 在非 root 下读不到、或路径不存在。
**别用 GPU 占用判断是否真在训练**，用 ultralytics 自己的输出：

```
Epoch  GPU_mem  box_loss  cls_loss  dfl_loss
1/3    0.297G    1.793     2.279     1.216
```

`GPU_mem > 0` 且三项 loss 单调下降 ⇒ 真在算。loss 不动就是空转。

## 实测速度参考（Arc B390, 18,900 张）

| 阶段 | 数值 |
|---|---|
| 训练 320px, batch 8 | 4.2~5.9 it/s，约 9 分钟/epoch |
| 训练 640px, batch 8（= 部署口径） | 2.4~2.6 it/s，约 20 分钟/epoch |
| 验证（2,100 张） | 约 4 分钟/次 |
| 2 epoch 完整流程 @320 | 27.4 分钟 |
| 4 epoch 完整流程 @640 | 约 85 分钟/代 |

比 4060 CUDA 慢约 3 倍，但**不占独显**，适合与产线检测并行。

## 自主进化守护

脚本 `tools/zmax_evolve_intel.py`（本技能配套），systemd unit
`deploy/systemd/zmax-evolve-intel.service`，只读端点 `:8810`。

### 四条硬规矩

0. **没有变异就没有搜索。** 训练是确定性的（同超参+同数据顺序+固定 seed）⇒ 从同一 best.pt 出发的每一代
   产出**逐位相同**的 mAP。台账实证：gen8/9/10 的 mAP50 都是 `0.740945867230116`（15 位小数全同），
   这 14 代 "平台期" 是没搜索，不是数据到顶。必须按代采样变异（尺度/旋转/mosaic/HSV/lr/冻结层）并把
   选中的 `mutation` + 完整 kwargs 写进台账。

0b. **`optimizer=auto` 会静默吃掉 lr0。** 日志原文：`optimizer: 'optimizer=auto' found, ignoring 'lr0=0.01' ...
   determining best 'optimizer', 'lr0' and 'momentum' automatically` ⇒ 变异表里的 lr 档位全是空转。
   要 lr 生效必须显式 `optimizer="AdamW"`。同理 `warmup_epochs` 默认 3.0，在 3~4 epoch 的短程里等于整程
   都在 warmup、调度走不到衰减段 ⇒ 短程必须 `warmup_epochs=0.5`。从 best.pt 微调 `lr0` 用 0.002 量级，
   默认 0.01 会把已有能力打散。

0c. **epochs 是最大的那个旋钮，而且 1 就是灾难。** 实测同一数据同一起点：3 epoch → mAP50 0.7381；
   1 epoch @640 → 0.6550（掉 8 个点），而且 1 epoch @640 要 23 min，比 3 epoch @320 还贵。
   平台期要按阶梯加算力（4 → 12 → 20 epoch），不是反复换增广小步微调。

0d. **imgsz 跟部署口径走。** 在役 OpenVINO IR 是 640×640（`grep '<dim>' ir/*.xml` 可核）⇒ 训练/评估用 640，
   别为了省时间降到 320 再拿 mAP 去跟 640 的部署模型比。

1. **采纳判据是「有提升」，不是「不回退」**
   ```python
   if cand_map > best_map + MARGIN:  accepted = True
   elif cand_map is None:            accepted = False   # 未测到绝不采纳
   else:                             accepted = False   # 回滚, 台账写清差多少
   ```

2. **重启必须从台账恢复 `best_map50`**，否则第一代会被当成「首个基线」
   无条件采纳，哪怕比历史最优更差。恢复代号用 `max(e['generation'])`，
   **不能用 `len(entries)`** —— 基线 gen0 不占进化代号，用条数会跳过一代。

3. **每代从 `best.pt` 出发**，不是从预训练权重重来。日志里验
   `model=/path/evolve/best.pt`，错了就是白跑。

### 判活的正确姿势

```bash
curl -s http://127.0.0.1:8810/health
# phase: training gen2 | gen: 2 | best: 0.6491 | acc/rej: 2 0 | mut: aug_scale | streak: 0
```

`phase` 停在 `error` 且 `last_error` 长期不变 ⇒ 看 `traceback` 字段，里面是完整栈。

**别用 `tail`/`grep` 看 evolve.log**：ultralytics 的进度行是一条几十 KB 的单行 `\r` 串，`tail -40` 会把
十几万字符灌进上下文。要看进度只读 `runs/genNNN/results.csv`（每 epoch 一行，四个指标齐全）。

### XPU 掉卡：`xe GT0 job timeout` → `level_zero ... DEVICE_LOST`

长跑时偶发（实测一次发生在训练第 51%、跑了 27 分钟的位置）。`dmesg -T` 会看到
`xe 0000:00:02.0: [drm] GT0: Timedout job ... VM job timed out on non-killed execqueue`，
同一时刻 `zmax-edge`（OpenVINO NPU）也会被连带重启。GPU 会在几十秒内自恢复（`torch.xpu` 矩阵乘可验），
所以**不要重启机器**，做法是训练外层捕获 `device_lost|level_zero` 后同一代重试（90 s 间隔、最多 3 次），
连续失败才记一条失败代 —— 否则一次驱动抖动就把整条进化链拖成 `phase: error`。

## 实测效果

Intel Arc B390 上 YOLOv8n / peg_insert 18,900 张：

| 代 | mAP50 | mAP50-95 | P | R | 结果 |
|---|---|---|---|---|---|
| gen0 (2ep) | 60.75% | 49.87% | 99.47% | 56.24% | 基线 |
| gen1 (3ep) | **64.91%** | **54.85%** | **99.90%** | **57.10%** | 采纳 +4.16 |

四项指标同向上升 ⇒ 真提升，不是拆东墙补西墙。

## 不要做的事

- **别在 Intel 上跑 3DGS**：`gsplat/cuda/_backend.py` 只有 `cuda_toolkit_available()`
  分支，无 SYCL；kernel 是 `.cu`；`/opt/intel/oneapi/` 缺 `compiler/`。封死。
- **别用单线程 pip 下大 wheel**：外网慢且 CDN 边缘缓存不一致，单线程 677MB 要 170 分钟。
  用 16 段并发 curl 分段下载再合并。
- **别链 `dist-packages/cv2` 目录**：cv2 是单文件 `.so`，链目录会得到
  `__file__=None`、只有 7 个属性的空壳。链 `.so` 文件本身。
- **别信 `ls | wc -l` 的图片数量**：验 `-type f`。
