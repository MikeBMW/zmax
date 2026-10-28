---
name: open-vocab-segmentation-sam3
description: Use when 给状态空间加开放词汇分割(SAM3)或接场景叠加.
version: 1.0.0
author: 静静 (Hermes Agent)
license: Apache-2.0
metadata:
  hermes:
    tags: [segmentation, sam3, perception, overlay, l2, zmax]
    related_skills: [sim-real-scene-overlay, zmax-state-space-architecture, live-camera-detector-adaptation]
---

# 开放词汇分割 (SAM3) 接进状态空间

## When to Use
- 要给状态空间/机器人工位加**开放词汇分割**（"分割 anything"），参考 SAM3。
- 要把分割掩膜接进**场景叠加**（轮廓+半透明填充、页面点选/删除）或自动标注。
- 已接了 SAM3 但**出 0 实例 / 形状报错 / 推理崩**（先看下面“三个实测坑”）。
- 要判断“权重到底对不对”（meta 设备逐张量比形状，别靠重下）。

## 分层与落点 (老倪口径, 别越层)
- **能力落 L2**(感知原语): 一帧 + 概念提示词(文本/框) → 该概念**所有实例掩膜**(像素级)+框+分数。与 L2-A01 YOLO 同级, 差别 = 掩膜不是框 / 开放词汇不是固定类。
- **意图落 L5**: 概念短语由 VLM/人/工单给 —— 分割件**不自造概念**。不进 L3(不产动作)、不进 L4(不预测不规划)。
- **代码位置**: 算法内核 `src/lerobot/policies/<模型名>/`(与 `policies/yolo_3d` 同层级 —— 老倪纠正过: 别把模型算法写进 tools/); `tools/` 只放**调用方**(CLI/常驻服务/写规格/取证图)。
- 接入四件套: registry `_reg(key, [关键字], doc, fn)` + `_EXTERNAL_LOC[key]=(路径, 行号, "def xxx")`(源码视图指向**类内真推理**, 不是三行转发壳) + 画布节点(进对应 row_bg 行带) + capability_levels 一条能力。

## UI 显示: 模型引擎里 SAM3 摆在哪 (2026-10-14 老倪: 「在模型引擎里要增加 SAM3, 位置 L2 对不? 你来设计 UI 显示」)

**摆法 = 在役四层下面一行「🔎 L2 · 候选」(灰 = 未在役)**, 不是新层、更不搬 L5。在役行=绿/红(在役/异常),
候选行=`C_YELLOW` 的层标签 + 其余单元格压 `C_GRAY`; 一眼分清"在跑的"和"候选的"。

**唯一依据唯一 (三处必须同一个函数算)**: `tools/model_config_matrix.py::candidate_rows(models, st_models, layers)`
— 窗口 `tools/gui/model_engine_window.py::_rows()` 追加候选行、主界面配置通道「🔎 候选」组、配置中心模型配置域
都调它。规则: 名字压缩 `_cmpp`; **判据取 8796 `/status/all` 的 `note_short`**, 引擎没给备注就如实写
「产物未评估(尚无 A/B 判据)」—— **不许自己编"为什么没切"**。候选行 tooltip 必带候选清单 + 完整权重路径 +
候选产物数 + 最近训练; 单元格双击可复制路径。

**列宽红线 = 不截断(ElideNone)**: 显示串要**按像素预算**裁 (`_wpx`: CJK≈18px, ASCII≈9px), 放不下收成 ` +k`
(全清单进 tooltip), 不用省略号糊。实测踩过两处硬切: ① 候选版本串两个版本拼一起 297px > 版本列 278px;
② 层列只 56px 放不下 `🔎 L2 · 候选`。现列宽 `(132, 340, 278, 76, 78, 160, 180)` + 最后一列 Stretch,
且**判据要用真 8796 状态再喂一遍**(用空 stub 喂 ⇒ 版本/判据列都是 `—` ⇒ 越列宽检不出来 = 假绿)。

**判据**: `tools/verify_model_engine_unified.py` ⑬(L2 候选行显 SAM3) · ⑬b(带未切在役判据) ·
⑬c(候选权重路径存在) · ⑬d(真状态喂入不越列宽) · ⑭(窗口候选路径 == 配置通道「候选权重路径」同源同值);
面板自带 `model_engine_window.py --selftest` (行数=4+候选数/列宽余量≥24px/路径不截断)。

**命令通道坑 (能白等一整轮)**: 要在控制台外部弹这个窗口, `echo model_engine > /tmp/zmax_nav_cmd`。
但 `open_model_engine_window` 定义在 **`TrainingModule`(页面)** 上, 不在 `StudioMainWindow` 上 ——
在 `_poll_nav_cmd` 里写 `self.open_model_engine_window` = AttributeError 被 except 吞掉、命令文件已被删、
**什么反应都没有**。正确写法: 遍历 `self.stack` 找 `hasattr(w, "open_model_engine_window")` 的承载页再调。

**两处界面“保持一致”是硬约束，不是口头语** (老倪 2026-10-14: 「你单独打开的模型引擎窗口，与控制台功能区模型引擎标签打开的界面，要保持一致」):
同一个面板类**不够** —— 未列（权重路径）是 Stretch ⇒ 表宽跟随父容器 ⇒ 同一行在两处被裁的位置不同。实测: 弹窗 1900 宽时该列 622px、窄容器 1400 只剩 100px、而**功能区页面会把表撑到 2497px（路径列 1253px，全不裁）** = 用户看到的"两处显示两个样"。
- 口径: 面板 `setFixedWidth(设计宽)`（**Fixed 不是 SetMinimum**——minimum 挡不住页面把它撑大），页面侧不够宽就在**页面级 QScrollArea 里横滚**（先确认父链真有 QScrollArea 且横滚 max>0，否则右列永远看不见）。
- 窗口高度也按**内容**定 (`adjustSize()` + `resize(宽, panel.sizeHint().height())`): 窗口比面板高时多出的高度会把按钮行拉开/居中，与页面排布对不上（实测 660 高时抓图逐像素差 20%，差异全在表下那一条）。
- **比对方法（别拿 OCR 锚点凑）**: 用面板自己 `panel.grab()` 抓图，用 `tb.geometry()` 对齐**表格区**逐像素比（面板表头带 GPU 实时读数，两处各取一次天然不同，不比）。页面那个面板 `poll=True`，抓图前必须停它的轮询（`_t/_lt/_fetcher.stop()`），否则它自己刷成实时数据再抓 = 比两份不同数据。
- 判据: `tools/verify_model_engine_same_render.py` —— 窗口实例 vs **真*功能区页面实例** (`studio.TrainingModule().me_panel`) 逐列/逐格/字体/按钮一致 + 窄容器不变形 + 表格区逐像素差异 <0.5% (实测 0.000% / 0 px)。该脚本实例化页面会起 poll 线程，结尾必须 `os._exit()` 绕开 Qt 析构（否则 dump core）。

## 输出三个去向 + 「悬着」的诊断 (2026-10-14 老倪: 「SAM3 放 L5? 输出给融合定位建图合理么?」)

诊断: 老倪感觉"SAM3 悬着"——**它是对的, 但真因不在画布线上**。🖼 分割节点把"掩膜级 3D"写进
`_YOLO_CACHE['mask3d']`, 而全仓只有一个 `tools/` 取证脚本读它 ⇒ **算完就躺在缓存里, 零下游消费者**。
通用判据: `search_files 'mask3d|seg_masks'` 数消费者; 只有 tools/ 下的 ⇒ 悬着。

三个去向 (都在在役链路上):
1. **融合定位建图** (`📡 sssensor`, `node_ss_s1`): 读 `mask3d` 作独立观测入 `_SS_STATE['seg_mask3d']`
   + 与框法(39D 光模块段)**交叉校验**(偏差 mm 入状态); 掩膜过期(>3s)一律当没有。
   要真正改写状态向量必须显式开闸 `ZMAX_FUSION_SEG=1` (默认一个字段不动 —— 未证明提升不进默认档)。
2. **当 L5 大模型的输入选项**: 画布线 `ss_seg.out2 → n_dsvl.in4`(🧿DeepSeek-V4-Flash, in4 是空闲口) +
   代码在 `_vlm_ctx()` 里往 ctx 加 `seg`(实例数/类别/面积/IoU/掩膜 3D base 坐标) —— **两条都要有**:
   只画线不改 ctx = 装饰线; 只改 ctx 不画线 = 老倪在画布上看不见。
3. **场景叠加** (`origin='seg'` 规格): 见下文"集成到场景叠加/绑帧"。

层归属结论 (老倪提议"把 SAM3 挪到 L5"): **不挪**。分割是感知原语 ⇒ 能力留 L2(与 YOLO 同级),
L5 只给"要用什么概念"+把分割结果当**输入**。搬到 L5 的两个真损失: L2 感知链少掉开放词汇这一路;
L5 变成"产像素原语的层"(以后每加一个视觉能力都往 L5 堆)。想"一眼看到 L5 有这个输入选项"就接线 + 标签,
别搬节点 (搬节点 = 反向线 + 重叠断言, 是画布变乱的主因)。

判据 (已挂 `tools/run_gui_verifiers.sh`): `verify_seg_into_fusion.py` 11 条(消费+零回退+开闸+上下文) ·
`verify_seg_dsvl_canvas_link.py` 5 条(渲染级: 按**节点名**在 `SimLinkItem` 里找那条线, id 会被重编)。

## 权重获取 (官方 gated 时)
- `facebook/sam3` 在 HF 是 **gated(需审批)**, 匿名取 config.json 直接 401。走**未门禁镜像的逐文件复制**(键前缀 `detector_model.*`/`tracker_model.*` = transformers 命名)。落数据盘, **不入 git**(3.4GB)。
- 下载: 单连接 1.3~1.7MB/s; 分段并发要配**看门狗**(每 45s 查进度, 僵死就杀重连续传)。⚠️ 中途改分段数会让各段起点错位产生空洞 —— **续传必须段数一致**, 换段数先删 `.parts`。
- 加载一律 `local_files_only=True`, 并落 `sha256`。

## 三个实测坑 (各能浪费一整轮)
1. **多概念一次喂会崩**: `Sam3Processor(text=[c1,c2,c3])` → `Sam3Attention.forward` 里 `view(1,32,8,32)` 收到 24576 个元素(多概念提示特征按 3×256 拼起来, 实现却按单概念 heads×head_dim 切) ⇒ **一个概念一次前向**, 逐概念跑再合并(0.4s/概念)。
2. **中文概念 = 0 实例**: SAM3 文本塔是 **CLIP(英文)**。`光模块`→0, `green connector`→6。概念词必须英文。
   **英文词也要现场试** —— 同一帧实测: `green connector` 6 个 / `slot` 13 / `metal pin` 2 / `connector` 4(分数弱),
   而 `socket`/`port`/`receptacle`/`gripper`/`robot gripper`/`optical module` **全部 0**。默认概念只放**实测有命中**的词。
2b. **“掩膜边上还有残留物色”先算全局**: 该色全图像素数 vs 掩膜盖住比例 —— 实测全图绿 6854px、掩膜只盖 23.5%,
   残留“绿边”主体是**绿色台面/板子本身**, 不是漏掉的目标像素。`mask_threshold` 0.5→0.2 只多盖 16%, 默认不值得改。
2c. **标签会叠成一团**: 多实例小目标时逐个画标签会互相压住(目检直接报“不可读”) ⇒ 标签按 (y,x) 排序
   **逐个找空位**(上→更上→下→右→顶部→右缘)+ **深色底片**; 画面必须一眼可信(老倪会把画面当结果)。
3. **别把"形状报错"当成"权重不对, 重下"**: 判据是**用 meta 设备按本机 config 起空模型, 与 safetensors 头部逐张量比形状**(去掉 `base_model_prefix` 如 `detector_model.` 再比)。实测 1468 个可比对张量形状不符 **0 处** ⇒ 权重是对的, 崩的是入参。

## 微调通道 (框提示式) —— 4060 8GB 实测口径 (2026-10-01)
仓库**没有任何 SAM3 训练脚本**; 训练内核 = `policies/sam3_seg/finetune.py` + `lora_inject.py`, 调用方 = `tools/sam3_finetune.py` (子命令 `masks`/`train`/`verify`/`eval`)。

**显存账 (1008px, bf16, 单卡 4060 8GB)** —— 视觉塔是瓶颈, 先量再定:
- 冻结视觉塔+文本塔, 只训 4 个头(geometry/detr_encoder/detr_decoder/mask_decoder = 31.43M): fwd+bwd 峰值 **2.98GB**。
- LoRA 注**最后 N 个** ViT block (反向只留 LoRA block **之后**的激活): N=4→4.12GB, **N=8→4.91GB (推荐)**, N=16→6.51GB, N=32→**OOM**。
  `Sam3ViTModel.supports_gradient_checkpointing = False` (没有原生梯度检查点), 别指望它省显存。
- 训练时**必须先卸掉 8796 分割服务**: `sudo systemctl stop sam3-seg` (它常驻 2.3GB, 不卸就撞显存红线), 训完 `start` 回来 (服务是 `--lazy`, 起来不占显存, 健康检查 `loaded:false`)。

**四个必踩的坑** (每个都能静默毁掉一轮):
1. **注入前缀不能带前导点**: `named_modules()` 的名字是 `vision_encoder.backbone.layers.0.attention.q_proj`(无前导点),
   用 `.vision_encoder.backbone.layers.` 去 `in` 匹配 ⇒ **命中 0 个且不报错** ⇒ 一个适配器都没注入, 日志照常"训练"。
   判据: 注入后立刻断言 `n_inject > 0`, 并把数量打进日志。
2. **注入在 `.to('cuda')` 之后做 ⇒ 新参数默认落 CPU** ⇒ 前向抛 cuda/cpu 混算。新参数必须显式 `device=base.weight.device`。
3. **`input_boxes` 是 `[batch, n_box, 4]` 且归一化 `(cx,cy,w,h)`** (processor 自动做 xyxy→cxcywh): 自己拼张量少一个 batch 维 ⇒ `geometry_encoder` 里 `view(batch_size, num_boxes, hidden)` 报 `shape '[1, 4, 256]' invalid for input of size 256`。
4. **forward 不返回 `loss`** (只有 pred_masks/pred_boxes/pred_logits/presence_logits) ⇒ 损失得自己搭。训练可直接吃 `vision_embeds=` (可把视觉塔拆出去), 但**必须给 text 或 box 之一**(两者都缺会 `ValueError`)。

**输出口径**: `pred_masks` = `[B, 200, 288, 288]` (不是原图尺寸), `pred_boxes` = `[B,200,4]` 归一化 xyxy, `pred_logits`/`presence_logits` 走 text 点积 + presence token。

**监督从哪来 (数据只有检测框、没有掩膜时)**:
- **框提示能分出东西** —— 修正本文前面"概念常 0 实例"的印象: 那是**文本**概念的问题; **框提示**在真机帧上 58/58 全出掩膜
  (与 GT 框 IoU 中位 0.62 / 最大 0.91), 一条都不用回退。所以"框提示式微调"在这台机器上是可落地的路线。
- 掩膜目标 = 冻结基座 + **同一框提示**产出的掩膜 (教师伪标签, 落 PNG 288×288, 选与 GT 框 IoU 最高的那个 query,
  不是"分数最高"的)。**报告里必须写作"教师伪标签", 不许说成人工掩膜标注。**
- 真标注监督的那一路: 文本提示(类名英文) → 框, 用 Hungarian 匹配 200 个 query 到 GT 框, 监督 L1+GIoU+cls+presence。那一路是非退化的。
- ⚠️ **退化的陷阱**: 提示框=目标框、学生也是同一模型输出 ⇒ 首步 mask BCE 就 0.005 (几乎零损失)。
  要给出非退化信号, 训练时**扰动图像(光度)+ 抖动提示框**(目标仍是精确框下的教师掩膜) —— 就是"框不准也要分出来"。

**评估口径的铁律**: 掩膜 IoU 若以**教师伪标签**为对照方, 那**基座自己是上界**(它=教师), 蒸馏只能逼近、不可能超过。
只看这一个数会把"正常的逼近"误读成"LoRA 无效/变差"。要看真收益: ①抖动静默扫描 (抖动加大时谁衰减更慢) ②单看**用真标注监督的**那一路(框 IoU)。
且 val 只有 5 帧/5 query 时, 同一配置换一个抖动种子, 基座 IoU 就在 0.696~0.762 之间跳 ⇒ 单格 Δ±0.05~0.09 全是噪声, 不许当结论。

**已知死区 (登记, 别当故障)**: `mask_decoder` 有 6 个参数 `grad is None` —— `pixel_decoder.conv_layers.2.*` / `norms.2.*` (最深一级上采样被 instance_projection 绕过) 与 `semantic_projection.*` (semantic_seg 不进损失)。其余 4 个头逐模块都有非零梯度。

## 服务侧必踩的 dtype 坑 (框提示路径整条 500, 2026-10-01 实测)
`segmenter.segment()` 里用 `getattr(torch, self.dtype_name)` 转 dtype —— **`torch.bf16` 这个属性不存在**
⇒ 抛异常被 `except` 吞掉 ⇒ 处理器给的 **float32** 输入原样送上卡 ⇒ bf16 模型报
`mat1 and mat2 must have the same dtype` ⇒ `POST /seg` 只要带 `boxes` 就 500 (纯文本提示不崩, 所以不测框就看不出来)。
改法: 显式映射表 `{"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[self.dtype_name]`,
与训练侧 `finetune.build_inputs` 同口径。**验收判据: POST /seg 带 boxes 必须 200 且 count≥1** (只测文本提示会漏掉这条)。

## 适配器可选接入在役服务 (默认关)
- 开关: `ZMAX_SAM3_ADAPTER=<目录|.safetensors>` 或 `--adapter`; **两者都不给 = 纯基座**。服务是 `--lazy`,
  开关在**首次 /seg 触发加载**时读取 ⇒ 常驻服务起来时显存仍为 0。
- 加载器 `lora_inject.load_lora_adapter(model, adapter, targets, prefix_filter, r, alpha)`: 注入 + 逐张量
  `copy_`, **键不匹配/文件混入 `.base.` 键直接抛错** (不许静默退化成纯基座, 那会让"接了适配器"成为假象),
  返回 sha256/张量数/非零 B 数供 /health 对账。`n_inj==0` 但模型已有 lora 参数 = **模型本身就是训练装配的**, 直接加载即可。
- ⚠️ **`prefix_filter` 只能给视觉塔**: 训练口径是"视觉塔最后 N 个 block + 文本塔**全层**"。把 `i>=32-N`
  也套到 `text_encoder...layers.` 上 ⇒ 文本塔 24 层 (索引 0..23) 全部被跳过 ⇒ 少注入 96 个 Linear ⇒
  适配器 192 个键对不上直接抛错。文本塔 96 + 视觉塔 32 = 128 个 Linear / 256 张量才是对的。
- 显存账 (4060 8GB, 实测): 纯基座 alloc 1.79GB / **前向峰值 2.10GB**; 加适配器 1.80GB / **2.11GB**
  (适配器 8.4MB fp32 + 适配器 matmul 激活 ⇒ 增量 ~0.01GB)。默认关不是显存原因, 是产品口径。

## A/B 判据 ("有没有提升"怎么证, 别拿单次数字当结论)
脚本 `tools/sam3_ab_multiseed.py` (判据**先定后跑**硬编码在 docstring/输出 JSON 里)。方法要点:
- **K 折 × S seed**: 3 折会让**全部 50 帧各被留出一次** (留出帧不参与该折训练) × 3 种子 × 2 抖动档 × 3 评估抖动种子。
- **配对单位 = (帧, GT 框)**, 不是 query 下标 —— 基座与适配器 Hungarian 匹配可能落在不同 query 上。
- **两套指标分开报, 口径预先固定**: 框 IoU 对**真标注 GT 框** (基座**不是**上界, 唯一可能真提升的一路);
  掩膜 IoU 对**教师伪标签** (= 冻结基座自己的输出) ⇒ **基座在该指标上是上界**, 只能用来判"一致性有没有被弄坏"。
- **平凡基线合法性自证**: 训练口径模型 (注入 LoRA, B 零初始化) 与纯净 HF 基座同帧前向必须**逐位一致**
  (实测 `max|Δpred_masks| = 0.000e+00`) ⇒ "step0 基线 == 基座"这句话才有据。
- **判定**: 主指标 Δ 的 95%CI 下界 > 0 **且** 掩膜 Δ 的 CI 下界 ≥ 0 才算"有提升"; **幅度 < run 间标准差、
  有一折为负、逐单位胜率 <50% ⇒ 一律写"未证明提升"**, 保持 candidate。
- 本轮实测 (annot_v1, 522 配对单位/档): 框 IoU 精确框 Δ**+0.0036** [0.0020,0.0052] / 抖动0.08 Δ**+0.0080**;
  但**掩膜 IoU 精确框 Δ−0.0096 [−0.0144,−0.0048] 显著变差**、折1 三个种子框 Δ 全负、精确框胜率 45.9%
  ⇒ **未证明提升, 不转 in_service**。交付产物在自己 5 帧留出 val 上看着更好 (+0.02) 是**低功效假象** (基座
  自身换种子就跳 ±0.05~0.09)。

## 适配器**可选接入**服务 + A/B 判据 (2026-10-01 实测, 两处真坑)
- 接法: `ZMAX_SAM3_ADAPTER=<目录|.safetensors>` 或 `--adapter`; **默认关**。内核 `lora_inject.load_lora_adapter`
  (注入+键严格匹配+sha256 取证), 服务侧在 `segmenter.ensure()` 一次性装入; `/health` 出 `adapter{…}` + `mem.forward_peak_gb`。
  实测显存: 基座 1.79GB alloc / 前向峰值 2.10GB; 加适配器 1.80 / **2.11GB** (适配器 8.4MB fp32) ⇒ 增量 0.01GB。
- ⚠️ **`prefix_filter` 只能挂视觉塔前缀**: "最后 N 个 block"的谓词若也套到文本塔, 文本塔 24 层索引 0..23 全不满足
  `i>=32-N` ⇒ 静默少注入 96 个 Linear ⇒ 适配器键对不上 (`模型里找不到 …text_encoder…lora_A`)。
  训练侧 `build_trainable_model` 本来就是只给视觉塔挂谓词 —— 部署侧照抄, 别"顺手统一"。
- ⚠️ **服务侧框提示路径曾被 dtype 坑断**: `getattr(torch, self.dtype_name)` 里 `torch.bf16` **不存在** ⇒ 静默走 except
  把 float32 送进 bf16 模型 ⇒ `mat1 and mat2 must have the same dtype` (带 `boxes` 的 `POST /seg` 必 500, 纯文本提示却能过
  ⇒ 容易误判成"权重/适配器坏了")。用显式表 `{"bf16": torch.bfloat16, "fp16": …, "fp32": …}`。
- **判据方法 (可复用)**: K 折交叉验证把全部标注帧各留出一次 × ≥3 训练 seed × 2 档提示框抖动 × ≥3 评估抖动 seed;
  配对单位 = **(帧, GT 框)** 而非 query 下标 (两模型 Hungarian 匹配可能落在不同 query)。
  · 主指标用 **框 IoU vs 真标注** (基座不是上界, 是唯一可能真提升的路);
  · **掩膜 IoU vs 教师伪标签** 的对照方 = 基座自己的输出 ⇒ 基座=上界, "打平"是正常, **低于基座=真退步**;
  · 平凡基线用**纯净 HF 基座** (完全不注入 LoRA), 并给等价性自证: 训练口径 step-0 (注入 LoRA、B≡0) 前向与纯净基座
    逐位一致 (`max|Δ| = 0.000e+00`) —— 否则"step0 就是基座"只是口头禅。
- 实测结论 (annot_v1, 3 折×3 seed, 522 配对单位/档): 框IoU Δ+0.0036 [+0.0020,+0.0052] @精确框 / +0.0080 [+0.0061,+0.0100]
  @抖动0.08; 但**掩膜IoU @精确框 Δ-0.0096 [-0.0144,-0.0048] 显著变差**, 逐单位胜率 45.9% (<50%), 最低折 -0.0016
  ⇒ **未证明提升 ⇒ 保持 candidate**。判绿规则先定后跑: 主指标 CI 下界>0 **且** 掩膜 CI 下界≥0。
- ⚠️ 交付产物只有 5 帧留出 val 时, 逐单位 sd ≈0.03~0.09 ⇒ 均值标准误 ≈0.013~0.022, Δ+0.023 也**跨 0, 无功效**;
  必须把"逐单位明细 + 按独立帧数算的 CI"摆出来 (`tools/sam3_ab_units.py`), 不能拿均值当结论。

## 集成到场景叠加
- 规格元素 `{"origin":"seg","kind":"mask","polys":[[[x,y],…]],"area_px":…,"conf":…,"c3d":{…}}`; 渲染走 `scene_overlay.draw_overlay` 的 `elif b.get("polys")` 分支(**插在 box3d 之后、xyxy 之前** —— 否则带 xyxy 的掩膜会被矩形分支抢走)。
- **标签放轮廓外**: 不透明底片贴上去会盖掉填充与轮廓。大掩膜填充按面积减淡。
- `/boxes` 要给前端**真实轮廓点集** `contour`(取最大一圈), 页面 `bShape()` 才能画多边形并按多边形命中(否则退回外接矩形, 掩膜的"贴合"在页面上看不出来)。
- 服务化: 独立进程常驻(如 8796), **显存独占**红线; 推流服务只转发 + 落规格, 失败如实回页面。

## 残留: 按需分割写进规格后**不会自己消失** (2026-09-30 老倪问 "怎么残留历史的分割图")

分割是**一次性/按需**跑的, 结果以 `origin="seg"` 落进 `data/scene/overlay_spec.json` 后**没有任何过期机制**;
而推流服务 `cam_live_stream.py` **每帧热读**这份规格照画 ⇒ 只要规格里还留着掩膜, 页面就一直在画**那一刻的**掩膜,
相机/机械臂已经动了也不管 —— 看上去就是"残留的历史分割图"(实测: 06:52 一次补写留下的 6 条掩膜,
到了 20:5x 还在画, 坐标还是当时那帧的 640x480)。

**清层要这样清**(只动自己 origin, 不碰 meas/plan/trace/l5live/det/vlm):
```bash
cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/scene_clear_origin.py --origin seg           # 空跑
cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/scene_clear_origin.py --origin seg --apply   # 真删(自带备份)
```
清完复核 `GET /boxes?cam=arm` 的 drawn 里没有 `origin=seg`, 且 `meas` 条数不变(工具会自己打 `其它 origin 未被动: True`)。

⚠️ **别用页面上的 🗑 去删分割框**: `_boxes_edit(mode='delete')` 会把 id(`origin|label`, 如 `seg|metal`)写进
`spec.deleted`, 而 `draw_overlay` 对 deleted 里的 id **一律跳过** ⇒ 之后再跑分割拿到同名实例会被**静默吞掉**
(表现又是"分割没出图")。deleted 语义是给 VLM 的"不要再给", 不是清层工具; 要清就清层或用 "恢复全部" 清空清单。

## ✅ 治本已落地: 掩膜绑帧 (2026-10-07 老倪再问 "历史的分割图怎么一直在画布上?")

口径: **写规格的一方把"做分割那一帧"传给 `merge_origin(..., frame=img)`**(只有 `origin='seg'` 会盖签名),
规格里每条掩膜带 `sig`(dHash 64bit) + `sig_at`; **渲染侧 `draw_overlay` 算当前帧签名**, 汉明距离 > `SEG_SIG_TOL` 就不画,
并在**画面底部真值带**如实写"🧩 历史分割未画: 画面已变 N 条";`/boxes` 与 `/station/status` 也带 `seg_stale`/`seg_legacy`。

- 阈值实测标定(640x480 真帧, 64bit): 同场景静态 **0** · JPEG q40 **1** · 亮度+25 **1** · 强模糊 **2** · 缩放0.9 **0** · 旋转2° **1**
  (必须判"有效") ｜ 平移10px **5** · 20px **7** · 40px **15** · 80px **23** · 跨相机 **33~34** (该判"过期") ⇒ 默认 **tol=6**(余量 3 倍)。
  环境变量 `ZMAX_SEG_SIG_TOL` 可调, **`ZMAX_SEG_SIG=off` 整体关闸回旧行为**。
- **缺 `sig` 的旧掩膜判"不画"**(如实计 `seg_legacy`): 新代码一上线, 老规格里那批残留立刻不再贴画面 —— 这就是本次的第一层效果。
- 写方约定: `sam3_seg.write_spec_boxes(..., frame=img)` 必须给**分割那一帧本身**; 别在这一层重取一帧(签名与掩膜必须同帧)。
  手工拼规格的自测(如 `verify_seg_overlay.py`)也要自己盖 `"sig": hex(SO.frame_sig(img))`, 否则会被当旧数据拦下 ⇒ **假失败**。
- 坑: `/boxes` 的保障分支原来拿**全黑图**当画布算签名 ⇒ 掩膜永远"过期", 页面框清单里看不到分割框(选不中/删不掉); 已改成用该路**当前真帧**。

## 预算与定位
- 4060 8GB: bf16 载入 ≈1.7GB, 1008² 前向**峰值 2.1~2.4GB**, 加载 1.3s, 单概念 0.4s。
- 定位**关键帧/触发式**(页面按钮、画布节点双击、标注批次), **不做逐帧**; YOLO 每帧(轻) + SAM3 按需(重) 互补。

## 验收证据 (缺一不算完成)
1. 存档真帧 → 实例数/分数/面积/框。2. 同帧 A/B: 差异像素**落在多边形内**。3. 管道: 服务 → 规格 → `/boxes` 有 `origin=seg` → 叠加帧 vs 原始帧有差异 → 删除回退 → 恢复。4. 掩膜→3D: 缺深度/手眼/TCP **必须如实拒答**, 不许猜填。5. 目检: 让视觉模型看渲染图判贴合。**相机是黑帧时别拿实况当"贴合"证据**(先看 mean/std, 黑帧 mean≈5/std<1)。6. **绑帧三证**: ① 带本帧 `sig` 必画 ② 带别的帧 `sig` 或没 `sig` 必不画(计数如实) ③ `ZMAX_SEG_SIG=off` 能回旧行为 —— 用同一帧 A/B 比像素差, 别只看返回值。
