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
行号要与真源码一致（`grep -n "class X"` 复核）。改完**重启控制台并确认 `Traceback=0`**。

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
- 改画布**前先 `studio_ctl.sh stop`** (GUI 退出/另存为会把内存画布写回真源, 覆盖你的改动), 写完再 `restart --force`;
  控制台日志里 `已加载工作流: ... (89节点 185连线)` 是"新画布真读进来了"的唯一凭证。
