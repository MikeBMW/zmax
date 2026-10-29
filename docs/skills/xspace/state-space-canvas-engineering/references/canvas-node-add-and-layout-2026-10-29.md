# 画布加节点 + 连线整理的实测口径 (2026-10-29)

## 加一个能跑的节点 = 五件套，缺一件就不完整

1. **实现文件** `src/lerobot/engineering/nodes/<name>_impl.py`，函数 `run(ctx=None)`；
   `ctx["in1"] / ctx["in2"] …` 是上游来的值。失败一律 `{"ok": False, "err": ...}`，**不出空结果冒充成功**。
2. **源码落点** `library.py`：
   `_EXTERNAL_LOC["<id>"] = (os.path.join(os.path.dirname(os.path.abspath(__file__)), "<name>_impl.py"), <def run 的行号>, "def run")`
   行号写错 → GUI 右键「打开源代码」跳错位置；改完 impl 记得回来对齐。
3. **薄壳** `def node_<id>(ctx): from .<name>_impl import run as _r; return _r(ctx)`，
   再 `_reg("<id>", [别名…], "一句话职责 + 源码路径", node_<id>)`。
4. **话题类型** `tools/gen_topic_types.py` 的 `NODES` 字典：`"<id>": ("Stem", "中文名", {"out1": "Semantic"})`。
5. **画布节点** 写 `tools/canvas_add_<name>_node.py`，照 `canvas_add_moveit_node.py` 的模板：
   断言 id 唯一 / int 坐标 / 零重叠 / 端口存在 / 前向 / 无重复连线，最后走
   `flows.save_canvas(d, reason=...)`（原子写 + 自动备份 + **自动同步工程库**），不要 `json.dump` 直写。

## 踩过的坑

- **`gen_topic_types.py` 的 NODES 是手写白名单**：画布上任何一个功能节点 id 不在表里，生成器**整体拒绝生成**（报 `❌ 注册表缺节点: [...]`），不是跳过。
  2026-10-29 实测：`ssplan` 一直没登记 → 整张话题类型表停更。加新节点后先 `grep '"<id>"' tools/gen_topic_types.py` 确认。
- 新节点要连进已有节点时，若对方输入口已占满（如 `sssched` in1..in8），**给它加一个新口**（in9）并同时写 `_port_labels`，别复用别的口。
- `canvas_add_*` 脚本里 `by = {n["id"]: n}` 是在 append 之前建的 → 校验 `(新节点 → 下游)` 那条边会 KeyError，先把 `by[NID] = node` 补上。
- 画布写盘后必须回读：`flows.load_canvas()` 再看节点/连线数 + `tools/verify_canvas_render.py`（文件 95 → 渲染 95，连线 216/217 差 1 是既有去重行为，属正常）。

## 布局：只信实测，别信直觉

基线（79 功能节点 / 215 连线 / 15 行带）：交叉 1906 · 前向 209/215 · 重叠 0 · 均长 Δx 1831px。

试过并**否决**的三种全局重排：

| 做法 | 结果 | 结论 |
|---|---|---|
| 最长路分列 + 重心排序（Sugiyama 简化版） | 交叉 1906→2426，列数 32 | 机器重排不如手调斜阶梯 |
| 全局 340px 列网格吸附 | 1906→2041 | 破坏已调好的斜阶梯 |
| 带内 x/y 就近吸附（±60/±26px） | 只动 2 节点就出 1 处重叠 | 已经是对齐的，没得修 |
| 带内挪节点（爬山，判据 交叉↓+重叠0） | 可采纳 3 个，但会跨行带（ssfeat 从验证层搬去感知带） | 破坏语义分层，加「不许跨带」后 0 采纳 |

**唯一采纳的做法：行带整体平移**（`canvas_bandshift.py` 口径）
- 跨带连线占绝大多数，行带整体左右挪比节点级微调有效，且完全不动带内布局与连线拓扑。
- 硬约束（少一条就会把画布推飞）：交叉数严格下降 · 重叠 = 0 · 前向率不降 · **平均 Δx 涨幅 ≤ 2%** · 每带累计位移 ≤ 1400px。
- 实测结果：120px 步长两轮 + 60px 步长一轮 → 交叉 1906→**1814（-4.8%）**，均长 1831→**1814px**，前向 209/215 不变，重叠 0。
- 不加长度约束时：交叉能压到 1680（-11.9%），但均长涨到 2780px（+52%）—— 图看着更乱，属于「指标好看视觉更差」，必须否决。

## 「从左上到右下」的真相

14 个行带里有 5 个 x_min 比上一带更靠左，**这是对的**：L2 感知带（YOLO x≈640）必须承接左上角数据源（x≈240）的短边；
强行保证单调下行会把「数据源→YOLO」从 400px 拉到几千 px。取舍判据：**总连线长度优先于严格单调**。

## 两个「运动规划」不是同一个东西

- 画布 `n_moveit` = **MoveIt 关节空间规划**，位置在原子技能**之后**（技能→规划→执行器），对应 runtime 真执行链。
- 块流水线里的「运动规划」= **状态空间测地线块规划**（obs→潜空间→`compute_geodesic(H)`→ridge 解码→块[H,4]），与前馈 MLP **并列**、同在加权之前。
- 2026-10-29 按老倪定序新增 `n_geoplan`（🧭 测地线块规划, 实现 `nodes/geo_plan_impl.py`）承载后者：`ssobs→n_geoplan→sssched(in9)`，与前馈 `ssff→sssched` 同排并列、规划在右。
  **不要把 n_moveit 改线去凑图** —— 那会让画布与 runtime 不一致。

## 🔴 改完画布必须 space-save，否则下次开控制台就被总工程存档回滚

实测事故（2026-10-29）：加完 `n_geoplan` 后画布 95 节点/217 连线，重启控制台 → 回到 94/215，节点凭空消失。
根因不是写盘失败，是 **GUI 启动时自动「开总工程」** (`tools/project_archive.py space-open`，源 `data/database/zmax/zmax_space.proj`)
用存档里的旧画布**全量回填**，并先备份成 `_archive/state_space_obs_before_space_open_<ts>.json`。

正确顺序（缺一步就白干）：
1. 改画布（`flows.save_canvas`）
2. **`./gui-venv311/bin/python tools/project_archive.py space-save`** —— 必须看到 `· canvas   <N> 节点/<M> 连线` 与改动一致
3. 再重启 GUI，回读画布节点/连线数确认没被回滚

被回滚了怎么救：`_archive/state_space_obs_before_space_open_<ts>.json` 就是**被覆盖前的那份**（含你的改动），
`cp` 回真源 → `space-save` → 重启验证。别去重跑 canvas_add 脚本（会报「节点已存在」或重复连线）。

