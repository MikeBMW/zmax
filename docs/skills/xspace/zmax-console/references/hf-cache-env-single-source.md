# ⚠️ HF 缓存环境变量写错 = L3「静默 rc=1」 (2026-10-14 实测事故)

## 现象
演练 `--train-only --only L2,L3,L4` 汇总里 **L2 rc=0 / L4 rc=0 / L3 rc=1**(8s 就挂),
L3.log 尾部是:
```
OSError: We couldn't connect to 'https://huggingface.co' to load the files, and
couldn't find them in the cached files. Check your internet connection or see how to run the
library in offline mode
```
→ 看起来像"没联网/官方权重缺失", 实际是**本地缓存指错了目录**。

## 真因
`run_full_drill.py::self_train` 和 `tools/gui/model_engine_window.py::_spawn` **各写了一份**:
```python
HF_HOME=os.path.expanduser("~/zmax_data/hf_cache")   # ⇒ /home/ubuntu/zmax_data/hf_cache
```
**少了 `/zmax/` 一段**, 该目录根本不存在。真实缓存 = `/home/ubuntu/zmax/zmax_data/hf_cache`
(里面 `hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct/snapshots/<rev>/model.safetensors`)。

失败链: 坏 HF_HOME → `HF_HUB_CACHE=坏路径/hub` 不存在 → `joint_train_all.py:49` 主动放弃 HF_ENV
(它宁可报缺也不瞎指)→ transformers **不带 offline 标志**去连 huggingface.co → 连不上 ⇒ OSError ⇒ rc=1。
L2(YOLO 自带权重)与 L4(INTACT 本地 ckpt) 不碰 HF 缓存 ⇒ **"看起来正常", 故障被掩盖成 L3 不行**。

## 修法 (已落地)
新建 **`tools/zmax_hf_env.py` = HF 环境单一真源**:
- `hf_home()`: 依次认 `ZMAX_HF_HOME` → `HF_HOME` → 工程根 `zmax_data/hf_cache`,
  **但只认真正带 `hub/` 子目录的那个** (写错/空的直接跳过, 不瞎指)。
- `hf_env()`: 返回 `dict(os.environ)` + `HF_HOME`/`HF_HUB_CACHE`/`HF_HUB_OFFLINE=1` (继承 environ,
  别用 `env={...}` 全量替换 —— 会把 PATH 之类的挤掉)。
- `describe()` 打 JSON, 自检/取证用; `python tools/zmax_hf_env.py` 应打出 `hub_ok: true`。
演练 `self_train` 与模型引擎窗口 `_spawn` 都改成调它 ⇒ **同一个按钮和同一条演练走同一份环境**。

## 判据 / 验法
- 单层验证: `HF_HOME=<repo>/zmax_data/hf_cache HF_HUB_CACHE=$HF_HOME/hub HF_HUB_OFFLINE=1 \
  ./gui-venv311/bin/python tools/joint_train_all.py --only L3 --steps 20` → 应 `rc=0`(实测 64.2s)。
- **别只看总 rc**: 必须逐层读 `reports/joint_train_<ts>/summary.json` 的 层/rc/产物, 否则一个层失败会被
  "整体跑了"掩盖 (老倪零容忍: 链路须真实执行且可验证)。
- 修完必重跑: 旧轮次留下的 `train.json`/文档里是坏结果, 要整轮重跑并重出文档 (不留旧数值)。
