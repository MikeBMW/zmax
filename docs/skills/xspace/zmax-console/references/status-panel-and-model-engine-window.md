# 左下角状态面板一行化 · 模型引擎窗口 · 模型配置接线 (2026-10-14 老倪)

## 1. 左下角常驻状态面板 = `tools/gui/status_panel.py` (自绘, 不是控件排版)
老倪: 「主界面, 下面的硬件显示, 排成一行; 现在两行, 占地方, 修改」
- 它原先 **W,H=560,68 两行**: 第1行 GPU/CPU/内存/磁盘+训练进度+3DGS, 第2行 L2~L5 层 chip。
- 改法: `W,H = 1080,40` + 全部元素共用一条中线 `cy = h/2` (硬件 4 项 → 训练条 → 层 chip → 3DGS → 通信灯)。
  层 chip 的可用空间 = `3DGS 标签左缘 - 10`, 先算标签宽度再给 chip, 放不下就 `break` (真源 4 层实测放得下)。
- **一行判据在 `--selftest` 里**: 抓图按像素扫内容行带, 断言只有 1 条带 + 行带高 ≤40 + 横向跨度 ≥600px。
  实测: `面积 1080x40 · 行带 [(12,27)] · x 4..1076 · SELFTEST PASS`。
- 真数据核对: `--live-shot <png> --scale 2 --seconds 3` 拉 8796 真数据; 短名聚合正确 (L2 YOLO annot / L3 SmolVLA 004000 / L4 INTACT current / L5 DeepSeek deepseek-vl)。
- ⚠ 固定宽 1080 会撑窗口最小宽 —— 它挂在 `_pn_row` (面板 + stretch) 左下角; 需更宽改成 Expanding + 去掉 stretch。

## 2. 🧠 模型引擎窗口 = `tools/gui/model_engine_window.py` (新, 独立非模态窗)
老倪: 「改变模型配置，L2~L5 在模型引擎窗口，要能方便的查看控制所有模型的训练状态，执行任务工程」
- 一屏四行 L2~L5: 在役模型 / 在役版本 / 本层产物数 / 推理(青) / 训练中(黄, 带 pct+step/total) / 最近训练 / 在役权重路径。
- 数据真源: `tools/model_inventory.py --json` (nvidia-smi + 四层清单 + training[]) + `http://127.0.0.1:8796/status/all` (在役/推理标记)。
  后台 `_Fetcher` 线程取数, GUI 侧 QTimer 600ms 排水 —— **阻塞 I/O 绝不进 GUI 线程**。
- 控制: ▶ 训练本层 / ■ 停止 / 📄 训练日志 / 📂 权重目录 / 🚀 执行任务工程 / 📋 复制状态 / 🔄 刷新。
- **命令真源 = 配置中心「模型配置」的 `model.train_entry`** (窗口不另写一份):
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

## 3. 模型配置接线
机制与口径写在 `references/veh6-config-center-mcd.md`「生成器 tools/mcd_build.py」一节 (`read=("model",...)` 的四个键、
`_meta.sources` 加 sha16、改完必跑的判据链)。结论: **模型配置 9 项, `ckpt_l2/l3/l4/l5 + train_state + train_entry`
全部 ready=true**, L5 以前在配置里根本不存在。

## 4. 演练里新增的一步
`tools/run_full_drill.py::_model_engine_evidence()` — ⑥ 实际模型运行里离屏**真建模型引擎窗口**抓图
(`reports/drill/model_engine_window.png`) + 四层状态写进每个任务的文档; 每次演练只抓一次 (900s 内缓存)。
注意: 窗口要同时喂 `model_inventory` 与 8796 才有「在役版本」(只喂前者会全是 '—')。

## 5. GUI 硬约束 (跨界面通用, 改任何窗口/面板都要过)

* **面板/窗口的真源认准自绘文件**: 底栏硬显在 `status_panel.py` (不是 `hw_widgets.py`) —— 先在 `studio.py` 里
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
