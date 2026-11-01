---
name: intel-edge-npu-deployment
description: Use when 把模型部署到 Intel 边缘机 NPU/Arc 做端侧实时推理。
---

# Intel 边缘机 (NPU / Arc) 部署与端侧实时性实测

适用: Nodka/Intel Panther Lake 类工控机 (Core Ultra X7 358H, `/dev/accel/accel0` NPU + Arc B390 iGPU),
已装 OpenVINO venv (本机实测有 `~/openvino_2025.3/2026.1/2026.2` 多套, 用 `~/openvino_2026.1_env`)。

## 链路 (每步都有数字可核)
1. **本机导出 ONNX** (边缘机不装 torch): 用有 ultralytics+torch 的 venv
   `m.export(format='onnx', imgsz=640, opset=12, simplify=True, dynamic=False)`
2. **scp ONNX 到边缘机**, 用 `ov.convert_model(onnx, input=[1,3,640,640])` + `ov.save_model(..., compress_to_fp16=True)` 转 IR
3. **bench 三档**: NPU / GPU / CPU, 各 warmup 10 + 计时 N 次, 另报 async 队列 4 的吞吐
4. **同口径正确性**: 同一批真图, 本机 torch 出一份 JSON, 端侧 IR 出一份 JSON, 比 类别/框数/IoU/conf 差
   — 不做这一步的"快"不算数 (IoU>0.9 且类别一致才算同口径)
5. **端侧服务**: 零依赖 `ThreadingHTTPServer` + `/health` + `POST /detect`, 响应带 `infer_ms/device/model_sha16`
6. **systemd 常驻**: `User=intel`, `Restart=always`, 日志 append 到工作目录

## 实测 (yolov8n 3.01M 参数, 640×640, 现役 yolo_peg_live)
| 设备 | 单帧中位 | 并发4 ms/帧 | 编译 |
|---|---|---|---|
| NPU | **2.46 ms (407 FPS)** | 1.38 ms (727 FPS) | 1288 ms |
| GPU Arc B390 | 1.50 ms (668 FPS) | 1.12 ms (894 FPS) | 1775 ms |
| CPU (8线程) | 56.3 ms (17.8 FPS) | 56.6 ms | 272 ms |

端侧服务端到端 (JPEG 解码 + letterbox + NPU + NMS): **10.8 ms 中位 = 93 FPS** (LAN 往返另加 ~1 ms)。

## 硬件/算力真相 (2026-10-21 实测, Nodka PTL X7 机)

| 装置 | 型号 | 算力 (INT8, 取自 OpenVINO DEVICE_GOPS) | 备注 |
|---|---|---|---|
| CPU | Intel Core Ultra X7 358H | — (16 线程, 4.8/4.9 GHz) | YOLO 67.6 ms/帧 |
| iGPU | Intel Arc B390 (xe 驱动, arch v30.0.4) | **122.9 TOPS** | GPU 2.22 ms/帧 |
| NPU | Intel AI Boost (arch 5010, intel_vpu) | **50.4 TOPS** | NPU 4.74 ms/帧 |

同一份 IR (`ir/yolo_peg_live.xml`, 640×640) 三设备实测中位: **GPU 2.22ms(450fps) > NPU 4.74ms(211fps) >> CPU 67.6ms(14.8fps)**。
⇒ 吞吐优先选 GPU; NPU 的价值是 **不占 iGPU/CPU** (相机+渲染跑在 GPU 上时 NPU 干检测)。
**NPU 空闲不是坏了**: 服务只在收到 /detect 才占设备; `infer.busy=false` + `last_ms` 是上次实测值。

### 设备节点坑 (必记)
- NPU 真实节点是 **`/dev/accel/accel0`** (`/dev/accel/` 是目录), 不是 `/dev/accel0` —— 写错会让 `/health.hw.npu` 永远 `present:false` 而推理其实正常。
- `…/device/driver/module` 是**指向目录的软链**, `open().read()` 会失败 ⇒ 用 `os.path.basename(os.path.realpath(p))` 取驱动名 (xe / intel_vpu)。
- xe 驱动**不提供** `gpu_busy_percent`; 要想看 iGPU 占用只能用 `intel_gpu_top`(本机未装) 或从推理侧数请求, 别在界面上编一个数。
- 磁盘: `/` 1005.9 GB (用 33.5 / 余 921.2); `/boot/efi` 1.1 GB。OpenVINO 2026.1 venv = `/home/intel/openvino_2026.1_env`。

### 多模型/多设备服务接口 (edge_service.py 2026-10-21 起)
```
GET  /health                     → hw{cpu_model,cpu_mhz_now/max,cpu_pct,mem_*,disks[],temp_c,
                                     accel{cpu,gpu{name,arch,tops_int8,driver,in_use},npu{...}}}
GET  /models                     → 目录下所有 *.xml + 已编译过的设备列表
POST /detect?conf=&iou=&device=NPU|GPU|CPU&model=<xml 名>   body=图片原始字节
```
编译缓存按 `(xml 绝对路径, device)`; 共用 **CompiledModel**(线程安全), 每次调用新建 InferRequest —— 不要多个线程共用一个 InferRequest (实测 4 并发 RemoteDisconnected)。
**换模型不用改服务**: 把 IR 丢进 `ir/`, 请求里带 `?model=` 即可; 首次请求多 ~30ms(NPU)/~450ms(GPU) 编译, 之后复用。

### SmolVLA / INTACT 上 Intel 的路线 (尚未实导, 不报假数)
1. 在本机 (有 torch) 把网络包成 `nn.Module` + **固定 shape** → `torch.onnx.export` (视觉 encoder/动作专家可分开导)。
2. IR: 在 Intel 机 `ov.convert_model(onnx) + ov.save_model(..., compress_to_fp16=True)` → 丢进 `ir/`。
3. 跑: `POST /detect?model=<名>&device=GPU` 或单独写一个 bench 脚本 (参照 `edge_probe_devices.py`)。
4. 现实预期: YOLO 类 CNN 适合 NPU; **VLA/JEPA 是 transformer + 多帧窗口, 静态 shape 会很大**, 更适合 iGPU (122.9 TOPS, 共享内存),
   NPU 要看单次编译是否装得下 —— 未实测, 不得先说"能跑"。

## 全模型并行部署 (550C, 2026-10-21 实测落地)

三块板都能跑, 但**权重能不能对上代码**决定能不能转。已落地的是 YOLO + INTACT:

| 模型 | 来源/结构 | 转换 | Intel 上实测 |
|---|---|---|---|
| yolo_peg_live | 已有 IR | 无需转 | NPU 4.74ms / GPU 2.22ms / CPU 67.6ms (单帧 640) |
| intact_enc | external/INTACT-JEPA `jepa.JEPA` + encoder/projector, ckpt 同目录 config.json | strict 323/323 → onnx → IR fp16 | GPU 0.97ms / NPU 2.76ms / CPU 44ms; IR vs torch 8.6e-06 |
| intact_pred | 同上 predictor/pred_proj | 同上 | GPU 1.16ms / NPU 1.36ms |

并行结果 (两设备各 95%+ 占空): NPU=yolo+intact_enc / GPU=intact_pred+intact_enc → **合计 1770 fps**, 温度 62°C, 内存 7%.

### 占空顶满: 每设备多 worker (streams) —— 实测 1773 → 2080 fps

单设备一条 worker 是**同步**循环: 设备算完到下一次提交之间要做 numpy/py 开销 ⇒ 实测占空只能到 ~96%,
模型一多还会掉到 78%。解法不是加模型, 是**加 worker**: `streams=N` (支持非对称 `NPU:GPU` 如 `2:1`).

| 配置 (NPU / GPU 模型) | streams | NPU | GPU | 合计 fps |
|---|---|---|---|---|
| yolo+enc / pred+enc (旧默认) | 1:1 | 543fps 95.9% | 1244fps 95.6% | **1773** |
| yolo+enc+pred / pred+enc | 2:1 | **894fps 96.0%** | **1186fps 95.9%** | **2080** ✅ 在用 |
| yolo+enc+pred / yolo+enc+pred | 2:1 | 887fps 95.3% | 849fps 97.0% | 1737 |
| 同上 | 2:2 | 894fps | 680fps | 1574 |
| 同上 | 4:1 | 844fps | 839fps | 1683 |
| yolo+enc / pred+enc | 2:1 | 523fps 48.5% | 1221fps | 1744 |
| 任意 | +hint=1 (THROUGHPUT 编译) | — | — | **402~717 (崩)** |

定论:
- **NPU 加 stream 收益最大** (507→894 fps, 因为它单帧慢、主机侧空隙占比高); **GPU 加 stream 反而降** (1244→812)。
- **yolo 不要放 GPU**: GPU 跑 yolo 慢 (616fps) 且挤掉 pred/enc ⇒ GPU 全三模型时合计只有 1737。
  最优分工: NPU 背全部三模型 (2 streams), GPU 只背 pred+enc (1 stream)。
- `PERFORMANCE_HINT=THROUGHPUT` **在本机是负优化** (1211→402): 它把请求内部排队, 同步逐帧调用的延迟全暴露。
  留 `hint=1` 开关给异构机型复测, 默认必关。
- duty 必须**按 stream 数归一**再显示 (raw busy/wall 在多 stream 下 >100%, 界面会显示 186% 这种笑话);
  另存 `busy_ratio` 给人看原始值。
- 固化位置 = `zmax-edge-pipeline.service` 的 `EDGE_NPU_MODELS / EDGE_GPU_MODELS / EDGE_STREAMS / EDGE_HINT`
  + guard 的 `start_pipeline()` 透传; **guard 只在“流水线没在跑/计数不涨/报 err”时才重拉**,
  所以改完配置要 `restart zmax-edge` 把旧流水线清掉, 否则 guard 会继续看着上一份 plan 说 OK。
  自愈实测: `POST /pipeline/stop` 后 15~30s guard 自动按 unit 里的配置重新拉起 (同一 streams/模型集)。

### 转换三步 (固定路线, 不要跳)
1. `tools/edge/export_intact.py` / `tools/edge/ov_export_torch.py` → ONNX (静态 shape, opset17)
2. Intel 机: `tools/edge/ov_convert.py` → IR fp16 (`/home/intel/openvino_2026.1_env/bin/python`)
3. `POST /pipeline/start?npu=<模型名,...>&gpu=<...>` (或 `/detect?model=&device=`)

### 坑 (都是实测踩到的)
- **权重与代码对不上就别硬导**: hjepa_zflow_model.pt 与仓库 h_jepa_zflow.py 键名全对、只有 v_enc 卷积核不同 (ckpt 4/3/3 vs 代码 8/4/4) ⇒ 那是另一版代码训练的, 反推 stride 等于猜架构。判据: 先 `diff` state_dict 键+形状, 再 strict load。
- hydra `instantiate(cfg)` 前**不能 pop `_target_`**, 否则实例化出一个 dict 而不是模型。
- 多输入模型 (intact_pred 的 emb/act_emb) 给 OpenVINO **传 list**, 别用 `read_model` 的 Port 当 dict 键 (报 `Unsupported key type: Output`)。
- `partial_shape` 的元素是 `Dimension`, 动态维不能 `int()` → 用 `d.get_length() if d.is_static else 1`。
- 同设备跑多个模型时, **输入张量必须按 (设备,模型) 各建一份**, 共用一份会把第二个模型喂错 shape。
- 判活别用 “进程在不在”: 用 `/pipeline/stats` 的 **计数在涨 + duty + 无 err**, 否则 NPU 挂了但进程活着。

## 主界面要看「Intel 的硬件 + 模型是否在推理」(2026-10-21 落地)

老倪: 「主界面的最下面的指示灯, 当接到 intel 的时候, 能显示 intel 的硬件和模型的是否推理的状态么」

三处收口, 缺一处就看不到:
1. **Intel 侧 `/health` 自报** (`/home/intel/edge_models/edge_service.py`): 新增 `hw`(host/cpu_n/cpu_pct/mem_*/disk_*/temp_c/npu/load1)
   与 `infer`(busy=最近3s有请求 / req_rate_10s / last_req_age_s) 两个块。全走 /proc + /sys + shutil, **零第三方依赖**。
   `cpu_pct` 用两次 /proc/stat 差分, **首次返回 null(不编 0)** ⇒ 第二次调用才有数。
   改完 `sudo systemctl restart zmax-edge` (用户态 systemctl 会报 Interactive authentication required, 必须 sudo), 编译只 ~130ms。
2. **本机到 Intel 的通道**: `zmax-orin-intel-fwd.service` — `ssh -NT -p 22022 -L 127.0.0.1:18800:192.168.23.70:8800 -L 127.0.0.1:18822:192.168.23.70:22 tashan@39.102.211.79`
   (办公室无产线网时唯一入口; 18822 给 ssh 用, 本地 `sshpass -p intel ssh -p 18822 intel@127.0.0.1` 可登录, Intel 的 sudo 免密)。
3. **界面**: `tools/gui/studio.py::probe_intel_edge()` 读 `ZMAX_EDGE_URL`/`127.0.0.1:18800`/`192.168.23.70:8800` 三候选,
   把一颗灯塞进硬件卡的 `m["devices"]`; `tools/gui/hw_widgets.py` 的灯循环补 `setToolTip(d["tip"])`。
   灯色: **busy=蓝(推理中) / ok=绿(在线空闲) / err=灰(未连通)**; 灯面小字 `NPU · 推理中 26.4ms · 42°C`,
   悬停给全量硬件 + 模型 sha + n_req + 速率。`复制参数` 的「设备」行会自动带上它(无需另改)。

验收(实测): 离屏 `QT_QPA_PLATFORM=offscreen` 导入 studio 调 `probe_intel_edge()` → `busy / NPU · 推理中 26.4ms · 42°C`;
`HwVisual.set_data` 后灯带 `['Intel 端侧','本机']`(本机永远最后), tooltip 4 行; 截图 `/tmp/hw_lamp.png`。
改 GUI 必须**重启控制台**才可见: 本机现在是 user unit `systemctl --user restart zmax-studio`(不要裸 nohup, 会话结束会被带走)。

## 坑 (都是实际踩到的)
- **`INFERENCE_NUM_THREADS` 只对 CPU 插件合法**: 传给 NPU/GPU 直接 `[NOT_FOUND] Option 'INFERENCE_NUM_THREADS'` /
  `Check 'it != m_options_map.end()' failed` ⇒ 按设备分支传配置。
- **8400 行纯 Python 后处理吃掉 ~35 ms**, 比 NPU 本身 (2.5 ms) 大 14 倍 ⇒ 端到端假慢到 25 FPS。
  必须 numpy 向量化: `cs=p[:,4:]` → `argmax` → 掩码 → `cv2.dnn.NMSBoxes` (C++)。向量化后 40 ms → 10.8 ms。
- **numpy.float32 进 json 会 TypeError** (`Object of type float32 is not JSON serializable`): 响应里逐个 `float()`。
- lambda 里写 `out = []` 会把形参 `out` (模型输出) 覆盖掉 ⇒ 变量命名避开形参。
- `pkill -f edge_service.py` 在 ssh 远程命令里执行时**会杀掉自己这条 ssh** (命令行含同样字符串) ⇒ 用 `edge_serv[i]ce.py` 括号技巧。
- 边缘机 venv 没有 cv2: `pip install opencv-python-headless` (有网之后) — 注意装到的就是 cv2 5.x。
- 后台起服务不要用 `ssh 'cmd &'` 直推: 用 systemd 单元, 否则 ssh 会话挂着不走 (本机实测 timeout 300s)。

## NPU 编译报 "dense resource buffer ... doesn't match its type 'tensor<4xsi64>'" ⇒ 真因是图里有**动态维**

SAM3 编码器 (1x3x1008x1008 → 1x5184x1024, 894MB fp16 IR) 在 intel NPU 上编译失败, 逐层排除后的结论:

| 尝试 | 结果 |
|---|---|
| 原始 fp16 IR | ❌ `Constant .../Identity_output_0: dense resource buffer '1179648' doesn't match type 'tensor<4xsi64>'` + Level0 `ZE_RESULT_ERROR_INVALID_ARGUMENT` |
| `compress_to_fp16=False` 重存 fp32 | ❌ 同一报错 (不是 fp16 压缩的锅) |
| OpenVINO 2026.4.1 (隔离 venv, 不动现役 2026.1) | ❌ 同一报错 (也不是版本 bug) |
| ONNX 层把 int64 盲降 int32 | ❌ 转换期就挂: `Arguments do not have the same element type (i32 vs i64)` |
| **查图结构** | ✅ 真因: `/enc/backbone/embeddings` 下 3 个节点动态输出 `Tile [?,?,?,?]` → `Slice_1` → `Transpose` (位置编码插值), VPUX 要全静态图 |

**10 秒判据**:
```python
dyn = [n for n in m.get_ordered_ops() if any(o.get_partial_shape().is_dynamic for o in n.outputs())]
print(len(dyn), [(n.get_type_name(), n.get_friendly_name()) for n in dyn[:5]])
```
有动态维 ⇒ 别看那个常量报错, 先把图变静态。修法按代价: ① 导出时固定网格 (1008/14=72) 让位置编码插值变纯常量;
② `onnxsim` 常量折叠后转 IR; ③ encoder 拆两段 (patch-embed conv 上 NPU / transformer blocks 上 GPU)。

**同机 GPU 对照 (同 IR)**: 2026.1 → 266 ms/帧 = 3.75 fps; 2026.4.1 → 438 ms/帧 = 2.28 fps (**反而慢**) ⇒ 端侧留 2026.1。

**边缘机无外网**: `pip install` 直接死 (name resolution failed)。离线装法: 本机
`pip download --no-deps --only-binary=:all: --python-version 3.12 --implementation cp --platform manylinux_2_28_x86_64 -d /tmp/w openvino==<ver>`
+ 单独下 `openvino-telemetry` (它要这个依赖, 不装会报 no matching distribution), scp 过去 `pip install --no-index --no-deps *.whl`;
建 venv 用 `--system-site-packages` 蹭系统 numpy。

## 判据/取证
- `tools/edge/edge_yolo_bench.py` — 三档延迟/吞吐
- `tools/edge/edge_yolo_infer.py` — 端侧 IR 推理出 JSON (手工 letterbox + v8 decode)
- `tools/edge/edge_yolo_ref.py` — 本机 torch 同口径参考
- `tools/edge/edge_service.py` — 端侧服务 (550C 量产口)
