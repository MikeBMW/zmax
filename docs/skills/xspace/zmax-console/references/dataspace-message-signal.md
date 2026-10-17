# 数据空间: 工程库 → 话题 / 报文 / 信号

什么时候看这个文件: 要改「全局数据空间」(dds_space 页 / dds_canoe 独立窗) 的显示内容,
或要把画布连线关系落到工程库, 或要给节点输出补信号定义。

## 1. 一条链路, 一个真源

```
画布 JSON (人编辑)  --保存-->  flows.save_canvas()  --同口-->  db.sync()
                                                          ↓
                     zmax_engineering.db: mw_project / mw_node / mw_port
                                          mw_link / mw_topic / mw_signal
                                                          ↓
   数据空间(dds_space / dds_canoe) · busdb.build() · 监控 · CI   全部只读库
```

- `flows.save_canvas()` 是唯一写口: `os.replace` 成功后调 `db.sync(specs, links, p)`;
  库写失败**不回滚画布**但必须打印留痕。不要在 GUI 保存按钮里另写一份 sync。
- 库不可用时才回落画布 JSON (`busdb.build()` 的顺序), 且页面要标出来源。
- 🔴 **派生表是同源判据的一部分**: 只比 `canvas_sha` 时, 新增的表在旧库上永远不刷新
  (实测 sha 一致 + 113 个输出端口 + 0 条信号)。`ensure_synced` 要再核行数,
  例如 `COUNT(mw_signal) >= COUNT(mw_port WHERE dir='out')`。

## 2. CANoe 对应表

| CANoe | 本系统 | 存在哪 |
|---|---|---|
| Database (DBC) | 状态空间工程库 | `mw_project` / `mw_node` |
| ECU / Node | 画布功能节点 | `mw_node` |
| Message | **一个输出端口的一帧**: `ss.node.<节点id>.<端口>` | `mw_topic` (dir=out) |
| Signal | **payload 字段** (可扁平 `a.b.c`) | `mw_signal` |
| Signal 单位/量程 | 参数中心 | `mw_signal.param_id` → `params(min,max,unit)` |
| Sender | 节点自身 | `mw_link.f` / `f_port` |
| Receiver | 下游节点的 in 端口 | `mw_link.t` / `t_port` |
| Cycle | 节点节拍 (设计 Hz) | 注册表 `rate_hz` / 参数中心 |

读口: `db.node_rows()` (节点 → in/out 话题 + 上下游) · `db.message_rows()` (报文 + 信号)
· `db.links()` · `db.signals()` · `db.topics()` · `db.topic_map()`。

## 3. 展示规则 (页面里怎么摆)

```
Data 面板  只留报文树 (按层分组); 不再有「信号」「节点」两个根 —— 信号看 Trace, 节点看 Tx/Rx + 详情
报文行     名=n_dsvl.out1 · Type=语义类型 · Value/Unit/Age s/Bar (实测) · Tx 生产者 · Rx 下游
Trace      一行一个**信号**: Time·abs|rel | Layer | Signal | Value | Unit | Phys | Type | Tx | Rx | QoS | Hz
           (固定行与滚动模式**同一套列**; Lamp / Count / Age / Name 已删;
            点 Time 表头切 相对/绝对, 相对 = 快照 时间_s = 3D HUD 那根钟)
详情面板   选中行的完整属性 + 类型含义 + 质量判据逐条
```

- **Trace 每一列的语义 (用户口径, 越权改名会被打回)**:
  - `Name` 列**已删** (用户: 「删除 name 列」)。中文名只留在 `Signal` 的 tooltip 第一行;
    `middleware/cn_names.py` 仍是中文名真源, 别连工具一起删。
  - `Signal` = **英文变量名**, 要能在状态空间代码里对上那一个变量 (`end_x` / `grasp_prob` /
    `u_ff_x` / `descend_l2_force_mps` / `chunk.lambda0` / `latent_p2`)。真源 `middleware/signal_en.py`:
    逐键表 + gravity(阶段×层) / skillphys(SK编号) / ar(段.字段) 规则 + ASCII 原样透传。
    名字取自**生产者代码标识**, 没收录的键原样返回 —— 别按拼音/翻译凑一个像变量的名字。
  - `Type` = topic 的语义类型 (见 §2 / §5), 不是 topic 名也不是信封名。
  - `Tx` / `Rx` = 节点中文名; Rx 真源取工程库 `node_rows().outs[].to` (不依赖 busdb 是否已加载),
    无下游写 `—`; 注册表类话题 (heartbeat 等) 没有单一节点, Tx 就用它自己的中文名。
  - `Layer` = `L2~L5` / `SYS`。来源: `ss.node.*` 查工程库 `node_rows().layer`; `meta` 与注册表类话题
    (heartbeat / ss_state) 显示 `SYS` —— 它们本来就没有 L1~L5 归属。本工程层索引只有
    L2/L3/L4/L5/meta, **没有 L1**, 用户说"显示 L1~L5"时也不要凭空补一个 L1 组或 L1 值。
    列宽恒窄 (64~80px), 不要参与自动适配。
  - `QoS` = **DDS 标准策略名**: `RELIABLE|BEST_EFFORT · KEEP_LAST(n)|KEEP_ALL · VOLATILE|TRANSIENT_LOCAL`;
    内部简写只做别名 (`beat→BEST_EFFORT·KEEP_LAST(1)·VOLATILE`, `state→RELIABLE·KEEP_LAST(1)·TRANSIENT_LOCAL`,
    `cmd→RELIABLE·KEEP_ALL·VOLATILE`, 库里的 `reliable/transient_local` 同 state)。非 DDS 后端要明说
    (`SHM (非 DDS)` / `单步调试 (非 DDS)`), 解析不了写 `❌ 未知: <原值>`。一份 `middleware/qos_names.py`
    给所有入口共用, 别在页面里各拼一份。**空值/`—` 直接显示 `—`**, 缺失不是"未知协议"——
    否则滚动模式里一行一个 `❌ 未知: —` 全是噪声。
  - 判据 `tools/verify_trace_names.py`: 节点中文名覆盖 75/75 · 全部 ≤5 字 · 不重名 · 话题名 0 空 0 超长 ·
    未知字段退回节点名 · Type 无信封名 · 五种 QoS 写法都能翻 · 库内 273 条 QoS 全合规。

- 一个话题带 N 个数值字段 ⇒ Trace 展开成 N 行 (跳过 `ts/count/bytes/n/age_s/seq` 这类元字段);
  这才叫"具体信号", 而不是把 N 个值拼成一行字符串。
- `Unit` 取 `mw_signal`(← 参数中心); 没声明时按字段名后缀推断 (`_mm/_deg/_ms/_pct/_kg/_nm` …)
  并**显示加 `*`** 标明是推断值 —— 物理量不许裸数, 但也不许把推断冒充声明。
- `Phys` 列给判据结论 `✔ / 🟡 / ✘`, 具体原因进 tooltip (见 §9)。
- 来源列必须区分 **工程库 / 注册表** (库=画布实际配置, 注册表=另有其话题, 如板级遥测)。
- 缺测一律 `—`, 不许 0 冒充; 帧龄要显示, 让人知道画面有多旧。
- 全部可复制/可导出 (CSV + 一份含 channels/nodes/messages/alerts 的 JSON)。

## 4. 信号从哪来 (五级证据, 不许猜) —— `middleware/signals.py`

用户会追问 `signal 列的信号呢? 每个 topic 的 signal 哪里去了?` / `L1~L5 层所有的 topic 的所有信号都要加载`。
真因通常不是显示 bug, 而是**端口没声明信号** (`mw_signal` 里 113 条全是占位 `value`),
而 UI 只渲染 live.json 里有流量的 20 来个话题 ⇒ 看起来"信号很少"。

`signals.signals_of(topic)` 按证据强弱合并五级, **每级带 source 标签写进 tooltip**:

```
① 实测     live/busdb/trace.jsonl 里真出现过的载荷字段            src=实测
② 声明     mw_signal (排除端口占位 value)                      src=声明
③ 端口标签 画布 params._port_labels 的英文标识 ("u_ff 建议动作"→u_ff) src=画布
④ 实现     节点源码 return 字典的字符串键                       src=实现 / impl_node
⑤ 上游继承  入口 topic 按 mw_link 继承上游出口信号, fan-in 取并集    src=上游
⑥ 信封兜底  仍无证据的 ss.node.* 列 DDS 信封真字段 topic/ts/json    src=信封
```

- 生成器 `tools/gen_signal_dict.py` → 真源 `config/platform/dds_signals.json` (topic → [{name,src}])。
  抽键**只认 `return {...}` 与惯用返回变量** (`out/result/payload/ret`); 把实现里所有 dict 键都收进来
  会把 `path/size/mtime` 这类无关键混进信号表。
- 多输出节点: 端口没有 `_port_labels` 时实现键归属不明 ⇒ 挂到每个出口并标 `impl_node`
  (宁可多列不漏, 但 tooltip 要说清是节点级); 单输出才是端口级 `impl`。
- 单元/量程仍取 `mw_signal` ← 参数中心; 没声明就按字段名后缀推断并加 `*`。
- 铁律: 占位信号**不参与参数匹配** —— 实测 `value` 会乱命中 `calib:plane_z.value`, 凑出来的单位比空着更坏。
- Trace 侧同时要改**话题集合**: 并入 `db.topics()` 全部 273 个 (113 出 + 160 入), 不能只遍历 live.json;
  没数据的话题照样列信号名, `Value` 显 `—`。实测 1768 行 / 填充 0.10s。
- 判据 `tools/verify_signal_coverage.py`: 话题数==工程库 · 每层都有 · 0 个只剩占位 ·
  信号数≥1000 · 来源分级 · 中文名≤5 · 英文名是合法程序变量 · 入口有上游继承。

## 5. 分层分组 (报文按 L1~L5) + Tx / Rx 列

- **报文先按层分组, 不是平铺**: 层 = 端口所属节点的层 (`mw_node.layer`, 空则用
  `engineering/nodes/by_level.LEVELS_INDEX` 兜底)。组序 `L5 → L4 → L3 → L2 → L1 → 系统(meta)`,
  每组标题带条数, 根标题直接给分层条数:
  `🚌 报文 (Messages 157)   [L5 12 · L4 30 · L3 6 · L2 45 · 系统 64]`。
- **不硬造空组**: 本工程 `by_level` 里没有 L1 ⇒ 就不出现 L1 组 (在根 tooltip 说明“L1 本工程未用”)。
  组内排序保持“活跃在前 (hz>0) → 字母序”; 默认只展开最上两层, 其余收起。
- **信号表列序 (8 列, 全英文短表头)**: `Name | Type | Value | Unit | Age s | Bar | Tx | Rx`。
  Name = 短名 (报文 `n_dsvl.out1` / 连线 `S003 <连线标签>` —— **不要写 `源→目的`**, 箭头被点名嫌乱);
  **topic 全名只进 Name 的 tooltip 第一行** (不占列)。
  Type = **topic 的语义数据类型**, 由**主要发送 (Tx) 节点**决定 (`zmax::FeedforwardAction` /
  `zmax::ModulatedAction` …), 既不是 topic 名、也不是信封名 `zmax::SSNodePort`;
  真源 `config/platform/dds_topic_types.json` ← `tools/gen_topic_types.py`, 运行时 `middleware/topic_types.py`,
  判据 `tools/verify_topic_types.py` (覆盖 / 唯一主 Tx / 入口=上游 / 落库一致 / 零信封名 / 命名规范);
  节点行没有 topic ⇒ Type 写 `—`, 节点自身类型挪进 Name tooltip。
  报文行 Tx = 生产者节点名, Rx = 下游节点名; 连线信号行 Tx = src / Rx = dst;
  节点行 Tx = `Tx N` / Rx = `Rx N`。全部从 `mw_link` 派生, 没连线写 `—` —— 不许拿注册表猜。
- 表头/标题文案口径 (老倪会直接说“太乱”): **一列一个英文短词**, 不加中文、不加单位括号、
  不写“实测/设计”这类解释 (解释进 tooltip); 面板标题就一个词 (`📋 Data` / `🔎 Detail` / `📋 Trace`),
  原来那种 `📋 Data — 信号表 (报文 / 信号 / 节点)` 的括号堆叠就是被点名的“UI 太复杂”。
- 数据空间页签: 频道(topic) / 状态空间工程 / 报文·信号 / 质量告警 / 字段真值;
  独立 CANoe 窗底部只剩 质量告警 (数据闭环页已按要求删除; 删时连 `dds_bus` 质量告警文案里的
  闭环段、`tb_loop`、`_fill_loop`、`self._loop` 读取一起删)。
- 加列/加分组必须同步改: `setColumnCount` + 每处 `QTreeWidgetItem([...])` 元组长度 (少一个就
  整体左移) ⇒ 验证读 `headerItem().text(i)` + 逐行 `item(r,c).text()`。

## 6. 判据 / 命令

```bash
./gui-venv311/bin/python tools/mw_db.py status          # 哪套工程 + 行数 + 是否与画布同源
./gui-venv311/bin/python tools/mw_db.py node sssched    # 单节点端口 + 话题
./gui-venv311/bin/python tools/mw_db.py topics          # 话题注册表
PYTHONPATH=src ./gui-venv311/bin/python tools/verify_mw_db.py   # 7 项, 含"改库即改话题名"
PYTHONPATH=src ./gui-venv311/bin/python -m lerobot.dataspace.busdb --build   # 重新派生 CANoe 视图
```

页面级探针: `build_widget()` 后读 `tabs.count()/tabText`, 表行数 `t_ch/t_pj/t_ms.rowCount()`;
`dds_canoe` 要 `show()` 后**显式** `reload(force_tree=True)` (刷新函数有 `isVisible` 早退),
再读 `_busdb['counts']` / `tree.topLevelItemCount()`。

## 7. 列宽 / 对齐 / 表头不裁 —— 表格类 UI 的硬规矩

1. 🔴 **用户手拖过列宽后, 自动分配必须彻底停手**。真根因不是 QSS 也不是 resizeEvent, 而是
   刷新心跳里那句 `_fit_columns()` —— 它每拍按面板宽重算一次, 手拖的结果一秒就没了。
   做法: `header().sectionResized` 里判断 `_applying_cols` 标志 (防自己写自己触发) → 第一次拖动
   **快照全部列宽** (否则其余列下一拍仍被重排) → 写 `QSettings("ZMAX","studio")` 持久化 →
   `_fit_columns()` 开头 `if self._user_cols: 按存的宽度 apply 后 return`。
   复位要给**显式按钮** (`↺ 列宽` → 清 QSettings + 清 `_user_cols` + `_fit_columns()`), 绝不偷偷还原。
   判据: 拖到 500 → 调 `_fit_columns()` → 仍 500; 点 ↺ → 回自动值。
2. **列宽要按表头实测宽算, 且在样式表生效后量**: QSS 里 `font-size:9pt` 在 polish 时才应用,
   构造时用默认字体量出来的最小值偏小 (实测表头需 224px 只分到 180px ⇒ 表头自己就被裁)。
   先 `self.tree.ensurePolished()` 再取 `self.tree.header().fontMetrics()`, 每列最小 = `width(表头)+16`。
3. **对齐语义**: 数值列右对齐, 单位列居中, 名称/节点列左对齐; 非该语义的行把格子填 `—` 而不是留空 ——
   空串会让整张表看起来“没对上”。
4. 🔴 **不许出现省略号**: 口径是「字符不要显示 `...`，Tx Rx 都看不全，不要截断省略」。
   `setTextElideMode(ElideNone)` + `setWordWrap(False)` + 按内容铺列 + 放不下就横向滚动
   (`ScrollPerPixel` + `ScrollBarAsNeeded`)。宁可滚，不截字；列宽只影响要不要滚，不影响能不能读全。
   tooltip 仍然要有 (给更长的解释), 但它不再是"看不到就悬停"的替代品。
5. **列宽 = max(表头, 该列最长文本) + 内边距, 按内容算**: 数据行量宽留 20~26px 余量 (实测 +18 会差
   1~14px 被切); 分组标题会撑宽 Name 列 ⇒ 先把组标题压短 (`🚌 报文 157 · L5 12 · …`)。
   计算要缓存在**脏标记**上 (`_fill_tree()` 开头 `_need_dirty=True`), 别拿 `topLevelItemCount()` 当缓存键
   —— 它恒等于分组数 (3), 缓存永不失效, 实测改完列宽还是旧值; 新增/删行都要重算。
   每列给**语义上限** (Name 1200 / Type 900 / Tx·Rx 2400), 超过上限的极端值走 tooltip。
   **不要靠"窄面板藏列"解决挤** —— 藏了就跟"要能看全"直接矛盾 (`setColumnHidden(..., False)` 统一打开)。
6. **多消费者要聚合, 不是截断**: Rx ≤6 个全部列出; >6 个是广播话题 (实测最多 72 个下游)
   ⇒ 显示 `N 个下游`, 全名单进 tooltip。这是聚合口径, 不是省略号。
6. **加列时同步改七处**: `QTableWidget(0, N)` 的 N · `setColumnCount` · `_cols/_col_tt` ·
   每处 `QTableWidgetItem([...])` / `cells = [...]` 元组长度 · `_update_values` 里的列索引
   (插入一列 ⇒ 后面全部 +1) · `_ALIGN` 表与 delegate 的列号 · **构造里的初始列宽元组**。
   还有两类**不报错但取错列**的地方必须一起改: 选中行读名称 (`item(it.row(), 1)` → 新索引)、
   `_fit_name_col()` 里 `setColumnWidth(1, ...)` 的目标列。列数多于控件设定的 N 时,
   多出来的列连表头都不显示 (实测 12 列表头只显示 11 个, Hz 列凭空消失)。
   改完 `py_compile` + 探针读 `headerItem().text(i)` 与真实行 `item(r,c).text()`, 并数一次 `columnCount()`。
7. 探针的四个坑: ①控件在未显示的页签里 ⇒ `reload()` 的 `isVisible()` 早退, 树是空的, 要显式调用
   `reload(force_tree=True)` 或直接 `_fit_columns()`; ②放进 host 里 `resize()` 不生效 (控件自身最小宽
   撑着), 想验窄面板就直接按目标宽度算一次 `_fit_columns()` 读列宽, 别跟布局较劲;
   ③**先清 `QSettings("ZMAX","studio").remove("canoe/data_cols")`** 再验自动列宽 —— 否则读到的是
   上次手拖的持久化宽度, 会误判成"内容宽没生效";
   ④探针进程若用 `os._exit()` 收尾, `print()` 必须 `flush=True` —— 否则日志整个是空的, 会被误判成
   "脚本没跑/改动没生效", 白白多查一轮。
8. 🔴 **改列/表头前先全局 grep 旧列名**: 同一张表头常在**三处**写死 —— 控件构造里的
   `setHorizontalHeaderLabels([...])`、`_set_trace_header()`、`_set_trace_header0()`。只改一处 ⇒
   首屏仍是旧列 (实测构造里的 `Prob % / Sender / Class` 盖掉新表头), 列数对不上还会让单元格静默错位。
   判据: `grep -n 'Prob %\|Sender Id\|Lamp\|Count'` 在 Trace 相关文件里 0 命中 + 探针读
   `headerItem().text(i)` 逐列核对。
9. 🔴 **两种显示模式各自定义自己用到的局部变量**: 滚动模式的填充函数引用了只在固定行模式里定义的
   `_cur_topics` ⇒ 一切换模式就 `NameError`, 表直接空白 (报错发生在定时回调里, 不弹窗)。
   模式分支里共用的小表 (命中话题集/取值缓存) 要么提到方法入口统一算, 要么两处各算一遍; 改完必须
   `_toggle_mode()` 真跑一次并读行数。

## 8. 显示名归一 + 类型左右同源 (表格类 UI 的两条铁律)

**① Tx/Rx 只放节点本名。** 画布节点名是给人读的长名 (emoji / `L2~L5` 前缀 / `①..⑧` 序号 /
`SK01` 编号 / ` · 解释` / `→ 下游`), 直接进表格就是"L5 L4 都冒出来"。统一走
`src/lerobot/middleware/naming.py`:

```
clean(): 去 emoji → 去开头 L1~L5 / meta → 去圈号①..⑳ → 在 " (" 或 " → " 处截断
         → " · " / " + " 只取第一段 → 去 SK 号 → 名字内箭头统一成 "-"
unique_map(): 归一后重名的补 "(短id)", 保证 Tx/Rx 能唯一定位 (实测 75 节点 0 重名)
```

- 只在**显示层**归一, 不改画布真源; 导出要另留 `节点全名` 列, 否则追溯断链。
- 截断点必须带空格 (`\s+\(` / `\s+→\s+`), 否则 `SU(2) 统一状态空间` 会被砍成 `SU`、
  `2D→3D 解算` 被砍成 `D`、`3D 视图` 被当作序号砍成 `D 视图` —— 圈号正则也不能吃普通数字。
- 应用面一次改全: 报文行 Tx/Rx · 节点树 Name · 连线信号行 Name (用连线标签, 不用 `源→目的`) ·
  详情面板 · 数据空间报文表/节点表/导出。改完断言: Tx/Rx 里 `L[1-5]` token 数 = 0、`→` 数 = 0。

**② 表格与右侧详情必须同一个真源。** 症状: 左边 Type 列已经是语义类型, 右下"详细信息"还是
`zmax::SSNodePort` —— 因为表格读语义注册表、详情读 `live.json`/`busdb` 快照。
做法: 详情面板也调同一个 `topic_types.describe(topic)`, 并多给一行「类型含义」(中文语义);
非 `ss.node.*` 形态的话题 (heartbeat / link_value…) **保留它自己声明的类型**, 不要硬套注册表
(否则一次性把 44 条已知类型降级成 `Unknown`)。
判据: 同一条目在左表与详情里的类型字符串**逐字相等**; 连线的详情给 `zmax::LinkValue`。

## 9. 质量告警要判"值", 不是判"心跳"; 顶部工具条只留一个搜索

**① 告警的判据必须是物理量本身.** 只统计 QoS/频率/丢包/配对, 本质是心跳监视: 总线安静时
表里什么都没有, 于是"真的没告警"和"根本没接上"长得一模一样。真判据 (`middleware/quality.py`):

```
超上限 / 低于下限     声明量程 (mw_signal ← 参数中心); 无声明时按物理规律兜底
物理规律              概率/比例 ∈ [0,1] · 百分比 ≤100 · 质量/刚度/阻尼 ≥0 · 温度 ≥-273.15°C ·
                      压力 ≥0 · 角度 |x|≤720 · 速度 |x|≤1000 · Hz ≥0
数值有效性            NaN / inf / 非数值 / 空值
单位                  有值无单位 ⇒ warn (物理量不许裸数)
跳变                  相邻帧 Δ > 量程×10 或 >1e6 ⇒ warn (多半单位错/串帧)
```

- 告警行写成 `Level | Object(topic · signal) | rule: 说明`, 说明里必须带**实际值 vs 限值 vs 依据**:
  `range_high: 超上限: 999 > 720 deg* (物理规律)` —— "越界"两个字的告警等于没告。
- **空表要显式一行 `⚪ info` 列出判据清单**, 页签计数只算 fail/warn (info 不算告警)。
- 验证方式是**注入越界帧**: 造假 `fields={grasp_prob:1.4, joint1_deg:999}` → Trace 必须出现 `✘`,
  告警表必须出 `range_high` 两条; 正常值必须一条不报 (不制造假警)。只测"页面能打开"不算验证。
- 🔴 **只有实测数值才进物理判据**: 占位/信封行 (`signal="value"`、`src=占位|信封`) 与 `Value="—"`
  必须在喂给 `scan_frames()` 之前剔除。全量加载后大部分行没有实测值, 不剔除的话 `—` 被判成
  "非数值", 一次刷出上千条假 fail (实测 1429 条), 真告警被淹没。判据: 有实时数据时告警应为 0~个位数,
  打开页面不该满屏红。
- 一个判据两个入口同源: `dds_canoe._fill_alerts()` 与 `dds_space.alerts()` 都调同一套 `scan_frames()`;
  别在一个页面修好、另一个页面继续只看 QoS。
- 覆盖缺口要**如实说**: 端口信号若还是占位 (`mw_signal` 里 0 单位/0 量程), 量程告警就只能靠物理规律
  与名称推断; 要按设计量程报警, 得先在节点模块声明 `SIGNALS` —— 不要把"推断"讲成"设计判据"。

**② 顶部工具条能删就删, 只留一个搜索.** 一排 `档位 / 拍照 / 灯 / 刷新龄 / 报文计数 / 计时`
加 `⚡Start / ⬢Stop` 大按钮, 用户读到的是噪声; 口径是"都删掉, 只保留一个搜索信号, 放在 Trace 按钮区"。

- 搜索从"置顶"改成**真过滤**: 话题名命中 ⇒ 该话题全部信号行; 只字段名命中 ⇒ 只留那几行;
  占位词直接给例子 (`ss_plan · grasp_prob · tcp_x`), 不要只写"搜索"。
- 🔴 **删控件前先查引用**: 顶部条的 `_on_start/_on_stop` 与 `_toggle_pause()` 互相联动
  (`btn_start.setEnabled(...)`) —— 只删控件不删联动, 点一次"暂停"就 `AttributeError`。
  删完 `grep` 这些属性名, 把方法一起删或解耦, 再 `py_compile` + 真屏点一遍。
- 删完当面取证: 可见按钮/标签列表 (`findChildren(QPushButton/QLabel)` + `isVisible()`)
  里不应再有被删文案; 搜索框输入一个字段名, 表行数必须从 N 降到命中数。

## 10. 表不动先查"源有没有在发", 并与信号分析窗口共用同一份数据

**症状**: 用户说「数据空间的信号怎么不动? 要实时运行啊」。真因多数不是刷新率/Timer: Trace 读的
`zmax_data/dataspace/live.json` 是 DDS 桥输出, 探针里 `matched_pubs=0`、`hz=-1`、`fields` 为空
⇒ 值永远是 `—`。这时把 1500ms 调成 800ms 一点用都没有。

诊断顺序 (别跳):
1. 读 live.json 的 `topics[*].{hz,count,matched_pubs,age_s,fields}`: `matched_pubs=0` + fields 空
   = 发布端没配上 (不是 UI 没刷新)。
2. `journalctl -u zmax-dataspaces-probe` 出现 "窗口内 0 条(发布端没起?)" 是同一件事。
3. 再决定: 修 DDS 配对, 还是换"同源文件源" (下一条)。

**同源文件源 (推荐, 同时满足"与信号分析一致")**: 数据空间不要自己再采一遍, 直接读「信号分析」窗口
正在读的那几份本机真值文件 —— 同一拍数据, 两处数值天然相等, 不是各算一套再对齐。
真源 `zmax_data/ss_live/{trace_live,engine_trace,gravity_trace}.json` (sstrace / sseng / gravity),
封装成 `middleware/live_signals.py::topics()` (0.25s 缓存, 带 `ts`/`age_s`), Trace 侧按 topic 覆盖字段。

- 覆盖时**按短名 + 全名双向去重**, 否则 `ss_state` 与 `zmax/ss_state` 会出现两行。
- 刷新 800ms 量级就够 (源多为 5~10Hz); `reload()` 在 `isVisible()` 为假时直接 return 省 CPU。
- 判据 `tools/verify_live_consistency.py`: 数据空间读的文件 == 信号分析 `SOURCES` 那几份 · 帧龄 <3s ·
  provider 与文件逐信号相等 · 1.3s 内 ≥10 个信号在变 · Signal 保留源文件真实键名。
- 边界要如实说: 这只让**显示**实时; DDS 总线上若仍是 0 发布者, 要单独排 daemon 配对, 别把
  "显示动了"讲成"DDS 通了"。

## 11. 信号分析窗口 = 数据空间 Trace 的另一半 (列口径 / 同源同值 / 可拖宽)

用户会把它当同一个东西看: 「要与数据空间 Trace 的数据同步, 列保持一致」。

- 列口径 (8 列): `Name | Layer | Signal | Value | Rate | Type | Tx | Rx`。`Rate` = 变化率 (末两点差分 ÷ 时间差,
  按显示单位每秒; 缓冲不足两点写 `-`)。用户会要求「每个信号都要看到变化率」—— 这是常见追加列,
  加它时按 §7-6 的"加列七处 + 判据下标"一起改。🔴 `Layer` 必须放**第 2 列** ——
  放最后一列时左栏窄(实测视口 440~510px)会被挤出视口, 用户只会问「Layer 列呢?」;
  `Signal` 与数据空间 Trace 共用 `middleware/signal_en.py` ⇒ 同一条信号两个窗口同一个英文名。
  他说「信号名称→signal · 当前值→value · 输出节点→Tx · 来源节点→Rx」并「增加 type / Layer / 中文名称」
  ⇒ 中文名进 `Name`(≤5 字), 程序真实变量键进 `Signal`, 两列都要有, 不是二选一。
- 🔴 列宽: 原第 0 列是 `Stretch` ⇒ 鼠标拖不动(用户: 「怎么调整完了又自动还原」)。改成 7 列**全部
  `Interactive`**, `header().sectionResized` 里快照整组宽度写 `QSettings("zmax","canoe")`,
  启动时读回。判据: 拖 Name 到 333 → 重开仍 333。
  ⚠️ **改列序就换缓存键** (`sig/tree_cols` → `sig/tree_cols_v2`): 旧 key 里存的是按旧下标记的宽度,
  顺序一变就会套到别的列上。
- 图标: 页签/窗口要显式 `setWindowIcon(QIcon(ROOT + "tools/gui/logo.png"))`; 没设就是空白图标,
  别怀疑主题或 DPI。
- 🔴 **同源同值**: 窗口若各自 parse 同一份 json, 会与数据空间差 0.1~0.2s 的采样, 数值肉眼对不上。
  三路本机真值 (sstrace / sseng / gravity) 全部走 `middleware/live_signals.topics()` 的**同一份缓存快照**;
  判据是"同一缓存窗口内两次读逐信号相等", 不是"两个窗口各读一次再比"。
- 🔴 **值缓存键必须是 `(id(item), key)`**: 同一 key 会在多个场景组各有一行; 只按 key 缓存 ⇒ 第一行
  写完后第二行永远停在 `-`(实测 41 行一半是空)。
- 选"谁置顶"可以看帧龄 (`age_s < 3`), 但**只用于一次性定位活跃源, 不能每拍按帧龄重排** ——
  帧龄每拍都在变, 行序跟着动, 用户看到的就是「signal 在跳, 你不要乱动每个 signal」。
  固定行模式必须按**常量键**排: 属于实时源集合 → 层 L2..L5 → 话题名; 判据是同一批
  (Layer, Signal, Tx, Rx) 元组在 1.5s 内两次填充后逐行相等 (实测 1948 行, 变动 0)。
  也不要按"fields 非空": 停了的单步话题 fields 还在 (`state=[] count=0`), 会压在最上面, 让人以为有数据在跑。
- 时间列 = `time.time() - age_s`; 源文件里的 `ts` 是采集机时钟(本机 NTP 回拨过), 直接上屏差 8 小时。
- `Type` 兜底: `topic_types.type_of_topic()` 对 `zmax/ss_state|ss_engine|ss_torque` 返回空串 ⇒
  再取 `lerobot.dataspace.topics.TOPICS[短名]["type"]` (`zmax::SSState` / `SSManifoldStep` / `SSDrivingTorque`)。
- `Name`: 源键本身是中文就直接裁短 (`下降·L2 力大小_mps` → `L2力大小`), 英文键才走 `cn_names`。

## 12. 面板瘦身: 按钮一行 + 只留一行文字 (用户口径)

原话口径: 「上边好几行文字, 除了八阶段那行, 全都删掉; 按钮合并成一行, 第二行没有用的都删掉」。

- 删的是**可见性**, 不是构造: 别处还在读 `b.isChecked()` / `b.toggled`, 直接删控件就 `AttributeError`。
  一律 `w.setParent(self); w.hide()`。
- 🔴 未上布局又没 `setParent` 的控件会变成**漂浮的顶层窗口**; 探针用
  `QApplication.topLevelWidgets()` 确认没有多余顶层窗。
- 取证三件: `findChildren(QPushButton/QLabel)` + `isVisible()` 列表 · 按 `mapTo(w).y()//10*10` 分行
  (必须只剩一行) · 最右 `mapTo(w, rect().topRight()).x()` < 窗口宽 (实测 9 个按钮 1244/1500 不溢出)。
- 状态行 / `⚙️ 当前配置` / `场景排序 · 当前数据源场景 · 计数` 这类也算"文字行", 一并撤; 真要显示数值就
  给表格加列, 不要另起一行 label。八阶段那种**每拍都在变的状态文字**是唯一保留项。

## 13. Tx 必须是真发送方 + 列头按值过滤

**① Tx 不许拿"像节点的名字"顶上.** 用户会核对画布: 「Tx 是发送的节点, 状态空间没有 XX 节点啊?」
真实的坑是 Tx 表里写的是**描述性标签**(`🌍 万有引力表 (主参数 M 页 · 力的大小/实部)`),
而画布里只有 `sscalib`(标定层·引力-斥力-动作) —— 名字读起来像节点, 一查就没有。
口径:

```
OUT_NODE_RULES = (键前缀, 工程库 node_id, 无节点时的进程名)
  sstrace.前馈速度 → ssff · 动作调制/阶段 → sssched · 安全边界 → sslimit ·
  接触概率 → ssinnov · 光模块 → ssyolo · 光模块头/吸嘴 → ss2d3d · 夹爪 → ssact ·
  触觉类 → sstactile · 光学/AOI → ssaoi · sseng.* → ss_mani_eng · 潜表示 → ssvlm ·
  skill闸 → ssphys · ds.ss_meta_pred → n_intent_direct · 默认 → swworld
有 node_id ⇒ 工程库名字过 naming.unique_map() (只剩本名, 与所有面板同一词表)
无 node_id ⇒ Tx 写 "—" —— 进程名 / 服务名 / .py 一律不许出现在 Tx/Rx 列;
             出处只进 source_of() 的 tooltip「来源:」行
```

判据 (`tools/verify_tx_real_nodes.py`): Tx 里 0 条 `.py`/进程/服务字样; 每个 Tx 取值 ∈ 工程节点词表
(或阶段标签/`—`); `sstrace.前馈速度_mps` 的 Tx 恰好是 `前馈加速器`。再加 `verify_layer_node_strict.py`
核 Tx/Rx 与工程库节点名单射、Layer 全 L2、横杠行 = 0。

**② 列头过滤 (Layer 只选 L2 / Type 只选一个类型).** 用表头, 不另加一行下拉:
`header().setSectionsClickable(True)` + `sectionClicked` → 该列取值 + 条数生成 `QMenu`
(`QActionGroup` 单选, 首项「全部」, 末项「清除所有列的过滤」) → 选中后递归隐藏不匹配的叶子行,
子行全被过滤掉的分组也一起 `setHidden`。列头常显 `▾` 提示可点, 生效时显示实际值 `Layer ▾ L2`;
重建树之后要**再套一遍过滤**, 否则刷一拍就恢复全量。
判据: 劫持 `QMenu.exec_` 返回 data=="L2" 的 action ⇒ 行数 556→274 且层只剩 L2;
再选一个 `zmax::` 类型 ⇒ 82 行且只有一种类型; 只清 Layer 时 Type 过滤仍在。

**③ Tx / Rx / Layer 只许有一份真源 (`middleware/attribution.py`).**
两个窗口各写一份映射 = 必然漂: Trace 从工程库话题推导, 信号分析用另一套规则表 ⇒ 同一条信号
两处显示不同节点, 用户直接指出「Tx Rx 要同步, 你现在显示的不一样」。真源只留一个模块:

```
key_of(topic, field)   zmax/ss_state|ss_engine|ss_torque → sstrace./sseng./gravity. 前缀
                       (另认 ds./ros./ar./skill./skillphys./space./safety./pose./state. 等)
tx_of(key) / rx_of(key) / layer_of(key)      两窗口都调这三个, 别各自算
fmt_value(v, key) / display_unit(key, unit)  数值与单位也走同一份
```

- 层必须由 **Tx 那个节点**算 (`layer_of` 先取 `tx_of`, 再查该节点的层) —— 两条路径各查各的就会出现
  「Tx=Z-MAX 引擎(L4) 但 Layer=L2」的自相矛盾。`gravity.*` 键里带的那段 L2~L5 是「哪个层对元任务施加的力」,
  不是生产者层, 别拿它当 Layer。
- 键前缀 → 工程节点归属写在 `PREFIX_OWNER` (sstrace→ssest · sseng→ss_mani_eng · gravity→n_calib_mani ·
  yolo→ssyolo · ar→ssaoi …); 字段级规则优先, 规则无节点才用前缀属主, 都没有 ⇒ `—`。
- 判据 `tools/verify_trace_sync.py`: 面板每一个信号键在 Trace 里都要找到 (Layer,Tx,Rx) 完全相同的行
  (实测 506 键, 不一致 0); 再叠「行不跳 / 单位 mm/s / 数值同量级」三项。

**④ 数值/单位也必须同口径.** 速度类键 (`_mps`) 两个窗口统一按 **mm/s** 显示 (真源 m/s ×1000)
+ `.4g` 格式; 只同步 Tx/Rx 不同步单位, 同一条信号会变成 0.032 对 32.21, 用户照样说"不一样"。
判跳变/量程仍用**原始值** (行里另存 `vraw`), 显示换算不能污染判据。

**⑤ 一次画几百条曲线会把 GUI 拖死 —— 列表全显示, 波形限量画.**
实测 pyqtgraph 每信号一个图时 278 条曲线 ⇒ 一次刷新 14.5s (界面等于卡死), 共用一根轴也一样慢。
口径: **列表里全部勾选、全部实时刷新数值**; 波形 `MAX_DRAW = 24` 条, 顺序按优先级而不是树上顺序:
TCP 位姿 (`末端_x/_y/_z`) → 八阶段 (`阶段序号/八阶段序号/阶段限速`) → 接触/夹持 → 前馈/调制/安全 → 其余。
- 想看某一条就用列头过滤收窄或点行, 不要靠"全画"。判据: 已选 278 / 绘制 24 · 前 6 条是 TCP+八阶段 ·
  5 次刷新 < 1s (实测 0.09s/10 次)。
- 🔴 `set_curves()` 里做截断后, **勾选变化必须重新调一次 set_curves** (`_fill_tree` 末尾也要调),
  否则先勾上的那批键会一直占着前 24 个绘图位, 后勾的 TCP/八阶段根本画不出来。

**⑥ 场景组默认显示 = 该组全部动态信号, 不是几条代表曲线.**
「插拔绿色的信号, 要显示所有在场景中我可以观察到的信号, 包括 8 个状态、TCP 位姿」⇒ 默认勾选按
**分组归属**算 (遍历场景组叶子行, 只剔 `.ts` 时间戳行), 不再维护一份人工 DEFAULT 键清单;
增量补勾逻辑保留 (手动取消的不顶回来)。实测 285 行勾 278, 剩 7 条正好是各文件的 `.ts`。

**⑦ 大 GUI 文件里同名方法后定义覆盖先定义.** 改 `_sig_layer`/`_out_node` 这类方法前先
`grep -n "def _sig_layer"` 数一遍: 同一 class 里有两处定义时, **后一处静默生效**, 改第一处等于没改
(实测改完仍走旧映射)。要么删掉重复定义, 要么确认只有一处, 改完用探针直接调该方法取值自证。

## 14. 固定行"不许跳"的最后一公里 + 真同源判据 + 位姿告警

### ① 字段抖动会让整表下移 (固定行模式的隐藏杀手)

本机 JSON 里某个键一拍有一拍没 (可选键/NaN/源重启中途) ⇒ 重排后**已存在的行全部换位**。实测 10 拍里
1444 行跳位, 用户看到的就是「signal 在跳」。排序键换常量只解决"帧龄每拍变", 解决不了"行集合变"。
做法 (三条一起上):

```
老行严格按上拍顺序排 (self._trace_order 记 (topic, raw))
本拍缺失的键 ⇒ 保留上一拍的行, 值不动、标记陈旧, 60s 内不删 (self._trace_keep 存 (row, t))
新键 ⇒ 只插到它同话题的最后一行之后; 没有同话题就追加表尾
force=True (用户点刷新) 才允许重排, 并重建 keep 基线
```

判据必须走**增量路径** (`_fill_trace_fixed()` 不传 force): 探针里每拍 `force=True` 会把修复完全掩盖 ——
force 本来就允许重排, 测出来的"跳"是探针自己造成的。实测口径: 10s/10 拍, 行数恒定、每拍增量全 0、
位置变动 0 行。

### ② 同源只认"同一份快照", 不认"两次采样差不多"

面板若对部分前缀自己读文件 (只有 sstrace/sseng/gravity 走快照, 其余 skill/skillphys/pose/state/…
各读各的), 与 Trace 天然差一拍: 快变量 (动作调制、循环耗时、加速度) 差一拍就是几倍, 用相对容差比
必然误报"源不一致"。

- 做法: **所有前缀**都映射到同一个 `live_signals.topics()` 快照再取值 (`_PROV` 表列全 11 个前缀)。
- 判据: 冻结快照 (monkeypatch `LS.topics` 返回固定 dict) → 两窗口强制重填 → 逐键比**字面值**, 期望不同 0 条
  (实测 400 键 0 不同; 改前 34 条差一拍)。比"同一缓存窗口内两次读相等"只是必要条件, 不能替代。
- NaN: `fields == fields` 在含 NaN 时恒为 False ⇒ 用 `repr(a) == repr(b)` 比。
- 加列后所有判据的**列下标**要跟着改: 硬编码 `text(5)/text(6)` 会读到邻列, 报出"Tx 显示的是 Type"这类
  假 FAIL —— 先怀疑判据下标, 再怀疑代码 (本轮连续踩两次)。列宽 QSettings 键也换版本 (`sig/tree_cols_v3`)。

### ③ 位姿信号: 没有真值就写 -1 + 告警, 不许补角度

用户会拿 3D 场景对信号: 「3D 都抓起来了、插拔成功了, 为什么抓取的 x 位置一直不变」。诊断顺序:

1. `pgrep -af pose_tap|rokae` + 位姿文件 mtime/`ts`: 采集进程不在 / 文件停更几十小时 ⇒ 源头没数据。
2. 位姿发布器原本在"读不到新鲜位姿"时写 `-1.0` (不拿旧值充现在), 于是 8 个技能 x/y/z 恒为 -1。
3. 有 3D 场景真值 (`trace_live.json` 末端_x/y/z, m) 时回落: 只在**文件新鲜 (<2s) 且场景时钟在推进**时用,
   秒杀冻结快照; 短暂断流沿用上次值 ≤3s 并标 `·保持`; 超时老实回 -1。发布时带 `pose_src` 让人能追。
4. 位置与"在职"**解耦**: 位置 = 当前 TCP 真值, `在职` 只决定 v/a/s/err 这类过程量。
5. 🔴 姿态 a/b/c: 3D 场景出口**只有位置没有姿态**, tap 停更时没有真值 ⇒ 发 `-1` + 一条 warn
   「姿态不可观测」, 绝不按动画推角度。

一致性判据 (`middleware/pose_check.py::check(tl, sp, tol_mm=5)`, 纯函数可单测): 场景末端 m→mm 与每个
SK 的 x/y/z 比, >tol fail / >tol/2 warn; 接进 Trace 的告警表 (`tb_alert`)。**验证方式是注入**: 把某个 SK 的
x 加 25mm, 判据必须出 `fail SK04 抓取 · x ... Δ25.00 > 5.0`, 再读真表确认那一行真的出现 ——
只断言"函数返回列表"不算。

### ④ 只读发布器(写 JSON 的驻留进程)重启规矩

- 宽泛 `pgrep -f "xxx.py"` 会匹配到**你自己这条 bash 命令**(命令行里带脚本名) ⇒ 把自己杀掉 (实测连续两次)。
  只杀 `cat /proc/<pid>/comm` 以 `python` 开头的进程。
- 🔴 **多实例同写一份 JSON 会让 schema 回退**: 老实例没有新字段, 后写覆盖先写 ⇒ 新加的 `a/b/c` 看着像没生效。
  启动后立刻 `pgrep` 数实例数并**回读关键字段**, 不是"启动成功"就算完。

## 15. 只留 L2 + Tx/Rx 只认工程节点 (两个窗口的最终收口)

口径会一路收窄 (先"L2~L5"再"只保留 L2 层 topic"), **以最后一条为准**, 并且旧判据要同批翻转 ——
旧判据往往正把旧行为钉死 (`gravity.*` 的 Tx 必须是 `gravity_trace_pub` 就是在要求假节点)。

### ① 过滤只写在 `middleware/attribution.py`, GUI 不许各写一套

```
l2_names() / names_l2(n) / topic_in_l2(t) / layer_l2(t) / tx_l2(k) / rx_l2(k)
show_in_l2(k)       信号分析: Tx 是 L2 节点就显示 —— Rx 允许 "—" (画布上确实没连线)
show_in_l2_link(k)  数据空间 Trace: Tx 与 Rx 都必须是 L2 节点 ⇒ 横杠行整条不显示
```

- 两个窗口对同一类行给不同待遇是故意的: Trace 是连线视图, 信号分析是信号清单。改口径时先问
  "这条要不要在数据空间出现", 别把两处合成一个布尔。
- 删横杠行是**过滤**, 不是把 `—` 改成空串; 判据写"横杠数必须 = 0", 否则下一轮又漂回来。

### ② 阶段节点 (SK) 归一化只认名字以 SK0x 结尾

画布上同时存在 SK 阶段节点 (`SK03 下降`) 和 meta 容器 (`⚖ 物理约束 · 惯性/质量率闸 (SK01-08)`):
按"名字里出现 SK 就算阶段"会把 meta 容器漏进 Tx/Rx。判据会当场报出来:
`物理约束 in l2_names(): False` / `接近: True` / `前馈直方图: False`。

- SK 信号的 Rx 走 SK 节点的**真连线** (`sssk*.out1 → n_moveit`), 不要因为键不是端口形态就写 `—`;
- 没有连线的 (3D 场景 `sstrace.*`: 末端/八阶段) 老实不显示, 不要为了填满 Rx 编一个下游。
  代价要当面讲清: 这两类信号会从数据空间消失, 只在信号分析里可见。

### ③ 判据白名单要用显示名真源, 不要用工程库原始名

原始节点名带 emoji / `L2~L5` 前缀 / 圈号 / SK 编号 / `· 解释`, 逐字比对必报几百条假违规
(实测 202 条)。白名单一律 `A.l2_names()` 或 `naming.unique_map()` 的输出 (75 节点 ↔ 75 唯一名)。

### ④ 逐行算属性 ⇒ 工程库查询必须缓存

Trace 每行都要 Layer/Tx/Rx, 若每次都 `db.node_rows()` 全表重查: 1618 行 ⇒ 1936 次调用 / 5.6s
(整表刷新 4.6s)。做法: 按工程库文件 **mtime+size** 做 `lru_cache(maxsize=8)` 并**返回副本**
(库重建自动失效, 调用方改不动缓存); 修后 0.12s, 判据阈值 0.25s。

### ⑤ 判据纪律: 别钉死数量和显示串

- 节点数写死 (89) ⇒ 画布加到 90 就假红; 用 `>=` 或直接读画布真源。
- 显示文案 (SK 编号) 会被统一改一次 ⇒ 改成按集合/前缀比。
- 列头过滤判据要跟口径一起改: 窗口只剩 L2 时"过滤 L4 应 0 行"成立, 但"过滤后刷新仍保持"要看
  刷新路径有没有重套过滤 (`reload` 重建整表会冲掉过滤)。
- 离屏探针: 控件要 `show()` 才建树; Trace 的**原始字段名只在 tooltip 第一行**, 显示文本是中文短名
  —— 按显示文本取值会取错 (同名短名还会撞)。

## 16. 两窗口同值: 统一信号库 (SQLite) 而不是各读各的 JSON

```
单写者 daemon (2Hz, pidfile 自锁)  live_signals.topics_from_files()  --整份-->  zmax_data/dataspace/signals.db
读侧  live_signals.topics()  优先读库, 要求 meta.updated < 3s; 过期回落文件直读 + 打印一行告警
```

- 库: WAL + 三表 (`topics`/`signals`/`meta.updated`), **单事务整份替换** —— 逐条 upsert 会留下
  半新半旧的快照, 两个窗口读到的不是同一拍。
- 写库要把 `topics_from_files()` 的字段**全部回填** (src_file_ts/count/type/qos/unit…), 少一个键
  就会出现"值全空"或整行消失。
- 不静默降级: 回落文件必须打印告警; 保留 `ZMAX_SIGNAL_DB_OFF=1` 走旧路排障。
- 判据: 库里改一行既有信号 ⇒ 两个窗口同拍都变; 守护恢复后回真值; 关库有告警。
  **按换换算比判** (m/s 显示 ×1000 mm/s), 直接比原值必假红。
- 跨窗口哨兵要选**两个窗口都有**的信号: 只属于 3D 场景的键在收口到 L2 后可能已不在 Trace 里。
