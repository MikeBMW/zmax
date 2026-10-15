# 本地 VLM 的加载、探测与“不跑就当没跑”

## 权重目录先看真名（大小写/命名都会坑人）
实测本地合并权重的目录是小写前缀（`zmax_data/models/l5_vlm_merged_<ts>`）；glob 写大写前缀会找不到目录，
而找不到的后果是**静默退化**到规则/编码器路径（看着有输出，实际 VLM 没跑）。
做法：多个 glob 模式都试 + 只在目录里有 `config.json` 时才算命中 + 多个候选时取 mtime 最新的；
找不到就把 `backend` 如实标为 fallback（如 `encoder+fusion` / `rules`），**不要**把 fallback 输出当成 VLM 结论。

## 加载类要按模型族试，不要写死 CausalLM
SmolVLM 系权重用 `AutoModelForCausalLM.from_pretrained` 会报
`Unrecognized configuration class <class 'transformers.models.smo...'>`。
按这个顺序依次试，哪个不抛错就用哪个：
```python
for name in ("AutoModelForVision2Seq", "AutoModelForImageTextToText", "AutoModelForCausalLM"):
    cls = getattr(importlib.import_module("transformers"), name, None)
```
processor 统一 `AutoProcessor.from_pretrained(...)`；调用用 chat template：
```python
msgs=[{"role":"user","content":[{"type":"image"},{"type":"text","text":prompt}]}]
text=proc.apply_chat_template(msgs, add_generation_prompt=True)
```
（SmolVLM/SmolVLM2 会出现 `pad_token_id must be None or within vocabulary` 类警告——能跑就只记一笔，不阻断。）

## 图像不可用就别喂（否则视觉推理被状态推理冒名）
全黑/纯色帧（灰度均值≈0 或标准差≈0）先判掉：标 `degraded` + 原因，跳过 VLM/检测调用（省算力也更诚实）。
要出 JSON 就用短提示 + 小 JSON 契约 + `do_sample=False`，并对返回做“截取第一个 `{` 到最后一个 `}`”的容错解析；
解析失败也要把**原始输出**留在证据里（`raw_head`），而不是当成没发生。
