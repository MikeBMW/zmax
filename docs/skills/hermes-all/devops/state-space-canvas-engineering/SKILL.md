---
name: state-space-canvas-engineering
description: "Use when 改 Z-MAX 状态空间画布(加节点/改接线/重排/清节点)且要保证不把画布改坏。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [canvas, topology, state-space, zmax, verification, links, layout]
    related_skills: [web-agent-canvas-bridge, zmax-state-space-architecture, zmax-console]
---

# 状态空间画布工程 (改节点/连线/拓扑的安全做法)

> 深度参考: `references/node-source-mapping-and-run-button.md` — 节点右键「打开源代码」三层解析（节点 params.source → 中间件 SOURCE → registry file:line，id 失配也能开）；画布「▶ 运行/■ 停止」按钮点亮、写点只读拦截、stop_sim 先解播放态。

## When to Use
- 用户要求"加一个节点""把它接到 X 后面""所有 Y 都要进 Z 节点""整理连线/不要交叉/删掉不相关节点"。
- 任何要写 `flows/state_space_obs.json`（画布真源）的改动 —— 包括只加 1 个节点。
- 画布出问题要定位（"连线都没了""节点不显示""控制台起不来"）。

## 铁律: 验收是有层级的, 上一级通过**不代表**下一级通过
| 层级 | 手段 | 只查这一层会漏什么 |
|---|---|---|
| ① 语法 | `ast.parse` | 常量未定义 (`_REPO` 不存在) → 导入即炸 |
| ② **导入** | 真 `import` 一次模块 | 节点 type/端口不合法 → 加载循环中断 |
| ③ **渲染** | 离屏真加载, 数 item | 连线静默全丢 (见下) |
| ④ **字段契约** | 实测服务返回键名 | 闸门读空值 → 静默拒绝执行 |
| ⑤ 运行 | 真跑一次 + 看 Traceback | "改完就好" 的假成功 |
| ⑥ **交互** | 真点一下按钮/双击一次节点, 看目标界面到底变没变 | 日志写了"成功"、画布纹丝不动（handler 里根本没有回画布的代码路径，或副作用静默失败）；**反馈落在节点小字/底部日志栏 ⇒ 用户仍然报"没反应"**（见下节"长任务触发器"） |

**改画布最低要求 = ②+③+⑤**；动到按钮或节点交互的改动必须再加 ⑥。`tools/verify_canvas_render.py`（离屏真加载 → 打印 node items / link items）是标准工具。

## 三类"看起来对"的致命坑 (2026-09-26 实测)
1. **节点 `type` 必须是注册表里的合法值**
   写成 `"node"` → `add_node` 抛 `KeyError` → **`load_flow_file` 的节点循环当场中断 ⇒ 该节点之后的所有连线一条都不建**。
   现场表现极具误导性: **节点 88→87 而连线 167→0**（用户只会看到"画布连线怎么都没了"），异常被吞成一行 `⚠️ 工作流加载部分失败`。
   构图工具里加 type 白名单断言；合法例: `model` / `data` / `hardware` / `condition`（背景行条是 `bg`/`row_bg`）。
2. **端口必须是字符串列表** `["in1","in2"]`
   历史节点里混着 `[{'id':'out1','label':...}]` **字典格式**（本次归一了 ssff/sssched/ssdec 三个）→ 断言/渲染都可能踩。
   归一后把原标签存进 `params._port_labels`，不丢信息。
3. **接线用的常量先 grep 确认存在**
   本次在 `node_logic.py` 的新 `_EXTERNAL_LOC` 条目里用了**不存在的 `_REPO`** → `NameError` 阻塞整个 GUI 导入 → **控制台起不来**（语法校验完全看不出）。
   对照既有写法（如 `_YOLO_DIR`）先确认常量；改完**重启控制台并确认 `Traceback=0`**。

## 加节点标准流程 (六断言 + 备份)
`tools/canvas_add_*_node.py` 的既有范式，逐条断言后才写盘：
1. id 唯一 2. 坐标 int 3. **零重叠**（`bg`/`row_bg` 整行矩形**必须排除**在重叠判定外）4. 落在正确行带
5. 端口存在且**前向**（`f.x + f.w <= t.x`）6. 无重复连线
写盘前 `shutil.copy2` 到 `flows/_archive/state_space_obs_before_<事由>_<ts>.json` 并**打印还原命令**。

**只加一条连线的改动, 验收 = 证明"现有连线一条没动"** (用户最在意这个, 说"现在的连线还很整齐"):
把 `_archive/` 改前快照的 links 与当前 links **剔除新增那条后**逐条比对 —— 各自 `json.dumps(l, sort_keys=True)` 排序后
判相等 + 节点 id 集合不变。**别拿两边的汇总 md5 直接比**: 各人 canonical 形式不同, md5 值本来就不一样,
结论是"逐条相等"这个布尔量(子代理报的 md5 和你复算的对不上 ≠ 它改坏了)。
渲染级连线项比 JSON 少 1 是**既有重复 (f,t) 对被 add_link 去重**(改前同样少 1) —— 别去找那条不存在的线, 也别当成本次丢线。
新线要落成"左进右出": 选源在它所在行带的**左端**、目标在另一行带**右段**, 天然满足 `f.x+f.w <= t.x`,
不许为了接线去挪任何现有节点(挪节点才是把画布搞乱的主因)。

## 新增连线的约定 (端口 + 连线, 2026-10-09 沉淀)

### 🔴 同一对 (源,靶) 只能有一条边 —— GUI 会静默去重

`tools/gui/simulink_module.py::add_link`: 已有 `lk["f"]==src and lk["t"]==dst` 就直接 return (只打一句
`⚠️ 连线已存在`) ⇒ JSON 里写下 202 条、渲染只剩 200 条, `tools/verify_canvas_render.py` 判据 (容忍 N−M ≤ 1)
直接变红, 而新加的那条**在界面上根本看不到**。

想表达"同一对节点之间两条语义不同的流" (例: 🧪状态校正器→📡融合定位 已有回灌边, 现在还要"大偏差"边) 时:
* **起一个真新节点做仲裁/分流** (例: ⚖物理约束闸 收 8 个技能的动作 → 出 可行动作/小偏差/大偏差 三路),
  再接向各自目标 ⇒ (源,靶) 对天然唯一; 新节点就是代码真身 (`physics_constraints.InertiaLimiter`), 比给一条边塞两种含义诚实。
* 落盘后自己先算重复对: `len(links) - len({(f,t) for l in links})`, 必须 ≤ 1 (那 1 条是历史遗留);
  再跑 `verify_canvas_render.py` 看「文件 N / 渲染 M」。
* 顺带: 往行里插节点会挪 `fn_id` (描述真源 `function_notes.json`/`config_meta.json` 静默错挂,
  判据只看得见"空描述"看不到"错挂")——修法 `tools/fix_function_notes_align.py` + `tools/config_meta.py build`,
  细节见 zmax-console::references/canvas-insert-shifts-fn-id.md

- **端口一律字符串列表** (`["in1","out1"]`); 历史遗留的 `[{'id':'out1','label':...}]` 字典格式要先归一(原标签存 `params._port_labels`)。
- **新线必须前向**: `f.x + f.w <= t.x`(源节点右边界 ≤ 目标节点左边界), 否则渲染成交叉/反向线, 被断言拦下。
  **例外 —— 用户点名要的闭环反馈线**: 语义上就是"下游结果回灌到上游"(物理状态回灌 / 观测反馈 / 记忆汇聚)
  的线**必然是反向**, 照接、用 label 写明闭环反馈、交付时**直说它是反向的反馈线**;
  绝不为凑前向去挪语义节点或干脆不接。此时判据换成「前向率 ≥97% + 反向线逐条列出源→靶+Δy」。
- **新增线不得改动任何已有连线**: 写盘前后把 `links` 各自 `json.dumps(l, sort_keys=True)` 排序, 剔除新增那条后**逐条比对相等** + 节点 id 集合不变(别只比汇总 md5)。
- **写盘只走 `flows.save_canvas()`**(自带校验 + 备份); 手工改 JSON 前先 `shutil.copy2` 到 `flows/_archive/state_space_obs_before_<事由>_<ts>.json` 并打印还原命令。
- **范例**: `ssbypv:bypass_out → ssact:in1`(线 id=`lkbypv_net`, 2026-10-09, label「上网通道状态 → 执行器 (借道 proxy 回显)」) —— 源在旁路可视化行左端、目标在自主体行, 前向 `980 <= 15666` 成立;
  加后 **89 节点 / 184 连线(JSON)**(渲染级 183, 少 1 是既有重复 (f,t) 对去重)。剔除该线后与改前**逐条完全一致**(canonical md5 `d6ec2c763de1dac2cef1b543ffaa728f`)。
- 🔴 **跨行接线前先看两端的 x 极值**: 可视化行(`ssbypv`)在整图**最左端**(x≈700), 而 L4/L2 行的业务节点在 x=1500~19000 ⇒
  任何"业务节点 → 旁路可视化"的线**必是反向**, 一定被断言拦下(别花时间试)。要交互就走**数据面**:
  节点写状态(`_SS_STATE[...]` + `reports/*.jsonl`), `SSBypassView` 里加一个**区块**去读它
  (照「🛰 上网通道」区块的既有范式: 同款 `CurveWidget` + 一个 `*_status_line()` 汇报函数);
  若用户要"画布上看得到这条线", 就在**可视化行右端另开一个轻节点**接住(前向成立) ——
  **绝不为了连线去挪 ssbypv 或任何既有节点**(挪节点才是交叉变多的主因)。
- 🔴 **接线 ≠ 被消费 (上一条的镜像)**: 加完线要分清它是**状态线**(只回显)还是**控制线**(真驱动下游) ——
  大多数新加的线是前者, 而用户默认理解成后者。落法:
  ① **上游那个函数真被调用**才有内容输出: 若节点逻辑里只有 ports 声明、没人取那个值写日志/回传, 输出口就是空口
  (应像 `library.py` 的旁路可视化节点那样, 汇报函数里加一行取 `net_channel_status_line()` → 写日志行);
  ② **查下游有没有从该口读值** —— 执行器不读, 就不是控制线;
  ③ 交付时**直说**"这条线目前是状态回显, 不驱动动作", 并把数据真源给出(状态 JSON 绝对路径 + 节点日志行前缀),
  别让它听起来像"已经接通控制了"。
  ④ 🔴 **实现里取不到的输入 = 装饰线, 引擎里 `ctx` 是端口表不是参数表**: `Node.step` 里 `ctx = self.pull()`
  ⇒ `{port: {value, age_s, fresh}}`, **没有 `params` 键** ⇒ 任何 `ctx.get("params")` 取参数在引擎里**恒为空、静默走默认值"
  (GUI 双击演示会传 params ⇒ 本地自测完全看不出来, 到引擎里才发现"用户改了参数没反应")。
  取上游值的写法 = `(ctx.get("in1") or {}).get("value")`; 取参数/入边/共享态要写 **参数→入边→共享态→默认** 三级回落。
  🔴 **让 A 真的喂 B = 三件套, 少一件就是装饰线** (实测: plan 段要喂进机器人执行器):
  ① **画布连线** `A.out1 → B.in1` (改前 `cp` 备份 JSON, 加后回读确认出边存在);
  ② **常驻循环白名单**: `zmax-ss-canvas-loop` 的 `ZMAX_CANVAS_ONLY` 只 step 列出的节点 ——
     加了线但 B 不在白名单, 那一拍 B 根本不跑, 现象是"连线在、下游不认"; 支持逗号
     (`ZMAX_CANVAS_ONLY=ssplan,ssact`, 走 drop-in `Environment=`), 判据读
     `zmax_data/ss_live/canvas_loop.json` 的 `only` / `n_ran` / `cost_ms` / `traces[].status`;
  ③ 🔴 **消费实现必须在外壳早返回之前取输入**: 壳 `compute()` 里 `if not PURE: return _passthrough(ctx)`
     在调用实现**之前** ⇒ 只在实现里读 `ctx['in1']` 等于永远读不到 (PURE=False 的节点尤其)。
     要真消费就在那句之前拦: `seg=(ctx.get('in1') or {}).get("value")`, 命中条件就干真活并
     `return {"out1": out}` + 在 `LAST_STATUS` 写明"由哪一层驱动", 这样 traces 里读到的是"实现执行…"
     而不是"直通"。安全类节点还要在这里守规矩: 授权没开只写渲染/观察用文件, 绝不写下发 FIFO。
  ④ 段类信号要带**段内累计时间**(`elapsed_s`): 14 件循环里同一段 a/b 端点会撞, 少了它消费端无法
     判断"这是第几件", 手里/孔位状态会错位 (计划节点 `out1` 就要一起给, 别只在写文件那条路补)。
  验证四证(缺一条就是没接上): ① `canvas_loop.json` 两节点都在、下游 status 是"实现执行…"
  ② 下游落盘产物 `age < 1s` ③ 服务端只读端点 `fresh=true` 且带 `src/from` ④ 消费端自己的"驱动源"
  字段真变成下游节点; 再加一条反向证据证明没越界 —— 如真机零指令时 `zmax_data/l2_cmd.fifo` 的 mtime 未变。

  "输入不通"的三处断点 (外壳 `PURE=False` / 实现 `return True` 非 dict / 写 `_SS_STATE` 没人读) 与
  不靠 GUI 的 trace 判据 (必须先 `systemctl stop zmax-ss-canvas-loop`, 否则读到的 trace 是常驻循环的):
  `references/wiring-contract-and-rewire.md` §8。

## 新增节点 = 画布 + 节点逻辑 + 库同步 (少一件就是装饰节点)

用户说「这个功能也要做一个节点, 我要看到」时, 三件套缺一不可:

1. **画布**: id / layer / 坐标 / 端口 / 连线 (写盘走 `flows.save_canvas()`)。
2. **节点逻辑** `src/lerobot/engineering/nodes/library.py`:
   `def node_xxx(ctx)` + `_reg("<key>", [关键字…], "<显示名> (真源: <文件>)", node_xxx)` +
   `_EXTERNAL_LOC["<key>"] = (<外部实现文件>, <起始行>, "def ...")`。
   只改画布不注册 ⇒ 节点在图上但双击落兜底, 注册表里也查不到它。
3. **库同步** (画布改了不会自己进注册表): `db.ensure_synced()` 或 `tools/mw_db.py sync`
   → `tools/engineering_db.py build` → `tools/gen_topic_types.py`。
   判据三件一起看: `len(db.node_rows())` 比改前 +1 · `config/platform/dds_topic_types.json` 的 `nodes` 里有该 id ·
   该节点每个新端口的 type 都不是兜底的 `zmax::SSNodePort`。
   🔴 **顺序不能换: 先 sync 再 gen_topic_types** —— 反了的话 gen 读到旧的 port 集合, 只加出已连的口
   (实测新增一个 `out2` 后仍写 114 出口, 补跑一次才 115); 口数没变 = 那个口没进库, 回去查它有没有真连线。
   只跑 `engineering_db.py build` 是不够的 —— 它不重建 `mw_node/mw_port` (画布 sha 没变或没调 sync 时,
   库里仍是旧节点名, 症状=「画布改了, 数据空间还是旧名字」）。

   🔴 **`tools/gen_topic_types.py` 有一张硬编码 `NODES` 映射表, 新节点不在表里它就 `exit 2`**:
   `❌ 注册表缺节点: ['<id>']` —— 这一行把整条生成链停住(话题类型不更新, 数据空间里没有该节点的任何话题),
   而节点本身在 registry/画布上都是好的, 现象很像"加了节点却没通电"。加节点时顺手补一条:
   `"<id>": ("<TypeName>", "<中文名>", {"out1": "<PortType>"})`, TypeName 全局唯一;
   补完跑一次, 判据 = 打印的总数(节点/出口/入口)回升 **且新 id 在 `config/platform/dds_topic_types.json` 里出现**。

### 🔴 端口是**连线派生**的: 声明了但没接下游的端口 = 不存在
`middleware/spec.py::parse_canvas` 的 `Node.inputs/outputs` 由 **links 两端**收集, 不看画布 JSON 里的
`inputs/outputs` 声明 ⇒ 给新节点预留 `out2` 却没接到任何下游时, 工程库里根本没有这个端口,
`mw_port` 查不到、Trace 里也没有它。
要么给它一个**语义正确的真下游**再落盘, 要么先只留已连的端口 (别在交付里许诺一个查不到的出口)。
新增**入口**同理: 判"哪个口还空着"要扫 `links` 里该节点的所有 `t_port`, 不要看节点自己声明的 `inputs` ——
声明与连线不一致是常态 (实测某校正节点声明 `in1~in3`, 而 `in4` 早已被上游占用), 按声明挑口会撞车。

## 🔴 槽位/孔位必须从工程配置读, 代码里不留坐标常量 (2026-10-28)

老倪: 「每个槽位的位置, 要通过工程配置的点读出来, 然后由 plan 节点进行规划」
—— 原状态是**三套坐标各说各话**: 段表槽位写死在 `tools/sim_insert_plan.py:27` 的 `SLOTS`,
真机示教点在 `taught_points.json`, 画布/面板又各读一份。

**真源分工 (frame 不同, 不许混用)**:
| 文件 | frame | 单位 | 内容 |
|---|---|---|---|
| `config/points/cell_points.json` | `sim_base` | mm | 14 槽位 / 4 孔(孔口+插到底) / golden / 4 侧面 / 2 废料 / layout(lift,trav_z,dy_lower,half_w) |
| `data/skills/l2_atomic/taught_points.json` | `base_link` | 米 | 现场示教点位 (slot1..slot7 / insert_pose / 插入口_1020 …) |
| `config/calib/zmax_calib.json → cell_geometry.points` | `base_link` | 米 | 示教几何 (peg_head/hole …) |

实测两系差: 槽位 y 几乎相同, **x 约 -157mm, z 约 +8mm** ⇒ 仿真基座系≠真机 base_link,
拿 sim 点去真机规划必错 (所以 plan 节点要**拒 frame_mismatch**, 不做"差不多就乘个系数")。

**落法**:
- `src/lerobot/engineering/nodes/points_source.py` = 唯一点位入口: `find(name, frame)` / `slot(n, frame)` /
  `list_points(frame)` / `sources_status()`; 单位按文件声明换算 (米<10 ⇒×1000), 返回值带 `src`(文件:键) 与 `ts`。
- 规划节点 `plan_impl.py` 的 `in1` 认 `{"point":"slot5"}` / `{"slot":5,"frame":...}` / 裸 `{"tcp":[..]}`;
  起点是真机 TCP 真值(base_link) ⇒ 目标 frame 不是 base_link 就 `reason=frame_mismatch` 拒出段表;
  输出必带 `goal_src/goal_frame/goal_name/goal_ts`, 让"这个目标点从哪个配置来"可追溯。
- 段表生成器 `tools/sim_insert_plan.py` 顶部**只读配置**, 读不到 `raise SystemExit` 拒跑 (`ZMAX_CELL_POINTS` 可换文件)。
- 段表消费者 `plan_long_impl._load()` 加**新鲜度闸**: 配置 mtime > 段表 mtime ⇒ 拒跑并打印重出命令。

**判据 (缺一条就是假同源)**:
1. 用同一份配置重出段表 → 与旧段表**逐段数值零差异** (只允许 JSON 类型 int→float 变);
2. 改配置里 `槽5` 的 y +10mm → 重出段表, 只有 **9 段** (槽5 抓取 5 段 + 下料盘落位 4 段) 变,
   其余 **383 段零变化** —— 这正是"配置驱动"的反证法 (全变 = 没接上, 全不变 = 仍在读常量);
3. `touch` 配置让 mtime 比段表新 → 画布循环 `_load()` 必须拒跑并给出重出命令; 重出后恢复 392 段。
4. 真机侧: `{"slot":5,"frame":"base_link"}` → 段表目标 = `taught_points.json:slot5` 的数值;
   `{"slot":5,"frame":"sim_base"}` → 必须 `frame_mismatch`。

## 🔴 L2 视觉 3D 观测点 → plan 只消费不看相机 (2026-10-28 契约)

分工铁律: **识别+2D→3D 在 L2 感知节点, plan 只吃位姿**。把相机/推理塞进 plan 会把相机独占、
传感器依赖、误差归因全拖进规划层 (段表偏了分不清是识别错还是分段错)。

**正式写者 = 画布节点** `🎯 YOLO 目标检测` (`ss_yolo` → `library.node_ss_yolo`), 不是 tools 脚本:
节点跑完 `align` 后调 `engineering/nodes/vision_points.publish_from_det(det3d, det2d, meta, ...)`;
`tools/vision_points_pub.py` 只是人工/回放入口, 复用同一份 `vision_points.write()`。

源可切 (节点级, 不新开节点): `ZMAX_L2_SRC=sim|real` (默认 sim)
- sim: metaworld 渲染帧 + 仿真域权重, `detect_3d_meta` 给 `frame="world"`;
- real: `_yolo_capture_real()` 取 `zmax_data/ss_live/cam_*.png` 最新帧 + **真机在役权重** `models/yolo_peg_live.pt`
  → 2D 框/conf → `K + T_base_cam + plane_z` 射线∩台面 得 base_link mm。

契约 `zmax_data/ss_live/vision_points.json`:
`{t, ts_str, frame, units:"mm", verified, source:{kind,cam,K_src,ext_src,depth_src,gaps[],notes[]}, points:{名:{pos_mm,conf,err_mm,ts,cam}}}`
`verified = (frame=="base_link") and not gaps` —— 所以仿真点**永远 verified=false**, 拿不去真机规划。

plan 侧 (`plan_impl.py`) 吃 `in1={"obs":"光模块·当前"}` / `{"point":"obs:<名>"}`, 三道闸按序:
`frame!=base_link → frame_mismatch` · `verified false → obs_unverified` ·
`conf < ZMAX_PLAN_MIN_CONF(0.7) → low_conf` · `age > ZMAX_PLAN_OBS_STALE_S(2s) → obs_stale`;
段表带 `goal_src/goal_conf/goal_err_mm`。

**实测 (2026-10-28)**:
- 节点 sim 源 → 3 目标 (conf .97/.98/.97), 写文件 `frame=world verified=false`; plan 取它 → `obs_unverified`
- 节点 real 源 → `cam_rs.png` 123182s 陈旧 + `T_base_cam`/`plane_z` 未标定 ⇒ 0 点, gaps 三条如实写盘
- 人工 base_link 点 (verified=true, conf .92) → plan 11 段, 末段 `abs_mm` = 该点; 验证完**删文件**不留假观测

🔴 **`ss_yolo` 壳是 `PURE=False`** ⇒ 常驻循环 (`prj.step`) 里只直通不执行实现; 要让它在流水线里真跑,
要么 GUI 单步/双击走 `engineering.runtime.execute_node_logic`, 要么给它一个低频宿主循环 (≥0.5Hz 级以上别开 ——
metaworld 渲染重), 真机源建议 `ZMAX_L2_SRC=real` 低频常驻。

## 🔴 Plan 节点必须自己算段表 (tools 脚本降为薄壳) — 2026-10-28

老倪: 「所有层的所有节点，要真正的状态空间代码执行」⇒ 预烤段表喂节点 = 假执行。

落地形态 (`src/lerobot/engineering/nodes/cycle_plan.py`):
- 规划**本体**在节点侧 `build()`（纯计算, 返回 dict; 不写盘不下发）; `write(out)` 才落盘;
- `tools/sim_insert_plan.py` 只剩 `CP.build() + CP.write() + 打印` (旧实现备份在 scratch);
- `plan_long_impl._self_plan()`: 每次加载先自算, 与磁盘表**同配置指纹**时逐段对拍
  (段数/kind/t/端点 ≤0.01mm), 不一致或异常 ⇒ **回退磁盘表**并记 `plan_src=disk(原因)`;
  配置改了 `cfg_sha` 不同 ⇒ 直接以自算为准, 不再要求人重出段表。

判据 (可复现): 自算 vs 磁盘 392 段 **0.000mm / 0 处时长差**; `plan_src=self`; 现场 `ar_cmd` 帧龄 0.01s。

## 🔴 感知节点读视频 (真机帧/实时流不在时仍能真感知) — 2026-10-28

`ZMAX_L2_SRC=real` + `ZMAX_L2_VIDEO=/abs/x.mp4`: 节点每次被调度 = `cap.read()` 下一帧 (真读视频,
不是拿静态图冒充); 0 检出时按 `ZMAX_L2_VIDEO_SCAN=24` 扫帧找目标, 扫完没检出就如实报; 播完回卷。
帧号/帧率/扫描帧数/box/conf 全部写进契约留证。

metaworld 渲染 = **MuJoCo** 离屏渲染器 (`env.render()`; 无 X11 用 `MUJOCO_GL=osmesa`),
所以仿真帧和真机 `cv2` 帧可以走**同一套节点代码 + 同一套契约**, 只换 `src`。

### 节点要显示"正在执行的计划/执行状态" = plan 出段表 + exec 收口 (两层, 判据要对账)
用户说「执行器也要做一个节点, 我要看到」时, 别把执行器整包搬进规划节点:
**plan 只做"意图 → 段表", exec 保留 授权/闸/下发/等真值/台账**。闸门挪到上游 = 谁能动臂多一个入口。
- 🔴 **plan 节点给的 token 序列 ≠ 几何规划, 别把两者当同一件东西接起来**: `left_right/state_space/planner.py`
  的 `TaskPlanner.plan(指令)` 返回原子技能 token 表 (NPO0xx/XPO0xx), **不带任何几何量** (目标点/槽位/接近方向/速度)。
  实测「从左料盘运送光模块到右料盘」与「把 7 号位的光模块插到孔 1」给出**同一串** token 且夹带语义无关项
  ⇒ 直接接到 ar3d/轨迹链路, 页面写着"状态空间规划"而几何仍是脚本写死的 = **假规划**。
  接之前先让 plan 输出**带几何的结构化计划** (技能 + 目标位 + 方向 + 速度档 + 后置条件);
  判据 = 同一技能换目标点时几何跟着变 · 两条不同指令不能给出同一串。
  🔴 **为什么不同指令出同一串: `_KW_MAP` 每阶段只收完整词** (取料/对准/插入/检测/拔出/分拣/运输)。
  自然说法「先插QSFP模块, 测完把Pass的放到右边料盘」命中**0 个阶段** ("插"≠"插入"、"测"≠"检测"、"放"≠"放料"),
  而「插入光模块」只命中 1 个 (阶段数 <2 也退默认主链) ⇒ **规则模式对绝大多数自然指令都是同一条默认链**, 别把"指令进去又出来"当规划成功。
  这个词表在 `planner.py` 里 —— 用户可能明令**不许动规划算法源文件**, 此时只有两条路: 在**节点层**做同义词归一化 (library 里的 ins 预处理), 或配 `llm_url` 走已有的 `_plan_llm`。
- **段表落盘**: 规划完先写 `zmax_data/runtime/plan/plan_latest.json` 再执行 (skill / backend=rule|moveit /
  n / segs[{id,pos,speed,dir,lin_mm,service}]), 一次规划一条, 与真执行的表**同一份**——不要另算一份给界面看。
  🔴 **两条规划路径都要落盘**: 多阶段技能走 `run_stages`, 方向键/单点回位走 `build_move` —— 只在一处落盘时,
  plan 节点“只有空间点才有信号”, 用户点方向键就以为节点坏了。落完各跑一次(方向键一条 + 空间点一条)看 n/seg。
- **请求值同表对账**: 把页面来的 `req_speed` / `req_manual_point` / `req_auth_epoch` 与"实际用的 speed/段长"
  写进同一张表。用户问的永远是"页面设的值到底用上了没", 只有同表才答得了; 判据 `abs(req_speed - speed) < 1e-6`,
  不一致就显式记差值, 不要只留实际值。
- **执行状态两个文件**: `exec_state.json`(5Hz: phase/seg/n_seg/target/residual_mm/transport/blocked_by/auth_epoch/t_pub)
  + `exec_events.jsonl`(每条受理/拒绝/到位追加一行)。都**只读观察**, 不改控制流。
- 🔴 **落盘/状态写入函数的异常不许自己吞掉**: 一个 `try/except` 包住整个 `plan_dump`, 里面因**变量名复用**
  (spec 字典与速度列表都叫 `_sp` ⇒ `sum(dict)` 抛 `int + str`) 抛错, 只在日志留一行"落盘失败(不影响执行)",
  文件几小时没更新, 而日志看着像成功。两条铁律: ① 写产物的函数里变量名逐个别重复;
  ② 验收看**文件 mtime + 新字段在不在**, 不信日志里那句"已落盘"。
- **字段名要说功能, 不说位置与序号**: 名字 = 物理量 + 单位后缀 (`travel_mm` / `speed_gain` /
  `arrive_error_mm` / `stage_total` / `target_rx_deg`), 不用 `n_seg` / `v_page` / `seg1_mm` / `tgt_x` /
  `mps` 这类缩写 —— 用户在 Signal 列里唯一能用的线索就是名字, 看不懂就等于没接。
  一条命令只发**能回答问题的量** (位姿 6 自由度 / 多远 / 多快 / 速度被压到几成); 恒等值与重复项
  (`t` 与 `t_pub` 重复、每段 `id`、`service`、每段 speed 等于均值、窗口已有的帧龄列) 一律不发。
- 🔴 **配额是硬约束: 每节点 ≤10 条, L2 总数 ≤100 条**, 由**一处**策略模块 `middleware/signal_policy.py`
  统一裁决 (白名单制 + `filter_rows` 改名/去重/截断), Trace 与信号分析共用; 数学/审计层节点默认屏蔽。
  判据 `tools/verify_signal_policy.py` (7 项)。落法、命名表与坑: `references/message-signal-db.md` §7c。
- **抬升/横移/下落按相邻目标点的实际位移归集, 不按阶段标签**: 阶段 note/`dir` 会写反 (实测某段标 `↓下降`
  实为竖直段) ⇒ 规划时把**起点**一起传进落盘函数, 用逐段 Δz 与 Δxy 判 role, 两个窗口只读聚合值不再各自解析。
- 判据模板(可复制)`tools/verify_exec_node.py`: 节点在库且层对 · 每个端口有类型 · 上游/下游是真连线 ·
  进程在跑(argv 精确匹配) · 状态文件帧龄 ≤5s 且 phase 合法 · Trace 里 Tx=节点名且有实测值 ·
  段表 n≥1 且每段有 pos/speed · req_* 与实测可对账。

### 🔴 验收脚本别写死节点/信号条数
判据里 `len(NAMESET) == len(rows) == 75` 这种写法, 加一个节点就整条变红, 而红的原因不是缺陷。
判据用**关系式** (`名数 == 节点数`, 唯一性单射), 把具体数字放进 detail 打印, 不进断言。

### 🔴 耗时/帧率类判据会因并发跑而假红
断言“N 次刷新 < 1s / 帧率 ≥ X”这类**时序阈值**的判据, 和别的判据 (或 GUI/采集器/录制进程) 同时跑时
会因抢 CPU 超额而变红 —— 实测同一条判据并发时 5 次全部超 1s, 单独复跑 0.76s 通过。
规则: 时序型判据**单独跑一次**再定回归; 要进批跑就改成“相对基线倍数”或“单次重建 << tick”这类不随机器负载翻转的关系式。

## 配置项不要做成"可视化层节点" (写入口只能有一个)
用户问「页面上的配置点也做成一个 node, 放可视化层, 合理吗」时, 默认答**不合理**, 三条理由都要说:
1. 可视化层(前馈直方图/物理约束)不进 Tx/Rx ⇒ 做成可视化节点后, Trace 里照样看不出"这个参数约束了谁", 目的直接落空。
2. 配置是**写**, 可视化是只读。页面上的写已经收口在 授权 → 限流 → FIFO → 执行器 一条路上; 再挂一个画布节点
   = 第二个写入口, 破"谁能动臂只有一条路"。
3. 一类配置 ≠ 一个节点: 执行参数(速度/步长/回点)归收口节点, 点位库归技能库, 外部服务档位归该服务节点,
   授权窗口归执行器闸。合成一个节点就退化成"out1 说不清是什么"。
落法: 每个配置量挂到**真正约束它的那个节点**的 live 信号(当前值/来源文件/最后修改时间); 要总览再加一个
只读 meta 节点, 不出现在 Tx/Rx, 写仍只在页面一处。
🔁 用户接着问「真实节点选 plan 节点, 可以么」时, 答**可以**, 但只限那些真是**段表输入**的量
(速度/步长/点位/回点/请求时的授权 epoch): 把它们当请求值写进段表, 与实测值同表对账 (见上节
「plan 出段表 + exec 收口」)。授权**判决**与外部服务档位仍不归 plan —— 记录请求时的 epoch 属溯源, 不属控制。

## 拓扑重连纪律 (改执行链 / 加汇聚节点)
- 断言: 端口存在 · 无重复 · 不许反向 · 零重叠 · 删完后 **孤立节点 = 0**（用入/出度统计，排除背景）。
- **交叉必须量化**: 节点中心连线的两两线段交点计数（`tools/rewire_cross_check.py` 可复用），报前/后数字，不要凭感觉说"清晰了"。
- **布局原理（实测有效）**: 斜阶梯（每级 x+320/y+124）的汇聚点若放在阶梯**右上**，扇入必然两两交叉；挪到阶梯**末端右下**则成嵌套式无交叉
  （本次把 MoveIt 从右上挪到阶梯末端: 全图交叉 1175→1136）。
- 行内 barycenter 重排**无效甚至更差**（实测 +9.2% 交叉）—— 交叉由**跨行超长连线**主导（如 `ssdata→swds` 61 对，跨距 8000~17000px）。
  真要清零只有一条路: **渲染层正交折线布线**（沿行间走廊走线），不要靠搬节点硬凑。
- 移动节点会连带产生反向线: 挪"接收方"之前先想清楚它的上游在哪（本次为满足"安全边界 → 原子技能 → MoveIt"的走向，把整条链
  `动作调制器 → 安全执行边界 → 原子技能阶梯` 一起左移，否则 `sslimit(13666) → sssk2(10219)` 就是右→左反向线，被断言拦住）。

## 清理节点 (删"不相关节点") 的客观判据
先用 `tools/canvas_level_audit.py` 与入/出度统计拿事实，**别凭感觉删**:
- 本次实测: 无执行注册 **0** · 真缺口 **0** · 完全孤立 **0** ⇒ 画布本来就是接线完整的, 没有"死节点"可删。
- 可删的只有**有文档依据**的: 属于已关闭任务线的节点（例: 参数寻优线关闭 → 通用算子 A/B/C 节点）。
- 删前跑安全判据: **删除后每个邻居仍 ≥1 入且 ≥1 出**（不许产生断链）；删后复扫孤立=0 + 渲染复核 + 控制台重启。

## 工程架构 (2026-09-28 迁移后): 逻辑在包内, GUI 只显示

节点逻辑与画布 JSON 已从 GUI 目录搬到工程包里 (lerobot 哲学: 能力有注册表、实现有归属、GUI 只是调用方):

| 东西 | 真源 (改这里) | 说明 |
|---|---|---|
| 节点逻辑 (148 个注册 key) | `src/lerobot/engineering/nodes/library.py` | 原来在 `tools/gui/node_logic.py` (5129 行) |
| 注册表/匹配 | `.../engineering/registry.py` | `register(key,[关键字],doc,fn)` · `match_node(name)` |
| 执行派发 | `.../engineering/runtime.py` | `execute_node_logic(module,node,...)` · trace · 演示 |
| 源码视图/编辑 | `.../engineering/sourceview.py` | 双击看源码/改逻辑/恢复默认的后端 |
| 画布 JSON | `.../engineering/flows/state_space_obs.json` | 仓库根 `flows/` 是指向它的**软链**, 老脚本零改动可用 |
| 路径 | `.../engineering/paths.py` | 别再 `dirname(__file__)/../..` 上溯 |
| 档位契约 | `.../engineering/levels.py` | L2/L3/L4/L5 「必须还能干的事」+ `check()` |
| 档位索引 | `.../engineering/nodes/by_level.py` | 节点↔key↔函数 (自动生成) |

`tools/gui/node_logic.py` 现在只有 33 行**兼容壳**(转发包命名空间) —— 老写法 `import node_logic` 照旧可用,
但**不要再往里写逻辑**。

三条硬规矩:
1. 改节点逻辑 → 只改 `nodes/library.py` (关键字要和画布节点名对得上, 否则双击落兜底/不可执行)。
2. 画布 JSON → 只经 `flows.save_canvas()` 写 (自动备份 + 校验不过拒写); 写 `flows/` 软链也通。
3. 改完必跑 (数字必须与迁移基线一致):
   `gui-venv311/bin/python tools/verify_engineering.py` (架构自检 6 项: 逻辑住包里/JSON 真源/档位契约/壳一致)
   `QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_canvas_render.py` (2026-10-15 实测 **90 节点项 / 201 连线项**)
   `QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/canvas_level_audit.py` (应仍 R1 15·R2 34·R3 13·R4 7·R5 3·真缺口 0)

⚠️ **注册 key 重名会静默覆盖**: 同一个 key 注两次 ⇒ 后一条把前一条的 fn+关键字一起换掉,
画布上那个节点就**永远 match 不到逻辑** (实测 `ss_pred` 被「先验动力学」与「流形专家」重复注册,
导致「📈 先验动力学预测器」长期不可执行)。每加节点/改关键字后跑 `levels.check()` 或
`match_node(<画布节点名>)` 验证返回非 None。

### 第三个核心体归位: 闭环总装 runtime 搬出 GUI 目录
`RealStateSpaceSim`(L2/L3/L4 闭环总装, 原 `tools/gui/state_space_sim_real.py`, 4240 行) **零 Qt 依赖却住在 GUI 目录**
⇒ 真身已迁 `src/lerobot/engine/runtime.py`。搬这类"被一堆脚本按裸模块名 import"的大模块, 四步缺一就断:

1. **先证它不属于界面**: `grep -cE "PyQt5|pyqtgraph|pyqtSignal|QWidget" <文件>` == 0 才搬 —— 真碰 Qt 控件的是界面件, 留在 `tools/gui`。
2. **留别名 shim, 不用 `from ... import *`**: 老路径留 ~30 行 `sys.modules[__name__] = _runtime`(先 `sys.path.insert(0, <repo>/src)`)。
   星号转发会把模块级全局(`SS_LIVE_FRAME`/`_SS_STATE`)复制成第二份 ⇒ 读写各走一份 = 假一致;
   别名替换后老写法 `import state_space_sim_real` / `from state_space_sim_real import X` 拿到**真身同一对象**, 类身份与 isinstance 不变。
3. **`__file__` 相对根推断必须全换**: 这类文件常有 6~9 处 `dirname×3(__file__)` 去拼 `models/`、`tools/`、`src/lerobot/...`,
   层级一变全指到 `src/lerobot`。改成一个**按标记向上找**的 `_repo_root()`(同一目录下同时有 `src/lerobot` 与 `tools`), 并把数量写进验收。
4. **加位置判据** `tools/verify_engine_location.py`: 真身在 `src/` · `tools/gui` 只剩 shim(≤40 行、无实现体) · 零 Qt ·
   两条 import 同一对象 · `_repo_root()` 命中仓库根 · `tools/` 与六层源码目录定位可用 · 类身份一致。

搬完的 smoke 必须**真跑**: 实例化 → `_reset(0)` → `run(max_steps=12)`(看 env 是 `SawyerPegInsertionSideEnvV3`、步数与耗时); 只 import 不跑等于没验。

**三层身份别混** (用户会问"这不就是流形引擎节点吗"): 闭环总装 `src/lerobot/engine/runtime.py` ≠ 流形引擎节点
(`node_ss_mani_eng` → `src/lerobot/manifold/manifold_engine.py`) ≠ 物理积分(metaworld/MuJoCo 内建)。
改物理保真度动 metaworld 参数与动作缩放(`a_gain`/`action_scale`); 改控制律/阶段时序才动 runtime.py。

## 执行派发链本身会"静默死" (迁移后必查 runtime.py)
- 2026-09-28 `node_logic.py` → 包 的迁移**漏搬两处依赖**: `runtime.py` 用了 `os.environ` 却没有 `import os`(NameError),
  `_demo_node_output` 还引用着留在 `nodes/library.py` 的 `_YOLO_CACHE`(**悬空引用**)。
- ⇒ **任何节点经文档化入口都跑不起来**, 而 GUI 单步外层是 `try/except` ⇒ 异常被**静默吞掉**。
  症状与"接线没接好"**完全一样**(节点看得见、双击没反应) ⇒ 会把人骗去改画布(本次差点白改一版)。
- 判据/修法: 用**真入口**跑一次, 别靠 GUI 点击 ——
  `gui-venv311/bin/python -c "from lerobot.engineering import runtime; runtime.execute_node_logic(<节点>)"` 报 `NameError` 即命中;
  修完**两条路径各验一次**(`engineering.runtime` 与 `tools/gui/node_logic.py` 兼容壳), 再重启控制台确认 `Traceback=0`。
- 排查顺序: **"节点不执行"先查派发层(runtime) → 再查注册/关键字匹配 → 最后才怀疑画布接线**。
- 🔴 **`PURE` / `EXEC_MODE` / 节点注释里的「会动设备」都不是行为事实, 只认 `LAST_STATUS` 实测**:
  中间件节点壳 (`middleware/nodes/n_<单词>.py` 的 `compute`) 只收 **dict 返回** —— 注册的实现若返回非 dict
  (numpy 数组/标量, 如 `execution.py::RobotExecutor.execute` 的 `np.asarray(u)`) 就落成
  `LAST_STATUS = "实现返回非 dict → 直通"` ⇒ **PURE=True 也照样不动**。`EXEC_MODE=act` 只表示"归在会动设备那一类"
  (所以默认锁成数据面), 不是它真会动。真机执行只有 `tools/l2_daemon.py` 一条路 (FIFO → 授权 → 逐段闸 → 550C),
  画布节点没有硬件句柄、不碰 FIFO、不查授权 ⇒ 安全开关的消费点必须在 `l2_daemon._auth_guard()`,
  写在节点 compute 里就是装饰。
- 判一拍干了什么用 CLI, 别靠 GUI 点击: `tools/mw_project.py node <id>` · `mw_project.py step`, 或
  `load_project() → prj.step() → [n for n in prj.nodes.values() if n.spec.id=='<id>'][0].last_status`。
  ⚠️ `Node` 只有 `spec.id` / `last_status` / `last_routed` / `module` —— **没有** `.id` / `.last_outs`, 猜属性会断探针。

- 🔴 **自己定义的控件状态不许被别的代码写回去** —— 初版只挂 1s 轮询去“纠回来”, 结果写者每秒再改一次,
  用户看到的是「运行/停止 跳变好几次」。定稿见下方「在写入点拦截」: 轮询只做兜底, 真正收口在 setText 上。
  症状词: 按钮“闪一下又变回去” / 在两种文字间来回跳。
- 🔴 **标题横幅的时间戳要冻结**: 文案里挟 `strftime()` 就会每秒变一次 ⇒ 1s 轮询把标题刷成"每秒跳"。
  存 `self._ar_started_at` 一次, 横幅只读它。
- 🔴 **`_l5_poll` 每秒会把 `idle` 态的标题重写回 base** ⇒ 抹掉一切自定义横幅: `if state=="idle"`
  必须加 `and not getattr(self, "_ar_play_on", False)`; 类似"轮询里重写标题/按钮"的地方都要这个豁免。

- 🔴 **定稿: 在写入点拦截 (改 `btn_run.setText` 本身), 轮询只做兜底** (2026-10-28):
  用户看到「运行/停止 在两种文字间跳好几次」= 轮询纠一次、写者每秒再改回一次, 互相拉扯。
  正解: 把实例方法包一层 shim ——
  ```python
  _orig = self.btn_run.setText
  def _set(t):
      if self._ar_playing() and t != "⏸ 停止 AR 播放 (运行中)":
          self._log("🔍 运行按钮被写「%s」→ 已顶回 ← %s" % (t, file:line))   # 顺手点名写者
          t = "⏸ 停止 AR 播放 (运行中)"
      return _orig(t)
  self.btn_run.setText = _set      # PyQt 实例上可用, 能 shadow 方法
  ```
  实测: 敌对写者每 0.5s 写一次持续 4.8s, 按钮文字只出现 1 种 (零跳变);
  再点一次停/按 stop_sim ⇒ `_ar_play_on=False` 先解掉只读, 文字正常回「▶ 运行」。
  🔴 **播放态还要同一点亮「■ 停止」**: 运行分支 `btn_stop.setEnabled(bool(在跑))` + 1s 收口再盯一道 ——
  用户只看按钮亮没亮(原话「停止按钮应该亮了, 现在是灰色的」), 不看他没打开的执行逻辑。
  ⚠ `stop_sim()` 开头必须先写 `ar_play action=stop` + `_ar_play_on=False`, 否则“只读”会把按钮锁在播放态。
  ⚠ 同时要把 `_recover_run_btn / _flow_next / _on_real_poll / stop_sim / _ss_finish` 的 `setText("▶ 运行")` 都加 `if not self._ar_playing():` 守卫 (双保险)。

> 右键「打开源代码」报 `该节点未配置源码映射 (params.source)` ⇒ 按 `references/node-source-mapping.md` 逐层查:
> **① 现场节点自带 `params.source`(最优先) → ② spec.source → ③ 中间件模块 SOURCE → ④ 注册表 file/line**。
> 🔴 `load_flow_file` 会给节点重编 id ⇒ 拿界面节点 id 去磁盘画布找 spec **恒失败**, 即使已补 ③④ 两层也照样弹窗
> ⇒ 节点 dict 自己带的 source 必须放第一层。别往画布 JSON 里塞 params (会被 GUI 内存旧副本覆盖)。
> 🔴 实现正文留在 `library.py` 里时, 注册表记的位置就是 `library.py:<行>`: 用户会报「怎么是 library.py 而不是功能代码」
> ⇒ 实现挪到 `nodes/<功能>_impl.py`, `library.py` 只留转调壳, 同步 `_EXTERNAL_LOC` + 中间件 `SOURCE`。

## 按钮/节点"点了没反应"的分层取证 (别猜, 证据链三级)
1. **handler 跑了没有** —— GUI 日志**始终**落盘: `_log` 无条件写 `/tmp/simulink_log.txt`(与底部日志区是否展开无关);
   studio 的 stdout/stderr 在 `/tmp/studio_launch.log`。日志里出现该按钮自己的行 ⇒ 点击确实到达了代码。
2. **handler 里有没有"回画布"的路径** —— 看它是否碰 `self._items` / 节点属性 / `update()` / scene。
   只做 `subprocess.Popen(...)` + `QDesktopServices.openUrl(...)` 的 handler **结构上不可能**让画布动 —— 那不是故障, 是没接线。
   工具栏按钮的验收口径: 点击结果必须落在**用户正看的那个界面**上(画布节点上画帧/状态小字/横幅),
   只弹外链/只写日志 = 用户眼里"没反应"。
3. **外部副作用真发生了吗** —— 报"已打开"不算: 查进程 (`ps -o lstart`) 与浏览器 `History` 库里搜 URL。
   自报的成功日志 ≠ 副作用发生（实测: 日志连打三次"页已打开", 但点击时刻无浏览器进程、History 里 0 条该 URL）。

   外部副作用的两个常设坑（都是"点了没反应"的真因）:
   - **地址别缓存**: 开页 URL 里含 LAN IP 时, 每次开页前重取并 `curl -s -o /dev/null -w '%{http_code}'` 实测可达。
     工位机 WiFi 走 DHCP, 重新租约**一分钟内**就换 IP ⇒ 打印出去/存下来的地址当场作废。
   - **要给另一个界面送画面就拉单帧快照**, 别在其中嵌 MJPEG: 视频流侧已有 `/snapshot/overlay_local.jpg` ·
     `/snapshot/overlay_arm.jpg` 等端点(实测 200 / 80KB / 0.8ms 本机), 定时器拉帧 → QPixmap → 节点 `video_pixmap` 即可。

## 长任务触发器的反馈必须"不可能看不见"(按钮起后台流水线)
- **节点上画状态小字 = 等于没有**: 87 个节点的画布里, 即使 `paint` 真画了 `L5 · annotate 3/6`,
  用户读不出来、自己看截图也读不出来 ⇒ 他连报三轮"点击运行没反应", 而功能其实每次都真启动了。
- **合格形态(2026-10-01 用户定稿, 以此条为准)**: **画布上不铺任何状态文字** —— 用户看到画布上的大字后要求
  「simulink画布 `L5运行中` 这几个字太丑了, 在下面终端显示信息就可以了, **赶紧删掉**」。三条交付口径:
  ① **下面终端日志** 承载全部文字, 且**只在内容变化时写一行**(1s 轮询无脑 `_log` 会刷屏 ⇒ 用 `_last_log` 去重);
  ② **他刚点的那个控件上的文字**(`⏳ 运行中 · <阶段>`); ③ **节点边框状态色**(黄=运行/绿=完成/红=失败) ——
  一眼看得出在跑, 又不占地方。落法: 显示函数**保留名字与签名**(调用点一处不用改), 内部改成只 `_log` +
  `hide()` 旧标签, 旧实现改名 `*_canvas_disabled` 留在文件里(可回溯, 比删段安全); 节点上的进度行函数直接 `return []`。
  （更早的形态, 只在用户明确要求恢复时用: 画布 viewport 通栏横幅 —— 必须用 **viewport 坐标**画(场景坐标会随缩放/平移跑掉),
  运行中=黄/橙, 完成=绿, 失败=红, **未运行时不画**; 以及主窗口标题栏 / 右侧栏固定区块。）
- **标题栏是最省事又最稳的一条**: 它永远可见(画布被遮挡/最小化/缩放到看不清也还在), 实现只要在轮询里
  `_w = self.window()`(**不能用 self**: 画布常是子 widget, 标题设错对象 ⇒ 屏幕毫无变化) →
  `_w.setWindowTitle("%s   ⟪ %s ⟫" % (base, banner))`。**首次先把原标题缓存进 `_win_title_base` 再拼**,
  否则会把版本号/项目号那段前缀冲掉; 任务结束时还原。
  ⚠️ **标题栏带" - <页面>"后缀是设计** (画布/其它模块会追加当前页) ⇒ 任何"实机窗口标题 == XSpace ZMAX <档>"的
  判据必须**先去掉 ` - …` 后缀再比**, 否则控制台停在画布页时判据假红 (实测某判据因此长期红着)。
- **反馈要挂在用户刚点的那个控件上**: 他盯的是自己点的地方 —— 运行按钮的文字变成 `⏳ 运行中 · <阶段>`,
  比在他没看的角落画任何东西都有效。
- **代码改了 ≠ 用户看得到**: 说"改好了"时必须同时说清 **要重启控制台才生效**; 他没重启就继续报"没反应"时,
  不要重复解释"功能其实在跑", 先让他重启一次再看标题栏/横幅。
- **"已在运行 → 不重复启动"这类静默分支也必须显示**(`⏳ 已在运行: <阶段> <进度>`): 用户重复点击时,
  这是最常命中的分支, 只写一行日志 ⇒ 在他看来还是"没反应"。
- **轮询要在打开画布时就自动起**(1~2s 定时器读状态文件 → 写节点 → `update()`), 不能只在"从 GUI 点运行"之后才起:
  否则他开着画布、任务在别处跑时看不到任何东西。状态文件读失败要**静默降级**, 不许抛异常/卡 GUI 线程。
- **验收判据 = 截图**: 启动 → 点运行 → 截图 → 自问"不看底部日志栏, 一眼能不能读出当前阶段?" **读不出就是没过**。
  配套: 状态真源用 `state.json`(status/stage/updated/pid/stage_detail/results/stages_done), 汇报时给"进程 pid + 状态文件 + 产物路径+时间戳"三处, 不要只说"已在跑"。

## 横幅的生命周期: 运行态常显, 终态"闪一下"(否则用户会要求关掉)
- 横幅若**每次轮询都重铺**, 那么只要状态文件停在 `failed`, 它就会永久顶在画布上 —— 用户会直接说"这个提示无法关掉"。
- 规则: `running` 常显(要一直看到阶段) · `ok` 常显 · **`error` 只闪 ~15s 后自动隐藏**。
  实现: 首次展示时记时间戳(`_err_seen = time.time()`), 到点调 hide;_banner 显示前用**局部变量**取时间戳再算差
  (写成 `time.time() - self._err_seen` 会被类型检查/None 分支咬到)。
  **新一轮 running/ok 时把标记清空(`= None`)**, 否则下次失败再也不提示。
- **历史终态不是"当下故障"**: 启动后读到的是上一轮的 `failed`, 文案要写"**上次** … 失败: <原因>",
  不要常驻一条红色"失败"—— 用户会以为现在崩了。
- 失败文案要**带原因**: 从状态文件 `results` 里找第一个 `ok=False` 的阶段, 拼成 `<阶段>: <reason>`;
  只显示"失败: slots"他看不懂, 显示"尚无已记录槽位(等演示)"他才知道下一步做什么。
- **别在终态 `timer.stop()`**: 老实现跑完就停轮询 ⇒ 画布/标题永久冻结, 之后在别处起的任务再也不上屏。
  轮询保持常驻(1s), 用"**内容不变则不重绘**"(`if key == self._last_key: 跳过 update`)控开销 ——
  常驻 1s 轮询 + 无脑重绘会一直烧 GPU。
- 进度分母**从状态文件读**, 不许写死: 写死 `n/7` 而实际 9 阶段 ⇒ 一开跑就显示 `9/9`, 用户以为已经跑完了。

## 点击瞬间的反馈: 三个必踩的实现坑
- **同一次同步调用里被自己回写**: handler 先 `btn.setText("⏳ 运行中…") + setEnabled(False)`, 同一函数的后面分支
  又把它设回 `"▶ 运行"` ⇒ 按钮**视觉上永远不变**(用户照旧报"没反应")。修法: 设完再 grep 本函数内该控件的**所有**写点;
  更稳的是把按钮文字交给 1s 轮询驱动(轮询读状态文件 → 写按钮), handler 只负责启动。
- **坐标混口径**: 画布上弹气泡/浮层时把 `scenePos()`(场景坐标)直接喂给要**屏幕全局坐标**的函数 ⇒ 气泡飘到窗口外/被盖住。
  正解 `canvas.mapToGlobal(canvas.mapFromScene(...))`; 气泡内容要用**真实状态**, 不能写死"已启动"(已在运行时会谎报)。
- **"改好了"的判定**: 反馈面必须同时满足 ①他一开机就看得见(打开画布即起轮询) ②不阻塞(鼠标穿透/非 modal)
  ③能走(终态会自己消失)。三条缺一条就会被下一轮投诉。

## 🔴 会动的东西只能由人点的那一下启动 —— 不许为了消「没反应」加自动播放

用户报「点了运行没执行」时, 正确修法是**让那一下真的生效**, 不是绕过那个按钮。
- **绝不加自动播放**: 页面收到指令就自己 `plantStart()` / 打开就开跑 / 定时自启 —— 无论跑的是真机还是仿真,
  用户都会当场质问「我没点运行, 你怎么让机器人跑了」。动 = 运行, 不管它是不是仿真。
- 他要的语义是**人点 → 才动**: 画布「▶ 运行」写一个播放意图文件 (如 `zmax_data/ss_live/ar_play.json`
  `{ts, action:start}`), 服务端只读端点把它带出来 (`play.ts/age_s/fresh`), 页面**收到一次新的 ts 才启动**
  (`ts > 上次处理的 ts` 去重); 人点「停」后置 `userStop` 标记, 之后任何路径都不再自动拉起。
- 播放开关与安全开关分开: 播放意图只决定"界面动不动", `real_auth` 一类授权**永不**由它代写。
- 验收两条相反向都要测: 打开只观察 → `PLANT.on=false / units=0`; 写一次 play → `on=true` 且 `seq` 推进。
  只测后者会把"自动播放"的 bug 当成通过。

## 🔴 按钮 `setEnabled(False)` 之后失败不恢复 ⇒ 永久卡死「点不动也没提示」

启动型按钮 (`start_sim` 这类) 的常见形态是第一句就 `setText("⏳ 运行中…") + setEnabled(False)`,
然后在 N 个分支里各自恢复 —— 只要有一个分支抛异常/提前 return/被中断, 按钮就**永久灰**, 用户点它没任何反应,
比"跑了没效果"更难查 (他连点都点不动)。
- 修法: 进入 disabled 的**同一处**挂一个兜底定时器 (`QTimer.singleShot(8000, self._recover_run_btn)`),
  回调里判定「仍 disabled 且文字还是『运行中』」⇒ 恢复可点 + 日志写明「上一次没走完, 原因见上面日志」。
- 判据不要只看 `isEnabled()`: 同时看**按钮文字**——真在跑的分支文字会变 (`⏸ 停止`/阶段名), 只认「⏳ 运行中…」这态, 才不会把长任务误恢复。
- 任何新增分支都要记得恢复按钮; 兜底定时器只是保险, 不是替它擦屁股的理由。

## 🔀 多态循环切换控件一律改成「点开直接选」

`sstate` 数据源这类 N 态切换做成**单击循环**时, 用户为了切到第 4 态要点三四次, 还会点过头
(加上任何强制改写就是无限拉锯)。用户明确要求: **点一下弹出菜单/下拉, 一次选到位, 当前项带 ✓**。
- 实现: 处理器里 `QMenu` 逐项 `addAction(("✓  " if s==cur else "     ") + 描述)`, `a.setChecked(s==cur)`,
  `exec_(QCursor.pos())` 取选中项; **选同一项或取消 ⇒ 什么都不写** (日志「保持「X」不变」)。
- 菜单构造失败要 **fallback 回单步切换 + 明说**, 不能点了毫无反应。
- 切换后的副作用链一条不能少: 场景真源 (`_apply_src_scene`) → `_data_source` → 节点 `update()` → `_save_param_to_flow` → 进度存档, 最后写**一行**日志带当前态与实际生效取值。

## 改在役 GUI 的节奏: 一次改全 → 只重启一次 → 先自证分支会命中

Python 只在启动时读一次源码, 改完不重启零效果; 但反复重启会打断用户正在做的演示/操作。
- **先把这一轮要改的分支全部改完、`ast.parse` 过, 再重启一次**; 不要"改一版 → 重启 → 被报还是不对 → 再改 → 再重启"
  (实测这样连重启四次, 每一轮都在浪费用户的时间)。
- 重启前用 `ps -o lstart= -p <pid>` 对比 `stat -c %y <改的文件>` 说清「他现在跑的是不是旧代码」;
  重启走仓库启动器 `tools/gui/launch_studio.sh` (自带环境 + 启动前对齐), 不要手拼命令。
- **新分支先自证命中再交付**: 分支条件依赖的函数 (如 `_canvas_src_state(module)`) 单独跑一次打印它的返回值,
  确认等于预期 (`AR场景`), 而不是靠读代码推断。
- 🔴 **按 id 找 GUI 内存里的画布节点必然找不到** (`load_flow_file` 会重编 id): 判断"画布当前是哪一态"一律调
  现成的 `_canvas_src_state(module)`(遍历节点取 `params.src_state` 再 `_src_norm`), 不要写 `n.get("id")=="ssdata"` ——
  那种写法永远拿不到值, 分支静默不命中, 于是又落到旧的重量流程上, 症状与"代码没改"完全一样。
- **同一个抱怨被说第二遍 = 根因还没找到**, 不要再调一次参数/再解释一次原理; 换取证角度
  (谁在写这个文件 / 分支条件实际取了什么值 / 进程启动时间 vs 文件 mtime)。

## 用户正在操作控制台时的改写纪律
- 他在现场演示 / 准备重启控制台时, **冻结** `tools/gui/*.py` 的写操作 —— 你改一半他就起不来或按钮坏掉。
  改前先看 `pgrep -af studio.py` 与 `/tmp/simulink_log.txt` 最近 30 秒有无新增点击; 没写完的改动
  **隔离在独立 draft 文件**(`tools/*_patch.py.draft`)里, 等他演示完再并入 —— 冻结期间照常做不碰 GUI 的活(数据/训练/脚本)。
  **冻结是临时的**: 演示/重启一结束就立刻显式解冻(或自己接手), 并说清剩余工作归谁 ——
  冻结忘了撤, 按钮链就停在他抱怨的那半成品上(他下一次投诉的正是缺的那一半)。
- 冻结前**必须确认文件处于可用状态并说出来**(`ast.parse` + `QT_QPA_PLATFORM=offscreen` 真 import 双过), 否则他重启就是白等;
  同时回读一次"按钮链在不在盘上"(如 `grep -c <闭环脚本名> tools/gui/studio.py`) —— 只写日志的"已冻结"不算证据。
- **不要同时让两个子代理改同一批 GUI 文件**, 也不要在没读上一个交付报告前重复派活:
  先读上一个的报告/产物清单, 确认哪些已完成再派新的(本次"假训练闸门"上一个代理已实现并实测, 重复派了一次, 靠 steer 才拦下)。
- **自己接手改同一批文件前, 先把还在跑的兄弟子代理 stop 掉**: `patch` 工具报
  "modified by sibling subagent … but this agent never read it"(**或 `stat -c %y` 显示的 mtime 不是自己写的**)就是"两个写者"信号
  ⇒ 先 stop + 复核(ast + 真导入 + 关键方法/常量都在)再动, 别直接覆盖 —— 否则你俩各写一半, 用户重启后是坏文件。
- **导入探针的假阴性**: `import` 报 `ModuleNotFoundError: No module named 'version_sync'` 这种**兄弟模块**缺失, 多半是探针 cwd/sys.path 不对
  (不是代码坏)。用 `cd <repo>` + `QT_QPA_PLATFORM=offscreen` + `sys.path.insert(0,'tools/gui')` 重跑一次再下结论, 别据此回滚。
- 用户重启后**先看控制台是否加载完**: 画布离屏加载要几十秒, 期间点按钮什么都不会发生 —— 报"点了没反应"时要先排除这个空窗(`grep -c "已加载工作流" /tmp/simulink_log.txt` + 比对进程 `lstart`)。

## 画布节点的"能力"要先验真 (声明 ≠ 接线)
- **节点画视频的分支是死代码**: `SimNodeItem.video_pixmap` 全仓库只有赋 `None` 那一处、配套信号 `_mlp_frames_ready`
  声明后从未 emit/connect ⇒ `paint` 里那段永远不执行。要给节点送帧得自己接定时器拉单帧 → 赋 `video_pixmap` → `update()`。
- **双击靠节点名关键字匹配** `node_logic.match_node`(最长匹配, 表在 `NODE_LOGIC`): 名字没命中任何关键字就落兜底 ⇒
  节点"看得见、点不动"。加节点时名字与关键字**一起**设计, 并真双击一次。
- 通用判据: 接入前先查目标字段的**写点**(`search_files`)。只有声明、只在 paint 里读 = 没接线; 别把"代码里有这个字段"当既有能力。

## 关键数字基线 (每次改画布前后都要对)
| 指标 | 基线 | 怎么查 |
|---|---|---|
| 画布节点项 / 连线项 | **93 / 212** (2026-10-28 实测; 更早 90/201 · 89/183 · 87/172) | `verify_canvas_render.py` |
| 节点数 / 连线数 (JSON) | **93 / 213** (2026-10-28 实测; 更早 90/202) | 直接数 `state_space_obs.json` |
| 档位审计 | R1 15 · R2 **40** · R3 13 · R4 7 · R5 2 · 无执行注册 1(既有: 元数据MOE门控路由) | `canvas_level_audit.py` |
| 档位测试 | L2 275/275 · L3 94/94 · L4 178/178 | `xvfb-run -a ./gui-venv311/bin/python tools/ss_level_tests.py --level Lx` |

加 L4 节点的落位判据: 别用"全域最大空档"硬套 —— 语义节点应在它的**上下游之间**的区间里取空档
(如标定节点必须落在 `标定层(sscalib)` 与 `被标定引擎(ss_mani_eng)` 之间), 否则为凑空档会接出反向线被断言拦住。

## 单步跟随 / 定位 / 逐节点实现审计 (2026-10-09, v5.22.0)
老倪: 「我要全面检查状态空间工程的每个节点的实现; 单步运行, 运行到哪个节点哪个节点高亮,
**而且画布要跳到这个节点** —— 画布太大了, 我找不到单步节点到底在哪里」。

**高亮本来就有** (`node["status"]="step_active"` → 金框 2.8px, 或 `node["hl"]`), 缺的是**跳转**。落法:
- `SimCanvas.focus_node(node_id, min_scale=0.45, max_scale=1.6)`: 缩放夹到看得清区间 → `centerOn(节点包围盒中心)` →
  `viewport().update()`。**必须夹缩放**: 用户在全览缩放(0.05)时直接 centerOn 依然看不到东西。
- `SimCanvas.fit_all(margin=240)`: 所有节点 `united` → `fitInView` → **回来同步 `self._scale`** (Ctrl+滚轮的 `_scale` 是真源)。
- 挂钩点选在 `_highlight_node(node, ms, follow=True)` (它是所有节点级高亮的公共入口) ⇒ 单步/右键运行节点/全局运行
  都自动获得跳转; 开关用工具栏 `☑ 🎯 跟随单步` (默认开), 关掉时**仍要在终端报一行位置**。
- **同一节点 2 秒内只跳一次**: 一次单步会经 `step_sim → _run_node_single → _highlight_node` 两条路进来,
  不去重就跳两次、终端刷两行。
- 反馈口径不变: **画布上不铺文字**, 位置/进度只进下面终端; 画布留给金框与状态色。

**逐节点实现审计** (`tools/ss_node_impl_audit.py`, 只读): 每行 = 序号/id/名称/层级/实现 key/是否在单步序/**文件:行**。
- 实现真源: `registry.match_node(名) → key → fn`; 位置用 `sourceview.get_node_location(key)`
  (自动处理 `_EXTERNAL_LOC`, 真实现在 `left_right/state_space/*.py` 等外部文件, 并按符号名现搜行号)。
- 单步序判据 **直接调用 GUI 的 `_ss_node_cap_level` / `_ss_is_observer`** (不是抄一份), 再用内联副本**逐节点交叉核对**
  —— 两份不同步时立刻暴露。实测 89 节点(功能 74/背景 15) · **实现命中 74/74** · 判据核对 74/74 ✅。

配套验证: `tools/verify_step_follow.py` (离屏真建 SimulinkModule + 真加载画布, 9 组交互级断言:
渲染回归 / 控件在位 / 实现位置 / 真跳偏差 / 跟随开-关 / 定位 / 全览 / 金框)。

### 两个必踩的坑
1. 🔴 **`load_flow_file` 会给每个节点重新 `gen_id()`** ⇒ 文件里的 id (`sssensor`/`n_calib_mani`) 在 GUI 内存里**查不到**,
   只有运行时生成的 id 有效。**任何"按 id 找画布节点"的代码必须带名字/语义标记兜底**
   (既有 `_ov_live_target_item` 就是这么写的)。写盘的 `ss_node_sync.py` 之类也要补兜底,
   否则用户从控制台「另存为」重写过 id 后就再也找不到节点。
2. `_follow_to` / `_highlight_node` 必须能吃 `node is None` (画布为空/名字没匹配) —— 否则点一下就 Traceback。

## 右键「打开源代码 (模块实现)」= 一律投 VSCode 并停在符号行

用户口径: 内部弹窗编辑器「UI 不好」, 要 **VSCode 打开并定位到实现那一行**(界面上还要看得出绝对路径:行号)。
- 两个菜单项分工别混: 「打开源代码 (模块实现)」→ `open_node_source()`(真实实现) ·
  「打开 node (中间件 · 输入输出)」→ `open_in_vscode(node, target="node")`(外壳 `n_<单词>.py`, 停 `PORTS_IN` 那行)。
  后者本来就走 VSCode, **只有前者在纯 Linux 工位机会落到内部弹窗** —— 别把"弹窗"当成设计如此。
- 落法: 兜底分支改成 `code -r -g <绝对路径>:<行号>`(`-r` 复用已开窗口, `-g` 跳行列);
  行号从 `registry.match_node(节点名) → sourceview.get_node_location(key)` 取, **不要写死 1**;
  `which code` 之外再兜底 `/usr/bin/code` `/usr/local/bin/code` `/snap/bin/code` `/usr/share/code/bin/code`;
  全拿不到才回退内部弹窗(不能点了没反应)。`Popen(..., start_new_session=True)` 不阻塞 GUI 线程。
- 为什么老实现总进弹窗: 分支顺序是「有 impl 目标 → VSCode / 有 `/mnt/c` → explorer.exe / 其余 → 内部弹窗」,
  无 `/mnt/c` 的机器**点任何节点都命中最后一条**。改这类多分支时先看清哪一条是本机实际走的。
- 验: 离屏 `import` 过 + 真跑一次 `code -r -g <file>:<line>` 用 `wmctrl -l` 看窗口标题挂着该文件;
  再对 3 个不同层的节点各打印一次落点(`文件:行`), 确认行号不是常量。
- 改了 `tools/gui/*.py` 必须**重启控制台**才生效; 按用户规矩**不要自己重启 GUI**, 交付时把"要重启"说在前面。

## 画布右侧「参数标定」侧边页 = 工程的 测量/诊断/标定/配置 (2026-10-09, v5.23.0)
老倪: 「将①~⑥ 这 6 个运行开关整合进画布右侧的参数标定侧边页面, 这个页面对应工程的 测量 诊断 标定 配置;
这个侧边页面, 你检查一下其它功能, 没有用的都删掉」。

**面板是 `model_tree.py` 的 `ModelTreeDock`** (2026-08-14 起嵌在 SimulinkModule 右侧 split 列, 不是 dock widget),
顶部一个 `cmb_view` 下拉切视图。四轴分组 (11 视图, 标签直接带轴名):
📏测量 数据字典(tree)/状态空间变量(ss_tree)/性能指标(perf)/数据总线(bus) ·
🔍诊断 运行汇总(run_summary)/场景状态(scene_state) ·
🎛标定 参数标定(pole_place+tree同屏)/现场标定(stage_calib)/数学分析(lbl_math+plot+response) ·
🔧配置 工程需求(eng_req)/运行开关(run_cfg)。

> ⚠️ 2026-10-09 晚 (v5.24.0) 已**收紧为 5 视图** —— 上表里 perf/scene_state/run_summary/
> pole_place/stage_calib/math/eng_req 已停用 (挪 `_model_tree_ffpd_legacy.py`), 见下面 «v5.24.0 收紧»。

### 把工具栏开关「归位」到侧边页: 搬, 不是复制
- 做法: `attach_run_switches({...})` 把 6 个 `QCheckBox` 从工具栏布局 `removeWidget` 后再 `addWidget` 进右页
  —— Qt 控件**只有一个父**, re-parent 后**是同一个对象** ⇒ 所有运行路径读 `self.chk_*` / `getattr(self,'chk_*')` **一字不改**。
  这比"新做一套控件再信号同步"好: 不存在两份状态, 天然零回退。
- 工具栏留一个入口按钮 → `_show_run_cfg()` 把下拉切到该页 (`cmb_view.setCurrentIndex(len(VIEW_KEYS)-1)`) 并 `refresh()`。
- 页面每行给: 开关本体 · 适用档位 chip · 作用 · **生效位置(文件:行)** · 实测代价(风险行橙色);
  档位 chip 按画布「能力档位」节点 `params.cap_level` 判定命中, 本档无效的开关显示 `(本档无效)` —— 一眼看出这个勾现在管不管用。
- `_switch_view` 要**表驱动** (`VIEW_KEYS` 一处定义索引→控件), 否则每次重排视图都要改 10 个索引 if, 必错。
  重排时注意保留老行为 (例: 参数标定视图 = 极点配置器 **+ 数据字典树同屏**)。

### v5.24.0 收紧: 11 视图 → 5, 右侧栏重点 = 配置 + 标定 + 主参数 M
老倪: 「右边侧边栏, 重点是 配置 和 标定, 以及主参数 M; 其它功能要精简, 没联系的**全注释掉**, 确定没用的删掉」。

**【核心判据】「这个页跟状态空间工程有没有真联系」= 画布真源里有没有它读的键** (不是"点了有没有反应"):
```bash
C=src/lerobot/engineering/flows/state_space_obs.json
for k in z700_internal gain_schedule; do echo -n "$k="; grep -c "$k" $C; done   # 都是 0
```
状态空间画布没这两个键 ⇒ `analyze_system()` 走 else 分支填**硬编码默认**(m=1.0/b=2.0/k=5.0),
极点配置 `_write_back` 直接弹「当前画布无 Z700 内部模块」, 现场标定找不到状态机节点
⇒ 性能指标/场景状态/运行汇总/数学分析/参数标定/现场标定/工程需求 7 页**看着有数、与画布无关**
(= 工程师最恨的假数)。它们属于另一套「前馈 PD 顶层」画布 (带 `z700_internal`)。

处置手法 (满足"注释掉"且让 4300 行文件瘦一半): **8 个部件类 + 5 个分析函数整体挪到
`tools/gui/_model_tree_ffpd_legacy.py`** (带复活说明), 原位置留注记注释;
面板侧: `cmb_view` 5 项 + `VIEW_KEYS` 表。留下的 5 项全有真连接:
🧮 主参数 M(画布 M 节点 params) · 🔧 运行开关(`self.chk_*`→引擎分支) · 📏 数据字典(画布 params+feature.dbc) ·
📏 状态空间变量/数据总线(引擎 `_ss_tr` io_trace)。

**新页「🧮 主参数 M · 测量/标定/诊断/配置」** (`MasterParamMView`, 默认页): 数据源 = 画布 M 节点
(`n_calib_mani`) 的 `cfg_entries/cfg_snapshot/measure_view/calib_view/diagnose_view/task_layer`
(由 `ss_node_sync.py` 从真源同步进节点) ⇒ 页 ↔ 节点 ↔ 文件 同源。按钮: ✏️ 写 M (走
`zmax_params.write_manifold_M`: 范围校验+只改 `manifold_engine` 键+回读) / 📥 同步 / 🔁 刷新 / 📋 复制;
无节点时诚实空态 + 给补救命令。

### 三个必踩的坑 (v5.24.0 实测)
1. 🔴 **`load_flow_file` 给节点重编 id** (`n_calib_mani`→`n1791534…acq`) ⇒ 取节点必须
   「语义标记 `params.manifold_calib` + 名字关键词」兜底; 按 id 写判据的 verifier 必假红。
2. 🔴 **往方法里插代码块, `ast.parse` 抓不到插错位置**: 本次把懒刷新钩子插到**两个方法之间**
   (8 空格缩进紧贴上一个方法体尾, 语法合法) ⇒ 钩子挂到了上一个方法, 现象=不生效。
   定位法: 找 `    def X(self):` 后, 再找**下一个** `^    def ` 之前的一行插; 插完务必复核
   「新块行号落在 [defX, 下一个 def) 区间」(脚本里 `assert`)。
3. **刷新钩子别用 `isVisible()` 判据** (窗口隐藏/离屏恒 False ⇒ 静默跳过): 用「当前页索引 →
   `VIEW_KEYS[idx]` 名」判断。

### v5.24.1: 测量三行合一 + 新增「标定」页 (老倪「测量类三行太多只留一行 + 增加一个标定类」)
下拉 4 行: 🧮 主参数 M (默认) / 📏 测量 / 🎛 标定 / 🔧 配置·运行开关。
- **📏 测量 = `MeasureHub`**: 原 `tree`/`ss_tree`/`bus` 三个控件 `attach()` re-parent 进 3 个页签
  (又是「搬不是复制」: 外部读 `dock.tree` / `_show_state_space()` 一字不改); 切签只刷当前签。
- **🎛 标定 = `CalibTruthView`**: 逐行读真源 `config/calib/zmax_calib.json` (9 段同序同值), 未标定 3 项
  (`T_base_cam`/`plane_z`/`cell_geometry`) 高亮 + 给**可执行**现场标定命令 (`ss_geom_calib.py` 零运动示教 /
  `board_handeye_solve.py` 采板 / 夹爪量台面高度); **只读无写按钮** —— 唯一写口留给主参数 M 页。

### 坑 4 🔴: 仓库根路径少一层 `dirname` + 判据打在「测试自己调脚本」上 = 假证据
`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 在 `tools/gui/xxx.py` 里只到 `tools/`,
要**三层**才到仓根 ⇒ 拼出 `tools/tools/ss_node_sync.py`、`tools/config/calib/...`,
按钮静默走空路径。**更坑的是上一轮判据没抳到**: 测试自己 `subprocess` 跑脚本“通过”了,
而那只是脚本能跑, **按钮那条路根本没验**。
=> 铁律: 凡是面板按钮背后的路径 (子进程/写文件/调脚本), 判据必须**真点按钮 + 抳按钮自己的日志**
(`v._log = lambda m: logs.append(m)`, 再断言日志里有成功句), 不能直接调脚本冒充。

### v5.24.2 再收紧: 「测量」只挂数据总线 (老倪同日改主意)
面板里 `📏 测量` 行只挂 `bus`; 数据字典 `tree` / 状态空间变量 `ss_tree` **对象与刷新逻辑没动**(不删),
只是不 `addWidget` 进面板; `MeasureHub` 类保留停用 (`self.measure = None`), 一会话里就能复活。
**副作用要如实报**: 「双击节点参数直接标定/调节」入口随树一块从面板消失 (编辑器代码还在)。
→ 教训: 用户说「只保留 X」时, 把**同时失去的能力**(而不只是行数) 一并报出来, 别让人事后才发现。

### 侧栏定稿: 3 页 = 主参数 M / 数据总线 / 参数中心 (删运行开关)
老倪: 「画布右侧栏, 保留 主参数：对应流形引擎； 数据总线：对应数据空间的 Trace； 参数中心：对应数据库服务的所有参数；删除 运行开关。」
- 下拉只剩 3 行, **三处必须同源**: `cmb_view` 文案 · `VIEW_KEYS` 元组 · 工程存档段 `available_views`(`project_file.py`)。
  加减页只在 `_switch_view` 的**表驱动**里动一条, 别再堆索引 if。
- 🔴 **撤下某一页 = 控件对象留下, 只是不进可见布局** (`setVisible(False)` / 不 `addWidget`), 绝不删对象:
  引擎与画布有几十处 `self.chk_*` / `dock.calib` / `dock.run_cfg` 的读点(实测 40 处), 删对象 = 引擎早退 + 一批判据全红。
  撤一页时**被撤页承载的能力要给出新去处**(标定数字改从「参数中心」🟡标定 类看; 6 个开关仍在主界面「参数中心」🟠开关 类可改)。
- 「🎛 参数中心」页 = **只读**, 直连工程库只读服务 `http://127.0.0.1:8798/params`(`engineering_db.serve` 的端点:
  `{total, by_cat, params[]}`); 服务没起就**诚实空态 + 给启动命令**, 不显示 0 或旧值。
  **不许在这里开第二条写路径** —— 唯一写口仍是主界面「参数中心」页(`param_center.py`: 校验/影响链/备份/留痕)。
- 🔴 **页面上的数必须来自它要写的那个真源**: 「主参数 M」页原来读**画布节点快照**的 M(画布默认 1.0), 而真源
  `config/calib/zmax_manifold.json` 是现场标定值 ⇒ 页面显示 1.0, 按一下「✏️ 写 M」就把真源覆盖成 1.0。
  修法: 微调框**以真源为准**(真源缺才退回节点值), 两者不一致时页头标 `⚠真源≠节点`(具体数字塞 tooltip, 行仍守 ≤115 字预算)。
- 判据 `tools/verify_sidebar_views.py`(改侧栏就补一份同型): 3 行文案 · 逐页真切换(一次只有一页可见) ·
  参数中心表行数 == 服务 total · 撤下两页对象在且永不显示 · 开关仍是同一对象 · `view_is` 表驱动仍准 · 存档同源 · 三页出图。
- 连带一致性: 注册表与单一工程库必须**同数** (`param_registry.registry()` 少 58 条 `spec:perf.*` ⇒ 759 ≠ 817)
  ⇒ 补 `scan_perf_spec()` 读 `config/platform/zmax_perf_spec.json`(只读, `status=已定义(目标值)`, 类别色/图标同补)。

### 面板 "没有用的都删掉" 怎么答才站得住
1. **逐个视图切换实测** (offscreen 真建窗口 + `setCurrentIndex` + `processEvents` + 读 `isVisible()`/标签/树/表行数),
   不要凭代码猜: 面板里很多视图是 `paintEvent` 自绘 (无 QLabel) 或"未跑仿真=诚实空态", 看着空其实有数据源。
2. 判"有没有用"的证据链 = **数据源 (文件/`module._ss_tr`) 是否真实 + 是否被消费**。全是活的时候,
   老实报"无空壳可删", 然后去删**全仓零引用的死函数** (`grep -rn '<name>'` 只有定义行) —— 这才是能落地的"删掉没用的"。
3. 遇到"接了但没人消费"的 (例: `工程需求` 8 个输入框写 `module._eng_req`, 全仓只有本面板自己读) ——
   **不要默默删**, 删了会丢需求基线; 在界面上**如实标注**"这些值暂只喂本面板验收口径, 引擎不读"。

## 画布两栏的默认开合状态 (左侧模块库 / 右侧面板)
用户说「左侧模块栏默认关闭 / 默认打开」这类话时, 改的是**一处默认值, 不是行为逻辑**:
- 左侧模块库只有**一个真源**: `SimulinkModule.__init__` 里建完 `self.library = LibraryPanel(self)` 之后那句
  `self.library.set_collapsed(<bool>)`。**别去改 `LibraryPanel.set_collapsed` 本身** —— 它同时服务 ◀ 按钮 /
  双击「📚 模块库」标题 / 工具栏三条路, 动它会连带坏交互。
- 收起态 = `setFixedWidth(LIB_W_COLLAPSED=20)` + 隐藏标题/列表/提示, 只留 ▶(`expand_requested`);
  展开态回 `LIB_W=560`。**控件对象与 `_lib_btns`(454 条)一律不删** ⇒ 拖拽落画布 / 模块引导高亮 /
  「💾 存为新工程」全部照旧 (撤下显示 ≠ 删对象, 与右侧栏同一条规矩)。
- 这个默认值历史上被改成过强制展开 (为修「打开画布看不到模块库」) ⇒ 用户这次要的默认收起**不是回归**,
  别顺手再改回去; 收起态本身就保留 ▶ 且 tooltip 写明, 用户一点就开。
- 判据 (离屏真建, 别只看源码; 脚本 `scripts/probe_canvas_left_panel.py`): 断言 `_collapsed is True` ·
  `width()==20` · `_btn_expand.isVisibleTo(lib)` · `scroll.isVisibleTo(lib) is False` · `len(_lib_btns)>0`;
  再 `_expand_library()` → 560 + 列表可见、`_collapse_library()` → 回 20 —— 只验默认态不验回程, 等于没验可逆性。
- 交付口径: 明说**重启控制台才生效**; 正在跑的控制台**不要自己重启/杀掉**(可能是现场演示),
  先让用户目检, 目检过再 commit。
- 🔴 用户反驳「我本来就是 true 啊, 怎么打开还是展开」时, 先分清**两处同名写法**再用证据结案:
  `git show HEAD:tools/gui/simulink_module.py | grep -n "set_collapsed"` 一次列全三行 ——
  启动默认(在 `__init__` 里建完 `self.library` 那一句后面) · `_collapse_library()` 里的 `True`(◀ 按钮处理器) ·
  `_expand_library()` 里的 `False`(▶ 按钮); 用户常把处理器里的 `True` 当成默认值。
  再用 `ps -o lstart= -p <pid>` 对比 `stat -c %y <改的文件>`: 启动时间早于文件 mtime ⇒ **只是没重启**,
  不要改第二遍代码 (Python 启动时已把源码读进内存, 改文件对活进程零影响, 日志里还能看到他刚手动点过 ◀/▶)。

## 工程文件: 保存/加载整个「状态空间工程」 (2026-10-08 老倪: 文件菜单)
老倪: 「在控制台，文件下拉菜单，增加一个保存工程文件的功能，这样，我下次进入控制台，直接加载这个工程文件，就可以继续调试状态空间工程了。」
- 实现: `tools/gui/project_file.py`(逻辑, 可命令行自检) + `studio.py` 文件菜单两项
  (`💾 保存工程文件…` Ctrl+S · `📂 加载工程文件…` Ctrl+Shift+O)。
  **默认目录 = `data/database/`**(`project_dir()`; 2026-10-09 从 `reports/projects/` 迁来, 与工程库同目录), 扩展名 `.zmaxproj`;
  另有 v2「**总工程**」`data/database/zmax_space.proj`(七段: canvas/calibration/master_param/measure/tasks/panel/meta),
  对应控制台「文件 → 🗂 打开/保存总工程」—— 集成式回填(画布+标定+主参数+任务+面板), 见下方写盘铁律。
- 工程文件是**自包含** JSON 四段: `meta`(schema/时间/控制台版本/画布指纹 md5+统计) · `canvas`(画布真源全文) ·
  `run_cfg`(画布页 6 个运行档位勾选: chk_engine_demo/chk_l3_full/chk_mani_yaw/chk_intact_exec/chk_l4_dit/chk_l2_compat) ·
  `ui`(画布栈索引 —— 加载后自动切回画布页)。
- 🔴 加载 = **写画布真源**, 所以三道闸: ①先 `read_summary()` 把"这文件里是什么"摆给用户看, 他点确定才动;
  ②写盘只走 `flows.save_canvas()`(自带校验 + 备份到 `flows/_archive/`); ③坏文件(schema 不对/画布校验不过)拒载, 当前画布不动。
- 🔴 **「打开总工程」= 真写盘(集成式回填), 会把改动回滚**: 它按存档把 画布/标定/主参数/任务/面板 **写回现场**。
  改过画布后**必须先刷新快照 `python3 tools/project_archive.py space-save`**, 否则下一次打开(包括 `tools/probe_open_space.py` 这种离屏探针)
  就把你的改动**回滚**到存档那一份(实测: 改完画布跑一次打开探针, 改的注释被冲掉、库/绑定双双报漂移)。
  收尾跑 `probe_open_space.py` 验"打开后画布 md5 不变"= 幂等, 再交。
- 🔴 **快照别落进工程目录 (2026-10-12 实测)**: `project_archive.py save` 原默认输出 = `project_dir()`,
  与总工程 `zmax_space.proj` **同目录** ⇒ 控制台「打开/加载工程」的文件对话框里并排两个 `.proj`,
  用户当场问「怎么突然多出来一个工程文件? 两个工程文件加载哪个?」。已改: `save` 默认落
  `<工程目录>/archive/`(与既有 `archive/*.zmaxproj` 惯例一致), 工程目录只剩总工程。
  **加载永远只认 `zmax_space.proj`**(= `PF.space_path()`); 带时间戳的 `状态空间工程_<ts>.proj` 一律是
  时间点快照, 加载它 = 把画布/标定/主参数/任务/面板**回滚**到那一刻。
  排查口令: `find . -name "*.proj"` + `project_archive.py list`; 归属看 mtime 对不对得上当时跑过什么。
- ⚠️ `probe_open_space.py` 会把 `tasks` 报一次**假漂移**: 打开会刷新绑定文件的 `_meta.generated_at`
  (实测 13:29:57→13:33:50), 内容逐字段相同 ⇒ 它的比对本没忽略时间戳。看真漂移用
  `project_archive.py space-show`(已忽略 `_meta/generated_at`)。
- 📐 幂等判据要用**内容**不用 md5: 打开前备份 vs 打开后真源, **逐节点 JSON 相等(0 变化)+ 连线逐条相等**
  (实测口径); md5 变了只是重新序列化(键序/缩进), 不代表画布变了。
- 🔴 **改画布后的下游同步顺序 (不能换)**: ① 改画布 → ② `ss_node_sync.py`(节点配置段要同步时)
  → ③ `ss_task_bind.py --activate <task>` → ④ `project_archive.py space-save`(刷新总工程快照)
  → ⑤ `engineering_db.py build` → ⑥ `ss_task_bind.py --check` + `engineering_db.py check`(+ 工程库服务 restart)。
  为什么卡这个序: ⑤必须在④之后 —— 先 build 再 save, 库就比总工程旧, `check` 每次都报 `drift ['project']`(实测反复中招);
  ④必须在③之后 —— 快照里落的是任务绑定指纹, 早了存的是旧的。画布 md5 一变, `ss_task_bind --check` 就会报"需重绑定"。
- 🔴 **增删/改接线（删一条线同理）还要多两步** (漏了就留旧线): `engineering_db.py build` **不重建** `mw_link/mw_port`
  ⇒ 必须单跑 `tools/mw_db.py sync`, 再重建 `busdb.json`
  (`PYTHONPATH=src python -c "from lerobot.dataspace import busdb; db=busdb.build(); busdb.save(db)"`),
  否则数据空间 Trace 里那条线/那个端口行照旧在。回读断言: `mw_link` 里该 link_id **0 行**且 `mw_port` 无该 in 口,
  Trace 里该 `ss.node.<id>.<port>` 话题 **0 行**; 对端 `outs.<port>.consumers` 要一并去掉被删节点。
  `data/` 与 `config/` 都在 `.gitignore` ⇒ 这步通常**没有 git 提交**, 别拿"git status 干净"当没生效。
  七步完整顺序 (含备份位置/symlink 同 inode/判据清单): `zmax-state-space-architecture::references/trace-signal-panel-consistency.md` §11。
- ### 两条入口打开"同一个工程"为什么看起来不一样 (先证内容同源, 再量加载后几何)
用户报「画布的状态空间按钮打开的工程，和文件加载工程文件，打开的不一样」时, 默认**不是两个工程**, 而是同一份真源的两种加载姿势。

排查顺序 (顺序不能换):
1. **内容同源**: `os.path.samefile(flows.canvas_path(), SM._flows_path("state_space_obs.json"))` + 两份 canvas md5。
   真源与 `.proj` 存档的 canvas 段通常**逐字节同源** ⇒ 差异不在内容。
2. **再量加载后几何** (逐节点 x/y/w/h): 两条路各离屏加载一次再比。
   实测同一份 JSON: 按钮路 **38/74** 个节点被挪, 工程加载路 **33/74**, 同一节点 x 差几十~几百 px (如某推理节点 9456 vs 9323)。
3. 差异对不上就先看那张拓扑图 (下面第 3 条), 别去改 `flows.save_canvas` 的写盘链。

机制 (为什么必然不同):
- 🔴 **真源 JSON 里的 `x/w` 只是输入**: 画布加载会把普通节点统一画成 280×110 (真源里存的常是 160×68)
  ⇒ "文件坐标 ≠ 屏幕坐标"是常态, **不能拿屏幕坐标判断两个入口是不是同一个工程**。
- 🔴 **两条路的"加载后处理"不一致**: `open_state_space()` (工具栏「🧮 状态空间」) 在 `load_flow_file` 之后**额外调
  `_relayout_row_gaps(min_gap=56)`** (按 `round(y/60)` 分桶把桶内节点推到"前一个右缘+56");
  工程加载路 (`_write_canvas` → `flows.save_canvas` → 重载) **不调** ⇒ 同一份 JSON 摊出两套坐标。
- **回填范围也不同**: 按钮只回填**画布**; 文件加载/打开总工程是 **7 段集成式回填**
  (画布 + 面板/6 运行开关/画布栈 + 标定 + 主参数 + 测量 + 任务) ⇒ 右尸栏/档位/参数也会变。
  交付时要把这层一并说清, 否则用户会把"右侧栏不一样"也归到"画布不一样"。

统一口径的修法 (二选一, 别两边各改一半):
- 让两路走**同一套加载后归一**, 并把归一后的坐标**写回真源** ⇒ 文件==屏幕, 下次谁打开都一样, 也不再累积漂移; 或
- 两路都不做 relayout (但 `_relayout_row_gaps` 是当年为解决"放大后节点互贴"加的, 去掉要重验重叠)。

工具: `scripts/canvas_entry_geometry_diff.py` (离屏, 只读真源) —— 一次跑出: 是否同源 · A/B 几何差哪些节点 · 各被界面改了多少。
实测旁证: 工程加载留痕在 `zmax_data/logs/open_project.log`, 画布备份在
`data/database/<产品>/sources/canvas/_archive/state_space_obs_before_space_open_*.json` ——
**两者内容 md5 相同 ⇒ 加载只动了界面, 没改内容** (能当场排掉"工程被改坏"的怀疑)。
工程库 `.db` 的 `canvas_nodes` 只有 74 条 (真源 89 节点) 是**设计口径** (只存与 `functions` 对齐的逻辑节点), `engineering_db.py check` 全绿即正常, 不是漂移。

保存前也要校验: 把有问题的画布存成"工程"比存不上更糟(下次加载会把它们写回来)。
- 命令行自检 `gui-venv311/bin/python tools/gui/project_file.py`; 端到端自检(存→读摘要→载→画布 md5 不变 +
  备份生成 + 软链未被替换 + 坏文件被拒)见 `/tmp/verify_project_feature.py`, 加 `--studio` 再验 studio.py 离屏 import。
- ⚠️ `QFileDialog` 在 `studio.py` 里是**函数内局部导入**(不在顶部 import 块) —— 新写的 handler 里要自己 `from PyQt5.QtWidgets import QFileDialog`。

## 画布全图 PDF 导出 + 一条命令发布 (2026-10-01 起, 用户要"手机随时下载最新版全图")
| 东西 | 位置 | 说明 |
|---|---|---|
| 渲图 (矢量, 不吃 GUI/截图) | `tools/canvas_pdf_export.py` | 读真源 JSON 直画: 封面/图例页 + 全图总览 1 页 + 分层详图 (3 行带组 × 自适应分列)。页脚**逐页**写"累计已画 节点 N/89 · 连线 M/182"自查 + 版本 + 生成时间 |
| 发布/路由逻辑 | `src/lerobot/engineering/canvas_publish.py` | 真源 realpath · 版本号 `v<YYYYMMDD 真源 mtime>-<md5:8>` · 产物目录 `reports/canvas_pdf/` · `serve_route()` (8796 只读路由) · ECS 推/回读 |
| 一条命令 | `tools/publish_canvas.py` | 渲图→算版本→推 8796→推 ECS; `--if-changed` 幂等; `--shots DIR` 出首屏/总览截图 |
| 手机固定 URL | `https://datadrive.world/canvas_latest.pdf` (+ 留档 `canvas_<version>.pdf`) | 走 `ss3d_push.php` (token + 文件名白名单, 已加 `canvas_*.pdf`) |
| 自动更新 | crontab `7 * * * * … publish_canvas.py --if-changed` | 真源 md5 或**渲染器指纹**变了才重渲重推 |

布局 / 自查要点 (都实测过, 别走回头路):
- **PDF 字体必须同时有 Latin + CJK**: `DroidSansFallbackFull.ttf` 只有 CJK ⇒ 版本号/机位/数字**整段消失**(截图里看着像"排版空了"), 用 `wqy-zenhei.ttc` (subfontIndex=0)。emoji 无字形 ⇒ 用 `sanitize_label()` 去掉, 否则黑框。
- **页数不是靠"好看的固定比例": 列/行切点必须落在空白里**。行带组切点 = 相邻行带之间空档中点 (选 2 个使 3 组节点数均衡); 列切点 = 节点 x 空档中点, 列数与边界用"列宽 + 节点数"代价函数选 ⇒ 自动避免"某页只有 1 个节点"的废页, 且**不切断任何节点**。写死坐标的下场是画布一改版就切穿节点。
- 连线走**正交折线**: 跨行带走两行带之间的走廊 (不穿节点行), 同带走带内下轨; 跨距 >8000px 弱化为细线+低透明度。画序: 行带底 → 连线 → 节点 (交叉被节点盖住)。
- 自查口径: 页脚写"累计已画"(总览页一画完就是满值) + 每页另算窗口内数量; 收尾断言 `drawn_nodes/drawn_links == 真值`, 不通过就 `exit 3`, 发布脚本据此拒绝上传。
- **发布后必须自己把产物拉回来验, 不采信子代理/发布脚本的自述**(它们报的 md5、状态码、页数可能只是自己想象的):
  `curl -sI <公网 URL>`(200 + `application/pdf` + 字节数) → `curl -s <URL> | md5sum` 与**本地产物 md5 逐位比** →
  再用**独立引擎**复算页数与页脚自查数(`pdfinfo` 看 Pages / `pdftotext … - | grep 页脚`), 不读导出器自己 print 的那行。
- **`--if-changed` 不能只看画布 md5**: 改了布局/字体的"渲染器改动"不会被重推 ⇒ 把导出器+发布模块源码 md5 也当指纹比 (本项目曾因此漏推)。
- 8796 是 stdlib `BaseHTTPRequestHandler`: 想让 `curl -I` 可用必须补 `do_HEAD`(= 转 `do_GET` 但**不写 body**); 否则 501。
- ECS 白名单只加不改: `$ALLOW` 保留原两条, 新增 `$ALLOW_GLOB=['canvas_*.pdf']` + `fnmatch`; 上线前 `cp .bak_<ts>`, 改完远端 `php -l`。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| PDF 用只含 CJK 的字体 | 数字/英文/版本号整段不见 | 换 `wqy-zenhei.ttc` 等 Latin+CJK 字体 |
| 只做语法校验就交付 | 语法过、控制台起不来 | 必须走 ②导入 ③渲染 ⑤运行 三层 |
| 把"节点数对了"当成功 | 节点 88→87 但**连线 167→0** | 渲染级数字双看: node items **与** link items |
| 端口字典格式 | 断言/渲染随机踩坑 | 统一归一为字符串列表 |
| 长命令内联被拦 | heredoc/巨型单行触发 hardline 拦截 | 写成 `/tmp/*.sh` 再 `bash` 执行（本环境惯例） |
| 想靠重排消除交叉 | 改完交叉更多 | 量化后再判; 跨行长线只能靠正交布线 |
| 对画布文件做 `tmp`+`os.replace` 原子写 | 仓库根 `flows/state_space_obs.json` **和** `src/lerobot/engineering/flows/state_space_obs.json` 都是**软链** ⇒ 被换成普通文件, 工程结构破坏 (`verify_platform_spec` ⑦ / `instance_init.py --check` 立刻变红) | 写前 `os.path.realpath()` 取真源路径再 replace; 备份放仓库根 `flows/_archive/` (既有约定) |
| 以为画布真源只有一份 | 改了一份、GUI 读的是另一份 ⇒ 改了看不见 | **真源 = `data/database/<产品>/sources/canvas/state_space_obs.json`**; `src/lerobot/engineering/flows/state_space_obs.json` 是指向它的**软链** (GUI 经仓库根 `flows/` 软链读同一份)。判据: `bash`→`realpath flows/state_space_obs.json` 必须落在实例包内 + `tools/instance_init.py --check` ①全绿 |
| 改完画布没重存总工程 | `verify_project_archive` 报「集成式打开后 diff: 总工程 == 现场」❌ | 改画布后按序: 画布 → `ss_node_sync.py`(需要时) → `ss_task_bind --activate` → **`project_archive.py space-save`** → `engineering_db.py build` → 两个 `--check` |
| 以为两条入口打开的是**两个工程** | 同一个工程, 两入口画布摆位/右尸栏不一样 | 先证内容同源 (`samefile` + canvas md5), 再量"加载后几何" —— 差异多来自 `_relayout_row_gaps` 只在按钮路跑; 见«两条入口打开同一个工程» |
| 逐项比对探针报"一致 0 / 不一致 0" | 看着像"完全没差异", 其实是**键集合不相交** (一边用 id 一边用 name) = 假绿 | 探针先 `assert set(a) & set(b)` 且断言交集条数 == 两边条数, 再比内容; 键一律用同一个 `key(n) = name or id` |
| 画布真源被 GUI 保存**悄悄回滚** | 改了真源, 过几分钟内容又变回旧的 (实测 mtime 变、`params.core` 消失) | 控制台退出/另存为会把内存里的画布写回真源 ⇒ **① 改完立刻回读 + 记 mtime; ② 尽量在控制台没加载该画布时改; ③ 交付前再回读一次**, 别只看第一次写成功 |
| 加节点后忘了同步 `_EXTERNAL_LOC` 行号 | `t_auto_srcmap`(L2/L4 在跑) 报「Lx无符号」 | 改真源后重算 `class X`/常量的行号并更新映射 (±3 行容错但别赌) |
| 以为改 `capability_levels.py` 会改变断言数 | 只在 `groups` 里报真实 `t_*` 前缀才影响计数; 加 `groups: []` 的功能条目 (如 L4-C16) 计数不变 | 加能力条目用空 groups; 别写错前缀 |
| 标定参数写盘顺手 `sync_calib(write=True)` | `calib.json` 其他域 (内参/几何/TCP) 被一起刷新成"当前源", 意外改变在役读值 | 只读写自己那一节 (读-改-写单键), 别整表重合并 |
| 忘了重启控制台 | 用户看到旧拓扑 | 改完必重启 + 确认 `Traceback=0` |
| 现场拖动前没起录制 | 这一趟动作数据永久丢失 | 先架录制/叠加再回"准备好" |
| 生产端用 `x or []` 兜底(numpy 数组) | 首帧 `ValueError: truth value of an array ... is ambiguous` 被 `except: return False` 吞掉 ⇒ 产物文件永不生成、日志一句没有 | 用 `x if x is not None else []`; 生产函数的 except 必须打 traceback; 判活看**产物文件 mtime/点数**, 不看进程在不在 |
| 节点上画的开关点了没反应 | ①命中写在 `SimNodeItem.mousePressEvent` 里 ⇒ canvas 层先拦走左键, 永不执行 ②命中矩形与绘制矩形各写一遇 | 命中放 **canvas 层**、排在拖动之前; 几何抽成一个 `_rect(w,h)` helper 供绘制+命中同调; 每次点这个节点都 `print` 一行"点在哪/矩形在哪/命中与否", 用户报点不动时直读日志 |
| 拿自报日志当副作用发生 | "页已打开"其实浏览器没起 | 查外部痕迹: 进程 lstart / 浏览器 History, 不信自报 |
| **用自己的临时脚本判"孤岛/断线"** | 连线字段名猜错 ⇒ 误报 `ss_seg` "入度=0 出度=0", 差点"为改而改"去接一条**本来就存在**的线 | 判拓扑只用**工程自带**手段: `canvas_node_audit.py`(孤立/断头/悬空) + `match_node(节点名)` + 渲染级 link items; 自写脚本必须先用一条**已知存在**的连线做正例自检 |
| 按钮反馈只写日志/节点小字 | 用户连报"点了没反应" | 反馈落在**他刚点的那个控件**(按钮文字)+ **节点边框状态色** + 下面终端日志(变化时才写); 画布上不铺字(见"长任务触发器") |
| 把状态文字铺在画布上(横幅/节点进度行) | 用户嫌丑: 「这几个字太丑了…赶紧删掉」 | 文本只进下面终端(内容变化才写一行); 画布留边框状态色即可 |
| 用"它其实在跑"回答"没反应" | 用户继续报没反应 | 先把功能启动做成看得见, 再解释; 见"长任务触发器"节 |
| 以为节点能显示画面 | 赋了 pixmap 也没画面 | 先 grep 该字段写点; 死代码分支要自己接定时器 + update() |
| 新节点只有名字没关键字 | 双击无反应(落兜底) | 在 `node_logic.NODE_LOGIC` 补关键字 + 真双击一次 |
| 用 `stage_detail.pid` 判后台任务在不在跑 | 阶段切换间隙误判成"没在跑" ⇒ 徽章停更 / 重复启动 | 判活看**编排自身 pid**(状态文件顶层 `pid`) + state 文件 mtime 新鲜度兜底 |
| 产物落盘函数自己 try/except 吞异常 | 日志说"已落盘", 文件几小时没变 | 落盘函数里变量名逐个起(spec 与速度列表同名 ⇒ `sum(dict)` 抛 `int+str`); 判据断言文件 mtime 变 + 新字段在 |
| 只把状态写在画布节点小字 | 用户连报三轮"没反应" | 状态写到下面终端(变化才写)+ 按钮文字 + 边框色(见"长任务触发器"), 并把"需重启才生效"说在前面 |
| 横幅每次轮询重铺 | 状态停在 failed ⇒ 提示永久顶在画布上, 用户要求"怎么关不掉" | error 只闪 ~15s 自隐 + 新一轮启动时清标记; 历史终态文案写"上次…"; 别在终态 `timer.stop()` |
| 点击瞬间设的反馈被同函数后续分支回写 | 按钮文字永远不变(用户照旧报没反应) | 按钮文字交给轮询驱动, 或设完后 grep 本函数内该控件的所有写点 |
| 气泡/浮层用场景坐标当屏幕坐标 | 气泡飘到窗口外、被盖住 | `mapToGlobal(mapFromScene(...))`; 内容用真实状态, 不写死"已启动" |
| 进度写死分母 (n/7) | 实际 9 阶段 ⇒ 一开跑就显示 9/9, 像已跑完 | 分母从状态文件读 |
| 手工拼命令重启控制台 | GUI 起不来 / 窗口不出现（缺 `XAUTHORITY`/`XDG_RUNTIME_DIR`/DBUS） | 用仓库启动器 `tools/gui/launch_studio.sh`（自带环境 + 防重复实例）；或从旧进程复用环境：`cat /proc/<pid>/cmdline` + `tr '\0' '\n' < /proc/<pid>/environ \| grep -E '^(DISPLAY\|XAUTHORITY\|XDG_RUNTIME_DIR)='` 后再启 |
| 子代理起的控制台随它退出而死 | 交付验收时 GUI 是死的（用户那边"打不开"） | 常驻进程必须**脱离**启动（`setsid nohup … </dev/null &`，或 terminal `background=true, persist_on_release=true`）；父会话在子代理交付后**重验进程还在**，不在就自己重起 |
| 用 `pgrep -f "tools/gui/studio.py"` 判活 | 会命中**自己的 shell 命令行**（命令串里就含这个模式）⇒ 假"在跑" | 用脚本自带的精确模式 `pgrep -f "gui-venv311/bin/python studio.py"`，或 `ps -eo pid,cmd \| grep "[s]tudio.py"` |
| 用 `pkill -f <模式>` 杀进程（内联在命令里） | **连自己的 shell 一起杀**：模式匹配到当前命令行 ⇒ 命令输出戛然而止、后续步骤全没跑（比误判"在跑"更狠，本次实测把自己 shell 杀了，两条 `set -e` 脚本都断在半路） | 杀进程用 `pgrep -x <精确进程名> \| xargs -r sudo kill`（`-x` 只匹配进程名），或整段写成 `/tmp/*.sh` 再 `bash` 执行，别内联 `pkill -f` |
| 扫描 `/proc/*/cmdline` 自己找 pid 的长驻进程（`for p in /proc/[0-9]*; do case "$cmd" in *tools/x.py*)`） | 同样会命中**自己这条 bash 命令** ⇒ kill 掉自己，工具调用直接 `exit -15`，后面的重启/验证全没执行 | 常驻服务启动时写 pidfile/lock：**从 pidfile 读 pid**，再在 python 里核对 `/proc/<pid>/cmdline` 确实是它，然后 kill；不要在 shell 循环里按子串匹配进程 |
| 判据用 `abs(req_x - x) < 1e-6` 当"页面设的值真用上了" | 速度/步长链上有单位换算与限速闸，两者天然不等；若 req 取的是**限速后**的值，这条断言永远假绿 | 按**同一定义域**比：页面 `req_speed_mm_s` 对 `speed_mm_s_actual`，detail 打全四段值（页面/原始 units/限速后 units/实际 mm/s）；见 `references/message-signal-db.md` §10 |

## 工具栏按钮「建了没挂」类 bug (2026-10-10 老倪: 3D 视图按钮哪里去了)
- 症状: 用户说按钮不见了; 代码里 `self.btn_xxx = mk_btn(...)` 明明在, 且 clicked 也接好了。
- 真因: 按钮对象建了但 **`tl.addWidget(self.btn_xxx)` 被删**(工具栏精简/重构时只删了 addWidget 行)
  ⇒ 对象在、信号在、**永远不会显示**。
- 判据必须双重: ① 对象在 ② `.text()` 对 ③ **`isVisibleTo(m)` 真挂进布局**(删 addWidget 只有第③条能抓到)。
  `tools/probe_canvas_menu.py` 的工具栏循环就是这条判据 — 新按钮一律加进去。
- 入口丢失要先查 addWidget 所在层: `grep -n "addWidget(self.btn_" tools/gui/simulink_module.py`。
- 恢复习惯: 工具条常驻 + 「画布(C)」菜单双入口(菜单项 `triggered` 接到**同一按钮**的 click,
  不要把常驻按钮 `setattr` 成 QAction — `attach_canvas_actions` 里 6 个替身项是那个用法, 新按钮不是)。

### 从画布开一个「独立窗口」按钮的完整收口 (2026-10-14 老倪「在状态空间工程增加一个模型引擎按钮」)
1. 按钮 = `self.btn_xxx = mk_btn("🧠 模型引擎", "<多行 tooltip: 数据真源/复用口径/干什么>", self.open_xxx, "#c9a0ff")`
   + **紧跟 `tl.addWidget(self.btn_xxx)`**；挨着同类按钮放 (本次挂在「🗂 配置中心」右边)。
2. 打开方法 = **薄壳**: 已有且 `isVisible()` 就 `raise_()+activateWindow()` 复用 (不新开第二个),
   否则 `ModelEngineWindow(self.window() or self)` → `show()` → **写一行日志**。父窗口只用于定位/生命周期,
   窗口内容必须是**与控制台同一个面板类**, 不要为画布另写第二套界面 (两套必然漂移)。
3. **可见性必须查**, 别只看源码在: `tools/probe_canvas_me_button.py` 离屏真建 `SimulinkModule()` → 打印新按钮
   `isVisible()` + 全局 x 范围 + 模块右边界 (本次 1400 宽下 x=1214..1314 < 右边界 1402 ⇒ 完整可见;
   真屏上用按钮文字色 `#c9a0ff` 聚类找坐标，紫钮像素 x 1121..1292 ✓)。
4. **真鼠标点击取证** (`tools/click_canvas_me_button.py` 按色聚类算中心 → `xdotool mousemove/click`):
   先 `wmctrl -c` 关掉旧窗 → 点按钮 → `wmctrl -lG` 应出现新窗口 + 日志出现自己那一行;
   再点一次/再触发一次 ⇒ 窗口个数**仍为 1** (复用没重复开)。
5. 控制台命令通道同步开一条 (`elif line == "ss_model_engine": _oneshot(self, 600, self.simulink.open_model_engine_window)`),
   方便无鼠标复现; 但注意 `open_model_engine_window` 定义在 **SimulinkModule** 上 (不在 studio 主窗),
   写 `self.open_...` 会 AttributeError 被 except 吞掉 = 点了毫无反应。
6. 判据: `tools/verify_model_engine_same_render.py` ⑦a~⑦d 钉住「按钮在布局里 / 回调是同一个窗口类 /
   复用逻辑在 / 命令通道在同一执行体」。

## 两个 Python 级陷阱 (都在 simulink_module.py 真踩过, 2026-10-10)
1. **函数内某分支 `import sys` ⇒ `sys` 变局部名** ⇒ 同函数别处的 `sys.path` 抛
   `UnboundLocalError: cannot access local variable 'sys'`。open_ss_3d 里就是这句 —— 后果是
   `attach_scene_edit` 从来没执行, 被 `except Exception: print(...)` 吞成一行日志 ⇒ 界面看起来正常,
   功能其实没接上。**规矩**: 同函数内要用就用 `import sys as _sys`; 更狠的是这类 except 只 print ⇒
   判据必须**断言功能真挂上**(如 `getattr(win, "_scene_edit_attacher", None) is not None`), 不信日志。
2. **`QPushButton.clicked` 会把 `checked=False` 当第一个位置参数** ⇒ `btn.clicked.connect(fn)` 里
   若 `fn(level=None)` 就变成 `level=False` (静默错误参数)。一律 `lambda: fn()` 包一层。

## 打开工程即居中 + 核心节点色 (v5.37.1)
老倪: 「每次打开状态空间工程, 屏幕中心就是这个节点; 改变这个节点的背景颜色, 让人一下子就认出流形引擎是系统的核心」。
- **配色 (已定稿)**: 核心 = 全画布**唯一暖色**「琥珀金 #FFC53D」—— 双层光晕 (`255,197,61` α17/38) + 金渐变体 (`#6B4A00`→`#2A1C00`) + 3px 金框 + 右上「◉ 核心」金底徽章。
  其余节点一律冷色 (蓝灰/青/紫/绿) ⇒ 暖色即核心。**不要用金/橙做别的节点**, 否则标识失效。
- **判据数据驱动**: `SimNodeItem.paint` 里 `is_core = params.core or params.manifold_engine or type/id=='ss_mani_eng'`。
  ⚠️ 必须带 `params.manifold_engine` 兜底 —— `load_flow_file` 会**重编 id**, `type` 是 `model`, 只认 id/core 会在 GUI 里失效。
- **打开工程即居中**: `load_flow_file` 成功后 `QTimer.singleShot(0/450, self.center_on_core_node)` (两次, 防被后续 fit 覆盖) +
  工具栏「🧮 核心居中」开关 (默认勾选) + `Ctrl+Shift+C` 手动居中 + `showEvent` 兜底 (**只在 `canvas.viewport().width()>200` 即真布局时才算数**, 否则 centerOn 算到错位置)。
  `core_node_id()` 找不到核心要**如实报缺**, 不假装居中过。
- **取证 (无视觉工具时的口径)**: `tools/tests/test_core_node_ui.py` 真渲染成 QImage 数**暖色/纯金像素** (核心 975 采样值 vs 普通 0) +
  真 `SimulinkModule` 加载真工程后量「视口中心 vs 核心中心」偏差 (实测 dx=dy=1.0); 已并入 `run_gui_verifiers.sh` (core_node_ui)。
  活体复核: `DISPLAY=:0 scrot -o /tmp/x.png` + 像素统计 (画布不在前台时数不到暖色, 不要误判成"没生效")。

## 在画布节点上做一个「鼠标可点的开关/拨钮」(状态存节点 params)

用户说「这个开关做在 X 节点上, 我要用鼠标控制」时, 不要只给面板里的勾选框 —— 开关要画在节点本体上并且**点得中**。
五件缺一就是「点了没反应」:
1. **三处同一几何**: 绘制矩形、命中矩形、写回口径用同一个表达式 (底部条 `QRectF(8, self.h - 26, self.w - 16, 20)`)。
   各写一遇 ⇒ 画在这儿、判在那儿, 点偏几像素就不触发。
2. **绘制**: 开 = 绿框 + 实心点, 关 = 灰框 + 空心点; 文案带**当前生效值**(硬上限之后的值, 不是配置值);
   超宽用 `elidedText`, 不换行不裁字。
   🔴 **安全类开关(动真机/能量/桥接)不许做成 20px 小 pill** —— 用户会直接说"太不好看、看不出来"。
   定稿形态: **整条 34px 高**(占节点底部约 1/3) + 2px 描边(关=红 #e05252 / 开=绿 #3fb950) + 同色外发光,
   左侧**拨杆轨道 + 滑块**(关靠左红 / 开靠右绿), 两行文字: 标题「⚠ <功能名>」+ 状态行
   「已断开 · 不驱动 (点此接通)」/「已接通 · 输出 ≤10mm/s · 死区 3」—— 状态行必须带生效值,
   用户要的是"一眼看出通没通、限多少"。
3. 🔴 **命中**必须**写在 `SimCanvas.mousePressEvent`(canvas 层), 不是 `SimNodeItem.mousePressEvent`**:
   canvas 对"节点上的左键按下"一律先拦 (端口拖线 / `cap_switch` 档位 radio / 拖动节点) 并 `return`
   ⇒ 节点自己那层 `mousePressEvent` **永远收不到** (写在里面的命中 = 死代码, 用户报"点了没反应")。
   位置: 进 `if isinstance(item, SimNodeItem):` 之后、`p = self.mapToScene(...)` 拿到场景点之后,
   排在"端口/档位/拖动"之前: `_bridge_rect(n.w, n.h).translated(n.scenePos()).contains(p)` 命中就
   `self.module.on_toggle_bridge(n.node); return`。
   旁证: 画布上的 `cap_switch` 档位 radio 就是做在 canvas 层才点得中的; 节点层可以留一份同样的兜底,
   但**不能只有节点层**。
4. **处理器在 SimulinkModule** (`scene_ref` 就是 module 实例, 不是 QGraphicsView): 翻 params → `self._items[id].update()`
   → `self._save_param_to_flow(node, key)` → `self._log(...)`; 日志把**生效口径**(硬上限/死区)写出来, 别只写"已开"。
5. **状态唯一真源 = 画布 JSON 的节点 params**: 3D 面板/侧栏的勾选框读同一份(mtime 缓存), 两边改都生效 ——
   各存一份必然出现"面板开了、画布没开"。

上限类参数(速度/力/电流)另加一条: **代码里硬上限 + clamp 配置 + 超限打日志**, 配置写多大都不算 ——
真机安全不能依赖一个可被随手编辑的配置文件。
🔴 **仿真速度接到真机链路上的桥接开关**(把仿真 v_ff 变成位姿/动作): 用户对它的硬要求是
**只跟方向、不跟幅值** —— `v_cmd = normalize(v_ff) · min(|v_ff|, cap)`, 且
**cap 有代码常量硬上限 10mm/s**(配置写 20/50 一律按 10 执行并打日志), 另加**死区 3mm/s**
(低于就不动, 防仿真噪声让真机持续蠕动)。位姿只积分**位置**(p += v_cmd·dt), 旋转未建模就写 `null`
并标"未建模", 不许拿 0° 冒充已知姿态。

### 没鼠标也能验 (两件离线证据 + 一件真屏证据)
- **事件级(最硬的一条, 别省)**: 离屏真建 `SimCanvas(stub_module)` + `SimNodeItem` 进 scene, 用
  `QApplication.sendEvent(view.viewport(), QMouseEvent(MouseButtonPress, view.mapFromScene(点), LeftButton,…))`
  真走一遍 `viewport → SimCanvas.mousePressEvent → itemAt → 命中 → handler`; stub 模块记 `calls` 列表,
  断言"点开关条中部/拨杆 → 调用一次"、"点节点上部标题 → 不调用"(证明没抢走拖动)。
  只测 handler 单测会漏掉"事件根本没派发"这一层 —— 那正是用户看到的现象。
- **处理器单测**: 把方法绑到 stub 上 (`_items={}` · `_save_param_to_flow` 记 (id,key,值) · `_log` 记串), 连点 3 次断言
  `True→False→True` 且每次存回值对; cap 配 50 时日志里必须报硬上限值(实测 10)。
- **绘制**: 离屏造 `SimNodeItem(node, stub)` 直接 `it.paint(qp, opt, None)` 渲成 PNG, 再
  `tesseract -l chi_sim+eng --psm 7` 认那行字(开/关两态各一张)。现成脚本 `scripts/render_canvas_node.py`。
  🔴 stub `scene_ref` 至少要有 `links=[]` · `nodes={}` · `_items={}` · `_flow_path=None` —— `_paint_core` 会遍历
  `self.scene_ref.links`, 缺了就是 `TypeError: 'NoneType' object is not iterable`, 看着像"节点画不出来"。
- **真屏**: 最终以用户点一下为准(交付话术写"点它一下看状态变没变"), 别把离屏图说成"你屏幕上已经生效"。

### 🔴 安全开关必须有一个真消费点(否则只是画在节点上的装饰)

画布上做「AR 开关 / 真机开关」这类**安全类**双开关时, 语义分工与落法:
- **两个正交语义**: 路由开关(AR 场景=仿真左右臂 / 关=直接控真机) 管"发到哪"; 授权开关(真机) 管"发不发"。
  授权开关**必须写已有的那一个授权真源**(如 `tools/ctl_auth.grant/revoke`), 不要另立第二套授权表 ——
  否则页面授权开门、画布开关关门, 两处各说各话, 现场永远说不清"到底谁拦的"。
- 🔴 **消费点放执行器里那个集中闸门函数的最前面**(如 `l2_daemon._auth_guard()` 第一句), 不要散进每条命令:
  开关只写状态文件而没人读 = 画布上多个按钮而已。判据要能答"开了以后谁拒绝我"。
- 🔴 **开关状态文件要 fail-open(超龄即不拦)**: 状态文件帧龄超过阈值(实测定 **1800s**)就按"未拦截"处理并继续走原闸门。
  阈值必须**远大于控制台的写盘频率** —— 控制台只在"点开关那一刻"写一次, 取 120s 时页面两分钟后自己退回默认模式,
  用户以为开关失效; 1800s 兼顾"点一次撑完一场演示"与"控制台失联不把现场锁死"。改这个常量时两处必须同改
  (服务端端点与执行器闸门各一份), 一边大一边小就出现"页面还在 AR、闸门已经不拦"。
  反面(fail-closed)会让控制台没起/崩溃/断网时**把现场永久锁死**, 而用户此时连开关都点不到。
- 五层判据(缺一层就会交付一个点不中/不生效的开关): ①真源默认态(两个都关) ②绘制(关态渲出红、开态绿, 数像素两态都非 0)
  ③**事件级**(点左开关命中 1 次、点右 1 次、点标题区 0 次 —— 证明没抢走拖动) ④消费端(无状态文件=不拦 · 开=拦 · 关=不拦 · 过期=不拦)
  ⑤**判据自己收尾复位**: 事件级判据必然连点开关, 跑完就把安全开关**留在开的状态写进画布真源**(实测漏这条 → 下次打开控制台直接是 AR 模式)。
  脚本末尾必须把 params 复位成默认关并**回读断言**, 别信"我传进去的是 False"。

### 开关要「接上画面」时 = 服务端只读端点 + 页面轮询 + 只在跳变时应用
开关只落到执行器闸门时, 用户点开 AR 仍然"什么都没发生"(他要看到 AR 场景)。接法四层, 缺一层就是半截:
1. **服务端加只读端点**(如 8797 `/api/ar/mode`): 直接读控制台发布的那份 live 状态文件, 返回 `{on, real_auth, age_s, fresh}`。
   **过期口径要和处理方向一致地"不锁人"**: 文件帧龄超阈值 ⇒ 端点返回 `on=false`(页面自动退回默认显示);
   而执行器闸门那边是 fail-open(不拦)。两边都是"按默认处理", 不许一边不拦一边把界面锁在 AR 模式。
2. **页面轮询只在状态跳变时应用视图**(`if(on===LAST.on) return;`): 每 2s 无条件写视图会把用户**手动切的显示开关**一路抢回去,
   症状是"我关了真机臂它自己又跳回来"。横幅文案可以每轮刷新(带帧龄), 视图状态只在跳变时改。
3. **画面必须自报状态**: 横幅写清「AR 场景 · 由状态空间画布控制左右臂 · 真机不下发 · 开关帧龄 Ns」——
   用户把这个页面当结果看, 只靠执行器日志他读不出当前在哪一层。
4. 🔴 **判据要真开浏览器读 DOM**(`browser_navigate` → `browser_console` 读横幅元素/页面全局变量),
   别只 `curl /api/...` 拿到 true 就交付: **API 通 ≠ 页面进了那个模式**。实测口径 = 横幅 `display`、真机臂标志位、按钮文案三者同变;
   再切回关跑一遍确认横幅 `display:none` 且标志位复原(只验进不验回 = 没验可逆性)。
5. 测试期外部副作用用 env 开关抑制: 处理器里 `if os.environ.get("ZMAX_NO_OPEN"): 跳过 webbrowser.open`, 判据脚本默认置上 ——
   否则事件级判据连点几次就弹一堆浏览器窗口, 把"验证"变成干扰。

⚠️ **改了服务端 .py 必须重启该服务才生效; 同服务的 html 是热读的不用重启** —— 两者别一起等。
这类服务多半有守护(cron/keepalive), `kill` 后几秒会以**新 pid** 自己回来 ⇒ 验证看**新路由返回什么**, 不要拿 pid 变没变当判据。

三个本次实测才暴露的坑:
- 🔴 `flows.load_canvas()` / `save_canvas()` **返回元组** `(data, errors)` / `(path, backup)`: 直接当 dict/路径用会 TypeError,
  或被 `d or {}` 兜底 **静默当成空画布**(最坏情况: 写出一个只有新节点的画布, 原图全没)。
- 🔴 `ctl_auth.info()` 的字段是 `armed` / `left_s` / `until` / `epoch` —— **没有 `remaining_s`**。
  取错名字只会显示 0/过期, 不抛异常 ⇒ 授权明明开着, 界面报"未授权"。
- 🔴 用 `SimCanvas(stub_module)` 做事件级离屏验证时, stub 模块要比 `SimNodeItem` 那套更宽:
  `SimCanvas.__init__` 会 connect 一堆 module 信号/回调 ⇒ stub 用 `__getattr__` 返回**可调用的空壳**;
  且必须**手动塞 `cv.links` / `cv.nodes`**(真 GUI 由 `load_flow_file` 填) —— 少了这两项, `_paint_core` 遍历 None
  直接让 offscreen 进程 abort, 现象很像"渲染代码改坏了"。
- ⚠ **只改节点 params 也算改画布**: `save_canvas` 会顺手 build 一次库, 之后 `project_archive.py space-save`
  必须**再跑一次 `engineering_db.py build`** 再 `check`, 否则报 `drift ['project','canvas']`(实测)。
  "这次只动了参数不动结构"不是跳过六步同步顺序的理由。

## 已有页面上跑着的功能要「用节点重做一遍」⇒ 两条并行, 页面一个字不改
用户说「这个功能一步步由状态空间的节点实现」、同时又说过「保留当前已实现的 X 不动」时, 这是**两条并行实现, 不是迁移**:
- 现有按钮 / JS / 数据文件**一行不改**; 节点读**同一份数据文件**, 在引擎里自己推时间轴。
- 原方案里"让页面改读总线"那一步**直接作废** —— 改了就是破坏他"点按钮还是老样子"的要求。
- 交付时明说两套并行、各自真源是哪个文件, 别让他以为旧路径已被替换。
- 节点是「能力」不是「每一步一个框」: 一个节拍循环器 + N 个原子动作节点 + 检测/分拣/统计, 392 段也只多 3 个节点。
- 🔴 **它的上游是数据源, 不是规划器/大模型**: 读预存段表的节点全程不读 `ctx` ⇒ 接 `ssllm`/VLM 只是画出**装饰线**
  (用户会直接问「没有大模型层就不能工作了么? 我 AR 场景都记下来了, 默认一键工作, 也没有语言层」)。
  落法: 上游接 `ssdata` 的空口(如 `out2`), 节点摆在**数据源行带**与 `ssdata` 邻位 —— 语义 = 「场景已录 ⇒ 数据驱动, 离线可跑」。
  判据: 白名单里只放它一个、`ctx` 为空也照常出数(实测连续 8 小时、每拍产物刷新)。
  加线前先用 `search_files` 看该实现的函数体里有没有 `ctx` —— 没有就是装饰线, 无论画得多顺。
- 段表语义(哪个字段是件号/段号)、实时 UPH 的预热坑、判据清单: `references/uph-tact-loop-node.md`。

## 调度有四层, 画布 UI 不是调度器
用户问「`simulink_module` 是不是整个系统的调度节点」时, 答**不是** —— 它是 Qt 画布界面层(负责连线怎么画/点了怎么响应/参数怎么落盘),
没有任何调度逻辑。真调度分四层, 找错层就白改一版:

| 层 | 真源 | 干什么 |
|---|---|---|
| 画布 UI | `tools/gui/simulink_module.py` | 画线/命中/参数落盘 (纯界面) |
| 数据流调度 | 画布 JSON 的连线 → `middleware/loader.py::topo_order()`(SCC 缩点→拓扑序) → `middleware/project.py::Project.step()`(逐 `nd.step()`) | 每节点 pull→compute→push |
| 任务/场景调度 | `tools/ss_scene_switch.py` | 任务 ↔ 场景 ↔ 画布数据源节点 |
| 动作调度 | `tools/l2_daemon.py` | FIFO → 授权 → 逐段闸 → 真机 |

改"谁先跑"去 middleware 拓扑; 改"跑哪个场景"去场景切换; 改"能不能动"去 `l2_daemon`。
判某节点在一拍里干了什么用 CLI (`mw_project.py step` → 读 `n.last_status`), 别靠 GUI 点击。

## 往画布插一个节点 ⇒ 先想清楚 FN-*-NN 编号会整体平移 (2026-10-25 实测)

`engineering_db.py build` 的 `functions.fn_id` 是**按行序的位置编号** (`FN-SYS0-50` …)，
而功能点描述真源 `data/database/zmax/function_notes.json` 原来按 `fn_id` 取 ⇒
**在任一位置插 1 个节点，它后面所有功能点的描述全部张冠李戴**（实测插 1 个节点 → 27 条描述错位，
而判据 ⑦b 因为“条数满员”反而显示 ✅，只有人工对名字才看得出）。

铁律：
- 描述一律按**节点名**取：`notes_by_name` 优先、`fn_id` 只作历史兼容兜底（`engineering_db.py` 里已改）。
- 插/删节点后必须重建库并**抽 3 条按名字核对** work 文本是不是这个节点该干的活，别只看“77/77 全绿”。
- 定位移植办法（换名/换顺序都能用）：用旧画布 build 一份临时库 `--db /tmp/old.db`，把
  `fn_id → name` 映射出来，再去重写 notes，别手工数序号。

## 验证清单
```bash
# 架构自检 (迁移后新增, 6 项: 逻辑在包里/JSON 真源/档位契约/GUI 壳一致/档位索引)
./gui-venv311/bin/python tools/verify_engineering.py
./gui-venv311/bin/python tools/gen_by_level_index.py       # 重生成档位索引 by_level.py
./gui-venv311/bin/python tools/verify_canvas_render.py     # 渲染: node items / link items
./gui-venv311/bin/python tools/canvas_level_audit.py       # 档位级真接 / 无执行注册 / 真缺口
./gui-venv311/bin/python tools/rewire_cross_check.py       # 交叉前/后 + 每条线贡献
./gui-venv311/bin/python tools/canvas_cleanup.py           # 删节点(带安全判据, --apply 才写盘)
pgrep -f "gui-venv311/bin/python studio.py"                # 控制台在跑; 并确认 Traceback=0
```
参考实证: `docs/TASK_LEDGER_20260925.md`（会话七/十一/二十一: 连线失踪、清理、执行链重连）。
L5「能力档位 → 点运行 → 自动标注 → 自动训练 → 重启自动加载」这条链的机制、状态文件字段、
反假训练三道闸门与槽位标注工具: `references/l5-annotate-train-loop.md`。
画布上「配置/标定/诊断」接口节点(参数注册表 → 描述文件 → 面板/远程/诊断)的设计约定与 ASAM-MCD 类比:
`references/mcd-param-node-design.md`(完整方案: 仓库 `docs/design/manifold_mcd_master_param_M_20261009.md`)。
把画布连接关系落成**可查注册表**(报文/信号/Tx-Rx/单位量程)的口径与三个坑:
`references/message-signal-db.md`。
给节点接**实时数据源** (live JSON → 数据空间 Trace, 含 Tx/Rx 归属链路的四件套与 Rx 空行被丢弃的坑):
同文件 §8。
仿真 `v_ff` 能不能算位姿/能算多准、四层速度里哪层是模型输出、桥接到真机的限速与姿态缺口、
**桥接后真机 target 仍不动的三个断点** (发布≠消费 · target 写端被 `moveit_plan_req.py --auto --watch` 每秒覆盖 ·
MoveIt 容器已退出) 与 **仿真基座系≠真机基座系 (差 ~0.7m，只能叠方向增量)**: `references/velocity-to-pose-bridge.md` §1-§5。
信号分析(Graphic)树里找不到刚接的 live 话题、以及页面参数→执行器→段表的速度/步长对账口径(三处改写、限速闸)、
以及数据空间窗口"反映慢"的五段链路量法: 同文件 §9 · §10 · §11。

## 节点改名 / 新增任务 = 真源三件套 + 生成器, 别手改生成物 (2026-10-12 实测)

**① 改名必须同步的映射 (画布节点名 = 数据总线通道名, 漏一处即静默挂不上)**:
`data_world.MODULE_ORDER` · `simulink_module.SS_MODULE_TO_NAME` + 右键分支 · `state_space_sim` io 发布表 ·
`registry._reg` 注册关键字(**加新名时保留旧名**, 老工程/老 .proj 仍能开) · `gui/aoi_inspect_console.py` 标题 ·
`src/lerobot/verification/node_func_tree.py`(网页功能清单真源) · `yolo_perception` · `status_panel` 大屏模型名 ·
`model_feature`(能力特征库 B 条目) · **能力名的真正上游**: `config/platform/zmax_platform.json`(capability_ref/module_refs)
+ `config/platform/zmax_perf_spec.json`(+ `defaults/` 副本) + `data/database/<产品>/sources/feature.dbc`(`BO_ Bx …`) → 跑 `tools/mcd_build.py` 重生成。
**验证不能只 grep 代码**: 改完 `mcd_build.py --check` 幂等 + `node_func_tree`/MCD 的旧名计数归零, 再用 `verify_canvas_render.py` 看渲染。

三处同改 + 前后闸可一条命令跑完: `scripts/rename_canvas_node.py --id <id> --old '<子串>' --new '<子串>'`
(`--dry-run` 只算不改; 前置闸发现该词在注册关键字里会直接拒跑, 后置闸验回读名与 `match_node`)。

🔴 **改名前置闸: 先看注册表关键字里有没有被去掉的那个词** —— `registry.get('<key>')['match']`。
词的**不在**关键字列表里 ⇒ 双击看源码/单步/任务绑定/档位审计**都不会断**(实测某节点关键字是
`['长程序列规划器','任务规划器']`, 去掉层号前缀零影响); **在**列表里 ⇒ 必须先「加新名 + 保留旧名」再改画布, 别先改再修。
纯字符串子串改名可一次覆盖三处真源: 画布 `name`(走 `save_canvas`) + `data/database/<产品>/function_notes.json`
+ `config/platform/zmax_platform.json` —— 三处都是**值里的子串, 键不变**(改前 `json.loads` 验合法 + 备份,
改后再验一次), 生成物 (`param_spec`/`dds_topic_types`/`mcd`) 交给生成链自动跟上, 不要手改。

🔴 **名字里的层号只能写它真实所属的层, 不是装饰**: 画布的"层"是**行带语义**(大模型层/L4/L3/L2/可视化…),
与节点自身 L 编号**不是一一对应**(实测 L3 的 9 个节点只有 4 个在 L3 行带, 3 个住"大模型层", 2 个在 L4 行带) ⇒
用户问「既然是 L3, 为什么不放在 L3 层」时**先给这条分布**, 再谈要不要挪 —— 挪一个节点不解决问题,
按层全搬要动几十条线。反过来: 节点**不属于**某层时, `desc` 里也不许带 `[L3·…]` 这类标签;
外壳 `LAYER` 由名字里的 L 编号推导, 名字没写就留空, **不要在 params 里伪造 `layer`/`cap_level`**(档位审计会当真)。

**② 任务/场景配置别手改 `config/tasks/tasks.json`**(它头一行就写着「生成物, 勿手改」):
链路 = `flows/scenes_5jobs.json`(场景真源) → `tools/task_build.py`(`PLAN[scene_type]` = 类型/适用段/覆盖参数/model_ref) → 生成 tasks.json。
- 新增任务 = **加场景 + 加 PLAN 一条**, 然后跑生成器; 引号里的「任务N」= `SCN-0N-XXX` 的 N。
- 场景文件与 tasks.json 会**漂移**(历史里场景被顶掉, 生成物里却还在) ⇒ 生成前先逐条比对, 发现生成物里多出的任务就**按现任务反向补回场景**, 否则一重生成任务就丢。
- 🔴 `PLAN.get(type, PLAN["ats_test"])` 这种回落会**静默造出配方错误的任务**(实测 SCN-07-UP 被套成「检测插接」)
  ⇒ 改成无 PLAN 就**跳过并打印**提示; 场景本身留在真源里不动(不猜测性删除)。
- 生成后硬判据: 旧任务**逐字节不变**(json.dumps(sort_keys=True) 对比) + 新任务在 + `task_build.py --check` ✅。
- 绑定/库的定式顺序: `ss_task_bind.py`(重算绑定, 不动 active_task) → `project_archive.py space-save`(刷新总工程) →
  `engineering_db.py build` → `ss_task_bind.py --check` + `engineering_db.py check`(顺序反了会报 drift ['project'])。
- 界面要看得见: 配置中心「📋 任务配置」表加列直接在 `veh6_config_page.py` 的 `_mk_table([...])` 里加值 +
  给每行 `item.setToolTip()` 存完整口径(单元格只放短标签); 改完**一次性重启控制台**才生效。
  列里要带**场景色**(绿/蓝/紫)或任何颜色/映射时, 从单一真源 `tools/ss_scene_switch.py` 取, 别另写一份。

**③ 节点要「发出话题」= 建一条话题总线真源, 别让节点自己到处写文件**:
模式(2026-10-12 实做, `tools/ar_aoi_bus.py`): 注册表 JSON(`config/topics/<域>_signals.json`, 含 组/单位/真源说明)
+ 单一写入器(原子写 + `.bak` + 回读, 键 → 组映射写进文件) + 生产者(节点执行时 `publish(部分信号)` 合并写入; 外部真源用 `pull()` 拉)
+ 常驻拉取器 `*_ctl.sh start|stop|status` + 消费端(信号分析页 `HOST_SOURCES` 加一条 + 去前缀显示 + 分组树取注册表的组名)。
判据: 真跑节点后**回读 live 文件**数话题 ≥N 且自洽(如 缺陷数 = 划伤 + 污点); 演示值不许填 0 冒充, 缺的键不写。

**④ 数据源/场景新增一态 (如「AR场景」) = 三处同改 + 一个收口判据 + 挂在唯一激活路径上**:
- 词汇表加新态: `SRC_CYCLE` / `SRC_DESC` / `SRC_SCENE_ID` + `_src_norm`(`tools/gui/simulink_module.py`)。
- 🔴 **把所有 `== "真机"` 收口成一个判据**(如 `_src_is_real()`): 新增一态若没进这个判据, 它会**悄悄走仿真算路**
  (界面写着新场景、引擎跑的是 metaworld 演示)。改前先 `grep -n '真机' tools/gui/simulink_module.py` 数清有几处分支。
- 任务→场景/数据源切换的**单一真源** = `tools/ss_scene_switch.py`(内含 任务→场景→颜色 映射表), 直接写**画布数据源节点**
  `ssdata.params.src_state`(经 `flows.load_canvas` / `save_canvas`, 不手改 .db), **写完回读校验**。
- 挂钩点选**唯一激活路径** `ss_task_bind.py --activate`, 并用 try/except 包住: 切场景失败只提示, **不能拦激活**。
- 判据: 逐个任务 `--activate` → 回读 `active_task` + 画布数据源 + 节点色 → 最后**还原成用户原来的任务/场景**
  (验收不要把现场停在测试用的那一态)。

- 🔴 **用户改过的数据源/开关会被 GUI 在启动/切换时覆盖 ⇒ 先找第二个写者, 守护只做「启动前对齐」**:
  真源里明明已是目标值、用户仍报「每次启动都要手动改回来」 ⇒ 那不是没持久化, 是**有第二个写者**:
  控制台启动时 `studio.py` 的**开机自恢复**从工程存档 `.zmaxproj` 的 `debug_state.src_state` 回填画布
  (存档里是旧值 ⇒ 每次启动都覆盖一遍), 加上「🔀 数据源切换」按钮 / 打开工程 / 另存为也会写回。
  排查顺序: ① `ls -l --time-style=+%H:%M:%S <画布真源>` 看 mtime 落在控制台启动之后 ⇒ 是启动期写者;
  ② 逐个工程文件读 `debug_state.src_state`(`data/database/<产品>/*.proj` 与 `reports/projects/*.zmaxproj` 都要看,
  空的 `{}` 与有值的是两份, 真正被回填的那份才要改); ③ 才去看切换按钮的处理器。
  落法(**两处, 都不是运行期强制**): 把存档里那个值改成目标态 + 在 `tools/gui/launch_studio.sh` 的 `exec` 之前
  调一次幂等对齐脚本 (`tools/ensure_ar_source.py`: 只认 `ar_scene=true` 且新鲜才纠正, 开关为假就什么都不做,
  `real_auth` 永不读永不写, 改前 `copy2` 备份 + 改后回读核对)。
  🔴 **绝不要挂 cron 每分钟强制改写** —— 那个按钮是**循环**的, 用户点一次被你改回一次, 永远切不到位,
  他看到的症状反而变成「怎么画布打开数据源总不是我要的」(实测来回拉锯多轮)。运行期只由人决定, 只保证**启动那一刻**对。
- 🔴 **页面上「点了没反应」先分清「指令源」与「播放授权」是两层**: 指令由**常驻画布循环** (10Hz 写指令文件)
  持续产生, 但页面**播不播**应由人点「▶ 运行」授权 (见「会动的东西只能由人点的那一下启动」)。
  用户说"画布打开后点运行还是没执行"时, 先把这两层分开讲: 指令在不在生产 ≠ 页面在不在播。
  三级取证顺序固定:
  ① `curl /api/ar/cmd` 连测三次看 `seq` 是否推进 + `age_s`(0.0x s 才算活着);
  ② `curl /<page> | grep -c '<新版标记>'` 证明**服务端发出去的已是新版**(新增区块/新写法);
  ③ 前两条都正常 ⇒ **浏览器缓存了旧 JS**, 让用户 Ctrl+Shift+R 强刷 (普通 F5 会复用缓存的 html)。
  改过页面 html 后用户反复报"还是老样子", 前两条能排掉服务端, 就不要再怀疑后端或重启服务。
  页面层再补一条: 用 `browser_console` 采样全局状态序列 (`PLANT.on` / `PREV.M` / `seq` / `q` 前三个分量),
  比截图可靠 —— 连续 4~7 个采样点里 `seq` 单调推进且 `q` 在变 = 真在动; `PLANT.on=false` 且 `units` 不动 = 真静止。

## 🔴 配置真源里加一个字段 = 改配置中心 UI 结构（北斗七星阵会整页不出来）

配置中心（`tools/gui/veh6_config_page.py`）**直接读配置真源字段渲染**，没有中间 schema 层:

- **`sources/config/ss_task_binding.json` 的 `run_cfg` 只能放复选开关**: 每个值必须是 `{"label": str, "checked": bool}`。
  活跃计数直接取 `v["checked"]` ⇒ 塞裸值(`300` / `"AR"` / `{}`)抛 `TypeError` ⇒ `ConfigCenterPage` 构造失败
  ⇒ **北斗七星整页不显示**，而用户看到的现象是「你把 UI 结构改了 / 北斗七星的设计呢」。
  任务级新参数一律放**独立键**(如 `task["ar300"]`)，UI 不读它就不会被拖下水。
- **不许拿 `active_task` 当业务副作用**: AR / 节点链自带 `task_id`，不依赖它; 切它只让配置中心「活跃」列变化,
  在用户眼里又是一次「结构被改」。任何切任务/跑进化的脚本**跑完必须还原原值**。
- 判据(改完任何配置真源必跑，不许只看代码):
  `QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_config_center_seven_stars.py`
  21 项 = 左树 7 / 页签 7 个次序(天枢…瑶光) / 阵图条↔页签 / 单星亮 / 点跳页 / 两种窗宽(1600×900、1120×700) 不截。
- 用户投诉「UI 被改了」时的排查顺序: 先 `git status` 证明 UI 代码是否 clean(多半一行没动), 再验**配置数据的形状**;
  别一头扎进 `veh6_config_page.py` 找 bug。
- 这类「数据驱动 UI」的配置，写字段前先 `search_files` 看该字段在 GUI 里的读取点，确认期望形状再落盘。
