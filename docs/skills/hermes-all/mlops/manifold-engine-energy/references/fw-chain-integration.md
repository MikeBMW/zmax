# 插拔场景空间智能链 集成 (渲染图→VLM→流形引擎→元任务→L3→L2 前馈)

老倪 2026-10-15 原话要点: 配制成插拔场景 · 自主进化 · 把实时监控 topic 一一对应出来 · 流形引擎的空间智能/预测的结构/输出的驱动扭矩张量 · 意图解码成元任务 → L3 长程任务规划 → L2 前馈加速预测 · 这些主要预测 topic 都要在「实时检测的分析界面」看到/观察/验证 · 要有世界的代码 · INTACT 要运行/微调/适配/驱动 L2 原子功能 · **信息连接是核心: 插拔环境的渲染图像进入 VLM, 被流形引擎结构感知到** · 元任务要发出来 topic 并明确记录。

## 关键认知: 链本来就通了一半, 缺的是「视觉入口 + 多层挂载」
- 常驻链路 (systemd 单元 `zmax-ss-engine-loop.service`) 一直在跑, 落 `zmax_data/ss_live/{engine_latest,torque_live,manifold_homeostasis,meta_tasks}.json`: 度规 M/特征值 · 势能 φ 分层 (L2/L3/L4) · 梯度 · 谷底距离 · **驱动扭矩张量 T=M·(−∇Φ)** · 元任务 51 条。
- 但两点没接: ①`encoder=pca` (内建 PCA, 不是 VLM) ②`pipe_on=false / pipe_calls=0` (L3/L4-INTACT/L2 没挂)。
- ⇒ 「集成」= 把这两个开关真正打开并常驻, 而不是重写链路。

## 怎么接 (零改链路, 只加开关)
1. **渲染帧源** (`tools/fw_render_server.py`, 端口 8799): 现场相机不在位时 (8791 快照 503 / 8797 返 0 字节) 用 `RealStateSpaceSim(seed,mode="insert")._render_frame()` 持续渲染插拔场景 → `GET /frame.png` + `/status.json`(帧号/帧龄/尺寸/std, 供核非黑帧)。口径与 `tools/pipeline_closure_run.py`「真输入=引擎渲染帧」一致。
2. **引擎回路加两个开关** (在 systemd 单元 ExecStart 里, 单一收口):
   `--encoder l4 --l4-hz 1 --l4-frame-url http://127.0.0.1:8799/frame.png` → 潜表示= VLM 视觉编码 + 黎曼度规约束 16 维 (真值看 `engine_latest.z_source`: 「VLM 视觉编码器 → 黎曼度规约束 16 维 · 帧龄 x · 成功 n/失败 0」)
   `--pipeline --pipe-every 10 --pipe-img 同帧` → 每 10 拍 L5/L4/L3/L2 在线 (证据 `zmax_data/ss_live/layer_calls.jsonl`: L5=planner.rules.builtin · L4=**vote[node.intact]** · L3=dispatch.k_act · L2=detect.yolo)
   环境变量 `SS_L4_INTACT=1 SS_INTACT=1` (不加 ⇒ L4 走解析链, INTACT calls=0, 会被误判「模型没跑」)
3. **常驻 + 回退**: `tools/ss_fw_chain_install.sh` 装两个单元 (渲染帧服务 + 引擎回路); `tools/ss_fw_chain_service.sh start|stop|restart|status|revert` — `revert` 回零回归档 (pca, 不挂管线)。
4. **元任务「明确记录」** (`tools/ss_fw_chain.py`): 采链上真值落 `zmax_data/task_runs/TASK-01-FW/chain_<ts>.jsonl` (字段名即信号名) + 追加台账 `zmax_data/ss_live/meta_task_ledger.jsonl` (时间/话题出口/publisher/任务/场景/条数/首条ID/**内容哈希**/源帧龄)。同步给两个如实定义的指标: 理解力 = 置信×潜表示非退化×结构非空; 掌控力 = 三层闸门在位比×谷底收敛×未限幅折扣 — 公式写在字段旁, 供 UI 核对。
5. **界面上看得到**: `tools/sig_scene_tags.py --build --from-runs` 会把 task_runs 里**真出现过的信号名**标到对应场景 ⇒ 插拔场景 6→64 条 (链上 13 项主预测信号逐条打标), 信号分析页 (`📈 实时监控 · Graphic 信号分析`) 按场景色过滤即可看/观察/验证。控制台命令通道 `echo monitor > /tmp/zmax_nav_cmd` 可直接开该页。

## 判据
`tools/verify_fw_manifold_chain.py` — 十条要求逐条取证, 25/25 PASS: 链上真值新鲜度/非退化 · 空间智能(度规正定+编码器真值) · 结构分层 · 扭矩张量+上限+限幅 · 元任务 topic+台账哈希同口径+在增长 · L3 在线 · VLM+管线+INTACT 真值 · 13 项信号已标插拔场景 · 渲染帧服务非黑帧 · 台账字段齐全。缺项一律 ⚠/❌ **并给出该开哪个开关**, 不许编。

## 坑
- **systemd Restart=always 会用旧 ExecStart 抢着重启**: 杀散跑的裸进程无效 —— 改档必须改**单元文件** ExecStart 再 `daemon-reload && restart` (仓库模板 `tools/systemd/` 与 `/etc/systemd/system/` 各一份, 要同步)。
- **`pkill -f '...原文...'` 会杀掉自己的 shell**: 命令文本里含同一串时自杀 (exit -15, 前功尽弃) ⇒ 杀进程写脚本, 模式用 `[s]s_engine_loop` 断开自匹配。
- 联调实例用 `--instance <名字>` (自己的 tap/pid + `engine_latest_<名字>.json`), 不打扰常驻 `main`; 判据读实例真源要挑**新鲜的**, 超时回落到主实例, 不然报旧档。
- 挂上 VLM(≈960ms/次, 1Hz) + 管线(每 10 拍 100~900ms) 后回路实测 ~5~8Hz (原 10Hz) —— 属预期, 报数要如实说节奏下降。
- 编码帧接不上时回路**明写原因并留在 pca** (不假装): 单元起完等 20~40s 再核 `z_source`, 首帧窗口内可能还是回退态。
- 现场 `config/topics/` 是**符号链接**(不在代码库内) ⇒ scene_tags.json 改了不会出现在 `git status`; 别以为没写进去, 用 `git check-ignore -v`/直接读文件核。
