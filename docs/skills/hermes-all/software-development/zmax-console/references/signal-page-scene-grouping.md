# 信号分析页(实时监控·Graphic 信号分析) 场景分色/目录树/波形 — 踩过的坑

真源: `tools/gui/canoe_graphic.py`(页面类) + `tools/sig_scene_tags.py`(场景打标) + `config/topics/scene_tags.json`(标签+overrides)。
判据: `tools/verify_scene_signal_green.py`(离屏真建同一类, 逐行走树取 层级/文本/前景色/勾选态/可勾选/组展开)。

## 铁律

1. **同一批信号键在两处出现时, 勾选状态会串台。** 目录树里 `self.selected` 按 **key** 记账, 而行是
   按 (区域, key) 铺的。非当前场景那一份若在建树时被 `setCheckState(Unchecked)` 强制取消(为了不让它
   跟着打勾), 这个 Unchecked 会走 `itemChanged` ⇒ **把同名 key 从 self.selected 摘掉** ⇒ 连当前场景的
   曲线也一起消失 ⇒ 主窗口空白“没有波形”。
   · 修法: `_on_item_changed` 开头 `if not (item.flags() & Qt.ItemIsUserCheckable): return`;
     非当前场景的行 `_make_item(..., interactive=False)` 去掉 `ItemIsUserCheckable` + 强制 Unchecked + 灰显。
   · 判据里必须同时查两件事: 当前场景区“可勾选且带勾”, 非当前场景区“不可勾选且不带勾”。

2. **波形有没有, 先看数据源是不是只有 1 个样本。** `sstrace.*` 的唯一发布者是 3D 面板
   (`ss_dreamview.publish_trace_live`): 3D 不播放 ⇒ `zmax_data/ss_live/trace_live.json` 不刷新 ⇒
   每键 1 个样本 + 帧龄几千秒 ⇒ 单点/平线, 看着就是“没有波形”。
   · 修法: `tools/ss_fw_trace_pub.py` + `tools/systemd/zmax-ss-trace-pub.service` —— 把**常驻引擎回路**
     每周期真值(φ/梯度/耗时/置信/内稳态/潜表示/动作调制)搬成 `zmax_data/ss_live/engine_trace.json`
     (schema 同 trace_live: `ts` + `时间_s` ⇒ 页面按场景时刻铺点), 与 3D 是否播放无关。
   · 只搬运不造数 + 发布前校验 `task_id` 前缀(如 TASK-01-FW*)⇒ 场景标签不会说谎。
   · 首屏默认曲线(DEFAULT_3D)要挑**每周期都在动**的量(如 循环耗时_ms/内稳态紧迫度), 否则一屏平线。

3. **场景归属: 前缀族 > 逐信号注册表。** `sig_scene_tags.tag()` 里通用名(帧/总帧/时间_s)会被注册表里
   早先某次运行记下的标签抢走(典型: 摆盘) ⇒ 蓝区冒出插拔的数。新来源族要**在最前面**判定:
   `if k.startswith("新前缀."): return "插拔场景"`, 并在 `_source_scenes()` 里同时登记(否则 --build 会再写错)。

4. **重名信号口径(老倪定的)**: 多场景共写的源, **每个场景区域各自重新加载一份**, 行色=所在区域场景色;
   非当前场景的组**默认折叠隐藏**(用户手动展开过的记在 `_expanded` 里, 别顶掉), 当前场景组自动展开;
   建树/切排序后 `scrollToItem(组, PositionAtTop)` ⇒ 重启后一眼看到当前场景(否则树长, 落点像“信号不在”)。
   当前场景判定: 排序选中优先, 否则 `ss_scene_switch.now()['src_state']`(实测返回 “插拔场景”这种中文场景名)。

5. **页面的 JSON 源解析有 48 键上限**(`flatten_json(..., 48)`, AR 曾因此只进 48 条)。新写一帧流别超;
   数值以外的东西(字符串)不进目录; 元数据键(ts/t/age/meta/groups/schema)要排除。

## 现场验收话术(老倪看画面, 不看代码)

- 先 `wmctrl -a '实时监控'` 把窗口抬到最前(3D 窗口会盖住波形区, 截图会拍到 3D 的界面 ⇒ 假“没波形”)。
- 证据用两帧差: `scrot -o -u` 隔 5~6 秒各一张, 裁波形区算变化像素(实测 39547 px / 3.84% ⇒ 实时在动),
  比“找曲线颜色像素”可靠(曲线颜色可能被抗锯齿/主题改掉)。
- 状态栏能自证: `本机: 采集中 · 信号 N 点` + 图例列出各曲线当前值。
6. **“只有某一条在动”先查输入是不是冻结的。** 实测症状: 10Hz 回路里只有 `循环耗时_ms`(CPU 抖动)有波形,
   潜表示/φ/梯度/置信 全是直线。根因不是图表: `RealStateSpaceSim.run()` 每次进来都 `_reset(seed)` ⇒
   渲染帧服务每 tick 调 `run(1)` 拿到的**永远是第 0/1 步的同一张图**(连取 4 帧 md5 全同)。
   · 排查手法(30 秒定案): 连取 4~5 帧比对 md5 / `mean,std`, 计数在涨但图不变 = 源没推进;
     再逐个比对源里各字段的(范围, 变化次数)。
   · 修法: 给 run() 加 `resume=True`(跳过 `_reset`, 内部复用 `self.env` ⇒ 不影响原语义), 渲染服务每 tick
     `run(max_steps=4, resume=True)`, 走完/异常才重开一轮; status.json 带 `episode_step` 供核。
   · 改后实测: φ 0.2325→0.3463(32.9%) · 梯度 18.1% · 置信 26.3% · 潜表示 p0..p3 全在动。
   · 判据要卡下限: “非平线曲线 ≥3 条”·否则冻结的链路也能“通过”。
7. **“耗时应该单调递增吧?” —— 先分清是耗时还是计数。** `循环耗时_ms` 是**每周期计算耗时**(0.6~1.7ms, 抖动),
   不是累计计时; 单调递增的是横轴(`时间_s`)和计数(`控制周期/帧`)。回答要把这个口径直接说清, 并把两条都用实测数说。

## 常驻单元

`zmax-fw-render.service`(8799 渲染帧) + `zmax-ss-engine-loop.service`(引擎回路挂 VLM+多层管线) +
`zmax-ss-trace-pub.service`(真值帧发布) —— 一条命令装/重装: `bash tools/ss_fw_chain_install.sh`;
单独回退引擎两开关: `bash tools/ss_fw_chain_service.sh revert`。
