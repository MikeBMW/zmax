# 画布接线契约 · 端口/登记顺序 + 执行链重连实录 (2026-09-26)

SKILL.md 的"三类致命坑"之外的补丁，全部来自本会话实测（连踩两次以上才算契约）。

## 1. 端口名不要硬编码 `in1` / `out1`
各节点的端口名**不一致**，照抄模板就踩：
- `ssworld`(物理世界) **没有 `out1`** → 用 `swworld` 的端口会断言失败
- `swworld`(Z-MAX 引擎) **只有 `in2`**，没有 `in1`
- `ssdec` 等 3 个节点曾是**字典格式**端口（已归一）

做法（写进构图脚本）：
```python
def p0(nid, key, dflt):              # 取节点真实第一个可用端口, 兼容字典格式
    v = by[nid].get(key) or [dflt]
    x = v[0]
    return x if isinstance(x, str) else str(x.get("id", dflt))
# 断言也用真实端口:
ins  = [x if isinstance(x, str) else str(x.get("id")) for x in (by[t].get("inputs") or [])]
outs = [x if isinstance(x, str) else str(x.get("id")) for x in (by[f].get("outputs") or [])]
assert t_port in ins,  "%s 无入端口 %s (有 %s)" % (t, t_port, ins)
assert f_port in outs, "%s 无出端口 %s (有 %s)" % (f, f_port, outs)
```

## 2. 新节点要先登记进查找表，再断言它自己的端口
否则 `KeyError: 'n_realscene'`（校验新节点时它还没进 `by`）。正确顺序：
```python
nodes.append(node); by[NID] = node      # 先登记
... 端口/反向线/重复连线断言 ...
links.extend(add)                       # 再接线
```

## 3. 位置搜索方向 = 连线方向
给新节点找空位时，搜索方向要和它的连线方向一致，否则必被"反向线"断言拦住：
- 新节点在**上游右侧**（`f → new`）→ 从 `f.x + f.w + 60` **向右**搜空位
- 新节点在**下游左侧**（`new → t`）→ 向左搜，且 `x < t.x - 余量`
本会话实录：先放在 `ssdata` 左边 → `AssertionError: 反向线 ssdata→n_realscene`。

## 4. 执行链重连实录（"所有原子技能都要进 MoveIt" 这类需求）
需求原文：「量产执行的通路是先 安全执行边界，再到 L2 原子技能，最后 MoveIt 执行给机器人；
原子技能也可以被高层 L4 直接调用；修改画布连接，注意 UI，保证清晰连线，不要有交叉」
```
① 先侦察: 目标节点的**真实**入/出线 + 各相关节点坐标（别假设）
   本次现状: 8 个原子技能直连执行器(绕过 MoveIt) · MoveIt 只接安全边界一条
② 删绕过: (sssk1..8 → ssact) · (sslimit → n_moveit) · (ssdec → ssact)  共 10 条
③ 加汇聚: 8 技能 → MoveIt(in1/in2 分流) · 7 条 安全边界 → 原子技能 · FlowMatching → MoveIt
④ 消反向: 回折的节点要连整条链一起挪 —— 本次把 动作调制器(8900) → 安全执行边界(9250) →
   原子技能阶梯(9889..) 整体左移，否则 sslimit(13666) → sssk2(10219) 是右→左反向线
⑤ 降交叉: MoveIt 从阶梯**右上**挪到**末端右下**(12819,5926) → 扇入变嵌套式, 全图交叉 1175→1136
⑥ 验收数字: 85 节点/167 连线 · 孤立 0 · MoveIt 入线 9(8 技能+FlowMatching) 出线 1 · 渲染 85/166
```

## 5. 画布之外的连带风险：改节点接线会打到 GUI 导入
在 `node_logic.py` 里为新节点加 `_EXTERNAL_LOC` 条目时用了**不存在的常量 `_REPO`**
→ `NameError` 阻塞整个 GUI 导入 → **控制台起不来**（`ast.parse` 完全看不出）。
修法：对照既有条目（如 `_YOLO_DIR`）先 grep 确认常量存在；路径用
`os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", ...)`；
行号要与唯一依据码一致（`grep -n "class X"` 复核）。改完**重启控制台并确认 `Traceback=0`**。

## 6. 一次性验证脚本（都留在 tools/）
```
tools/verify_canvas_render.py      离屏真加载 → node items / link items 双看
tools/canvas_level_audit.py        档位级真接 / 无执行注册 / 真缺口
tools/rewire_cross_check.py        交叉前/后 + **每条线贡献**(归因到具体连线)
tools/canvas_rewire_exec_chain.py  执行链重连(六断言+备份+还原命令) —— 可当重连模板抄
tools/canvas_add_realscene_node.py 加单节点(端口自动取真实值 + 位置搜索方向正确)
tools/canvas_add_seg_dsvl_link.py  加**单条线**(幂等+端口存在+前向+回读: 既有线逐条不变)
tools/verify_seg_into_fusion.py    消费链: 掩膜3D真进下游 + 零回退 + 开闸行为 (11 条)
tools/verify_seg_dsvl_canvas_link.py 渲染链: 按节点名在 SimLinkItem 里找那条线 (5 条)
```
两条已挂进 `tools/run_gui_verifiers.sh` (seg_to_fusion / seg_dsvl_link)。

## 7. 「节点输出悬着」的判定 + 接法 (2026-10-14 SAM3 → 融合定位建图 / DeepSeek-VL)

老倪这类直觉往往是对的, 但**在画布上看不出来** (线可能早就画着)。必须三步, 缺一步就答错:

① **它算出来的东西存在哪**: grep 缓存写点 —— 例 `🧩 分割节点` 把"掩膜级 3D"写进 `_YOLO_CACHE['mask3d']`。
② **谁读它**: 若全仓只有 `tools/` 下的取证脚本读 ⇒ **就是"悬着"**, 与"线画了没画"无关。
   (`search_files 'mask3d|seg_masks'` 一次就能把消费者列全。)
③ **渲染级确认**: 按**节点名**在 `SimLinkItem` 里找 (别按 id — `load_flow_file` 会重编)。

接法 (两层, **不挪能力节点所在层**; 上层只给意图/条件, 执行由下层收口):
- **数据面**: 在**下游节点逻辑**里读该缓存。本案例: `📡 融合定位建图`(`node_ss_s1`) 加"掩膜 3D → 独立观测入
  `_SS_STATE` + 与框法交叉校验(偏差 mm)"; 要改写状态向量必须**显式开闸**(`ZMAX_FUSION_SEG=1`),
  默认档一个字段不改 —— 守住"未证明提升不进默认档"。
- **意图面 (当大模型输入选项)**: 在**上层节点的上下文构造函数**里加一路 (本案例 `_vlm_ctx()` 往 ctx 加 `seg`),
  这样"作为大模型的一个输入选项"是**真被读**的, 而不只是画一条线。新鲜度闸: 只用同帧 (≤3s) 的结果,
  过期一律当没有 —— 拿上一帧掩膜套这一帧 = 假数据。
- 跨层接线优先找**空闲输入口**: `n_dsvl` 声明 in1..in4, 已占 in1/2/3 ⇒ 新线落 **in4**, 不动任何既有线。
  跨行前向判据 `f.x+f.w <= t.x` 要先算 (例 ss_seg 右缘 1776 ≤ n_dsvl 左缘 1995 ✓)。

坑:
- `flows.load_canvas()` 返回 **(data, errors) 二元组**(validate 默认 True) ⇒ 直接 `d['nodes']` 会 `TypeError`。
- 改画布**前先 `studio_ctl.sh stop`** (GUI 退出/另存为会把内存画布写回唯一依据, 覆盖你的改动), 写完再 `restart --force`;
  控制台日志里 `已加载工作流: ... (89节点 185连线)` 是"新画布真读进来了"的唯一凭证。

## 全图重排 — 用户说"接线要像左上→右下"时怎么做 (2026-10-15 实测定式)

触发语: 「UI 重新排布一下」「某某应该在某某的右边」「接线符合从左上到右下角的趋势」。这不是“手动推几个节点”, 是全图重排:

1. **y 不动**: 15 条背景行带 (bg/row_bg) 的 y 序天然是流水线序 (数据源→大模型层→…→执行层→验证层→可视化层),
   它就是"左上→右下"的主干; 行带矩形只按新节点范围重算。
2. **带内分轨**: 同带节点按 x 升序摆进 `rows_cap = (h − 2*PAD)//ROW_OFF + 1` 条轨道 (294→2 行 / 418→3 行 / 790→6 行)。
   **行数不限会把节点顶穿到下一条带** ⇒ 与下带节点重叠 (实测 2 对)。
3. **x 用像素级最长路径 (Sugiyama)**: `x(n) = max(x(父)+w(父)+gap)`, 带内紧排 ⇄ 最长路径反复迭代到稳定。
   好处: **每一条非环边天然指右** (不必按层号对列 —— 节点宽度不一, 对列必错), 且全图自动变窄 (实测 18819→10780)。
4. **环边 (反馈/闭环) 不参与分层**: 收尾只做"向右推目标 (若其后继都更右)"的贪心; 剩下的反向线**逐条打印**源→靶+Δy。
   判据用"数量至少减半 + 向下的过半": 纯跨层回环 (如 `swds→swintact` 渲染回流) 语义上必是反向, 不能硬判。
5. 🔴 **反边检测必须确定序遍历**: 对 `set` 直接迭代受 str 哈希随机化影响 (PYTHONHASHSEED) ⇒ 同一画布两次跑出不同布局
   (实测反边 13/6/3 三种结果, 判据时好时坏)。DFS 起点一律 `sorted(ids)`。
6. **不达标拒写盘**的判据: 零重叠 · 非环边全前向 · 反向至少减半 · 向下的过半 · 用户点名的那对关系成立。
7. **验收分两层**: ① JSON 级 (`tools/canvas_layout_flow.py`, 默认干跑, `--apply` 才落盘);
   ② **界面级** (`tools/probe_canvas_flow_ui.py` 真加载画布后读**界面几何**) —— GUI 会**重编节点 id**, 只能**按名字**对位;
   且 `open_state_space()` 额外跑 `_relayout_row_gaps` (gap 56 < 步长 60 ⇒ 幂等, 不会打乱顺序)。
   证据图用离屏真渲染 (`tools/shot_canvas_flow.py`, 不靠截屏): 全图 + 用户点名的局部。
8. 实测口径 (2026-10-15): 前向 178→**187**/190 (93.7%→98.4%) · 反向 12→**3** (全向下) · 交叉 1363→1357 ·
   ⚡前馈加速器 (6950,4438) → 🧭动作调制器 (7290,4872) —— 右且下。
9. 落盘后照旧顺序收尾: `ss_task_bind --activate` → `project_archive space-save` → `engineering_db build` → 两 `--check` → 重启控制台;
   还原命令要打给用户 (`flows/_archive/state_space_obs_before_flow_layout_<ts>.json`)。

## 单节点挪位 + “用户点名要的反馈接线” (2026-10-15 实测)

触发语: 「某某节点是用于反馈物理状态的, 位置可以放到最右侧」「它的输出也要接到某某节点, 你来连线即可,
节点位置可以不动」。这类请求=**只动 1 个节点的 x + 加 1 条线**, 四步定式:

1. **目标列用真实极值算, 不要拍脑袋**: “最右侧” = 全图功能节点的 `max(x)` 那一列 (不是自己行带的右端 ——
   实测节点已在行带最右 (9670) 但全图最右列是 10450, 用户看的就是后者)。同理“最上面/最左”也取全图极值。
2. 🔴 **同步延长它所在行带的矩形**: `bg/row_bg` 的 `x/w` 是**手存的固定值**, 把节点挪出带外它不会跟着长 ⇒
   界面看着节点“掉出带外”。写盘前算 `need_r = n.x + n.w + 40`, 带上矩形的右缘不够就补。
3. 🔴 **目标节点入端口占满时先加口, 不要抢既有口**: 先断言端口表是**字符串列表**(不是历史遗留的字典格式),
   再 `inputs = list(ins) + ['in5']`。抢口会把上游语义改掉, 用户不会发现直到行为变了。
4. **这条线必是反向时, 如实报**: “右下 → 左上”的回灌线物理上就不可能前向 —— 接上、label 写闭环反馈、
   交付时直说它是反向的反馈线, 并把反向线**逐条列出**(源→靶→Δy) + 报前向率 (实测 187/191 = 97.9% ≥ 97%)。
   不要把它藏进“全部前向”的话里, 也不要把目标节点挪位去凑方向 (用户明确说“节点位置可以不动”)。

判据工具形态 (单节点改动也写成脚本, `tools/canvas_innov_right_feedback.py` 可当模板):
干跑/`--apply` 双模式 + 备份到 `flows/_archive/<事由>_<ts>.json` + 打印还原命令 + 落盘后**回读**
(节点数/连线数/目标 x/目标节点端口表) + `assert 节点数不变 and 连线数只增这一条`。

界面几何探针的具体取法 (配合 SKILL.md「load_flow_file 重编 id」):
```python
m = SM.SimulinkModule(); m.open_state_space(); ...
for k, it in (getattr(m, "_items", {}) or {}).items():
    nm = str((getattr(it, "node", None) or {}).get("name") or k)   # 只能按**名字**对位
    p, br = it.pos(), it.boundingRect()                            # 场景坐标 == 唯一依据 x/y
```
重叠判定要**排除 bg/row_bg**并用**唯一依据 w/h** (界面 boundingRect 会带上选中/光晕余量, 直接比会报一堆假重叠)。


