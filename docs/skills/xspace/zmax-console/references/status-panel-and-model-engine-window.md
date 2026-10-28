# 左下角状态面板一行化 · 模型引擎窗口 · 模型配置接线 (2026-10-14 老倪)

## 1. 左下角常驻状态面板 = `tools/gui/status_panel.py` (自绘, 不是控件排版)
老倪: 「主界面, 下面的硬件显示, 排成一行; 现在两行, 占地方, 修改」
- 它原先 **W,H=560,68 两行**: 第1行 GPU/CPU/内存/磁盘+训练进度+3DGS, 第2行 L2~L5 层 chip。
- 改法: `W,H = 1080,40` + 全部元素共用一条中线 `cy = h/2` (硬件 4 项 → 训练条 → 层 chip → 3DGS → 通信灯)。
  层 chip 的可用空间 = `3DGS 标签左缘 - 10`, 先算标签宽度再给 chip, 放不下就 `break` (唯一依据 4 层实测放得下)。
- **一行判据在 `--selftest` 里**: 抓图按像素扫内容行带, 断言只有 1 条带 + 行带高 ≤40 + 横向跨度 ≥600px。
  实测: `面积 1080x40 · 行带 [(12,27)] · x 4..1076 · SELFTEST PASS`。
- 真数据核对: `--live-shot <png> --scale 2 --seconds 3` 拉 8796 真数据; 短名聚合正确 (L2 YOLO annot / L3 SmolVLA 004000 / L4 INTACT current / L5 DeepSeek deepseek-vl)。
- ⚠ 固定宽 1080 会撑窗口最小宽 —— 它挂在 `_pn_row` (面板 + stretch) 左下角; 需更宽改成 Expanding + 去掉 stretch。

## 2. 🧠 模型引擎窗口 = `tools/gui/model_engine_window.py` (新, 独立非模态窗)
老倪: 「改变模型配置，L2~L5 在模型引擎窗口，要能方便的查看控制所有模型的训练状态，执行任务工程」
- 一屏四行 L2~L5: 在役模型 / 在役版本 / 本层产物数 / 推理(青) / 训练中(黄, 带 pct+step/total) / 最近训练 / 在役权重路径。
- 数据唯一依据: `tools/model_inventory.py --json` (nvidia-smi + 四层清单 + training[]) + `http://127.0.0.1:8796/status/all` (在役/推理标记)。
  后台 `_Fetcher` 线程取数, GUI 侧 QTimer 600ms 排水 —— **阻塞 I/O 绝不进 GUI 线程**。
- 控制: ▶ 训练本层 / ■ 停止 / 📄 训练日志 / 📂 权重目录 / 🚀 执行任务工程 / 📋 复制状态 / 🔄 刷新。
- **命令唯一依据 = 配置中心「模型配置」的 `model.train_entry`** (窗口不另写一份):
  L2 `tools/joint_train_all.py --only L2 --yolo-epochs 1` · L3 `--only L3 --steps 20` ·
  L4 `--only L4 --steps 20` · L5 `--only L5 --l5-steps 20 --l5-merge`。
- 纪律: **同刻只允许一个训练进程** (8GB 卡) ⇒ 有任务在跑时 ▶ 变灰; 停止=真 SIGTERM 进程组 + 回读 `poll()`;
  训练输出逐行进日志面板, 不吞错误。
- 🚀 执行任务工程 = `tools/zmax_open.py step2 --activate --task <active_task>` (与主窗口右下角「🚀 启动工程」同一执行体)。
- **界面唯一**: 页面与弹窗共用**同一份代码** (见下 §2b); 入口在模型引擎页 (`TrainingModule`,
  `setObjectName("model_engine")`) 页首**内嵌** `ModelEnginePanel`, 顶栏按钮「⧉ 弹出为窗口 (同一界面)」
  → `open_model_engine_window()` (把同一个 Panel 装进 QDialog 弹出来, 已开着只抬起不重复开)。
- ⚠ **目检会漏、判据不会**: 首版 1360×620 时"在役版本 / 在役权重路径"四行全被省略号截断 (靠读屏子代理才发现)。
  现在: 窗口 1900×660; 列宽按真实文字定 (在役模型 258 / 版本 245 / 最近训练 150); 路径列显示**保留尾部的短路径**
  (`~/zmax/…/s3072/weights_epoch_xx`), 完整路径常驻单元格 (tooltip + **双击复制** + `📋复制状态` 导出)。
- 自检判据 (**18 项**, 离屏): 四层行齐 / 权重路径真存在 / 入口取自 `model.train_entry` / ▶ 使能与 ■ 停止互斥 /
  **Fixed 列不被省略号截断且关键列余量 ≥24px** (`fontMetrics().horizontalAdvance(t)+20 ≤ 列宽`; `ElideNone`
  下余量不足会被**硬切**而不打省略号, 所以只看"没超"不够) / **路径列放得下最长显示路径** /
  **完整路径在 tooltip 且可复制** / 一屏放得下 (≥1900×560) / 渲染非空 / 训练状态四判据 (见下)。
  `QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/gui/model_engine_window.py --selftest --shot x.png`
- **训练状态列的四条判据** (用构造的脏 `training[]` 做单测, 不赌真机运气): `JOINT(L2)` 归一到 L2 且取到进度 /
  同层多行取"有进度"那行 / 死 pid 不算训练中 (哪怕它有进度) / 活进程无进度 ⇒ 写 `训练中 · 已 Ns` 且**不得出现 `%`**。
  脏数据的三类归一规则、GPU 负载怎么测/为什么不高, 见 `references/training-status-truthfulness-and-gpu-load.md`
  (采样直接跑 `scripts/gpu_load_probe.sh`)。

## 2b. 页面与窗口 = 同一个界面 (老倪: 「界面应该是一个」)
同一功能既要"在功能区里能看"又要"能弹到第二屏"时, **不许写两套布局** —— 拆成一个 Panel 类 + 一个薄壳:
```python
class ModelEnginePanel(QWidget):      # 界面本体: 表 + 控制按钮 + 日志 (所有逻辑都在这)
    def __init__(self, parent=None, poll=True, interval=5.0): ...

class ModelEngineWindow(QDialog):     # 薄壳: 只把同一个 Panel 装进去 + 标题/尺寸
    def __init__(self, parent=None, poll=True, interval=5.0):
        self.panel = ModelEnginePanel(self, ...); _v.addWidget(self.panel)
    def __getattr__(self, name):      # 老调用方按旧名字( self.tb / feed() / _rows() )访问继续可用
        p = self.__dict__.get("panel")
        if p is not None: return getattr(p, name)
        raise AttributeError(name)
```
* 页面侧 `layout.addWidget(ModelEnginePanel(self, poll=True))` —— **就用这个类**, 不要"照着它再做一版"。
* `__getattr__` 转发是拆分类时成本最低的兼容做法 (演练/自检/studio 的旧调用点一行都不用改)。
* 样式表选择器跟着换 (`QDialog{…}` → `#modelEnginePanel{…}`), 否则页面内嵌后背景色丢。
* 判据 `tools/verify_model_engine_unified.py` (**7 项**): ① 共用类存在 ② 弹窗内容 `isinstance(panel, ModelEnginePanel)`
  ③ 表格 4 行 ④ 列名/按钮齐 ⑤ 页面源码里内嵌的就是该类 (`self.me_panel = ModelEnginePanel(`) ⑥ 按钮已是"弹出"语义
  (源码里不再有"另有窗口"的说法) ⑦ **两处界面实例化两遍逐字一致** (列名 + 按钮文字 list 相等)。
  改界面后它与 `verify_product_ui.py` 一起跑。

## 2c. 「推理中 / 空闲」的口径与唯一依据 (2026-10-14 老倪问诊「跑 L5 功能为什么 L2 L3 显空闲」)

那一列是**推理**列, 逐条 `probe` 真探针决定 (`models_manifest.json` 每条模型的 `probe`, 由 `status_hub._probe_inferring` 判)。唯一依据:

| 层 | 在役条目 | 探针 | 阈值 |
|---|---|---|---|
| L2 | YOLO 检测+2D→3D | `file_fresh` `ss_bypass/yolo_detections.json` | 10s |
| L2 | 状态空间小模型组 | `json_counter` `ss_bypass/status.json#layer_calls.perception` | 窗口 |
| L3 | SmolVLA+LEW 长程规划 | **`json_counter` `ss_live/layer_calls.json#L3.count`** (2026-10-14 新) | 60s |
| L4 | INTACT-JEPA | `http_counter` `127.0.0.1:8790/health#infer_count` | 窗口 |
| L5 | DeepSeek 视觉规划 | `file_fresh` `zmax_data/vl_safety.json` | 600s |

**口径 (写在窗口/文档里, 免得反复被问)**: `空闲` = 该层最近**窗口内没有任何画布节点被真跑过** —— 不是"模型没加载",
也不是"系统没用它"。跑**训练**列的是「训练中」(黄, pct/step), 训练不等于推理 ⇒ 训练时推理列本就应该空闲。
L5 标注→监督→训练闭环的**标注阶段**只调 L5 大模型 (碰不到 L2/L3) ⇒ L2/L3 推理列空闲是如实的。

🔴 **坑: 用「代理信号」当推理计数会变成恒假的探针**。L3 原来 probe = `json_age`
`dataspace/live.json#topics.ss_action.age_s` ("状态空间引擎动作节拍"代理)。实测 `live.json` 里 `ss_action` 只有
`topic/type/qos/allowed/hz/hz_design`、`count=0`, **没有 age_s 字段** ⇒ `_dig` 取不到 ⇒ 恒 `False`
(manifest 自己都注了"是代理, 系统中无该计数")。这类探针永远显示空闲, 看不出"该层到底有没被调"。

**修法 (已落地, commit 52efd88)**: `src/lerobot/engineering/layer_calls.py` + `runtime.execute_node_logic` 在
真调真函数**成功后** `touch(key,name)` 一次 (demo/异常不计) ⇒ `zmax_data/ss_live/layer_calls.json` = 逐层
`count/last_ts/last_key`; 节点→层 用 `nodes/by_level.LEVELS_INDEX` (禁猜)。改完把 probe 换成 `json_counter`;
判据 `tools/verify_layer_call_counter.py` (5/5: 真跑 L3 节点 ⇒ L3 计数 0→1 ⇒ /status/all L3 inferring=True)。
生效面: 新起进程立刻生效; **已在跑的 GUI 进程不会**, 且若该 GUI 正是用户那个长跑任务的父进程
(实测 `l5_annotate_train_loop.py --run` 的 ppid = studio pid) —— **先 `ps -o ppid` 再决定要不要重启控制台**,
否则重启会把用户正在跑的功能一起杀掉。

**目检前先自证**: 用户说"某层显空闲/在跑"时, 别直接答"机制就是这样" —— 先执行一遍
`ModelEnginePanel(poll=False)` + `_force_refresh()` + `_drain()` + `_rows()` 复现那一屏 (离屏), 再对探针目标
连续采样 (实测 L2 探针目标 20/20 次帧龄 0.0~0.6s ⇒ L2 真在推理, "显空闲" 是那个窗没刷到 ⇒ 让他点 🔄 刷新)。

## 2d. 「让某层运行」= 真跑那一层, 不是改显示 (2026-10-14 老倪「让L2 L3都运行，我看着」)

工具: `tools/ss_l3_live_loop.py --interval 1.0 [--seconds N]` (单实例 pid 文件; `kill $(cat
zmax_data/ss_live/l3_live.pid)` 停)。每周期: 抓一帧真相机 (`8791/snapshot/local2.jpg`) + 取一帧真轨迹
(`reports/ss_episode_latest.npz`) → `runtime.execute_node_logic` 真跑 L3 节点 (`ss_vlm` / `ss_skill` / `ss_mem_l3`)
→ 落 `zmax_data/ss_live/l3_live_status.json` + `jsonl`。`action_head`(DiT) 与 `ss_lora_l3` 是**结构/产物节点**
(只登记配置/产物, 不做前向) ⇒ 不许拿它们充"L3 在推理"。
L2 不用另起回路: 在役 `ss_yolo_on_real.py --auto --loop` 写 `ss_bypass/yolo_detections.json` (探针 10s 新鲜度)
就是 L2 的推理信号。

🔴 **坑: 节点“看着在跑”实际一次前向都没发生** —— `vlm_encoder.py` 原先是 `MODEL_ID` 联网 (`hf-mirror.com`)
加载, 而本机 HF 缓存**已有**权重 ⇒ 卡在 `loading` 永不 `ready`, `ss_vlm` 每周期 2ms 返回「权重加载中」
(实测连跑 26 周期 0 次真编码)。**判据: 看单周期节点耗时** —— 真前向 SmolVLM2-500M 在 4060 上 **350~420ms**,
2ms 就是没算。修法: 默认离线 (`HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` + `local_files_only`), 留
`ZMAX_VLM_OFFLINE=0` 回联网; 回路启动时先 `ensure_loaded_async()+wait_loaded(180)` 预加载 (实测 1.0s)。
另一个使“真前向”退化成缓存命中: 节点侧 `encode_stage(…, cache)` 按 (stage, seed) 缓存 ⇒ 回路每周期
把 `ctx._vlm_cache = {}` 清掉, 否则只有第一帧是真算、其余都是"(缓存)"。

📝 **回答老倪前先自证**: 改完拿**窗口自己的代码**复现那 4 行 (`ModelEnginePanel(poll=False)` +
`_force_refresh()`/`_drain()`/`_rows()`, 过滤 `ext` 与候选行), 并把 `/status/all` **连采两次** (计数探针需
两次采样间增长才判 True, 单采必为 False)。实测四层齐 `推理中` 才算交代。

## 3. 模型配置接线
机制与口径写在 `references/veh6-config-center-mcd.md`「生成器 tools/mcd_build.py」一节 (`read=("model",...)` 的四个键、
`_meta.sources` 加 sha16、改完必跑的判据链)。结论: **模型配置 9 项, `ckpt_l2/l3/l4/l5 + train_state + train_entry`
全部 ready=true**, L5 以前在配置里根本不存在。

## 4. 演练里新增的一步
`tools/run_full_drill.py::_model_engine_evidence()` — ⑥ 实际模型运行里离屏**真建模型引擎窗口**抓图
(`reports/drill/model_engine_window.png`) + 四层状态写进每个任务的文档; 每次演练只抓一次 (900s 内缓存)。
注意: 窗口要同时喂 `model_inventory` 与 8796 才有「在役版本」(只喂前者会全是 '—')。

## 5. GUI 硬约束 (跨界面通用, 改任何窗口/面板都要过)

* **面板/窗口的唯一依据认准自绘文件**: 底栏硬显在 `status_panel.py` (不是 `hw_widgets.py`) —— 先在 `studio.py` 里
  搜显示文案 (如 `3DGS ×`、`本地就绪`) 反查是哪个自绘类画的, 再动手。
* **形态即判据**: 用户说"排成一行/别占地方"时, 把形态写成离屏自检 (面积上限 · 内容行带条数 · 横向跨度),
  不靠目检 —— 否则下次改布局又回退。
* **显示完整性写成判据**: `fontMetrics().horizontalAdvance(文本) + 20 ≤ 列宽`, 任何一列超了就是会被省略号截断;
  窗口宽度**先量后定** (`sum(固定列) + 最长真实文本 + 40`), 不要先画后看。
* **省略号不许造成信息丢失**: 长路径显示短尾 (`~/zmax/…/<尾段>`), 完整值同时进 tooltip + 双击复制 + 导出 JSON。
* **不在 GUI 线程里做阻塞 I/O**: 取数 (subprocess/HTTP) 放 `QThread`, GUI 侧用 QTimer 排水。
* **一次只允许一个重进程** (机器人工具内存≈8GB): 有任务在跑时把 ▶ 变灰, 停止 = 真 SIGTERM 进程组 + 回读 `poll()` 确认。
* **杀后台窗口写脚本, 别内联, 且匹配串必须带判别词**: `pgrep -f '<脚本路径>'` 会匹配到**调用方 shell 自己的命令行**
  (它里面正好写了这个路径) ⇒ 直接把自己杀了 (exit -15)。`[ "$p" = "$$" ] && continue` **不够** —— 被杀的是父进程,
  `$$` 拦不住。正确做法: 匹配串带上只有目标进程才有的参数, 如 `pgrep -f 'model_engine_window[.]py --live'`。
* **改界面后必跑判据链**: 该窗自检 → `verify_model_engine_unified.py` (动过模型引擎/页面与窗口的关系时)
  → `verify_product_ui.py` → (动了 `studio.py` 配置面时) `mcd_build.py` + `engineering_db.py check` +
  `verify_task_order_split.py`。
* **同一功能已有页面时, 不要另起一个窗口了事**: 先把"这一个界面"抽成一个 Panel 类让两处共用
  (§2b), 再考虑弹出/内嵌 —— 否则两处会各自演进, 用户一眼就看出来"不是一个界面"。
