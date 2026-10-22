---
name: intel-xpu-training
description: Use when 在 Intel Arc 上用 torch XPU 训练 YOLO。
---

# Intel Arc XPU 训练 (torch xpu + ultralytics)

适用: Nodka PTL 类工控机 (Core Ultra X7 358H, Arc B390 iGPU, Python 3.12, 无 CUDA、无 oneAPI compiler)。
torch CUDA 版在这里只能跑 CPU; 要真用上 Arc 必须换 **`+xpu` wheel**。
推理走 OpenVINO 是另一条路, 见 `intel-edge-npu-deployment`。

## 链路 (顺序不能乱)
1. **torch 2.7.1+xpu wheel** — 外网单线程下不动 (CDN 边缘缓存不一致: 前 30MB 6.6MB/s, 150-180MB 574B/s)。
   用 **16 段并发 curl + 合并 + 大小校验**, 几十秒拿完 677MB。从有网的机器下好再 rsync 比在边缘机 pip 快得多。
2. **torchvision 0.22.0+xpu** (只 2MB) — **必须装**, 理由见下「NMS」。装前先卸掉 CUDA 版 torchvision。
3. **intel-sycl-rt + intel-pti** — 缺 `libpti_view.so.0.10` 时软链同族 ABI (`intel-pti` 只带 `.so.1`)。
4. **matplotlib 桩** — py3.12 没有可用 cp312 版, 现成的都是 3.11 编的 C 扩展 (报 `_c_internal_utils` / `kiwisolver._cext`)。
   不要一个个下 cp312 依赖, 写个桩顶住 import 即可 (ultralytics 只在画图/字体用)。
5. **数据集用 `rsync -aL`** — 见下「数据集全是坏链」。
6. 训练: `device="xpu"`, `plots=False`。

## 判据: 真在 XPU 上算
训练日志里 **`GPU_mem` 有数** (如 0.297G) 且 loss 三项稳定下降 ⇒ 真在 Arc 上算。
`torch.xpu.is_available()` + `xpu count: 1` 只是前提, 不代表训练用上了。

实测 (yolov8n, 18,900 张, 320px, batch 8):
- 速度 **~4.2 it/s**, 约 9.4 分钟/epoch
- 2 epoch 全流程 1642 秒 (27.4 分钟, 含每 epoch 末验证)
- **mAP50 60.75% / mAP50-95 49.87% / P 99.47% / R 56.24%** (2 epoch ⇒ R 偏低是欠训练, 不是烂模型)
- 同一数据 4060 约 14 it/s ⇒ **Arc 比 4060 慢约 3 倍**, 但完全不占 4060

## 坑 (每个都实测踩过)

### 数据集全是坏链 (最容易白跑几小时)
`ls images/train | wc -l` 显示 18,900, 但训练报 `No labels found in ...cache` 或读图 `Errno 2`,
且每张图都被"跳过"而预处理看起来在跑。
真因: 源目录本身是符号链接, **rsync 不加 `-L` 会把链接本身传过去**, 指向的还是源机器路径。
```bash
find images/train -maxdepth 1 -type f | wc -l   # 0 ⇒ 全是链接
find images/train -maxdepth 1 -type l | wc -l   # = 总数 ⇒ 确认
du -shL 源目录                                  # 看真实体积 (171M 的"数据集"实际 1.9G)
```
修: `rsync -aLz 源/ 目标/`。传完必须复查 `真文件 == 总数` 且 `坏链 == 0`。

### NMS 崩在 Intel IGC 编译器
`IGC: Internal Compiler Error: Termination request sent to the program` +
`RuntimeError: The program was built for 1 devices`。这不是代码错, 是 **Arc 图形编译器在 NMS kernel 上崩**。
修: 装 **torchvision +xpu**。ultralytics `utils/nms.py` 逻辑是「torchvision 可用就走它」,
而 torchvision 的 NMS **没有 XPU kernel** ⇒ 自动落 CPU, 绕过 IGC。
CUDA 版 torchvision 在这里没用 (`operator torchvision::nms does not exist`)。

### 守护进程自己要 import 桩
把训练包进 systemd 长驻进程时, **主进程**必须也 `import mpl_stub`。
ExecStartPre 里的预检查是独立子进程, 不会生效 —— 表现是服务 active 但每代都 `No module named 'matplotlib'`。

### 桩不能做得太万能
`__getattr__` 返回同一个 `_Anything` 会让 `inspect`/`hasattr` 失效而崩。
只补 ultralytics 真用的那几个: `font_manager.findSystemFonts / findfont / FontProperties`、`use`、`Figure`、`close`。
漏 `findSystemFonts` 会卡在 `check_font`。

### cv2 软链要链 `.so` 文件本身
把 `dist-packages/cv2` **目录**软链成 `cv2` 会得到 `cv2.__file__ = None`、只有 7 个属性的空壳。
链 `cv2.cpython-312-x86_64-linux-gnu.so`。headless 缺 `imshow/waitKey` 补桩。

### 别用 `pgrep -f ultralytics` 判进程
会匹配到自己的 grep 命令行, 看到 `RSS 2.4MB / CPU 0%` 的假进程。按脚本名 `pgrep -f run_x.py` 或查端口。

## 自主进化守护 (`zmax_evolve_intel.py`, `:8810`)
每代从 `best.pt` 出发训练 → 固定验证集评估 → **有提升才采纳**。
- 采纳判据: `cand_map50 > best_map50 + margin(0.005)`; **mAP 未测到一律不采纳** (绝不当 0 或放水)
- 台账 `ledger.json`: 每代记权重/指标/耗时/数据集指纹/采纳理由
- **重启必须从台账恢复 `best_map50`**, 否则第一代被当「首个基线」无条件采纳, 哪怕更差
- 恢复代号用 `max(generation)` 而非 `len(entries)` (基线 gen0 占一条), 否则重启跳代
- ultralytics 每 epoch 末都会验证一次挑 best.pt ⇒ 每代耗时 ≈ epoch数 ×(训练+验证), 3 epoch 约 40 分钟

## 相关
- `deploy/INTEL_XPU_SETUP.md` — 打通全过程记录
- `tools/dl_xpu_torch.sh` — 16 段并发下载
- `tools/mpl_stub.py` — matplotlib 桩
- `deploy/systemd/zmax-evolve-intel.service`
