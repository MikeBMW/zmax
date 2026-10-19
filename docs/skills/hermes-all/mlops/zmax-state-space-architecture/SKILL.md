---
name: zmax-state-space-architecture
description: "Use when 状态空间画布 debug — 字段来源(预定义vs预测), 教学解析层vs真实权重, 节点源码映射."
---

# Z-MAX 状态空间画布架构与源码溯源

状态空间(状态空间仿真画布)是 left_right 双脑策略的仿真蒸馏版。用户(老倪)反复 debug
此区域, 高频问题: "某字段是预先定义还是模型预测的?" / "为什么两个模块源码一样?" /
"这是不是写死的?"。本技能是溯源方法和架构事实。

## 分层模型 (谁产生什么)
- **感知层** (state_space/perception.py, tools/gui/state_space_sim.py): 构造 obs。
  仿真里 target/孔位 = **HOLE_POS 预定义常量** (metaworld goal) + `_stage_target()` 阶段子目标,
  由感知层写进 obs[36:39]; 真机同构 (gen_insert_video.py) = `aligner.detect_3d`(YOLO 检测+3D
  反投影解算) 写 obs[36:39]。
  **obs43 的确切布局** (`fuse_sensors` = `K_obs×visual39 + tactile4`, K_obs=1.0):
  `0-2 hand xyz · 3 gripper · 4-6 v_est · 7-9 peg · 10-12 goal · 13-15/16-17 预留 0`
  `| 18-35 上一拍同一组 (18-20 hand,21 grip,22-24 v,25-27 peg,28-30 goal,31-35 预留)`
  `| 36-38 target · 39 gripper · 40 contact · 41-42 预留`。前馈 MLP **只吃前 39 维**, 触觉 4 维不进网络。
  自证三式 (随口报数前先算): `v_est ≈ (hand_cur - hand_prev)/ctrl_dt` · `goal` 当前与上一拍逐位相等 (常量) ·
  `target - peg` 的 z 偏移量 = 当前阶段悬高 (如 0.1m ⇒ 接近段)。
- **并行层** (state_space/parallel.py): FeedforwardAccelerator (obs→u_ff) + AdaptiveStateEstimator
  (递归潜状态+卡尔曼)。**只读 obs, 不产 target**。
- **认知层** (state_space/cognition.py): 调度器 u = w_ff·u_ff + (1−w_ff)·u_fb + 状态机。
- **世界模型 (右脑 RightBrainWM)**: 只预测 next_obs + contact 概率, **不产出 target**。
  target 是任务目标(先验), 世界模型是动力学 — 语义两码事, 别混淆。

## 教学解析层 vs 真实权重 (识别"模拟伪装")
- `state_space/parallel.py` 的两个类 = **画布教学解析式, 全仓库零引用** (仅画布/验证脚本用):
  前馈加速器 = 手写 Kp·(target−pos) 限幅公式 (注释自称"等价于训练后学的" = 示意, 非真);
  状态估计器 = 线性卡尔曼 A=0.95/K=0.5 (非训练 GRU)。
- **真实训练权重前馈**: `tools/gui/state_space_sim.py::ff_forward` — 从 npz 加载 W0-3/b0-3 +
  归一化参数 (sm/ss/am/astd) 做真 MLP 前向; `tools/ss_verify_trained.py` 加载 LeftBrainMLP
  权重替换 FeedforwardAccelerator 做闭环验证。
- 通用判别: 手写解析公式 + 注释声称"等价于训练后学的" = 教学/画布层; 真权重必有 npz/pt
  加载处 (outputs/rl_peg/full_pipeline.pt 或 state_space_sim npz)。

## 🏢 工程实现包 (2026-09-28 起): src/lerobot/engineering/ —— 逻辑在这里, GUI 只显示

节点逻辑与画布 JSON 已从 `tools/gui/` 搬进包 (lerobot 哲学: 注册表 + 实现归属 + 调用方解耦):

```
src/lerobot/engineering/
  paths.py      路径真源 (REPO_ROOT / LOGIC_FILE / FLOWS_DIR / GUI_DIR)
  registry.py   register(key,[关键字],doc,fn) · match_node(name) · home_file(key) · logic_globals()
  runtime.py    execute_node_logic(module,node,...) · _trace_exec · _demo_node_output
  sourceview.py get_node_source / get_node_location / explain_node / save/restore/reload
  flows.py      load_canvas / save_canvas(原子+备份) / validate_* / orphans / stats
  levels.py     L2/L3/L4/L5 档位契约 (must 列表) + band_map() + check()
  nodes/library.py    141 条节点逻辑 · 148 个注册 key (唯一真源)
  nodes/by_level.py   档位索引 (节点↔key↔函数, 自动生成)
  flows/state_space_obs.json   画布真源 (87 节点 / 173 连线)
```

`tools/gui/node_logic.py` = 33 行兼容壳 (转发包命名空间) · 仓库根 `flows/state_space_obs.json` = 软链。
**新增/改节点逻辑请写包里那份, 不要再写回 GUI 目录。**

溯源链 (从画布节点名 → 真代码): `registry.match_node(节点名)` → key →
`sourceview.get_node_location(key)` / `registry.home_file(key)` (用 `fn.__code__.co_filename`, 所以搬完自动指对地方)。

四层契约 (`levels.py`, 实测节点数): L2 基础功能 25 · L3 连续功能 5 · L4 自主安全 17 · L5 场景理解+自动标注 11 ·
元层 12; 判据 = `levels.check()` 里每层 `no_logic_key` 为空。

同类搬运的验收口径 (以后照用): ①key 集合与顺序 ②画布全量节点名→key 映射 ③每条关键字/doc 逐字
④函数源码逐字哈希; 基线 = 渲染 87/172 · 档位审计 R1 15·R2 34·R3 13·R4 7·R5 3·真缺口 0。

### ⚠️ 注册 key 重名会静默覆盖 (实测事故)
同一个 key 注册两次 ⇒ 后一条把 fn+关键字一起换掉 ⇒ 画布上那个节点**永远 match 不到逻辑**。
实例: `ss_pred` 被「先验动力学」(dynamics.py) 与「流形专家」(manifold) 重复注册,
导致「📈 先验动力学预测器」长期不可执行 (落在档位审计 R5-待建); 已拆为 `ss_dyn` + `ss_pred`。
新加节点/改关键字后, 拿画布节点名跑一遍 `match_node()` 验非 None (或直接 `levels.check()`)。
**反过来: 目标节点若已有更长匹配的 key, 你新注册的短关键字 key 永远不命中** (实测给「标定诊断测量 · 主参数 M」
另立 `cfg_import` key 毫无效果, `match_node` 仍返回既有的 `n_calib_mani`) ⇒ 要给已存在的节点加行为, **改它自己的
节点函数或它已注册的 key**, 不要另立新 key。

### ⚠️ 往 `nodes/library.py` (5000+ 行, 一个文件装 140+ 节点) 插代码: 锚点必须唯一
1. **别拿通用注释当锚点** (`# ②`、`# 第2步`): 实测插进了**另一个节点函数** (`node_flight`) 里面 —— 编译通过、
   判据静默失败 (日志里就是没有那段输出)。插完必须回验: 取插入点前最近的 `def`, 确认正是目标函数。
2. **用「docstring 行 + 函数体首行」这类唯一多行上下文**作锚点, 交给 patch 工具插 (它会回报 diff)。
3. **缩进按该函数实际层级**: 节点函数体是 **4 空格**(不是 8), `try:` 4 / body 8 / `except` 4。
   `textwrap.dedent` 去掉的是**公共前缀**(不是固定 4 空格) ⇒ 8 空格内容会被削成 0 空格、函数被截断,
   报错形如 `'return' outside function` 且位置在几百行之后, 极难定位。
4. **插在函数 `try:` 块之前时, 该块要自带 `import numpy as np` / `import os`** —— 函数里的 import 在 try 内还没执行。
5. 改坏了的恢复链: `cp -a` 备份 → `py_compile` → `git diff --stat <该文件>` 应为空(即回到已提交状态) → 重做。

## 画布节点源码展示机制 (tools/gui/node_logic.py + node_logic_dialog.py)
- **执行层可共用分派函数**: 多个节点 _reg 注册同一 node 函数, 靠 `"关键词" in name` 分派
  (ss_ff/ss_est 共用 node_ss_s2, "估计"→AdaptiveStateEstimator, 否则 FeedforwardAccelerator)。
  这是设计, 不是 bug — 但会让"看源码"看起来重复。
- **编辑器源码展示优先级**: `node_logic_dialog._load_source` 先 `get_external_source(key)`
  (_EXTERNAL_LOC 按符号截取真实类源码, 只读), 无映射才回退 `get_node_source(key)`
  (返回注册的 node 函数整段)。**每个节点 key 都应挂独立 _EXTERNAL_LOC** — 两个节点
  显示同一段 = 缺映射或映射指向同符号。验证: `get_external_source(key)` 首行应为各自类名,
  不是 `def node_ss_s2`。
- 改 node_logic.py / _EXTERNAL_LOC 后必须重启 studio.py (旧进程跑旧代码)。

## 调试铁律
1. **"预定义还是预测"类问题 → 追字段的写入者**: 谁构造 obs / 谁写 [36:39] (感知层?
   仿真真值? YOLO?), 不是读它的 forward。forward 被动读 obs, 回答不了来源。
2. **"两个模块源码一样" → 先跑 `get_external_source(key)` 对比首行**, 再判断是缺映射还是
   共用分派函数, 别猜。
3. **画布节点"真实执行"必须完整闭环**: 分派分支里只调 predict 不调 update (卡尔曼校正没
   执行) = 名不副实 — 2026-09-02 已修 node_ss_s2 估计分支 (补 obs39 z_k 校正闭环, 日志打
   predict 与 update 两步数值; 手算验证匹配)。
4. 改完 GUI 代码必重启 studio.py; 验证逻辑用 gui-venv311/bin/python (项目无 .venv)。
5. **「这个量是模型算的还是公式算的 / 谁在算」→ 三问定源, 别从画布连线推断**: ①**哪个进程**在算 ——
   GUI 回放进程 ≠ 常驻引擎进程, 同一个量在两边由不同代码产出; ②该进程的**开关 env**
   (`tr '\0' '\n' < /proc/<pid>/environ | grep -E "^SS_|^ZMAX_"`); ③代码分支 (真权重 / 解析式 / 纯公式)。
   实测插拔 3D 场景的四层速度: `u_ff` = 模型或解析前馈 (控制台进程**没有** `SS_INTACT`/`SS_L4_INTACT`
   ⇒ 那个 `v_ff` 不是 INTACT 输出, INTACT 只在常驻引擎那侧跑), `u_fb` = 纯公式 `clip(0.5×残差EMA)`,
   `u` = `u_ff+k_fb·u_fb` + 阶段限速, `u_sat` = 饱和 + 插入段回退; 而位置/姿态/夹持/帧号这些
   **是回放 npz 真值, 不是算的**。回答"是不是只有 X 是计算输出"必须把「算出来的」与「模型算出来的」分成两问答。
6. **由速度反推位姿: 位置能、姿态不能**。位置 = 积分 (用执行量 `u_sat/u_exec` 比用 `u_ff` 准得多),
   姿态推不出来 (动作只有 3 轴线速度 + 夹爪, 无角速度); `SSPlan` 只是 MoveIt 规划结果的镜像,
   **不反推位姿**。实测误差表、量纲自证法 (拟合缩放 k, k≈1 才说明单位与 dt 对) 见
   `references/metaworld-closed-loop-contracts.md` 末节。
7. **「界面说在跑」≠「这一层在算」; 档位是意图, 在跑的子链路才是事实**: 同一轮里往往有两条真源 ——
   画布节点参数(用户点选)与子系统状态文件(实际在跑, 如 `zmax_data/l5_loop/state.json` 的 `status==running`)。
   取值必须**事实盖过意图**, 而且发布方与消费方两处都按同一优先级, 否则同一轮会得出相反的档位口径,
   用户看到的就是"运行了 L5 却没有 L5 的输出"。另一条同类红线: **归一化四元数 q̂ 的模恒为 1,
   不能用来编码强度** —— 长度/亮度要按原始 |F| 取尺度(对数尺度 + 保底), 并把数值直接写到屏上;
   量级只信数字。太阳系/S³ 面板的完整口径见 zmax-console 技能里的「力场可视化」参考文件
   (force-field-visualization.md) §8/§10。

## 🧮 流形层逐帧发布闭环 (2026-09-03 老倪: "为什么流形/潜空间没有输出连线")
- 回路外元层此前只读日志、无输出 → 半吊子。闭环: 引擎 run() 每步实算流形量
  (decompose/evaluate 纯 numpy, ~0.1ms) → tr["mani_risk/progress/eta/V"] 全程序列
  + _io_snapshot 发布 3 个 channel ("🧮 接触流形"/"🧮 性能流形"/"🧮 潜空间",
  out=进度/偏离/V·状态 | δ⊥/插深/V_p/η | 潜坐标/速度场 prior−x̂₋)。
- data_world.MODULE_ORDER 14→17 键 (物理世界后 append 3); 数据总线/3D 自动带出。
- StateSpaceScopeDialog 2x2→2x3 六格 (+ 法向偏离 #ff7b72 / η #a371f7), 画布连线
  ssmani_c→ssvideo(in2)/ssmani_p(in3)/sslat(in4) + 节点 outputs=["out1"]。
- 引擎加载流形: _find_mani_file/_load_manifold (module 名 state_space_mani, 缺失不阻塞)。
- 铁律: 回路外分析节点输出必须"有去向" — 要么进数据世界逐帧发布, 要么明确只读标注;
  禁止无输入也无输出(孤立)与有输入无输出(断头)。连线不改执行 (状态空间跑引擎拓扑)。

## 🧩 验证层 (2026-09-03 老倪: 系统要能逐个验证)
- 真源: src/lerobot/verification/verification_layer.py — FEATURES 注册表 (45 项:
  35 自动 F-A01~F-F04 + 10 GUI 手动 F-G01~G10) + **FEATURE_META (v4.0.1, 并行 dict:
  fid → (基本功能|泛化功能, 感知模型|世界模型|决策控制|规划推理|安全机制|引擎|数据平台|标定工具|GUI工具, 模型特点))
  — 加在文件末尾 main() 前 (勿插 FEATURES 后: 会错位 _EXTERNAL_LOC 行号锚点 47/97)**。
  list_features() 返回 dict 列表含 kind/role/spec (GUI 对话框/Excel 导出复用)。
- VerificationLayer (t_F_* 断言, 引擎跑一次缓存 tr; 六层/标定/流形 importlib 直载)。断言全部按源码契约手算可核。
- 画布: 底部「🧩 验证层」row_bg + 🧩 Feature 功能清单 (ss_feature) / 🧪 Test 用例执行
  (ss_test) — **v4.0.1 起双击/右键 = VerificationDialog (tools/gui/verification_dialog.py):
  45 项分类表格 + ▶运行全部测试 (后台 skip_slow) + 导出 Excel (3 sheet, scp 上传)**;
  单跑 ZMAX_VERIF_ONLY=F-xx; CLI tools/ss_feature_tests.py --list/--only/--skip-slow。
  ⚠️ ssfeat/sstest 带 source 字段 → on_node_activated 的 verif 分支必须在最顶部 (0.0),
  否则被数据源切换分支抢先拦截。
- 域: A引擎闭环7 (八阶段/收敛3.08mm/速度伺服0.211/台面/夹持/接触) B六层11
  C感知4 (YOLO 真检出3类 conf~0.95) D规划3 (离线规则) E元层5 (三域/潜空间PCA 2D@95%/
  流形) F画布4 (38节点10层/_EXTERNAL_LOC 35条/io_trace 14键=MODULE_ORDER)。
- 坑: 引擎 tr["u_sat"] 标量; 画布 io 键 "🛡 安全限幅"≠节点名"安全执行边界";
  行号映射随源码增行会漂 (F-F03 校验 ±3 行容错); YOLO 用例需 DISPLAY。

## ▶运行/单步/右键 执行语义 (2026-09-03 老倪: "运行状态空间后 detect_3d 没进" 根因)
- **▶ 运行 = 引擎仿真 + demo 播放, 不执行任何节点真实函数**:
  ① `_start_state_space_sim` (simulink_module.py) 只真执行名含"数据源"的节点;
  ② `StateSpaceSim.run()` 纯 numpy 引擎 (简化世界, 无 metaworld/无图像);
  ③ `_ss_tick` 播放每节点 `execute_node_logic(demo=True)` → `_demo_node_output` 只读
  DataWorld 帧数值展示 (v3.4.8 为防 YOLO/LLM 冷加载 1.6s+ 卡播放)。
- **⏭ 单步 / 右键"运行节点" = 真实执行**: `execute_node_logic(demo=False)` →
  node_ss_yolo → `_yolo_ensure_aligner`(best.pt + metaworld env) → `_yolo_capture` →
  `aligner.detect_3d` — 断点可进 (ZMAX_DEBUG_BREAK=YOLO 只停该节点)。
- **引擎 io_trace 曾写死伪装 (老倪红线)**: state_space_sim._io_snapshot 的
  "🎯 YOLO 目标检测" out 写死 "conf 0.99"、坐标抄仿真 peg/hole、hand 抄 peg → 总线/播放
  显示假检测。2026-09-03 已改 conf "--"(引擎无 YOLO 模型, 诚实标注) + hand=末端 self.x、
  peg=独立物体 self.peg (原误用末端当 peg)。
- **真实 YOLO 采样一次 (2026-09-03 落地)**: simulink `_real_yolo_sense_once()` —
  ▶运行/单步/右键同源, 引擎跑完对 ss_yolo 节点 execute_node_logic(demo=False) 一次:
  detect_3d 断点可进 + 真实 conf/3D 日志; `_demo_node_output` 对 ss_yolo 节点优先展示
  缓存真实值 "(真实YOLO采样)"。
- **⚠️ 勿把真实采样注入 io_trace**: 引擎是简化世界 (HOLE_POS y=0.462), 真实 detect_3d 是
  metaworld seed0 世界 (hole y=0.671) — 坐标不同源, 混进同帧自相矛盾。真实值留
  _YOLO_CACHE + 日志/演示展示, 引擎帧保持自洽。
- **YoloStateAligner.detect_3d 不带 conf**: node_logic `_yolo_detect2d` (同帧同预处理
  rot90+BGR 二次 predict) 补真实 conf/框, 存 `_YOLO_CACHE["det2d"]` (det3d 存 3D)。

## 🧮 标定层三域 + 潜空间节点 (2026-09-03 老倪: 潜空间=流形地图, 世界模型=导航仪)
- 标定层从引力/斥力二分 → **三域**: ATTRACTION(动作)/REPULSION(状态预测)/
  LATENT_CALIB(潜空间 — 世界模型预测流形): latent_dim=4(位置3+预测力1)/state_dim=39/
  manifold_kind=flat-linear/flow_kind=const-vel/force_ch/prior_A=1.0(latent_dim 改维=
  重构卡尔曼, 只标定+校验不写引擎字面量; prior_A 从斥力域迁入潜空间域, 引擎写回锚点
  PriorDynamicsPredictor(A= 单源不变)。
- 画布: 标定层 row_bg 更名「🧮 标定层 · 引力/斥力/潜空间」+ 新增「🧮 潜空间 · 世界模型
  流形标定」节点 (ss_lat, node_ss_lat): 真执行 — 引擎轨迹 39D 观测 PCA → 有效维@95%/99%
  (实测 2D@95%/4D@99%: 任务路径低维嵌入, 孔/姿态常量维无方差) + 潜坐标/速度场
  (prior−x̂₋) 取 tr 真实 latent_vec/prior_vec; 校验标定潜维 vs 引擎实际。双击/右键走
  标定面板/表格 (含潜空间组: 维度 spin/力通道 checkbox/prior_A)。
- 🐛 tr["u_sat"] 是**标量范数** (float) 不是向量 — node_ss_calib/面板取速度勿 [:3]
  索引 0-d 数组 ("too many indices", 既有 bug 被 try 吞, 09-03 已修)。
- 🧮 流形层 已更名 **流形导航层** (测地线地图视角): 流形=潜空间地图, 节点=地图导航读数。

## 🧮 流形导航层 (2026-09-03 老倪: 光模块精密插拔 = 低维流形上的运动; 回路外几何元层)
- 拓扑: state_space_obs.json 底部 y≈1040 「🧮 流形层」row_bg + 两 model 节点
  (ssmani_c 接触流形 x240 / ssmani_p 性能流形 x640), 无连线, 不进引擎 io_trace。
- 源码: src/lerobot/manifold/manifold_layer.py (与 calibration/ 同级) —
  ContactManifold (L51) / PerformanceManifold (L124); 常量 HOLE_POS/HOLE_MOUTH/
  PEG_HEAD_OFF 与 state_space_sim.py 逐字同源 (别改单边)。
- 数据真源: node_ss_mani 从 module._ss_tr 当前帧取 tr["x"/"peg_head"/"target"/
  "v_vec"/"stage"] (node_ss_calib 同款 idx=_ss_round); 无轨迹 → 提示先 ▶ 运行。
- 接触流形数学: e=T−hand (x 通道=e=peg_head−HOLE_POS); 通道轴按阶段 —
  下降/抓取/抬起=z 垂直, 插入=工艺斜线 AXIS_INSERT (孔口上方悬高 2cm→孔底,
  ≈(−0.957,0,−0.29)), 完成=孔轴 x; progress=‖e∥‖, risk=‖e⊥‖, V=½‖e‖², V̇=−e·v;
  状态=risk vs RISK_TH (下降/抓取 0.03=engine 抓握接触容差, 插入/完成 6/4mm)。
- 性能流形数学: δ=销头−孔底 → V_p=½δᵀWδ (W=diag(0.4,1,1), 横向重权),
  η=exp(−V_p/σ²) σ=0.004 (高斯光束近似 — 是模型非光功率计实测, 真机标定 W/σ)。
- 实测语义 (引擎 305 步): η 全程≈0 到完成段 0.57→0.77 (没插好光路不通);
  插入段起始带 ~10mm 工艺偏离被如实标红后收敛 (引擎 D_CONTACT=2cm 提前切插入)。
- 坑: engine stage 名带推进后缀 ("下降 · 接触") → _stage_name 清洗主阶段;
  接近/对位/转移=空中自由运动归 CHANNEL_FREE (误当 z 通道会全程误报离流形)。

## 🧠 右脑 WorldModel 蒸馏接入 (2026-09-06, commits 2283efbb + 74405273)
- 训练右脑 = RightBrainWM (modeling_left_right.py): obs39(raw)+act4(raw) → next_obs + contact
  (enc 2×256 MLP, **非 GRU** — parallel.py 注释"A≈GRU W_hh"是教学类比)。角色对应链路
  世界模型/先验 (dynamics.py PriorDynamicsPredictor), 不是卡尔曼估计器 (est 是估计器)。
- 导出: tools/export_ss_right_brain.py (ckpt→npz, 自动测定 pred_next 量纲=归一化空间
  需反归一化 *ss+sm, numpy vs torch 对照 MAE 5e-8); models/ss_right_brain.npz 不入库
  (同 ss_left_brain)。**坑**: state_space lerobot 训练只优化 left action loss, 右脑
  近随机 (contact acc 0.721 无区分度近0.519/远0.511) — 导出前必实测质量!
- 重训: tools/train_ss_right_brain.py — 引擎域数据 (ss_insert_lerobot, next=同ep下一帧,
  contact=手obs[0:3]-peg obs[7:10]<5cm 自建标签) → next 位置误差 0.1cm + contact acc
  1.000 (近1.00/远0.00)。**训完直接导出 npz (同结构)**; best.pt 在 outputs/rl_peg/。
- 接入: dynamics.contact_of(obs,act) (逐通道域检 4σ + wm contact; 域外 None) → 引擎
  contact_p = max(经验残差公式, 右脑真权重) — 抓取时机由训练模型主执行, 教学公式兜底。
- **实测否决 pred_next 位置先验主执行**: 引擎纯积分动力学线性先验即最优 (u→位移精确),
  右脑 1cm 级实时残差反而加噪 (残差 0.108 vs 0.0485, 状态机卡对位)。wm 位置先验能力
  保留 (predict obs=), 待真实物理/非积分动力学场景启用; real sim 布局漂移域外
  use_wm=False (同 accel 强制解析)。验证: 引擎 8 阶段 done 无回退, 残差复原 0.048。

## 🚀 L3 扩展: 插拔+AOI 闭环任务链 (2026-09-08, commit 74ffbb95)
- 状态机 8→13 段: ActionModulator.STAGES 尾部追加 拔出/AOI转移/AOI检测/回程/放下/完成
  (插入后按 mode 分流: "insert"=直接完成 (回归默认) / "full"=插→拔→AOI→回放闭环)。
  sim_real 用 mode 参数或 SS_MODE env; GUI 默认 insert (演示基线), full 待 GUI 开关接线。
- **AOI 工位 = 台面固定标定设备** (AOI_FOCUS 常量, 3D ss_dreamview 同源常量勿改单边):
  光模块头悬停镜头对焦点保持 25 帧 = 采图; 检测报告 = **真实过程指标代理** (不造假):
  插入残余深度最小 / 接触力峰 / 回抓次数 → PASS 阈值 (深度<8mm & 力峰<1.0 & 无回接近);
  _meta 带 aoi_focus/mode/aoi_report (3D 画设备/演示消费)。光学判定留真机 AOI 接口。
- **拔出两段式**: ①沿孔轴反方向水平拉出 (depth>pull_out_m 脱孔) ②垂直抬离孔口
  (pull_clear_h → 平移不刮盒); 与插入段①同款"引擎切目标, advance 等证据"模式。
- **放件流程**: 放下段 z_stall 触台 (z_stall 统计须含"放下"段! 只算下降/抓取会永不触发
  — 09-08 实锤) → _drop_ready 开爪指令覆盖 → 观测爪开 → placed → 完成。
- 🐛 已踩: AOI转移 判据曾用"到对焦点距离<2cm"但目标是**悬停点** (focus+0.08) → 永远
  等不到卡死; 判据目标必须与 _stage_target 目标同点 (引擎几何到位事件驱动更稳)。
- 夹持回退范围 RETREAT_LO..HI = 4..10 (排除「放下」: 放件主动开爪非滑脱)。
- 画布: DiT(ssdec) y-610 回 L3 行 (v5.2.0 设计位); VLM→DiT 主输入 in1 (潜空间 z,
  接触流形让位 in3, 性能流形 in2); DiT 双下行通路 lkdc_ff→ssff (前馈=肌肉记忆固化点)
  + lkdc_act→ssact (执行端直通)。node_logic: VLM 识别 AOI 设备/报告 + DiT 双通路
  教学标注, 真实权重推理接入点 = smolvla_lew 容器/远程 (模型引擎三模式)。
- 实测: R0 mode=full seed101-104 全链闭环 4/4 (872-989 步), AOI PASS 深度 5.3-5.9mm;
  insert seed104 343 步零回归。R1 视觉 full 未验 (每步 YOLO ~1s, GUI 演示时跑)。

## 🧩 VEH.5.041 统一状态空间 = SU(2) 二阶特殊酉群 (2026-09-20 老倪升级)

**旧口径作废**: 该节点源码曾是 `perception.fuse_sensors()`(传感器融合拼接 43D) —— 老倪指出
"这是传感器融合, 不是统一状态"。统一状态空间是**群**: `SU(2) = {U∈C²ˣ²: U†U=I, det U=1}
= exp(−i·ω·σ/2)`, 全部层/全部节点数据都映进这个群, 在群里观察并理解整个场景。

- 内核: `src/lerobot/policies/left_right/state_space/su2.py`
  - `SU2Element`: 哈密顿积(群乘)/逆元/`from_rotvec`(exp)/`log`(主值分支, exp∘log 精确可逆)/
    `bloch()`(‖r‖≡1 — 群元素↔纯态, 全在 Bloch 球面 S²)/`theta()`/`visibility()`=|w|=收敛度/
    `distance_fs`/`commutator_norm`;  参数化 `U = w·I − i(x σx + y σy + z σz)`, (w,x,y,z) 单位四元数
  - **有界映射律** `ω = π·tanh(g·‖v‖)·v̂`: 任意实向量 → su(2); θ<π 永不绕圈(否则 θ 3.14 与 0 混在
    一起 = 假收敛), 方向保留, ‖v‖→0 ⇔ U→I(场景收敛)。别用 ω=g·v(会绕圈)。增益 L2=2.0/L3=3.0/L4=1.0
  - 层: L2=43D 几何误差(光模块头−孔位) / L3=流形规划(progress,dperp,rem) / L4=安全动作(u_sat,
    contact_p,1−η) / L5=大模型意图(**未接入 → 单位元, 不编造**);  `U_scene = U_L2⊗U_L3⊗U_L4⊗U_L5`
    (群不可交换 = 层序敏感), `peel_layers` 逐层左乘逆元读贡献, 全剥离残余应≈0(分解自洽)
  - 节点级全面映射 `NODE_SPECS`(17 节点): 每个节点的 io_trace 真实 out 按语义规则取向量
    (vec/slice/diff/chans/obserr; 字符串里的数值用正则提); 本帧无数值输出者 → 单位元 + 标注
- 画布: `flows/state_space_obs.json` 节点 ssobs 改名「🧩 SU(2) 统一状态空间 (二阶特殊酉群)」,
  params 带 `su2_unified_state/group/map_law/blocks/observables/viz_tools`; 43D 拼接语义归 📡传感器融合
- node_logic: `_EXTERNAL_LOC["ss_obs"]` → su2.py `class SU2UnifiedState`(右键显示群代码);
  执行函数 `node_ss_su2`(真跑 su2.py, 读 `module._ss_tr` 当前帧, 写 `_SS_STATE["su2_*"]`)
- 观测面板: `tools/gui/su2_dialog.py` — 双击节点打开(simulink `_open_su2_panel`, 分发分支
  `params.su2_unified_state` **必须在 source 分支前**, 否则被"数据源切换"抢先); 5 视图 = Bloch 球
  (QPainter 拖动旋转/滚轮缩放) · 层贡献+反演 · 层间不可交换与 FS 距离热力矩阵 · 节点映射 · 阶段轨迹;
  按钮含"可视化工具统一入口"(波形/3D/直方图/归因/视频/输入图像 → `_open_viz_node`)
- 验证/图: `tools/ss_su2_verify.py`(群公理 + 真实引擎 369 步 → `reports/su2_state_report.json`),
  `tools/plot_su2_state.py` → `reports/su2_bloch|converge|layers|node_map.png`
- 实测(引擎 接近→完成): θ_total 2.86→0.98, |w| 0.14→0.88(向恒等元收敛); 剥离残余 ≤3e-8;
  层间不可交换 L2|L4=0.587(最强); 群公理 封闭/酉/det/结合/单位/逆/exp-log/Bloch 全 ≤1e-15

**踩过的坑**
1. **数组进布尔上下文**: `float(frame.get(k) or 0.0)` 遇 ndarray → "truth value of an array is
   ambiguous" → 用 `_scalar()` 兜底(ndarray/0-d/None 全安全); `obs43_geometry` 兼容 (1,43)/列表。
2. **FakeMod 必须显式 `_trace_nodes = False`** — `__getattr__` 返回 lambda(truthy) 会让
   `execute_node_logic` 走 `_trace_exec` 逐行执行 → 节点"失败且无日志"的假象(排查浪费最久)。
3. **画布加载会重映射 node id**(id_map): 断言/查找一律按**节点名**, 不能按 json id。
4. **同一关键词只能注册一次**: `_reg("ss_su2",…)` 与 `_reg("ss_obs",…)` 关键词相同 → match_node
   歧义(返回 ss_su2 而 _EXTERNAL_LOC/画布 id 是 ss_obs) → 只保留 ss_obs 一条。
5. **工程库里的「功能」要落回画布节点, 必须两步 join**: `config_meta.json` 的每个功能带 `module_ref`(节点**显示名**)
   与 `row_name`(行背景节点名 —— 实测只 15 条 row_bg)。`module_ref` → 按 name 建的反查表 → node id。
   直接拿 `module_ref` 当 id 查字典 **全 miss 且不报错**; 拿 `row_name` 当功能则命中行背景 ⇒ 报「该功能不属于任何任务」。
   静默失配的后果不是异常而是**下游聚合整表落到同一个桶**(按优先级/按任务计数看着像业务结论)。
   定式: **join 完先断言命中数 == 期望总数**(实测 74/74), 每个任务侧再核一次(要素数 == 启用节点数,
   实测 51/42/51/51/51/51/31 逐任务相等) —— 再相信任何下游统计。
6. **任务 × 节点是「子集」不是「映射」**: 实测 7 个任务的启用节点都是**同一个 51 节点集**的子集, **无任务专属节点** ⇒
   功能/参数为全工程共用, 任务之间只差配置(`overrides` 参数覆盖 + `applies_segments` 配方段 + `run_cfg` 执行开关)。
   所以不能按「某任务独有功能」给它排期: 先看优先任务启用的并集是否等于全量启用集(实测摆盘∪插拔 = 51 = 全量),
   是就只能把它们需要的那批**整体压在时间窗前段**、后段留收口。
5. `data/` 与 `reports/*.png` 被 .gitignore → 映射表 `data/su2_mapping.json` 是**本地生成**
   (`load_mapping` 缺文件回退内置 DEFAULT_MAPPING, 不阻塞), 图不入库。
6. 扩展新层/新节点映射: 改 `NODE_SPECS`/`encode_layer` 即可(数据驱动), 不用碰画布 JSON。

## 🔌 引擎 L4 注入开关盘点 (2026-09-24 血教训: A/B 前先核对链上开关默认值)

`tools/gui/state_space_sim_real.py` 的 L4 注入链上有**一串默认关**的开关; 不核对就会把"上游没开"
误判成"模型无效" (2026-09-24 实例: 因为 `SS_L4_ALIGN` 默认关, 把"注入被闸死"写成了"新 LoRA inert"):

| 开关 | 默认 | 作用 | 不设的后果 |
|---|---|---|---|
| `SS_L4_INTACT=1` | 关 | L4 直驱接入 (decoder 量纲逆运算 act×K_ACT) | 完全没有 L4 注入 |
| `SS_L4_ALIGN=1` | **关** | 施加对齐层 `models/l4_align_map.json` (锥角 cos≥`SS_L4_ALIGN_COS_MIN`(0.9) + 幅度封顶 ≤`SS_L4_ALIGN_RATIO_MAX`(1.2)×L2) | 原始提案 cos 中位 **−0.605** / 幅度比中位 **5.8×** → 被 L2 收口闸逐帧否决 (实测 0/90 通过) |
| `SS_L4_INTACT_GATE=1` | 开 | L2 收口闸 (cos<0 或幅度>1.5× 否决) | 上层越界提案直接进执行 |
| `SS_L4_INTENT_LINE=1` + `_W` | 关 | 直连线注入 (另一条注入通路) | 只有直驱一条通路 |
| `SS_INTACT=1` | 关 | 标定映射接入 (需 `models/intact_action_map.json`, R² 负 → 全拒) | 用 SS_L4_INTACT 那条 |
| `ZMAX_SKILL_FF=1` | 关 | 走技能口分支 (u_ff 过原子技能) 并**每拍落 `zmax_data/ss_live/skill_gate.json`** | 闸文件永远停在旧时刻, 读它的 `moveit_plan_req.py --auto` 只能退回示教点(不报错) |

⚠️ 这两条一起才叫“引擎在发闸”: ① env 开关 ② L4 帧源 `fw_render_server`(8799 `/frame.png`) 在跑。
帧源不在 ⇒ 引擎每拍 `safe_stop`、`‖a‖=0`, 日志照打 (看着正常), 但**闸文件不更新**。
联调顺序: 先起帧源 `tools/fw_render_server.py --port 8799 --hz 2` → 带 `ZMAX_SKILL_FF=1` 重启引擎 → 回读闸文件帧龄 <1s。

**实测 (2026-09-24, 在役 `intact_l4_current`, 90 步 direct 臂)**:
`SS_L4_ALIGN=1` ⇒ 闸门 **90/90 全过** · cos 中位 −0.605→**0.963** · 幅度比 0.86 (0 帧超标) · blend **90/90** (原 0)。
闭环 A/B 同口径 3 seed × 4 臂: **消除回退** (seed1 direct 13.6mm→27.7mm, 与解析链 30.9 同级) 但
**未证明提升** (成功数与解析链同 1/3) ⇒ 不切在役指针/不进默认档。报告 `docs/design/lora_align_ab_20260924.md`;
复现 `tools/diag_lora_du.py`(带闸门内部量输出) + `tools/ab_intent_line_closedloop.py`。

**判据纪律**: 任何"注入无效/零影响"的结论, 先用 `tools/diag_lora_du.py` 打**逐级计数**
(本帧提案 → 闸门 pass/方向否决/幅值否决 → blend → u_ff 逐位比对) 再下结论。

## 🧬 模型进引擎的**只读旁路**挂点 + 口径 (2026-09-24 实测, 换靶子前必读)

工具 `tools/moe_engine_bypass.py --model {moe,dense}` (同一套框架跑两模型, 同口径可比)。

- **挂点**: 引擎 `run()` 里唯一每步一调的物理推进点是 `env.step(act)` (行 ~2637) →
  直接 `sim.env.step = hooked` 包一层。计数必须 `== 步数` (实测 52,212 帧 / 0 失败),
  这是"每帧真调"最硬的证据; 别用 `_io_snapshot`/每 5 步的 `ss_publish_metrics` (那是节流点)。
- **口径逐项 (对不上就是白测)**:
  | 输入 | 引擎侧取法 | 训练侧同源 |
  |---|---|---|
  | obs 39D | `sim._obs39()` == `env._get_obs()[:39]` | h5 `observation` (8715,39) **同源同义** |
  | px | `sim._render_frame()` → 224×224 INTER_AREA | 采集像素即 224×224 uint8 |
  | px 归一化 MOE | `float/255` → CHW, **无** mean/std | `stage_moe_backbone` 训练侧 |
  | px 归一化 dense | `to_img()` = `/255` + `(x-0.5)/0.5` | `joint_unified_backbone` 训练侧 |
  | mem 13D | `zeros(13)` | 训练侧就是 `torch.zeros(B,13)` |
  ⚠ `tr["obs"]` 是 **43D** (`perception.fuse_sensors`) 不是 39D —— 想比 39D 必须 `[:, :39]`。
- **零回退实证法**: 同 seed 跑两次 (挂钩 / 不挂钩) → `dist` 序列 `np.array_equal` 逐位相同才算只读
  (实测 10/10 seed, 最大差 0.0mm)。冷记忆隔离 `SS_MUSCLE_PATH=/tmp/...` 否则热记忆让同 seed 漂移。

### 🎯 结论: 认知头"预测下一帧观测"= 靶子定错 (2026-09-24, 两模型同证)

| 口径 | 持久基线 | MOE | dense |
|---|---|---|---|
| 同源留出 (v6 2000 样本) | **0.002972** | 0.009894 (3.33×差) | 0.015417 (5.19×差) |
| 引擎流 (52,212 帧) | **0.00042** | 0.01214 (29×差) | 0.01665 (40×差) |

机理: 引擎每步 `|Δobs|` 均值 **0.000298** vs 采集集 **0.002966** (≈10×) → 两边"预测下一帧"难度不同源,
持久基线在引擎上天然近乎完美。⇒ **不接管**; 改法是换靶子 (多步 K=5/10 或事件级: 接触/阶段切换/残余插深),
且**一律带持久基线+平凡基线同表**。与 09-06 右脑 world model "一步预测打不过纯积分先验"同一条教训。

## 🧮 流形引擎 (Manifold Engine) — L4 核心内核 (2026-09-24 老倪架构升级)

**定义**: 高维状态空间 → 低维流形, 在流形上做 表征/投影/度量/测地线导航/梯度流/有界反馈。

- 源码 `src/lerobot/manifold/manifold_engine.py::ManifoldEngine`; 画布节点 `ss_mani_eng`
  (x=7500 y=1546, L4 专家自主功能行 **前向输入前沿 4690 与输出前沿 10016 之间**);
  三件套 = `_reg("ss_mani_eng")` + `node_ss_mani_eng`(读 `module._ss_tr` 当前帧真跑) + `_EXTERNAL_LOC`
  + 能力清单 `capability_levels.py::L4-C15`。
- 复用既有真件 (别重写!): `su2.py`(群) · `manifold/lie_intent.py`(SO3/SE3 四元数) ·
  `manifold/manifold_layer.py`(接触/性能势能 Φ) · `manifold/fiber_bundle.py`(丛提升)。
- 流形注册表 **9 种 = 7 ready + 2 planned**: ready(euclidean/sphere/torus/so3/se3/su2/latent_flat);
  planned(calabi_yau 缺 Ricci-flat 度量 / hyperbolic 缺图卡) → `project()` 对 planned **拒答**,
  只返回 status/confidence=0, **不造数** (这是本仓库的红线, 新流形没实现就别标 ready)。
- 实测 (真跑引擎 160 步, `tools/manifold_engine_bench.py`): 端到端 **0.056ms/帧** · 投影 0.019ms ·
  测地线T=16 0.24ms · 上限 ~3500Hz · **约束违例 1.1e-16** · Φ 0.96→0 (向收敛态)。
- 踩过的 5 个真 bug (都写进自检): ①潜维不足 SO(3) 静默退化成单位阵 (改补齐+标注 `latent_padded`)
  ②SE(3) 12 维点 (R9+t3) 被当 9 维 reshape → 必须 `[:9]` ③"残差"要拆成 **约束违例**(验投影器, ≈0)
  与 **投影改动量**(‖p−z‖, 做置信/异常) ④反馈残差维数 ≠ 切空间维数时必须显式对齐(截断/补零+标注)
  ⑤无界岭回归解码器**外推发散**(预测幅值 3.05 vs 真值 1.0, 全段 R² +0.561→−3.55) → 必须用训练数据的
  动作界做**硬限幅**, 并**分段报 R²**(训练段/未见段) + 逐维相关, 别只报一个聚合 R²。
- 画布接入脚本 `tools/canvas_add_manifold_engine.py`: 6 条硬断言 (居中/最大空档/零重叠/全前向/幂等/行带内),
  新增"核心内核类"节点照这个模板改 X/Y 即可。

### 🧮 主标定参数 M —— 流形引擎向标定层暴露的**唯一**结构参数 (v5.16.4)
- 口径(老倪定调): 流形引擎 = 整个工程的核心结构 ⇒ 它向标定层暴露一个主标定参数 **M**(类比发动机标定的质量), **M 是系统最主要的参数**。
  物理: 等效惯量 `a=F/M ⇒ Δx=F·dt²/M`; 信息论: 交叉熵 H(p,q) 的"单位换算/曲率尺度"(Fisher/Hessian 尺度的单标量代理)。
  **M 由流形结构导出, 不是拟合出来的自由参数** — 结构决定可能性, 质量是果不是因。
  过阻尼含义: `M→0` = 现在的一阶 GD(速度∝力, 感觉不到惯性); `M>0` ⇒ 状态带**动量** ⇒ 过渡更平滑、抑制突变。
- 落点: 引擎 `src/lerobot/manifold/manifold_engine.py`(MANIFOLD_M_DEFAULT/RANGE/UNIT + `set_M()` + 有惯性二阶分支)
  · 真源 `config/calib/zmax_manifold.json` → `tools/zmax_params.py --check | --m <v> [--inertia on|off]`
  · 标定层新域 `calibration_layer.MANIFOLD_CALIB`
  · 画布新节点 `n_calib_mani`「🧮 流形引擎标定 · 主参数 M」+ 5 条前向连线(sscalib/sslat → 本节点 → ss_mani_eng/ssmani_c/ssmani_exp)。
- **零回归红线**: 默认 `M=1.0 · inertia=false` 必须与旧一阶过阻尼**逐位相同**; 判据 = 引擎内建 selftest(M=0/关 ⇒ 与旧轨迹相等)
  + `tools/manifold_M_experiment.py`(同场同起点: 关与 M=0 逐位相同; M=1 时反转 −F 后**仍沿原方向前进** ⇒ 动量可观测)。
- 画布节点改动后**须重启控制台才可见**; 若重启前有人在画布上点了「保存」, 内存旧版可能覆盖磁盘 ⇒ 重跑 `tools/canvas_add_manifold_calib.py --apply`(幂等+六断言+自动备份)。

### 🔷 主参数 M 升级为**张量** = 度量张量 g_ij(x) = M·G_ij(x) (det G = 1)
- 老倪定调: 主参数是一个**张量** —— 随状态变化的度量张量 g_ij(x), 大小 n×n, 独立分量 n(n+1)/2;
  梯度/联络/曲率/测地线**全由它导出**。
- **必须按尺度×形状分解** `g = M·G (det G = 1)`: **M 仍是那个现场单标量**(范围 [0,8]; 各向同性 ⇒ Γ=0 ⇒
  `a = F/M` 逐字零回归), **G 是形状**(各向异性 + 随状态变化)。
- 为什么非分不可: **Γ 对度量的整体尺度不变** ⇒ 弯曲只由形状决定 ⇒ 尺度与形状**可分开标定**, 互不污染;
  不分离就会「标 M 的时候曲率跟着动」, 现场根本标不动。
- 真源实现 `src/lerobot/manifold/metric_field.py`(∇Φ=g⁻¹∂Φ 用 Cholesky 解 · Γ 中心差分 · R^i_jkl+Ric ·
  测地线半步辛积分; n>8 的曲率如实降为 3 维子空间抽样)。参数化 `isotropic / diag / full`(n(n+1)/2 独立分量:
  3→6 · 6→21 · 16→136 · 43→946) + 可选状态相关项 `G(x)=G₀+Σx_k G_k`。
- 标定接口 `tools/zmax_params.py::manifold_metric()/write_manifold_metric()`; 真源 `config/calib/zmax_manifold.json`
  的 `metric` 段; 画布节点「标定诊断测量 · 主参数 M」运行即打印 dim/mode/独立分量/正定性/‖Γ‖/‖R‖/测地线偏离。
- 判据 `tools/verify_metric_main_param.py`(7 组: 独立分量数 · 正定+det G=1 · 零回归 · 解析 Γ 张量对照 ·
  常度量 ‖R‖=0 / 弯曲 ‖R‖>0 · 配置真源读写+非正定拒写 · 真跑节点报数) ✅ 23/23 PASS。
- 公式/解析对照值/两个数值坑见 `references/metric-tensor-main-param.md`。

### 📊 健康度 H 与**尺度分离** (分级口径红线)
- `g = M·G` ⇒ 特征值 λ = M·λ̃, 而 **κ = λmax/λmin 与 anisotropy 对整体尺度不变** ⇒
  **H = (1/κ)·λ_min = M·H̃** (H̃ = (1/κ)·λ̃_min 才是尺度不变的几何健康度)。
- 🔴 **分级/阈值一律落在 H̃, 不许落在 H**: 同一套形状 M=3.643 ⇒ H=0.557/H̃=0.153(良好); M=4.423 ⇒ H=4.423/H̃=1.0(优秀)
  —— 拿 H 分级会把"物理尺度变大"读成"几何变好"。对外报数 **H 与 H̃ 两个都给**。
- 口径唯一实现 `src/lerobot/manifold/health.py`(`health_from_metric(g)`/`health_from_eigvals` → H/κ/λmin/λmax/
anisotropy/status/trend); 阈值真源 `config/calib/zmax_health.json`(现场可标定) —— 别在调用处复制阈值常量。

### 🔁 闭环引擎 · 配置单→M 映射 · 集成总线 (落点分工)
- 分工: **「标定诊断测量 · 主参数 M」节点 = 配置单→M 的映射关系** · **「流形引擎」节点 = 用 M 实现功能**。
- `tools/config_to_M.py`: 显式规则表 R1 dim / R2 mode / R3 diag·components / R4 gain(待标定) / R5 scale=M(能量标定),
  每条带来源依据; 幂等以 **`m_audit_sha`** 为准(不是文件 sha —— `_updated_at` 每次都变)。
- `src/lerobot/manifold/engine_loop.py`: 度量 → H → 动力 τ=‖g⁻¹F‖ → L5(路径/系统边界/规划) → L4(认知+监督否决)
  → L3(调度) → L2(原子技能+肌肉记忆+快速反馈) → 记忆上行 L2→L3→L4→L5 → **L5 汇总回写**(调 L4/L3 增益 + 补偿 L2)。
- 集成接口 = AOI/AR 总线: `tools/engine_bus_publish.py` 把引擎信号(含 H̃)**并进 `tools/ar_aoi_bus.py` 的同一 live 文件**, 写完回读。
- 判据: `verify_engine_loop.py`(闭环完整性) · `verify_config_to_M.py`(映射/闸门/幂等) · `sil_test_engine.py`(SIL 真 trace 重放)。
- 深度(尺度分离推导/映射规则表/SIL 数字/写盘与判据两坑)见 `references/metric-tensor-main-param.md` §8–§12。
- 🔴 **映射存在 ≠ 已落役**: `tools/config_to_M.py --task <T>` 算出的是**提案**(实测摆盘 M=4.423 · dim6 · isotropic),
  而真源 `config/calib/zmax_manifold.json` 是**在役值**(实测 M=3.283 · dim3 · full) —— 两者不一致时只能报
  "映射链在、**未落役**", 绝不说"已映射/已生效"。节点侧判据 `verify_metric_main_param.py` 23/23 PASS
  **只证明映射本身对**, 不证明作业链在用这个 M。核口径 = 真源 JSON 的 `M/dim/mode` 与 `config_to_M` 输出**逐项对照**。
- 驱动扭矩 topic: `ss_torque = M·(−∇Φ)` 由 `tools/tdrive_bus.py` 发布, 落**系统服务常驻**(`zmax-torque-bus.service`,
  10Hz; 写 `zmax_data/ss_live/torque_live.json` + `torque_<场景>.jsonl` tap)。🔴 **发布器里的场景必须现取**
  (跟 `ss_scene_switch` 的活跃场景), **不许写死 `SCN-xx`** —— 写死会让 tap 文件名与场景标签长期指错任务
  (实测手跑 120s、published/errors 全对, 却整份写进了另一个场景的 jsonl)。改完重启服务并**回读 tap 的场景字段**。
  判据口径: 逐项 PASS 里**只有依赖真录像/真相机源的那几条**在办公模式必然未过 ⇒ 如实标"待现场复跑", 不算回归。

## 🎛 GUI 安全启停 (2026-09-24 血案)

- **别用 `pkill -f studio.py` / `ps|grep studio.py`**: 你的命令行里含 "studio.py" 字样 → **匹配到自己 → 自杀**
  (实测 SIGTERM -15 中断整条命令)。用 `bash tools/studio_ctl.sh {status|stop|start|restart}` (按 /proc cmdline
  精确匹配, 判断逻辑在脚本文件里所以不会自杀)。
- **venv 在仓库根**: `/home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python` (launch_studio.sh 硬编码),
  **不在** `tools/gui/` 下 → 按 tools/gui 路径匹配会永远报 "stopped" (假阴性, 实测踩到)。
- 启动脚本用 `nice` 包一层, 所以 **argv[1] ≠ 解释器**; 匹配要"任一段是解释器 且 任一段是 studio.py"。
- 改 `node_logic.py` / 画布 JSON 后: 先 `studio_ctl.sh stop` → 改 → `studio_ctl.sh start`;
  GUI 存活核验 `xdotool getwindowgeometry $(xdotool search --onlyvisible --name "XSpace Studio"|head -1)`。
- **同一份 live JSON 的发布器只许 1 个实例**: 两个 `ss_skill_dispatch` 同时在写 `skill_phys.json`, 老实例会把新实例
  刚加的字段覆盖没 (实测 a/b/c 周期性消失, 误判成"代码没生效")。重启脚本两件事必须同时做:
  ① 杀进程只认 `cat /proc/<pid>/comm` 以 `python` 开头 —— 宽泛 `pgrep -f <脚本名>` 会命中**自己的 bash 包装**
  (命令行里就有那个字符串) 把自己 SIGTERM 掉, 实测连杀两次; ② 起完回读实例数必须 == 1。

## 🐞 「断点打不进」的真相 = 分层生效, 不是 bug (2026-09-29 老倪现场: 跑L5时 move_pose 进不了断点)
- **画布 L5 档不下发真机动作**: `node_l5_loop`(src/lerobot/engineering/nodes/library.py:4643) 只读状态+触发 VLM 标注→训练; 节点 `n_moveit`(同文件 2990-2999) 只 `precheck()` + `MoveItPlan.plan(...)`, **一行 move_pose 都没有** ⇒ 断在 `arm_control.ArmController.move_pose`(src/lerobot/arm/arm_control.py:165) 永远不命中。上层只给意图/条件、执行由 L2 收口 —— 看到这现象先想"分层对", 别去改画布节点代码。
- **真机下发是另一个常驻进程**: GUI/CLI → `~/zmax_data/l2_cmd.fifo` → `tools/l2_daemon.py`(独立 pid) → `ros2 service call /move_pose|/move_line|/gripper_driver`(l2_daemon.py 325/518/916)。断点要 **attach 到 daemon 的 pid**(VSCode: Attach using Process ID), 不是另起的调试会话; 断在真实执行器里会暂停下发, 现场臂动着时别停太久。
- **别为了看下发去改 daemon**: `l2_daemon.py:79 maybe_reload(reg)` 会热加载 ⇒ 现场改码可能 reload。用只读镜像 `tools/l2_dispatch_watch.py`(tail l2_daemon.log → reports/l2_dispatch.jsonl, 分清 DRY-RUN/真发) 代替断点。
- **契约式退出码 ≠ 崩溃**: `raise SystemExit(main())` 得 1/2 = 工具按判据拒绝(VSCode 报成 "Exception has occurred: SystemExit")。真原因打在 traceback **上面**; 判断他跑了哪个模式看产物 mtime, 不要猜。
- **L5 槽位工具 0 框退出码**: `tools/l5_slot_tool.py --build-dataset` 默认只收 `status=已记录`; VLM 复核不一致 / 无 TCP 真值 / 深度未上线 → 一律停 `待确认` ⇒ 0 框 ⇒ exit 1(不是崩)。跑通管线用 `--include-pending`(仅供冒烟, 报告标注); 要真标签必须现场 `--record --slot N`(判据: 投影 ok + TCP≤3s + VLM 一致)。
- 现场拖动时的实时叠加三件套见 `sim-real-scene-overlay`: 50Hz 录制真关节+TCP(`tools/live_motion_recorder.py`) · 停顿点自动打点+实测轨迹层(`live_pause_marker.py`, origin=`trace` 黄) · 同源规划段(`live_plan_segment.py`, 两端真机真值, 按执行器守卫 ≤50mm/下降≤20mm/≤10°分段)。
- **断在具体某一召却不停 (上条的镜像)**: 三因按序分离 —— ①方法被**实例属性覆盖** (`self.accel.forward = analytic_forward`，门是 `SS_USE_MLP`) ②跑这段的是**另一个常驻进程** (引擎 loop 无 pydevd) ③模块是 `spec_from_file_location` 动态加载、**不进 `sys.modules`** ⇒ debugpy 解析不到。修法与自证见 `references/breakpoint-and-realization-notes.md` 末节 (含断点友好加载器、`真身执行 #N` 执行证据、`SS_FF_BREAK=1` 硬停)。

## 三级能力测试(L2/L3/L4)运行口径 (2026-09-29 实测)

```bash
xvfb-run -a ./gui-venv311/bin/python tools/ss_level_tests.py [--level L2|L3|L4]
```

- **必须 `xvfb-run`**: 不加会出现假失败(`无 DISPLAY 无法渲染真实帧` + `ModuleNotFoundError: No module named 'tools.gui'`); 加上即全过。
- 🔴 **现场机上不跑 L2/L4**: L2 里有**碰真机**的用例(`t_sssensor_real` / `t_sobs_realalign` 等 `t_*_real` 一族),
  在有人作业的现场跑会动真机、可能引发控制器报警(实测过一次)。现场要验回归只用离屏/离线手段,
  或先确认无人在场、臂处于安全位姿再跑; 要真机证据时单跑指定用例并提前告知现场。
- **节点逻辑迁 `src/lerobot/engineering/` 后验证层会假失败**: 审计/映射仍指旧壳 `tools/gui/node_logic.py`(已不含逻辑)。
  · `verification_layer._audit()` 用 `_MIGRATED_SRC` 同时扫【旧壳 ∪ 新真源】, 命中任一即过。
  · `_EXTERNAL_LOC` 行号随真源漂移, 须按真源实测校正: n_web_agent 1→93 · n_hil 1→157 · ss_test 111→123 · ssa/ssb/ssc 3900→3533 · ss_lat 58→55 · ss_moe 42→50 · ss_mani_eng 395→403。
- **L4 `t_sched_real` 必须放在子进程里跑**(已改, 否则套件内假失败): 它调 `lerobot.engine.runtime.quick_run(n_episodes=2, vision=False)`(真身; `tools/gui/state_space_sim_real.py`
  已是 27 行别名 shim, 老 import 路径照旧可用), 判据 **2 集 ≥1 完成**。
  同进程内跑过前面一堆用例后两集都折在 1000 步(❌ 0/2); **单独子进程跑 = 1/2 ✓**(完成那集只 395 步、夹持=True)。
  静机复跑仍然 ❌ ⇒ **不是资源竞争, 是同进程状态污染的顺序敏感性**。
  定式: `subprocess.run(["xvfb-run","-a",sys.executable,"-c",<跑 quick_run 并 print N_OK=>], cwd=REPO_ROOT, timeout=900)`,
  解析 `N_OK=` 判 ≥1 ⇒ 既保留"真跑/真渲染/env.step"的强度, 又消掉顺序敏感性(改后 L4 178/178 全过)。
  同类启示: 任何**带真环境/真渲染的合成断言**都优先子进程隔离, 别在同一个长套件里前后串着跑。

## 📊 数据空间 Trace ↔ 信号分析: 同源/固定行/归属/位姿 (2026-10-17)

两窗口 (`dds_canoe.py` / `canoe_graphic.py`) 用户会拿任意一行对账。铁律:

1. **同源 = 所有前缀都走 `live_signals.topics()` 一份快照**。面板自己读文件 ⇒ 差一拍 ⇒ 快变量看起来"不一致"。
   判据用**冻结快照后逐字比对**, 不要用 ±25% 容差 (那是给实时两窗口的假报警)。
2. **固定行: 行集合必须稳**。老行按上拍顺序、新行插同话题末尾、本拍缺失字段保留上一拍那行 (标陈旧 60s)
   判据走**增量路径**, `force=True` 是用户点刷新, 允许重排。
   同一份带 TTL 缓存 (0.25s) 的真源, 判据**不许 `sleep()` 跳窗口**: `a=read(); sleep(0.1); b=read()` 会随机跨边界 ⇒
   单跑必过、批量偶红 (实测), 看起来像被测代码出了问题。修法: **强制刷新一次缓存 → 紧接着连读两拍**再比。
3. **删层前先补归属**: `ss.node.<id>.<port>` 没规则 ⇒ 判 SYS ⇒ 删 SYS 时整类话题消失。
   真源 `config/platform/dds_topic_types.json -> nodes.<id>` (ins.producers/outs.consumers/layer);
   in 口 Tx=上游、out 口 Tx=本节点/Rx=下游 consumer。
   · **画布上有节点 ≠ 有层索引**: `attribution.layer_of` 看的是 `db.node_rows()` 的 layer, 它由
     `src/lerobot/engineering/nodes/by_level.py::LEVELS_INDEX` 兜底 —— 节点在画布里、但 LEVELS_INDEX 里没有这一条 ⇒
     layer 落 `meta` ⇒ `layer_of` 返回 **SYS** ⇒ Trace「SYS 不入表」⇒ 该节点**整族信号一行都不显示**
     (实测「🛡 安全执行边界」`sslimit` 一直在画布, 而 `sstrace.安全边界_*` 4 条一条都看不到)。
     修法是**补 by_level 的层索引**(按语义归 L2 —— 执行由 L2 收口), 不是改 attribution 的 `PREFIX_OWNER`:
     那里本来就有 `("sstrace.安全边界", "sslimit", "")` 映射, 是层判定把它筛掉的。
     验: 新开进程跑 `attribution.layer_of("sstrace.安全边界_mms")` 应从 SYS 变 L2、`tx_of` 给中文节点名 ⇒ 再重启控制台。
     同型指纹: 用户说「数据空间怎么没有 XX 这个 Tx 节点」⇒ 先查 `db.node_rows()` 里该节点的 `layer`, 不要先怀疑映射表。
4. **给表加列 = 所有 `verify_*.py` 的列下标位移** ⇒ 判据会读出"不一致 398 处"的假故障; 加列必须同步改下标或改成按列头名取列。
5. **元数据过滤会把"只有信封字段"的端口整行滤掉** ⇒ 兜底用端口名占一行, 不回信封、不编 payload 字段。
6. **位姿信号**: x/y/z 是当前 TCP (不是每技能规划点); tap 停更时用 `trace_live.末端_x/y/z`(m→mm) 代偿并写
   `pose_src/age`; 3D 出口无姿态 ⇒ a/b/c 发 -1 + 一条 QoS warn, 不许凑。偏差 >5mm 走 fail 报警, 判据要注错值验。
7. **"3D 里位姿谁规划的" = 没人规划**, 是回放 `reports/ss_episode_latest.npz` (蒸馏 MLP + 八阶段状态机 +
   L4 闸 + MuJoCo 积分); `n_moveit` 不在环里 (`PURE=False` 只直通)。先看 `npz['meta']` 再说结论。
   **物理引擎每步只吃 4 维动作** (3 轴笛卡尔增量 → mocap 位移 + 夹爪 ±1), 8 阶段不进物理 ——
   它只在上游给 target/限速/夹爪时序。契约与换算 (a_gain=ctrl_dt/action_scale, mocap 工作空间 clip)
   见 `references/metaworld-closed-loop-contracts.md` 末两节（含**四段动作 u_ff/u/u_sat/u_exec 的落点**：
   哪些有实时字段、哪些只有 npz、DDS Action 话题图上有但无 publisher）。

8. **没有连线就不许写来源** (老倪: 「实际上也没有连线啊, 在 Rx 里删掉…没有这个连接」): 闭环内部算出来的量
   (帧/总帧/时间_s/估计值/估计误差/估计抖动/残差/残差系统偏差/接触概率/净接触) 画布上没有任何一条线 ⇒
   Rx 返回 `—`; 同时**不许用 catch-all 前缀规则**把它们糊给某个节点 (实测 `sstrace.*` 兜底把残差/帧全判成
   「Z-MAX 引擎」)。能指到真正算它的 L2 节点就指 (估计→`ssest` · 残差/净接触→`ssinnov`), 纯簿记量指进程
   (帧/总帧/时间_s→`ss_dreamview`)。归属表里出现「(无话题)/(无节点)」这类后缀 = 编造连接的痕迹, 直接清掉。
   最终口径比逐条判断更简单: 3D 场景那族 (`sstrace.*`) **整族 Rx 全清成 `—`** (全空不辩), 取数来源表
   (`SS_TRACE_SRC`) 只作历史存档, 不参与显示; 只有真有连线的 `ss.node.<id>.<port>` 才写 Tx/Rx。

9. **工程连线 ≠ 被消费**: 回答"某节点用这个输入干什么"必须看节点函数有没有读该端口 (`ctx.get("inN")` /
   `PORTS_IN` / `compute()` 里出现), 不能凭 `dds_topic_types.json` 的 producers/consumers 答。实测
   `ssintact.in3` 声明了 `ssff.out2`(`zmax::FeedforwardAction`), 但 `node_intact(ctx)` 只用 `ctx["log"]`/`ctx.get("root")`,
   端口值一次都没被读; 而且方向是反的 —— `u_ff` 是 INTACT 的**输出**(`policies/intact/decoder.py` 用
   `act×K_ACT` 算), 引擎侧 `SS_L4_INTACT=1` 走的是 L4→L3 注入。凭连线答"在用它"就是编造: 要么如实说
   "画了线但实现不读", 要么提出删线 (flows JSON + dds_topic_types + 工程库三处一起改)。
   **删线的落地顺序与坑** (`engineering_db.py build` 不重建 `mw_*` 表、`busdb.json` 必须单独重建,
   否则数据空间 Trace 还显示旧线) 见 `references/trace-signal-panel-consistency.md` §11。
   顺带: 工程 JSON 的 consumers 常有重复项 (实测 `ssff.out1` 写了两遍) ⇒ 显示前 `dict.fromkeys` 去重,
   否则 Rx 出现 "A / A" 这种一眼假的样子。

10. **Tx / Rx / Layer 必须是同一个工程节点算出来的, 且这两个窗口只留 L2** (老倪最终口径:
   「数据空间和信号分析…只保留 L2 层的 topic, 删除其它层的 topic; 信号也只能显示 L2 层的信号,
   signal 是 topic 的组成单元; Tx Rx 节点只能是 L2 层节点, 其它层都删掉」)。
   · `layer_of(key)` 先取 `tx_of(key)` 的第一段再查层 —— 两条独立路径会出现「Tx=Z-MAX 引擎(L4) 但 Layer=L2」。
   · Tx/Rx 不许出现进程名/服务名/`.py`/总线标签/「本机真值流 (JSON)」; 没节点就 `—`; 出处只进 tooltip「来源:」。
   · 显示名统一走 `naming.unique_map` (75 节点 ↔ 75 唯一名, 判据断言单射); SK 节点库里是 meta、信号层按 L2,
     但归一化只认**名字以 `SK0x` 结尾**的阶段节点 (散着出现 "(SK01-08)" 的是「物理约束」, 仍是 meta)。
   · 真值流话题在画布上没端口 ⇒ 用显式 `PREFIX_OWNER` 前缀→node_id 表; **字段级规则优先**
     (`sstrace.前馈速度` 归前馈加速器, 不归前缀属主); 前缀映射 None = 不是总线话题 ⇒ SYS ⇒ 不进 Trace。
   · L2 口径只在 `attribution` 收一次 (`l2_names/tx_l2/rx_l2/layer_l2/topic_in_l2/show_in_l2`), 面板不各写判断;
     规则节点不是 L2 但前缀属主是 L2 ⇒ 用属主 (`sstrace.末端_*` 归状态估计, 不归 L4 Z-MAX 引擎)。
   判据 `tools/verify_layer_node_strict.py` (8 项, 含数据空间页三张表) 一轮锁死, 细节见 reference §13/§17。
   · 两个窗口的显示口径**不一样时**, 用一个谓词族而不是各写一份:
     **数据空间 Trace = Tx 与 Rx 都是 L2 节点** (`show_in_l2_link`), **信号分析 = Tx 是 L2** (`show_in_l2`, Rx 允许 `—`);
     判据就按“Trace 里横杠数 == 0、面板可以有”写, 别把两个窗口的硬约束混成一条。
   · ⚠️ 闸门放错层级会把整表清空: 把“Rx 必须非 `—`”加到**话题级**过滤 ⇒ in 口话题的 Rx 天生是 `—` ⇒ **0 行**。
     闸门只放在**信号/行级**; 话题级只判 Tx/Layer。现象指纹: 改完 Trace 一行不剩, 而过滤器看起来“很合理”。
   · SK 类信号 (`skill.*`) 的键不是节点端口键 ⇒ `rx_of` 天然解不出 ⇒ 整族被当横杠删掉。
     要用 SK 节点的**真连线**解析 (sssk*.out1 → n_moveit), 不要就地补个“—”。
   · 删完横杠行后, **跨窗口同源探针得换信号**: 原来探的 `sstrace.*` 已不在这两个窗口里,
     改成两窗口都存在的 (实测 `接近_mps`, 两窗口共用 203 个同名信号); 且显示可能带单位换算
     (m/s → 屏上 mm/s), 断言要按换算比而不是字面值。
   · 真实数字约定: Trace 413 行 / 61 话题 · Rx 横杠 0 · 数据空间页 话题 97 / 节点 29 / 报文 45;
     一次性回退判据: 横杠 > 0 或出现非 L2 名 ⇒ 口径被破坏。
11. **同源快照 ≠ 统一数据库**: 要"同一个数据库"就落 SQLite `zmax_data/dataspace/signals.db`
   (`src/lerobot/dataspace/signal_store.py` + 2Hz 守护 `tools/signal_store_daemon.py`), `live_signals.topics()`
   先读库 (新鲜 <3s), 过期才回落文件并打印一行, `ZMAX_SIGNAL_DB_OFF=1` 强制旧路。
   单源证明用「停守护 → 改库一行 → 续期 `meta.updated` → 两窗口同值 → 恢复真值」, 别只比对冻结快照。
   细节 (含为什么必须续期 meta、判据容差) 见 reference §14。
12. **每行重查全表 = 刷新卡死的隐形大坑**: `db.node_rows()` 无缓存被 1936 次调用累计 5.6s ⇒ 整表刷新 4.6s;
   按源文件 (mtime_ns, size) 做 `lru_cache` 键 (库重建自动失效, 返回副本) ⇒ **0.12s**。先 `cProfile` 再优化。
13. **"面板不实时更新"先查 refresh 有没有每拍抛异常, 别先怀疑数据源**: 实测 `dds_space.refresh()` 里用了
   `_naming`, 而它的 import 写在另一个函数的局部作用域 ⇒ 每 2s 一次 `NameError` ⇒ 页面冻在第一次内容,
   而 live.json/trace.jsonl 一直 1s 新鲜。凡 `refresh()/timer` 里用到的模块一律**模块级安全导入**
   (`try: from ... import x as _x / except: _x = None`), 并加一条判据: 连刷多拍不抛 + 「live 龄」跟着源变
   (`tools/verify_dds_space_live.py`)。
14. **取值/探针必须用界面真实的字段名口径**: Trace 行显示的是中文友好名, **原始字段名在 tooltip 第一行**
   (`话题:`/`来源:` 同行); 信号分析树的原始键在 `item.data(0, Qt.UserRole)` 且带前缀 (`sstrace.<字段>`);
   树只在 `show()` 之后才填充, 判据里要 `panel.show()` + 泵事件 3~4s 再读。探针写错名字 (`末端.x` vs `末端_x`)
   会安静地读到 `None`, 看起来像功能坏了。

15. **信号名必须表意: 端口名 (out1/in1) 不许直接上屏** (老倪: 「out1 in1 根本看不出来是什么意思」)。
   端口名是画布的机械命名, 语义在**报文类型**里 ⇒ 真源 `mw_topic.type`, 不是端口名、也不是话题名猜。
   · 名字只在**一个函数**里生成: `src/lerobot/middleware/signal_en.py::en_of_key(prefix, field, mtype)`。
     两张窗口 (Trace / 信号分析) 都走它, 别各写一份映射 —— 各写一份必分叉。
   · 规则顺序: `TYPE_SIGNAL_EN` 人工短名 (`MotionPlan→plan` · `MotionPlanIn→plan_in` · `RobotActionIn→action_in`
     · `OpticalInspection→aoi` · `MuscleSkillBank→muscle_bank`) → 表里没有就 CamelCase→snake_case 兜底;
     **拿不到类型就不编**, 保留原端口名。同一类型多条入口 (`in1/in2`) 只有第一条用裸名, 其余带序号 (`plan_in_2`)。
   · 类型查不到时用**行自带的 `type`** 兜底 (`type_of_topic()` 只对 `ss.node.<id>.<port>` 命中; 直播话题/别名不带)。
   · 改名放在**渲染前一次**, 原始端口名留在 `raw`/tooltip 可追溯; 别在每行的渲染循环里做 (会撞上变量复用坑)。
   · 判据 `tools/verify_signal_names.py`: 全端口 (272) 裸端口名 == 0 · Trace 行裸端口名 == 0 · 点名口对照
     (`n_moveit.out1→plan` / `in1→plan_in`)。回退指纹: 屏上再出现 `out1`/`in1` 就是口径被破坏。

16. **速度类信号统一 mm/s: 后缀 `_mms` + 只在一处换算** (老倪: 「以后不要出现 mps」)。
   · 键名用 `_mms`, **不要 `_mmps`** —— 后者仍含 `mps` 子串, 违反用户口径; 也别用 `_m_s`。
   · **换算点只有一个: 生产端** (`ss_dreamview.publish_trace_live` / `ss_fw_trace_pub` 写值时 m/s×1000)。
     显示层**不许再按键名后缀乘** —— 旧 `canoe_graphic` 有 `if "_mps" in k: v *= 1000`, 改名后照样命中就二次放大 1000 倍。
     规则: 单位换算不能靠"键名后缀"判定, 后缀只用于**标注** (图例/Y 轴 `(mm/s)`)。
   · **契约内部仍是 m/s**: DDS 的 `v_cap`、`gravity_table`、物理约束表这类消费端读到 mm/s 键要显式 `/1000`,
     别顺手把内部契约也改成 mm —— 改的是信号口径, 不是接口单位。
   · 注册表同步: `config/topics/scene_tags.json` 的场景信号名 (真源在 `data/database/zmax/sources/config/`, **不在 git**,
     所以 `git add config/...` 会 exit 1 —— 那是软链到工程库 source); `signals.db` 里旧 `_mps` 行要顺手清,
     否则面板新旧两套名同时存在。
   · 验收: `tools/verify_trace_sync.py` 的「速度类信号单位 = mm/s」「数值口径 ±25% 越界 0 例」两行 + 现场采 2~3 帧看值在
     **同一量级且逐帧变化** (例: 插入段 10~32 mm/s、阶段限速 85 / 350 / 120 mm/s)。数值从 0.03 直接变 30 才叫改完。
   · 还有人改口径时把旧名留在注释/文档里: 只要**键名**不再出现 `mps` 即可, 注释里解释历史可以, 但别让字符串再进注册表。

全过程 (判据代码骨架、实测数字、报警注入法、归属单链、统一库、刷新性能、**L2-only 收口与闸门顺序**) →
`references/trace-signal-panel-consistency.md` §1–§17

## 关键文件
- src/lerobot/engine/runtime.py (闭环总装 `RealStateSpaceSim`, 4240 行零 Qt; 原 `tools/gui/state_space_sim_real.py`,
  那边现在只剩别名 shim `sys.modules[__name__] = 真身`。**三层身份别混**: 总装 runtime ≠ 流形引擎节点
  `ss_mani_eng`→`src/lerobot/manifold/manifold_engine.py` ≠ 物理积分(metaworld/MuJoCo 内建)。
  改物理保真度动 metaworld 参数与动作缩放 `a_gain`/`action_scale`; 改控制律/阶段时序才动 runtime.py)
- src/lerobot/policies/left_right/state_space/{parallel,perception,cognition,dynamics,execution,safety}.py
- tools/gui/state_space_sim.py (HOLE_POS 常量 + ff_forward 真权重 + _stage_target)
- tools/gui/node_logic.py (node_ss_s2 分派 + _EXTERNAL_LOC 映射, 行 2062-2075)
- tools/gui/node_logic_dialog.py (_load_source 源码展示优先级)
- tools/ss_verify_trained.py (训练权重替换验证)
- tools/gen_insert_video.py (真机同构: YOLO detect_3d 解算写 obs[36:39])
- 数据空间(DDS 总线)的信号表与关键词、MoveIt 规划/action 取数地图（含"域是 42""action 话题默认隐藏"
  "规划结果走 get_result 服务不走话题""`tcp_path` 只存 x y z""姿态比对只能用四元数夹角"）
  → `references/dds-bus-signal-map-and-moveit-action.md`
- **末端位姿 x/y/z/a/b/c 的真源与坐标系口径**（仿真 episode 不记姿态 · 真机走 `rokae_sdk/tcp_out/latest.json`
  `frame=base_link` · 现场世界系须标定才存在 · `ss_live/trace_live.json` 是单槽会被不同任务互相覆盖）
  → 同上文件末节「末端位姿 x/y/z/a/b/c 的真源与坐标系」
