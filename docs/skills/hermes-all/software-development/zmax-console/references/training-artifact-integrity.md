# 训练产物是否真生效 + 多层串跑的资源与报数纪律

## 产物静默失效: 适配器键在, 但配置说“不加载”
lerobot / peft 系产物里 `model.safetensors` 带 `lora_*` 键, 而同目录 `config.json` 写 `"use_peft": false`
(或 `train_config.json` 的 `peft: null`) ⇒ `from_pretrained` 按**无适配器**建模型: 加载成功、不报错、
参数就是基座的 ⇒ **训了等于没训**。这是“LoRA 训完没提升”最常见的伪装。
判据 (合并前/上线前必跑): `n_lora = 数 safetensors 里的 lora 键`; `use_peft = 读 config.json`;
`n_lora>0 且 not use_peft` ⇒ 必须先合并, 不得直接拿去对比或部署。

## 合并与验证 (一次做到位)
- 键名约定跨模型通用: 包装后原 Linear 存成 `<prefix>.base.weight`, 适配器 `<prefix>.lora_A/B`, 合并后
  输出普通 Linear 键 (`<prefix>.weight`, 去掉 `.base.`)。**合并逻辑不用重写**。
- 合并工具必须**按扩展名分流**: `.pt` 走 `torch.load`; `.safetensors` 走 `safetensors.torch.load_file/save_file`。
  拿 safetensors 喂只认 `torch.load` 的脚本会得到 `UnpicklingError: invalid load key` (看着像文件坏了, 实为工具窄)。
  **扩工具, 不要新增第二个合并脚本**。
- `r / alpha / scaling` **从本次训练日志里读**, 不许用工具默认值 —— 不一致时折出来的 ΔW 比例是错的且无报错。
- 合并后必**用真实加载器复盘**: `Policy.from_pretrained(merged_dir)` 成功 + 模型内 `lora` 参数计数 == 0 +
  参数量与基座同量级 + 落在目标 device。只看“残留包装键 0”不算过。
- 产物旁留 `MERGE.json`: 源 ckpt / r·alpha / 键数进出 / 残留包装键 / sha256 / 加载复盘结论 / **是否已进默认档**。

## 进默认档的门槛
未证明提升**不得**进默认档: 必须与**在役权重同口径对照** (同帧、同判据、同口径)。
对照结论为“持平/回退”时明确写“不上默认档”, 只把产物留档。

## 多层串行训练器 (L4→L3→L2→LLM 一个进程串跑)
- 8GB 卡上同刻只允许一个模型进程: 串跑时**自己那一层的峰值/前层残留**就能把后层顶掉, 后层起步即
  `Tried to allocate 46.00 MiB ... of which 38.94 MiB is free`。读日志先分清 `Process X has N MiB`
  说的是本进程还是别人, 别误判。
- 处置: **只单独重跑失败那一层** + 该层 batch 减半 + `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`。
  别重跑整条链 (前几层白跑且更挤)。默认 batch 是按“独占整卡”给的, 串跑必须显式降。
- **报数纪律**: 串跑收尾必须**分层列 rc / 用时 / 产物**, 不许一句“训练完成”盖过去; 一层 rc=1 时写“完成”
  就是造假; 失败层单跑修好后要说明是“单跑修复”, 不得归并成一次成功。
- 负载取证要同时报 `utilization.gpu` 与 `temperature.gpu/power.draw` (8GB 卡满载实测 ~94-100% / 66-70°C / 52W),
  只有利用率高、功耗温度却贴着待机, 说明没真在算。
