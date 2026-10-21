# 模型引擎 · 运行位置/运行权重/转换工具/状态 四列

老倪要的不是「模型列表」, 是**这一行现在到底在哪儿跑、跑的是哪一版权重、谁把它转成那个格式、现在是在推理还是在训练**。
答不上这四问的界面等于没有。

## 界面 (tools/gui/model_engine_window.py · ModelEnginePanel)

11 列, 顺序固定:

```
层 | 在役模型 | 在役版本 | 运行位置 | 运行权重 | 转换工具 | 本层产物 | 状态 | 训练中 | 最近训练 | 在役权重路径
```

- `运行位置`: `Intel NPU×2 96% · GPU×1 96%` —— 设备 × worker 数 × **占空(算力占用比)**, 已按 stream 数归一。
  只写一个 `Intel ` 前缀(窄列), 云端写 `云端 API`。
- `运行权重`: IR 项写 `名字 sha16`(两份就 `enc … + pred …`); torch/目录权重写最后两段路径
  (`004000/pretrained_model`, 只写 `pretrained_model` 分不清哪个 run)。
- `转换工具`: `ov_export_torch → ov_convert` / `export_intact → ov_convert`; 没进 IR 的写 `无 · torch 直跑`、`无 · 云端 API`。
- `状态`: 推理中 / 训练中 / 空闲 —— **rt item.status 也算数**(Intel 流水线在跑就是推理中,
  只看 8796 的 `inferring` 会把满载的 NPU 写成空闲)。

配色: 状态=推理中 cyan, 训练中 yellow; 候选行整体压暗 + `🔎`; `ElideNone` + 路径列 Stretch ⇒ 窄屏横滚不截断; 双击单元格复制。

## 真源 tools/model_runtime_map.py (一份, 界面不自猜)

```bash
./gui-venv311/bin/python tools/model_runtime_map.py            # 人话表
./gui-venv311/bin/python tools/model_runtime_map.py --json     # 界面/脚本
./gui-venv311/bin/python tools/model_runtime_map.py --check    # 自检(非0=采集缺项)
```

四条信息各自只有一个来源:

| 问题 | 来源 |
|---|---|
| 在哪跑 | Intel `GET /pipeline/stats`(设备→模型, fps, duty, streams) + 8796 `/status/all.edge` |
| 哪份权重 | Intel `GET /models` 的 `sha16`(服务侧现算) + 本机 ckpt `sha256[:16]` |
| 什么工具转的 | 文件内 `CONVERTERS` 表(tool/chain/gate) + `zmax_data/models/ir/intact_export.json` 的 parity |
| 推理还是训练 | `/status/all.models[].inferring` + `training[]` + map 里 `status` |

落盘 `config/platform/model_runtime_map.json` (生成物, 被 gitignore, 不进仓库)。

## 坑 (都踩过)

1. **只看 `/status/all` 的 `inferring` 会把 96% 占空的端侧写成「空闲」** —— 那字段说的是"HTTP 推理口有没有被业务打",
   不是"设备在不在算"。状态要并 `rt.status`, 设备占空要读 pipeline。
2. **端侧 `/models` 不给 `sha16` 就没法回答"跑的是哪份权重"** —— 加 `sha16`/`bin_mb`/`mtime`,
   IR `.xml` 几百 KB, 现场算 sha256 无感。
3. **IR 来源 ckpt ≠ 在役指针**: 端侧常是同一 run 的晚一个 epoch。map 里比 `realpath` 与 `intact_l4_current/weights.pt`,
   不一致就进 `warns`, 界面 tooltip 写"⚠ 与在役指针不是同一份" —— 不许静默。
4. **L5 别一句"云端 API"就完事**: 主路是 `api.deepseek.com`(`state_space/scene_vlm.py`), 本机还有 smolvlm 备用
   (`l5_vlm_merged_*`, 未转 IR) ⇒ 权重列必须写"云端权重 · 本机 smolvlm 备用未转 IR"。
5. **`_conv_short()` 会把 `无 (torch 直跑, 不进 IR)` 截成 `无`** —— 非工具链字符串要按语义映射, 不能一刀切 split(" (")。
6. **采集失败 ≠ 没在跑**: 一律写 `未加载` / 保留上次数值, 不许把读不到渲染成 0% 或空闲。
7. `config/` 是软链且被 gitignore ⇒ `git add config/platform/model_runtime_map.json` 会让整条 `git add` 失败
   (后续 commit 不执行), 只提交 `tools/` 下的代码。

## 验收口径

离屏渲染真 payload 打印 11 列 (`scratch/me_check.py` 那种), 不靠肉眼看截图:
L2 应出现 `Intel NPU×2 96%` + `yolo_peg_live <sha16>` + `ov_export_torch → ov_convert` + `推理中`;
L4 应出现 `Intel NPU×2 96% · GPU×1 96%` + `enc … + pred …` + `推理中`; L3 `4060×1` + `无 · torch 直跑`。
`--check` 必须 0 处不合规。
