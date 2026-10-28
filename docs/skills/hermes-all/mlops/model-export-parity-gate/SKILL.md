---
name: model-export-parity-gate
description: Use when 把权重导出到别的推理运行时并对账。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [onnx, openvino, tensorrt, export, parity, deployment]
    related_skills: [intel-edge-npu-deployment, same-source-eval-discipline]
---

# 模型导出对账闸 (权重 → 别的推理运行时)

## When to Use
- 要把训练好的模型搬到端侧/另一个运行时 (ONNX / OpenVINO IR / TensorRT) 前。
- 用户问"这个模型能不能在 X 上跑"、要求"全模型都部署"、或声称某个模型已在跑。
- 导出后数字很快但结果可疑 (输出无意义/精度崩) 时, 回头逐闸排查。
- 不适用: 新写训练代码、具体某台机器的服务/硬件/界面部署 (那些归各自的部署技能)。

适用: 把已在别处训练好的模型搬到端侧/另一个运行时 (ONNX / OpenVINO IR / TensorRT) 前的判定与验收。
不适用于"新写训练代码"和"具体某台机器的部署"(硬件节点、服务、界面归各自的部署技能)。

核心原则: **每一步都有可复现的数值对账, 过不了就停下报阻塞, 不要用"应该没问题"往下走。**
把架构对不上的权重硬塞进端侧, 比不部署更糟 —— 它跑得很快, 但输出跟训练时没有语义关系。

## 0. 盘点: 权重在不在、对不对得上代码

```bash
find <model_dir> -name '*.safetensors' -size +5M   # 裁剪/LoRA 归档常只剩 config.json + *_processor
python - <<'EOF'
import torch
m = ModelClass(); own = m.state_dict()
sd = torch.load(ckpt, map_location='cpu', weights_only=False); sd = sd.get('model', sd)
print('ckpt独有', [k for k in sd if k not in own][:6])
print('代码独有', [k for k in own if k not in sd][:6])
print('形状不一致', [(k, tuple(sd[k].shape), tuple(own[k].shape)) for k in sd if k in own and sd[k].shape != own[k].shape])
EOF
```

闸门: `load_state_dict(sd, strict=True)` 必须通过。

- 键名 100% 相同、只有个别 conv 形状不同 ⇒ 权重来自**另一版代码**。反推 stride/kernel 等于改架构,
  端侧跑出来的东西没有任何语义保证 —— 停下来要原始训练脚本或那台机器上的文件, 不要造一个"能 strict load 的版本"蒙过去。
- 同名权重文件偏小 (如 84 MB 的两个 epoch) ⇒ 先确认它是不是你要的那个模型。
- 权重根本不在 (只有 config.json + 归一化 processor) ⇒ 报"缺权重", 不要拿基座权重冒充适配后的模型。

## 0.5 认在役指针: 导的那一份必须就是线上在跑的那一份

“这个目录里的 ckpt”经常不止一份: 在役指针是软链，同目录里还躺着训练时存下的每个 epoch。
默认抓“最大的/最新的那个文件”就会导出一份 **同一次 run、晚一个 epoch** 的权重 —— 数全对、性能一样，
但与在役不同源，而交付时被问“这跑的是哪份权重 / 是你转的么”就答不上来。

```bash
readlink -f models/checkpoints/<在役名>/weights.pt        # → 真的那个 epoch 文件
sha256sum "$(readlink -f .../weights.pt)" | cut -c1-12   # 与导出报告里的 ckpt 对比
```

- `--ckpt` 一律写 **`readlink -f` 解出来的绝对路径**，不要写目录、不要写“最大 epoch”。
- 导出报告（`*_export.json`）必须带 `ckpt` 字段；跑完把那个字段拿出来与在役指针 sha 前 12 位比。
- 已有权重（没转过的，如 YOLO `.pt`）也照这条比: 端侧那份 `.pt` 与在役软链实体 `sha256sum` 逐字节一致才算同源。
- 不一致就在交付里**明写差在哪**（同 run 晚一 epoch / 另一 run），并给一条重导命令，不要含糊成“已对齐”。

## 1. 配置唯一依据: 用训练时那一份

用 **ckpt 同目录的 `config.json`** (那次跑实际用的), 不要用仓库里"看起来最像"的 yaml。
hydra 工厂时 **不能 pop `_target_`** —— `instantiate` 会返回一个 dict, 症状是随后 `state_dict` 报
`Missing key state_dict` (object_type=dict)。

## 2. 导 ONNX: 只导推理需要的子图

- 导出环境必须装 `onnx` (torch.onnx 末尾会调 onnx proto), 否则收尾才报 `Module onnx is not installed!`。
  uv 建的 venv 常没有 pip: `uv pip install --python <venv>/bin/python onnx onnxruntime`。
- **静态 shape** (dynamic=False) 是端侧编译的前提; 时序模型拆成"每帧那块"和"要动作才跑的那块"分别导。
- 导完立刻 torch vs onnxruntime 对账 (同一批随机输入, `max|Δ| ≤ 1e-4`), 不过就退出非 0, 别把这步留到后面。

## 3. 传文件: 慢链路必须验完整性

大文件经 SSH 转发/弱网会**静默截断** (实测 46.5 MB 落到 36.0 MB 不报错), 下游转换器随后抛一句
与文件无关的错 (OpenVINO `core.cpp:85`) —— 会把时间全花在错误的地方。
上传放后台, 传完两侧对 `stat -c %s` + `md5sum`, 一致才继续。

**GB 级 IR 过慢隧道 (实测 894 MB / ~0.4 MB/s)**: `scp` 与 `tar|ssh` 都会在中途断 (28 MB、320 MB 各断一次)。
改用 `rsync --append-verify` 循环续传 (断了几轮就从断点接), 收尾比 **sha256** 而不是大小:
```bash
for r in 1 2 3 4 5; do
  rsync -e "ssh -J <jump>" -P --append-verify big.xml.bin <host>:<dst>/ && break; sleep 5
done
sha256sum big.xml.bin; ssh <host> sha256sum <dst>/big.xml.bin   # 两侧必须相同
```
大小相同但 sha 不同 = 中途写过又续接, 直接重传那一段, 别信 `--append-verify` 的单侧输出。

## 4. 转 IR / 目标运行时 + 第二次对账

```python
import openvino as ov
m = ov.Core().read_model(onnx_path)
ov.save_model(m, xml_path, compress_to_fp16=True)     # 25.4 MB onnx → 0.8 MB fp16 IR
```

拿步骤 2 存的 `npz` (随机输入 + torch 输出) 在目标运行时跑同一输入, 再比一次 max|Δ|:
ONNX 过关不代表 IR 过关, fp16 压缩会引入新误差 (实测 8.6e-06, 可接受; 同一闸门判)。

## 5. 报数口径 (会被追着问)

- 少样本 bench 与稳态差一倍是正常的: 20 次采样的中位含首次分配摊销 (4.74 ms), 跑几万次后 1.8–2.1 ms。
  两个数都标明口径, 不能拿一次采样代表稳定吞吐。
- 声称"算力吃满"必须给: 占空比 (= 真在算的累计时间 / 墙钟) + 连续时长 + 累计推理次数 + 温度/内存。
  请求数、单点 FPS 截图都不算证据。
- 端到端 ≠ 纯推理: 预处理/后处理/传输单列, 否则会把 Python 后处理的锅算到加速器头上。

## 6. 多输入 / 多设备模型的喂入坑

- 多输入模型给推理 API **传 list** (按端口顺序); 用 `read_model` 的 Port 对象当 dict 键会被拒。
- 形状对象 (`partial_shape` 元素) 是 `Dimension`, 动态维 `int()` 会 TypeError → `d.get_length() if d.is_static else 1`。
- 一台设备轮转多个模型时, 输入张量必须**按 (设备, 模型) 各建一份**; 共用一份会喂错 shape,
  症状是计数照涨但 `err` 一直有值、占空只有个位数。
- 同一份 CompiledModel 可跨线程共用, 但**不要共用 InferRequest**。

## 7. 目标设备**编译期**拒绝 ≠ 算力不够: 先读诊断点名的那个节点

同一个 IR 在不同后端上的命运可以完全不同 —— 一个设备编译不过, 并不意味着 IR 本身有问题:

- 判据顺序: **先逐设备试编译** (`scripts/bench_ir_devices.py`), 再动图。GPU/CPU 能编译 ⇒ IR 有效,
  被拒的是该设备的编译器限制; 三个都拒 ⇒ 回头查导出。
- 实测 (SAM3 编码器, 1008×1008, fp16 IR 894 MB): GPU 编译 3.5 s → **266 ms/帧 (3.75 fps)**,
  CPU 23308 ms/帧 (不可用), NPU 编译直接失败。同一份模型在 4060 上 torch fp16 是 372 ms/帧
  ⇒ “端侧能跑”必须指名**哪块设备 + 多少 ms**, 否则等于没说。
- NPU (vpux) 的拒绝长这样: `Size of dense resource buffer '1179648' in 'baseContent' doesn't match
  its type 'tensor<4xsi64>'`, 点名 `.../Identity_output_0` 这个 Constant, 最后落到 Level0
  `ZE_RESULT_ERROR_INVALID_ARGUMENT`。**这条报错是假线索**: 实测 fp32 重存、换 OpenVINO 版本
  (2026.1 → 2026.4.1)、ONNX 层把 int64 盲降 int32 (= 转换期 `Arguments do not have the same element type`)
  三条都同报, i64 常量本身不是原因。
- **真因: 图里有动态维节点** —— VPUX 只吃全静态图。10 秒判据:
  ```python
  dyn = [n for n in m.get_ordered_ops() if any(o.get_partial_shape().is_dynamic for o in n.outputs())]
  print(len(dyn), [(n.get_type_name(), n.get_friendly_name()) for n in dyn[:5]])
  ```
  实测模型 (SAM3 ViT 编码器) 只有 3 个动态节点, 全在 `.../embeddings` 下 `Tile → Slice → Transpose`
  (位置编码插值), 其余全静态。有动态维就先固化, 别去调编译参数、别去降精度、别怪显存。
  固化做法 (导出侧 monkeypatch tiling 成常量) + 三项校验 + 远端长编译纪律: `references/static-graph-export.md`。
- **别用字符串比较找 i64 常量**: `str(node.get_output_element_type(0)) == "<Type: 'i64'>"` 会返回 0 条
  (实测编译器点名了 i64, 扫出来却是 0 条) ⇒ 用 `et == ov.Type.i64` / `et.get_type_name() == "i64"`,
  否则你会得出“没有 i64 常量”的错误结论, 然后去改别处。
- **OpenVINO 2026.1 没有 `openvino.runtime`**: 老脚本里的 `import openvino.runtime.opset13` /
  `openvino.runtime.passes` 直接 `ModuleNotFoundError` ⇒ 用顶层 `openvino.*` (opset 走 `openvino.opset13`)。
- 在**已有服务占着加速器**的机器上量: 先停服务/流水线再测, 量完恢复并回读占空 (否则量到的是争抢后的数,
  而且可能把线上服务留在停用状态)。

## 7.5 改了图之后怎么证明语义没变: 比**误差分布**, 不比单个数

固化/改造图 (常量折叠、去掉动态维、换导出分支) 后要回答"还是同一个模型么", 别只看一个 max|Δ|:
拿**同一份输入 + 同一份 torch 参考**, 把**旧导出**与**新导出**各执行一遍, 逐项比分布:

```python
for tag, ir in (("旧", OLD_IR), ("新", NEW_IR)):
    got = np.asarray(core.compile_model(ir, DEV)({0: x})[cm.output(0)])
    d = np.abs(got - ref)
    print(tag, "max %.3e p99.9 %.3e mean %.3e >0.1 占比 %.4f%%  |rel| 中位 %.2e" % (
        d.max(), np.percentile(d, 99.9), d.mean(), 100*(d > 0.1).mean(), np.median(d/np.maximum(abs(ref),1e-6))))
```

判读:
- **新旧逐项相同** (max/mean/p99.9/占比完全一致) ⇒ 图改动**没改语义**; 那么剩下的 max|Δ| 是**量化噪声**, 归因给 fp16, 不归给这次的改动。
- 只看 max|Δ| 会误判: 实测同一对导出的 max|Δ|=12.03 却 mean=5.3e-3、p99=3.0e-2、|rel| 中位 6.2e-3、元素>0.1 只占 0.06% ⇒ 是极少数离群元素, 不是模型坏了。
- 报给用户时把 "vs torch: max/mean/p99" 一起给, 单写一个 max|Δ| 会被追问到无法收场。

## 7.6 编译通过 ≠ 该设备可用: 用 "ms/帧 + 占比" 定设备

同一份静态 IR 逐设备实测 (SAM3 ViT 编码器 1×3×1008×1008 → 1×5184×1024):

| 设备 | 编译 | 单帧 | 结论 |
|---|---|---|---|
| Arc B390 iGPU | 1.8 s | **266 ms (3.75 fps)** | 端侧就用它 |
| NPU (vpux) | **1641 s (27 min)** | 2072 ms (0.48 fps) | 编译得动, 但慢 7.8×, 不可用 |
| CPU | 秒级 | 23308 ms | 不可用 |

规则: **大 ViT / 长序列 (5k token × 1k 维、27 层) 走 iGPU; NPU 留给小 CNN 与小 encoder**。
NPU 编译成功只证明"图合法", 不证明"该放这里"; 长序列 attention 在 50 TOPS NPU 上会被调度开销吃掉。
交付时必须同时报**编译耗时 + ms/帧 + 另一设备的对照**, 否则"上了 NPU"等于没说。

用户问“跑的是什么模型 / 需要转格式么 / 是你转的么”时，这四项一次性给齐（少一项就是没交付）:
1. **源权重** + 它与在役指针是否同一份（sha 前 12 位并列）；不是同一份就说差在哪。
2. **格式与体积**（`.pt` → `.onnx` → IR `.xml`+`.bin`，bin 存 fp16、网络 IO 仍 fp32；
   并说明“运行时不转，只在换权重/上新模型时转一次”）。
3. **同口径 parity**（torch vs ONNX vs 目标运行时 的 max|Δ|，或分类模型用同批真图的类别/框数/IoU）。
4. **哪些模型没转、为什么**（VLA/SAM3 无 IR、走 API 的、在别的机器上的）；不许用“全模型都部署了”一句话盖过去。

哪块过了闸、哪块停在闸前、阻塞点一条判据 (缺权重 / 形状不一致 / 对账超阈值), 以及要用户补什么才能继续。
不要用"已部署"包住未过闸的部分。
