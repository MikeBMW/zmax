# 数据空间 Trace ↔ 信号分析: 同源、固定行、归属、位姿真值

两个窗口 (`tools/gui/dds_canoe.py` = Trace / 数据空间, `tools/gui/canoe_graphic.py` = 信号分析)
共用一份 live 快照。用户会拿任意一行两窗口对账, 所以"看起来一致"不算, 必须可证伪。

## 1. 同源 = 所有前缀都走同一份快照
- 只有把**每一个**数据源前缀 (sstrace/sseng/gravity/skill/skillphys/pose/state/safety/yolo/space/ar)
  都映射到 `live_signals.topics()` 才叫同源。面板自己 `open(json)` 读文件 ⇒ 与 Trace 差一拍,
  快变量能差一倍以上 (动作调制/循环耗时/加速度)。
- `live_signals` 缓存 0.25s, 覆盖全部 11 个话题 ⇒ 同一拍两窗口拿到同一 dict。

### 判据: 冻结快照后逐字比对 (不要用相对容差)
```python
_frozen = {k: dict(v) for k, v in LS.topics().items()}
_orig = LS.topics; LS.topics = lambda *a, **k: _frozen      # 冻结一拍
# 两边各自重建 → 取 (话题, 原始字段名) → 值, 逐条比对 abs(a-b) > 1e-6 即失败
LS.topics = _orig
```
- 用 ±25%/±0.05 容差比实时两窗口必假报警: 快变量差一拍就超差, 那不是"源不一致"。
- NaN 字段用 `repr()` 比, `a == b` 恒 False。

## 2. 固定行模式: 行集合比排序更要紧
- 排序键去掉帧龄 (帧龄每拍变 ⇒ 行序每拍变) 只解决一半; 真正的位移来自**行集合抖动**:
  本机 JSON 里某个可选键/NaN 一拍有一拍没 ⇒ 排序后整表下移 (实测 10 拍 1444 行位移)。
- 做法: 老行严格按上拍顺序排; 新行只插到同话题最后一行之后; 本拍缺失的字段**保留上一拍那行**
  (值不动、标陈旧), 60s 内不删。行数才能恒定 (实测 1520 恒定 / 每拍增量 0 / 位移 0)。
- 判据必须走**增量路径** `_fill_trace_fixed()`; `force=True` 是用户点"刷新", 允许重排 ——
  拿 force 测稳定性会测出一个不存在的问题。

## 3. 元数据过滤的连带效应: 端口整行消失
- `signal_en.is_meta()` 覆盖 `ts/topic/json/src/count/bytes/n/seq/type/payload` (含末段命中)。
  全路径 (建树/取值/保障) 都要过它, 否则 Trace 会列出 `topic/ts/json` 当信号。
- 但 `ss.node.*` 端口**只有**信封字段时, 一过滤就什么都不剩 ⇒ 该端口整行消失。保障改为用
  **端口名**占一行 (值 `—`, 标「端口(未声明信号)」), 不要回信封元数据、也不要编 payload 字段名。

## 4. 删层之前先补归属规则
- 删某层 (例如 SYS = 无画布节点的信号) 前, 先确认没有整类话题正落在 SYS 上: 缺归属规则的
  话题会被判 SYS 然后**随层一起消失**, 现象是"这个节点的输出在表里根本没有"。
- `ss.node.<id>.<port>` 的唯一依据是 `config/platform/dds_topic_types.json` 的 `nodes.<id>`:
  `ins[].producers` / `outs[].consumers` / `layer`。归属口径:
  · in 口: Tx = 上游 fan-in 节点名, Rx = 本节点 · out 口: Tx = 本节点, Rx = 下游 consumer
  · `layer_of()` 取 `nodes.<id>.layer` (不按话题名前缀猜)
- `key_of()` 也要给 `ss.node.*` 返回归属键, 否则 Trace 的 Layer/Tx/Rx 与信号分析两套口径。

## 5. 给表格加列 = 全仓库判据的列下标全体位移
- 加一列 (`Rate`) 后, 所有 `verify_*.py` 里硬编码的 `text(5)/text(6)` 会静默改读别的列,
  输出看着像"Layer/Tx/Rx 不一致 398 处"的**假故障**。
- 加/删列时: 同步改每个判据的下标; 更好的做法是判据按**列头名**取列 (`headerItem().text(i)` 找 index)。
- 列宽记忆键要跟着换代 (`sig/tree_cols_v2` → `v3`), 否则旧宽度错位。

## 6. 变化率列 (用户要看速率)
- `Rate = (v[-1]-v[-2]) / (t[-1]-t[-2])`, 乘显示比例 (速度 m/s→mm/s) 后仍是每秒。
- 更新循环的"无变化跳过"缓存要把 Rate 一起纳入, 否则 Rate 永远停在第一次写的值。

## 7. 位姿信号: 代偿要标来源, 姿态不许伪造
- 技能位姿 (`skill_phys.json`) 的 x/y/z 是**当前 TCP**, 不是每个技能自己的规划点; "在职"只决定
  v/a/s/err 这些过程量, 不该让位置显示成 -1。
- tap 位姿源停更时用 3D 场景真值 `trace_live.json` 的 `末端_x/y/z` (m→mm) 代偿, 并且每条技能写
  `pose_src` + `pose_age_s`; 短暂停一两拍沿用上一拍真值 ≤3s 并标注, 超过就老实回 -1。
- 3D 场景出口**不含姿态**: 姿态只在真机 tcp_pose 链上。拿不到就发 `-1` 并在告警里写
  「姿态不可观测」, **不要**用位置差分/假设值凑 a/b/c。

## 8. 位姿与场景不一致 ⇒ 全局数据空间 QoS 报警
- 判据放在可单测的函数里 (`middleware/pose_check.py`: `scene_xyz()` + `check(tl, sp, tol_mm)`),
  再由 Trace 的告警表调用。>5mm = fail, >2.5mm = warn, 姿态缺失 = 一条 warn (不刷屏)。
- **判据验证必须注入错误值**: deepcopy 快照, 把某技能 x 加 25mm, 断言拿到 fail 报警 ——
  只断言"函数返回了列表"等于没验。
- 之后再去告警控件里读回那几行, 证明报警真的上屏 (不是只在函数里成立)。

## 9. "3D 场景里机器人位姿是谁规划的?" —— 没有规划器, 是回放
- 3D 面板 (`tools/gui/ss_dreamview.py`) 逐帧读 `reports/ss_episode_latest.npz` 渲染, 并把同帧数值
  `publish_trace_live()` 到 `zmax_data/ss_live/trace_live.json`。位姿=录制值, 不是 IK/规划解。
- episode 生产者 `tools/gen_ss_metaworld_episode.py::run_episode`: 每步
  ① `FeedforwardAccelerator.forward` 蒸馏 MLP (547K, `models/ss_left_brain.npz`) 出 4D 加速度级动作
  (插入段强制 `analytic_forward` 解析律) ② `ActionModulator.decide` 八阶段判定+限速+夹爪
  ③ `TaskL45.l4_check` Δ守卫/向下限幅 ④ MuJoCo 步进 (`ctrl_dt` 0.0125) ⇒ 末端真值。
- 直接看 `npz['meta']`: `seed/steps/success/stage_final/analytic` 就能说清这集是谁产生的、成功与否。
- `n_moveit` (MoveIt/Orin xCoreSDK 桥) 不在这个环里: `PURE=False` 只走数据面直通。
  仿真里 success=true 是物理判真, 不是真机动作, 也不是规划器输出的轨迹。
- 被追问"物理解算输入是什么"时: **只吃 4 维动作** (3 轴笛卡尔增量→mocap 位移 + 夹爪 ±1),
  8 阶段不进物理, 只给 target/限速/夹爪时序; 换算与 clip 细节见
  `metaworld-closed-loop-contracts.md` 末节「物理引擎每步到底吃什么」。

## 10. 归属不许编连接: 没连线 ⇒ Rx 空着, Tx 只写真生产者
- Rx 列用户会逐行对画布。闭环内部算出来的量 (帧/总帧/时间_s/估计值_len/估计误差_mm/估计抖动/
  残差/残差系统偏差_mm/占比_pct/接触概率/净接触) 在工程图上**没有任何一条线进来** ⇒ `rx_of()` 返回 `—`。
  写一个看着像连接的来源 (例如「L2 状态空间引擎 (无话题)」) 等于编连接, 会被当场要求删。
- 反向也成立: 不许用 catch-all 前缀规则把这些量糊给某节点 (实测 `sstrace.*` 保障把残差/帧/估计
  全判成「Z-MAX 引擎」)。口径: 能指到真正算它的 L2 节点就指 (估计→`ssest` 自适应状态估计器 ·
  残差/净接触→`ssinnov` 状态校正器); 纯写盘簿记量指进程 (帧/总帧/时间_s→`ss_dreamview` 3D 回放)。
- 自查: 拿 live 快照的字段列表执行一遍 `tx_of/rx_of`, 把所有非 `—` 的 Rx 逐条回画布找线;
  归属串里出现 `(无话题)` / `(无节点)` 这类后缀就是编造痕迹。
- 同一口径适用于 `ss.node.*` 端口: 只是没人声明信号时, 才用端口名占一行 (见 §3), 不借此编来源。

## 11. 删一条工程连线的完整落地顺序 (少一步就有旧线残留)

用户说"这条线不该有, 删掉"时按这个顺序做, 每步都要能回读证据:

1. **备份三处**: 画布 JSON → `data/database/zmax/sources/canvas/_archive/<name>_before_<why>_<ts>.json`;
   `config/platform/dds_topic_types.json` 与 `zmax_engineering.db` → scratch 目录。
2. **改画布唯一依据** `data/database/zmax/sources/canvas/state_space_obs.json` 的 `links` (按 link id 删)。
   ⚠️ `flows/state_space_obs.json` 与根目录同名文件是软链/存档, 只有 `sources/canvas/` 这份在役;
   删完 `grep <link_id>` 只应命中 `_archive/`。
3. **改话题注册表** `config/platform/dds_topic_types.json`: 删 `nodes.<id>.ins.<port>`, 并从对端
   `nodes.<src>.outs.<port>.consumers` 去掉该节点。`config/` 是指向 `data/database/zmax/sources/config/`
   的**软链**(同 inode), 一处改即两处生效, 不要以为要改两份。
4. **重落 `mw_*` 表** `./gui-venv311/bin/python tools/mw_db.py sync`。
   🔴 坑: `engineering_db.py build` **不会**重建 `mw_link/mw_port` (实测删线后 build 完 `mw_link` 还是旧条数,
   旧 edge 仍在) —— 画布→库的写入口只有 `mw_db.py sync` (或 `flows.save_canvas` 内部那次 sync)。回读断言:
   `select count(*) from mw_link where link_id='<id>'` = 0 且 `mw_port` 里无该 `in` 口。
5. **重建数据空间总线库** `PYTHONPATH=src python -c "from lerobot.dataspace import busdb; db=busdb.build(); busdb.save(db)"`。
   `busdb.json` 由工程库派生, 不重建就仍带旧话题 ⇒ 数据空间 Trace 里那条线/那个端口行照旧存在。
6. **判据**: `verify_mw_db.py`(含"改库→话题名即变"的唯一依据判据) · `engineering_db.py check` ·
   `verify_trace_cols / verify_trace_sync / verify_signal_panel / verify_global_source` · `ci/integrity_check.py`。
   端到端证据两句话就够: 该话题在 Trace 里 **0 行**; 被删端口从 Rx 里消失 (例如 `ssff.out2` 的 Rx
   只剩 `动作调制器`)。
7. `data/` 与 `config/` 都在 `.gitignore` 里 ⇒ 这步通常**没有 git 提交**, 别拿"git status 干净"判定没生效;
   证据看盘上回读与判据输出。

## 12. 判据自身的两个去抖写法

- **缓存窗口一致性**: 不要 `a=f(); sleep(0.1); b=f()` —— 0.1s 睡眠 + 0.25s TTL 会偶发跨窗口边界造成假失败。
  写法: 先强制失效 (`f._CACHE.update(t=0.0, data=None)`) 再连读两拍比对 (测的是"窗口内一致", 不掺运气)。
- **NaN 字段**: `a[k] == b[k]` 恒 False ⇒ 一律 `repr()` 比。

## 13. Tx/Rx/Layer 必须是**同一个工程节点**算出来的 (单一解释链)

三条解析路径各查各的 ⇒ 同一行自相矛盾。实测: `tx_of` 走字段规则给「Z-MAX 引擎」(节点层 L4),
`layer_of` 走前缀属主给 L2 —— 用户一眼就能看出"Tx 是 L4 的节点, 层却写 L2"。

- **定式**: `layer_of(key)` 先取 `tx_of(key)` 的第一段 → 查「节点显示名 → 层」表 (由工程库 + `naming` 生成);
  取不到才走端口/规则保障。层永远是从 Tx 那个节点读出来的, 不另起一条判断。
- **Tx/Rx 只许工程节点名**。进程名 (`.py`)、服务名、总线标签 (「🥽 AR/AOI 信号总线」)、
  「本机真值流 (JSON)」这类字符串一律不许进这两列; 没有节点就 `—`。出处说明只进 tooltip 的「来源:」行
  (`attribution.source_of()`), 不占列。
- **显示名词表 = `naming.unique_map`** (实测 75 节点 ↔ 75 唯一名)。判据要显式断言**单射**: 重名会让
  Tx 指向不明 (两个节点同名 ⇒ 用户无法对账)。8 个 SK 节点在工程库里是 `meta` 容器, 但信号层按 L2。
- **真值流话题没有画布端口** (`zmax/ss_state` / `ss_engine` / `ss_torque` / `ss_skill(_phys)` /
  `tcp_pose` / `yolo_det` / `ar_aoi` …) ⇒ 维护一张显式 `PREFIX_OWNER` 前缀 → `node_id` 表
  (sstrace→状态估计 L2 · sseng→流形引擎 L4 · gravity→标定诊断测量 L4 · yolo→YOLO 目标检测 L2 …)。
  两条细则: ①**字段级规则优先于前缀属主** (`sstrace.前馈速度` 归前馈加速器, 不归前缀属主);
  ②前缀映射为 `None` = 明确不是总线话题 (数据空间探针自己的快照) ⇒ 层 SYS ⇒ 不进 Trace。
- 判据 `tools/verify_layer_node_strict.py` 八项: 名字单射 · attribution 节点表 == 工程库+naming ·
  Layer 全是 **L2** (口径已从 L2~L5 收到只留 L2, 见 §17) · 每个话题有 L2 属主 · Tx 全 L2 节点 ·
  Rx 是 L2 节点或 `—` · Tx/Rx 无可视化层/meta 节点 · 数据空间页三张表全 L2。

## 14. 统一信号库 `signals.db`: 「同源快照」升级成「同一个数据库」

`live_signals.topics()` 同源只保证两窗口调**同一个函数**; 底下仍是多个 JSON 被各自轮询 ——
用户要"统一数据库"时必须真的落一个库。

- 结构 (`src/lerobot/dataspace/signal_store.py`): `topics` / `signals(topic,name,value)` / `meta.updated`; 写是
  **单事务整份替换** (读到的永远是一拍, 不会半新半旧); 读要求 `updated` 新鲜 <3s, 否则回落文件直读**并打印一行**
  (不静默降级); `ZMAX_SIGNAL_DB_OFF=1` 强制走旧路排障。
- 写库方 = 独立守护 (`tools/signal_store_daemon.py`, 2Hz, pidfile 单实例, 读 `live_signals.topics_from_files()`);
  启动脚本起控制台前确保它在跑。
- **单源证明定式** (只动库, 看两个窗口同时变):
  1) `SIGSTOP` 落库守护 (否则 0.5s 后它把值写回);
  2) 改库里既有信号的一行值;
  3) **起一个线程每 0.4s 刷新 `meta.updated`** —— 守护停了库会"过期" ⇒ 读取方回落文件 ⇒ 探针读到旧值, 白测;
  4) 刷新两个窗口 (树要 `_update_tree_values()`, 表要 `_fill_trace_fixed(force=True)`), 断言两边同值;
  5) `SIGCONT` 后断言值回到真值 (证明日常数据仍来自源, 不是我们把库改死的)。
- 判据: 库新鲜 · `live_signals` 读到的 == 库逐条 (允许 ≤2% 条数差: 可选字段随帧出现/消失) ·
  改库两端同值 · 恢复真值 · 降级路径有告警。

## 15. 每行重查全表 = 表格刷新慢的隐形大坑

症状: Trace 整表刷新 4.6s (阈值 0.25s), 界面像卡死。
`cProfile` 一眼定位: `db.node_rows()` 被调 **1936 次** (每行一次 `layer_of` → `_node_layer` → 全表重查 75 行),
累计 5.6s —— 单次 3ms 不显眼, 乘上行数就是秒级。

- 修法: 按**源文件 (mtime_ns, size)** 做 `lru_cache` 键 —— 工程库重建后键自动变, 不会读到旧配置;
  返回 dict 副本, 调用方改了不污染缓存。实测 4.6s → **0.12s**。
- 通则: 任何"每行都调一次"的归属/层/名字解析都必须带缓存; 先 `cProfile` 确认热点再改, 别凭感觉优化。

## 16. 判据不能把 bug 写成期望

- 曾有判据断言「gravity 的 Tx 是进程(非节点)」—— 它把假节点固化成契约, 修对之后反而判红,
  下一个人会照着它把 bug 改回去。**判据的期望值必须来自唯一依据 (工程库/画布), 不许把"当前实现的样子"抄成断言。**
- 别硬编码行数/节点数 (89 节点 → 画布加到 90 就假红): 断言"不少于基线"或直接从唯一依据取期望值。
- 期望词表变了要同步改判据 (SK 阶段名从「① 接近 · SK01」统一成「接近」), 并在判据注释里写明口径来自哪里。

## 17. 「只留 L2」收口: 闸门只在 attribution 写一次, 顺序错了会静默清空

用户口径从 "L2~L5" 进一步收到 **"只留 L2"** (数据空间 topic、信号分析 signal、Tx、Rx 四样都只许 L2)。

### 17.1 单一入口 (面板里不许再各写判断)
```python
attribution:  l2_names() · names_l2(name) · tx_l2(key) · rx_l2(key) · layer_l2(key)
              topic_in_l2(key) · show_in_l2(key)     # 面板/导出只有这几个入口
```
- 规则节点不是 L2、但它的话题有 L2 前缀属主 ⇒ **用属主**。实测 `sstrace.末端_*` 不带字段规则时
  落到前缀属主 L2 状态估计器; 带字段规则 (`前馈速度`) 时归前馈加速器 — 两者都是 L2, 不矛盾。
  只按 "Tx 节点层" 过滤会把这一类整族清掉 (现象: 所有 `sstrace.*` 行消失)。
- 非 L2 又无 L2 属主 ⇒ `—` / 不显示。**不要为留在窗口里而降级成 SYS 或糊给别的层。**

### 17.2 闸门顺序与豁免 (踩过的三个)
1. **topic 级闸不能套到工程话题上**: 先判 `if key 是 live 真值流话题 → 查 l2 属主`, 否则 `db / mw_topic`
   的 layer 字段 (可能空/L4) 会把正常 L2 端口全判掉。
2. **阶段话题 (skill / skillphys) 的属主**是逐行的 (接近/对位/…), 必须在**行级**判 L2,
   不能在 topic 级统一处理。
3. **SK 归一化必须锚到结尾**: `SK0[1-8]$`。实测「⚖ 物理约束 · 惯性/质量率闸 (SK01-08)」名字里带
   `SK01-08`, 用无锚点正则就被当成 "SK 阶段节点 ⇒ L2" 漏进 Rx —— 用户一眼看出来
   (「Rx 怎么还有物理约束呢? 也没有这个节点啊」)。同理可视化层「前馈直方图」是 meta, 不得出现。

### 17.3 组件层配合
- `canoe_graphic._make_item()` 在非 L2 时返回 `None` ⇒ **所有 `addChild` 必须包一层安全挂载**
  (取到 None 就跳过, 不抛异常), 否则一旦过滤掉某层整个窗口崩在刷新线程里。
- 数据空间页 `dds_space` 四张表 (话题/节点/报文/告警) 同一口径过滤; 实测话题 316→97 · 节点 75→29 · 报文 45。
- Trace 与信号分析实测: Trace 约 655 行、层集合 `{L2}`; 信号分析约 437 行、层集合 `{L2}`。

### 17.4 判据侧必须跟着改 (否则测的是旧口径)
- `verify_trace_cols` 的表头过滤原来按 L4 → 窗口只剩 L2 时必然 0 行假红: 过滤条件换成 L2。
- `verify_signal_panel` 里 `_at` 的 import 若写在函数内会被同名遮蔽 ⇒ 放回 import 区 (30/30)。
- 新增项用**跑真界面**取证: 数据空间四表逐表 `非 L2 == 0`; Tx/Rx 断言 `l2_names()` 不含
  「物理约束」「前馈直方图」而含「接近」; 改库一行两端同值 (见 §14)。

### 17.5 改完为什么用户仍看到旧内容
窗口跑的是启动时的旧代码 (`studio.py` 早于改动) ⇒ 只给命令, 不要自己重启:
`bash /home/ubuntu/zmax/tools/gui/launch_studio.sh`。

