# 画布 → 工程库: 报文/信号注册表 (CANoe 口径)

用户口径:「数据空间的显示要根据配置中心的参数中心的**数据库**实际配置」;
「状态空间工程的所有连接关系, 那个可以保存的 json 文件, 保存到状态空间的工程数据库」。
一句话: **画布 JSON 是人编辑的真源, 工程库是给系统查的注册表, 两者必须同一个写口。**

## 1. 概念映射

| CANoe | 本系统 | 表 (`data/database/zmax/zmax_engineering.db`) |
|---|---|---|
| Database (DBC) | 状态空间工程库 | `mw_project` |
| ECU / Node | 画布功能节点 | `mw_node` (+`mw_port`) |
| Message | **一个输出端口的一帧** = `ss.node.<node>.<port>` | `mw_topic` (dir=out) |
| Signal | 报文 payload 里的扁平字段 `a.b.c` | `mw_signal` |
| Signal 单位/量程 | 参数中心 `params` (unit/min/max) | `mw_signal.param_id` |
| Sender / Receiver | 连线两端 | `mw_link.f/t` |

节点输入 topic = 上游节点的报文; 输出 topic = 本节点的报文。一个端口恒等于一条报文
⇒ **报文身份跟着画布走, 不许在代码里另起名字**。

## 2. 单一写口

```
flows.save_canvas()  (写盘唯一入口)
  └─ os.replace(tmp, realpath) 成功后 → db.sync(specs, links, path)
       写 mw_project/mw_node/mw_port/mw_link/mw_topic/mw_signal
```

- 库写失败**不回滚画布** (画布已原子落盘), 但必须 `print` 留痕, 不许静默 `except: pass`。
- 不在 GUI 里另开写库路径: 双写口必然漂移。

## 3. 三个已踩过的坑

1. **只看 sha 会漏派生表**: 新加 `mw_signal` 后老库 sha 仍与画布一致 ⇒ `ensure_synced()` 直接
   返回"已同源", 信号表永远是空 (实测 113 个输出端口 / 0 条信号)。
   同源判据要带派生表: `COUNT(mw_signal) >= COUNT(mw_port WHERE dir='out')` 才算同源。
2. **占位信号不许参与参数匹配**: 未声明时写 `signal='value'` 占位; 若拿 `value` 去 `LIKE
   params.param_id`, 会乱命中(`value` → `calib:plane_z.value`), **凑出来的单位比空着更坏**。
   规则: 占位名或没有 node/impl 前缀时直接返回空, 页面显式标「端口整体值(未声明)」。
3. **报文必须带层**: 层 = 端口所属节点的 `layer` (空则回落
   `lerobot.engineering.nodes.by_level.LEVELS_INDEX`)。否则 150+ 条报文平铺, 用户找不到
   (「按 L1~L5 分类, 要不不好找」)。本工程不存在 L1 ⇒ **不硬造空组**, 根节点 tooltip 写"本工程未用"。
4. **端口是连线派生的, 不是画布声明**: `spec.parse_canvas` 的 `Node.inputs/outputs` 由 **links 两端**收集 ⇒
   画布 JSON 里写了 `outputs: ["out1","out2"]` 但 `out2` 没接下游时, 工程库里**没有 out2** (`mw_port`/`mw_topic` 都查不到)。
   要新增出口就先给它一个语义正确的真下游; 交付时不能许诺一个查不到的端口。
5. **`attribution.py` 里 `_rule()` 与 `rx_of()` 共用同一行锚点** (`_p = port_of(k)` / `if _p:`) ⇒ 补规则时容易插错函数。
   插进 `_rule` 会让 `tx_of()` 当场崩 `ValueError: too many values to unpack (expected 2)` (它要 `(nid, proc)` 二元组)。
   改完立刻 smoke 三个键: `tx_of / rx_of / layer_of`, 再跑 `verify_tx_real_nodes` 与 `verify_layer_node_strict`。

## 4. 信号从哪来 (优先级)

1. 节点模块/画布 params 里 `_signals = {port: [{name,unit,min,max,dtype}]}` (声明) —— 首选;
2. `live.json` 的 `topics[*].fields` (实测运行时) —— 补齐, 标 `src=实测`, **不覆盖声明**;
3. 参数中心 `params` 按 `<node>.<port>.<signal>` / `<impl_key>.<signal>` 补 unit/min/max;
4. 都没有 → 页面显 `—`, 不猜、不造。

## 5. 下游消费者

- `lerobot.dataspace.busdb.build()` 真源 = 工程库 (库不可用才回落画布 JSON)。
- 报文的下游 = `mw_link` 里 `f==node & f_port==port` 的 `t`: 这是 UI 里 Tx/Rx 两列的**唯一来源**,
  不要在显示层另算一遍 (两处算法必然漂)。
- 改库一行再重新 `load_project()` → `Node.topic()` 立刻变 = 话题名确实走库 (判据见
  `tools/verify_mw_db.py`, 7 项)。

## 6. 保存流程探针 (不动真源画布)

```bash
PYTHONPATH=src ./gui-venv311/bin/python tools/verify_mw_db.py          # 7 项
PYTHONPATH=src ./gui-venv311/bin/python -m lerobot.dataspace.busdb --build
```
写盘探针用**独立工程名** `flows.save_canvas(d, name="probe_xxx.json")` → 查三张表行数 →
删探针工程与文件。直接拿真源画布跑探针会把存档/库一起改动。

## 7. 信号名必须是人看得懂的语义名, 不许是裸端口名

端口名 (`out1` / `in1`) 是画布机械名。用户看到这种名字会直接说「根本看不出来是什么意思」—— 数据空间的 Signal 列、
信号分析的曲线名都属于"要给现场人读"的界面文字, 不是内部变量名。

命名真源 = **报文类型** `mw_topic.type`, 不是端口名、不是节点名:

- 只对**裸端口**改名: `re.fullmatch(r"(in|out)(\d+)", field)` 命中才换; 其它字段走原有中英映射, 不许乱改。
- 短名表 `TYPE_SIGNAL_EN` (`MotionPlan→plan` · `MotionPlanIn→plan_in` · `RobotActionIn→action_in` ·
  `OpticalInspection→aoi` · `MuscleSkillBank→muscle_bank` …); 表里没有就 `CamelCase→snake_case` 兜底
  (`ActionChunkCmd→action_chunk_cmd`)。
- 同类型多入口按序号区分 (`plan_in` / `plan_in_2`), 否则同一节点几条入口全重名, 用户照样分不清。
- **取不到类型就保留原名**, 不要用"节点名+端口"拼假名 —— 假名比裸名更误导。
- 一处改、全窗口生效: 取名函数在 `middleware/signal_en.py` (`en_of_key(prefix, field, mtype)`),
  Trace 与信号分析都调它; 行里自带 `type` 时优先用它 (话题名查不到类型时的兜底)。
- 渲染前再统一扫一遍「Signal 仍是裸端口就改名」—— 增量缓存里的历史行不会自己重新取名。
- 判据 `tools/verify_signal_names.py`: 全端口 0 裸名 · Trace 0 裸名 · 点名端口逐个对照; 改完并入回归。

### 坑: `attribution` 没有模块级 `db`
`attribution.py` 只在**函数内** `from lerobot.middleware import db`。新加的函数里直接写 `db.topics()` ⇒ `NameError`
被 `except` 吞成空结果, 现象是「类型一条都查不到 → 名字全是原名」而判据可能还绿。新函数里自己
`from lerobot.middleware import db as _db`; 判据要**打印几条真实映射**, 不能只断言"结果非空"。

## 7b. 节点自己的 live 字段名同样是界面文字 (裸端口改完不等于改完)

报文字段 (报文类型派生的) 改好之后, 节点 `host_sources` 里手写的**字段名**仍可能是 `n_seg` / `v_page_mms` /
`seg1_mm` —— 用户照样读不出"这个量干什么用"。规则: **名词 + 单位后缀, 一个名字回答一个问题**;
不许出现序号型缩写 (`seg1_mm` 换成 `lift_mm` / `traverse_mm` / `descend_mm` 这种按语义分口的名字)。

| 旧 (位置/缩写型) | 新 (功能型) | 名字要回答的问题 |
|---|---|---|
| `n_segs` | `seg_count` | 这条命令被拆成几段 |
| `total_mm` | `travel_mm` | 总共要走多远 (估时长唯一依据) |
| `seg1_mm`/`seg2_mm`/`seg3_mm` | `lift_mm`/`traverse_mm`/`descend_mm` | 向上/水平/向下各多少 |
| `v_page_mms` | `speed_req_mms` | 页面要求的 vs 真用的 |
| `v_actual_mms` | `speed_real_mms` | 被限速后到底多快 |
| `v_units_req`/`v_units_used` | `units_req`/`units_applied` | 限速闸前后各是多少 |
| `speed_kept_pct` | `speed_gain` | 你设的速度用上几成 (1.0=全用上, 0.584=被压到 58%) |
| `下降_mps` | `speed_mms` (mm/s) | `mps` 是 m/s 的手写缩写 (0.12 = 120mm/s), 与页面口径差 1000 倍 |
| `manual` | `manual_recall` | 为什么被限速 (人工回已记点位) |
| `age_s` | **不发** (Trace 最右列已有「帧龄」) | 重复占行; 事件型产物看着"停住"是正常 |
| `phase_code` | `exec_phase` | 1 受理 / 3 下发中 / 4 到位 / 5 完成 / 9 被拦 |
| `seg`/`n_seg` | `stage_now`/`stage_total` | 现在第几段 / 一共几段 |
| `residual_mm` | `arrive_error_mm` | 到位还差多少 |
| `tgt_x/y/z` | `target_x_mm`/… | 这次目标点, 直接能跟点位库对 |

配套三条, 否则改名只是换皮:
1. **不发恒等/重复字段**: `t` 与 `t_pub` 并存、每段 `id` 恒等、`service` 恒 0、每段 `speed` == 均速 ⇒ 全删
   (实测 21 → 11 条后用户才认"有用")。窗口自带的列 (帧龄 / 时间 / hz) 不要再用信号复述一遍 ——
   多一行不会让人多知道一件事, 只会把有用的挤下去。
2. **聚合值在落盘侧算一次**, 窗口只读: 抬升/横移/下落不许在前端按阶段标签判 —— 标签会写反
   (实测 `↓下降` 那条是竖直段)。落盘函数收 `start_pos` + 每段目标 `pos`, 用 Δz/Δxy 判 role,
   同一份聚合既进段表又进 live 信号, 两处口径天然一致。
3. **改名要一次改到底**: 发布端 (`host_sources` 命名块) · 信号库 (`signals.db` 旧话题行) · 判据脚本里写死的旧名
   · 提交信息。改完重启采集器 (`--hz 2 --force`) 再看 `signals.db` 里确实是新名 —— 只改代码不重启,
   界面照旧显示旧名, 会误判成"改错了"。

## 7c. 信号准入配额: 每节点 ≤10 条 · L2 总数 ≤100 条 (一处策略, 两个窗口共用)

用户红线: 「每个节点不允许超过 10 个; 总 L2 不允许超过 100 个; 不允许出现 signal 名字模糊不清、
表达混乱、直写几个字母、随机分配字母」。

**唯一实现** `src/lerobot/middleware/signal_policy.py`:
- `MAX_PER_NODE = 10` · `MAX_TOTAL = 100`; 白名单之外**一律不上屏** (宁缺勿滥), 原始字段名留在 tooltip 可追。
- `decide(tx, raw)` → 功能名 or `None`。技能节点按**含义片段**匹配 (`"· v 速度"`), 不能按最后一段字母 ——
  实测 `a` / `angle` / `b` / `c` 会混成一条; 其它节点走 `NODE_ALLOW[节点显示名][原始名]`。
- `filter_rows(rows)` 做三件事: 改名 · 去重 (同节点同功能名只留一行) · 截断 (≤10/节点, ≤100 总数)。
- `BLOCKED_NODES` 明确屏蔽数学/审计层 (SU(2) 统一状态空间 / MOE 门控 / 开放词汇分割 / 总装机记忆 /
  自适应估计 / 机器人执行器 …): 这些量不是 L2 动作 Trace 该铺的东西, 要看就单独加白名单, 不要默认全铺。
- 接线: `dds_canoe._fill_trace_fixed` 在算 `_sig` 之前 `rows = filter_rows(rows)`;
  信号分析侧在 `canoe_graphic._feed_live` 推 store **之前**用 `decide_topic()` 过滤 + 改名 ⇒ 曲线名与 Trace 同源。
- 判据 `tools/verify_signal_policy.py` 7 项: 每节点 ≤10 · 总数 ≤100 · 名字 `^[a-z][a-z0-9_]{5,}$` ·
  无禁用短名 (n/v/a/u/err/mode/head/pos/code/stage/phys/band_h/o_hat…) · (节点,名) 不重复 ·
  屏蔽节点不出现 · 每个节点都在策略表里。实测 441 行 → 52 行 / 11 节点 / 单节点最大 8。

配套四条 (都是踩出来的):
1. **名字用物理术语, 不用自己编的词**: `speed_kept_pct` 被当场否掉 (「这不就是速度的增益么」) ⇒ `speed_gain`,
   值 = 实际/请求 (0.584 = 200/342.2); 同一个量换个叫法就该换名, 不要硬解释旧名。
2. **单位进名字, 且用操作者口径**: `mps` 是 m/s 的手写缩写 (0.12mps = 120mm/s), 页面与真机都是 mm/s ⇒
   一律 `*_mm` / `*_mms` / `*_deg` / `*_n`; 跨量纲换算要在交付时算给用户看 (32mm/s ÷ 0.0935 = 342 units)。
3. **改完必须重启两个进程**: `signal_store_daemon --hz 2 --force` (库里的旧名不会自己变) **和** 控制台
   (Trace/树是 GUI 进程内代码)。只重启一个 ⇒ 界面照旧旧名, 会误判成"没改对"。
4. **判据别写死条数**: 断言关系式 (≤10 / ≤100 / 单射), 具体数字进 detail (见 SKILL.md 同名小节)。

## 8. 给节点接一路实时数据源 (live JSON → 数据空间 Trace)

节点要显示"真实在跑的数"时, 不是把文件塞进节点就算接上了: Trace 只显示**归属明确、且两端都有节点**的行。
一条 live 源从文件走到 Trace 要四处改, 少一处就静默消失:

1. `middleware/host_sources.py` 的 `FILES` 加 `("<前缀>", "<相对路径>", "zmax/<话题>")` —— 采集器据此写进 `signals.db`。
2. `attribution.py::LIVE_PREFIX` 加 `"zmax/<话题>": "<前缀>"` —— 不加就不在 `LIVE_TOPICS`, 整条不算本机真值流。
3. `attribution.py::PREFIX_OWNER` 加 `"<前缀>": "<节点 id>"` —— Tx 取该节点的显示名; 不给就是 `—`, 不进 Trace。
4. **Rx 必须有值**: `show_in_l2_link()` 在 rx 为空时返回 False ⇒ 整行被丢掉。live 前缀不是端口键,
   `port_of()` 给不出下游 ⇒ 在 `rx_of()` 里补一条"按归属节点的出端口 consumers 取 Rx"的规则
   (Rx 来自画布真连线, 不是自己编的下游)。

落完重启采集器 (`signal_store_daemon.py --hz 2 --force`) 再验四件:
`signals.db` 里有 `zmax/<话题>` · `tx_of/rx_of/layer_of("<前缀>.<字段>")` 三件齐全 · Trace 里该节点行**有值不是一排 `—`** ·
Tx 列显示的是节点名 (不是前缀/进程名)。

⚠️ **采集器只能有一个实例**: 多开时互相覆盖同一张表, 探针和判据会间歇假红 (同一秒里两种值来回写)。
重启前按 pidfile + argv 把所有实例杀干净再起一个; 判据红先数实例数, 别先改代码。

⚠️ **只有数值字段会进 Trace 表格** (`signals.value REAL`): 目标位姿/list 要摊平成标量 (`target_x/y/z`),
枚举与状态名留在文件里给节点读; 时间戳至少留一个"发布时刻"`t_pub` 给帧龄判据 ——
只留"最后一次事件时刻", 空闲时帧龄会一路涨, 看起来像掉线。

⚠️ **一次性产物不能当 5Hz 源**: 规划/执行类文件只在动作发生时更新, 空闲就变陈旧被正确过滤。
这类节点的判据看**归属链路** (`tx/rx/layer`) 与文件内容, 不要去追 Trace 里的实时值。

⚠️ **从日志文本反推状态只能按行首锚点**: 用日志行给执行器造状态机时, 子串匹配必假阳性 ——
阶段标签里会合法出现"拒发"二字(如"斜线会被 50102 奇异点拒发"的说明), 启动横幅也可能以 `🛡` 开头,
结果空闲态被标成 blocked。规则: 只认**行首固定前缀**或整行正则, 并用一个**空闲实例**验证
(空闲时必须 `idle`, 不是 `blocked`/`accepted`); 状态机里再加一条"每条新命令先清上一次的段号与拦截原因",
否则上一条的 blocked 会挂在新命令上。

## 9. 信号分析(Graphic)树里看不到 live 话题 = 目录只列 DDS 声明话题

Trace 有了不代表信号分析也有: `canoe_graphic` 的「🌐 全局数据空间」目录原来只枚举
`ds_src.seen/declared`(DDS 声明的话题), live 文件话题(`zmax/plan_live`、`zmax/ss_exec` 这类)
只在 store 里以 `ds.<topic>.<field>` 存在 ⇒ 用户打开信号分析找不到他刚接的节点。

改法(一处): 建完 `ds_topics` 后再扫一遍 `store.keys()`, 把 `ds.<topic>.<field>` 里出现、
目录里没声明的话题补进去(`type="live"`), 不改 DDS 区任何既有条目。

取证要注意两点, 否则会误判成"没生效":
- 目录块只在**非 3D 范围**才建 (`only3d = (self.scope == "3d")`) ⇒ 离屏判据必须先 `w.scope = "all"`。
- 空 store 时树里本来就没有话题节点 ⇒ 判据先 `w.store.push_many({"ds.zmax/plan_live.<字段>": 1.0}, 0.0, src="ds", scene=True)`,
  再 `w._fill_tree()`, 再递归走 `w.tree.invisibleRootItem()` 找 `plan_live`。

## 10. 页面参数 → 执行器 → 段表: 速度链上有三处改写, 对账要用同一个定义域

station 页面的量到执行器会换两次单位并被闸改一次, 只记一个 "speed" 无法回答"我设的值用上了没":

| 层 | 字段 | 口径 |
|---|---|---|
| 页面 | `speed_mm_s` | mm/s, 1~1000 |
| 服务层 | `speed` (units) | `mm/s / 0.0935` (腿里 `sp_mm = 0.0935 × units`) |
| 收口闸 | `MANUAL_SPEED_UNITS`(=200 ⇒ ≈18.7mm/s) | 手动回已记点位时把 units **压到上限** |
| 段表 | 每段 `speed`(units) + `speed_mm_s_actual` | 实际下发的值 |

落法: 段表同时写 `req_speed_mm_s`(页面) · `req_speed_units_raw`(限速**前**的 units) ·
`req_speed`(进规划时的 units) · `speed_mm_s_actual`。**限速前那份要在解析命令处立刻留**,
等到规划时再取就已经是被闸改过的值, 差异再也看不出来了。

🔴 判据别写 `abs(req_speed - speed) < 1e-6` 就当"对账通过": 存在限速闸时两者天然不等,
而若 `req_speed` 取的是限速后值, 这条断言会假绿。正确判法是**把页面值换算到实际值再比**
(`req_speed_mm_s` vs `speed_mm_s_actual`, 容差按档位), 并在不一致时把 4 个数一起打进 detail。

📌 步长同理: 页面步长不是前端记忆, 方向键按 `d_mm` 下发 ⇒ 服务层把**原值**一并带进命令
(纯溯源, 执行器只读不用), 段表才能拿 `req_step_mm` 对 `lin_mm`。

## 11. 数据空间窗口"反映慢"先量五段链路, 别先改代码

用户说"窗口反映这么慢"时, 按链路量五个数 (每一段都有实测值):

| 段 | 实测 | 怎么查 |
|---|---|---|
| 源 | l2_daemon 5Hz 写 `exec_state.json` / `plan_latest.json` | 读 `t_pub` 帧龄 |
| 落库 | `signal_store_daemon --hz 2` ⇒ ≤0.5s | `signals.db` mtime 帧龄 |
| 采集 | 13 话题 / ~650 信号 | `select count(*) from signals` |
| 窗口 tick | `dds_canoe` 的 `self._timer.start(ms)` | 代码一处 |
| 单次重建 | 469 行 80~340ms | 离屏 `_fill_trace_fixed(force=True)` 计时 |

结论公式: 端到端最坏 ≈ 落库周期 + tick + 重建。实测 0.5 + 0.8 + 0.3 ≈ 1.3s ⇒ tick 收到 **0.5s** 即 ~1.0s;
**重建耗时 << tick 才敢收**, 否则 GUI 卡得更像坏掉。

两条假“慢”要先把用户预期对齐:
- **事件型产物不随时间变**: 段表每条命令只写一次, 两次命令之间 `t_pub` 自然变老 —— 这是正确行为。
  要看"走到第几段"得盯执行器 `phase_code`(见 live-service-change-discipline §10), 不是盯段表。
- **字符串字段不进数值表**: 技能名/`phase`/`backend` 都不会出现在 Trace ⇒ 别让用户找"L2.goto_space4 那条"。
  要么给数值 code (点位号/阶段码), 要么明确告诉他"技能名只在段表文件里"。

## 11b. 「我在动, 但信号一个都不变化」先证链路, 别改界面

三步取证, 每步一分钟:
1. **值会不会变**: 离屏建 Trace, 连发两条**不同点位**的命令, 每次 `_fill_trace_fixed(force=True)` 后读目标列 ——
   实测 `target_y_mm` 8.1 → -37.5 → -123.6 · `travel_mm` 0.0012 → 88.1 → 167.8 ⇒ 链路与渲染都正常,
   问题就不在数据层。
2. **命令到没到执行器**: `grep -a "段表已落盘" zmax_data/l2_daemon_stdout.log | tail -5`。
   未授权 dry 也会落盘 ⇒ "没有用户那条"才说明请求没离开页面 (或撞了页面节流)。
3. **分清信号语义**: plan 是**事件快照**, 同一个点位重复点 target/travel 本来就不变, 只有帧龄在涨;
   要看"在动没动"得看 exec 的 `exec_phase` / `stage_now`。

⚠️ 守护进程用 `>> log` 启动时 stdout 是**块缓冲**: 日志会滞后几十行, 不能用"日志里没有"判命令没到 ——
看 FIFO / 计划文件 / `signals.db` 的 mtime 与内容。
