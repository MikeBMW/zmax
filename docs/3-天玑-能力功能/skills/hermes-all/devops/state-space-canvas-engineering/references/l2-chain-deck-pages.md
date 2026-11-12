# L2 链路 / L3-L5 层页 (解决方案 PPT) 的页序 / 重出 / 验收

方案册里那 N 页「L2 链路 k/N · 节点名 · id」和那批「认知层 · 第 k / 18 位」都是**构建期从画布真源烧出来的**,
所以"调页序"和"增删节点"都会牵动它。改错了用户只看到一条抱怨:「顺序不对 / 这页怎么还在」。

## 真源分工

| 东西 | 真源 | 说明 |
|---|---|---|
| 节点集合 / 名称 / 连线 | 画布真源 `flows/state_space_obs.json` | `l2_nodes()` 用 `l2_wiring` 的 L2 带口径取节点 |
| L2 页序 | `tools/l2_chain_pages.py::chain_order()` | 从「L2 下游只剩反馈边」的末端节点出发, 沿 links **反向 BFS**; 末端编号 1, 越上游号越大 |
| L2 手工锚点 | 同文件 `PIN_POS = {id: pos}` | 自动序不动, 只把指定节点搬到 1-based 目标位, **其余相对顺序不变** |
| L3/L4/L5 页序 | `tools/l345_pages.py::_ordered(lv, ids, links)` = `chain_order()` + `PIN_HEAD` | 头部几位由 `PIN_HEAD = {"L4": (...)}` 有序元组钉死, 其余按拓扑; **层首页 `layer_intro_page()` 与逐节点页 `add_layers()` 必须都走 `_ordered()`** |
| 每页正文 | 节点实现模块 (`middleware/nodes/_index.NODE_MODULES`) + 画布连线 | 无中间件壳的节点如实标「PURE 直通」+ 实现文件路径 |
| 节拍页 | `tools/l2_uph_measure.py` 现算 | 计划/实测两口径 + 收口路径 |

## 用户口令 → 动作 (别做多)

- 「X 放到 L2 链路 20/31，其它节点顺延」= **只在 `PIN_POS` 加一条** `"<id>": 20`, 带一行注释写清是谁的要求。
  锚点按 pos 升序逐个 pop→insert, 插入即把后面整体推一位 ⇒ **天然就是"顺延"**。
- 「X 放到 <某层> 第 k / N 位」(L3/L4/L5 层页) = 在 `PIN_HEAD` 里排好前几位, 用有序元组表达位次:
  ```python
  PIN_HEAD = {"L4": ("ss_mani_eng",    # 1 流形引擎
                     "ssintact_dec",   # 2 INTACT 意图解码器
                     "ss_lora_l4")}    # 3 INTACT LoRA 微调

  def _ordered(lv, ids, links):        # 层首页 + 逐节点页唯一入口
      order, _, _ = LC.chain_order(set(ids), links)
      pinned = [x for x in (PIN_HEAD.get(lv) or ()) if x in order]
      return pinned + [x for x in order if x not in pinned] if pinned else order
  ```
  用户会一位一位往上加(第 1 → 第 2 → 第 3 → 第 4..7), 元组按位次书写、每次只加一条, 其余相对顺序天然不动。
  🔴 **只在 `add_layers()` 里改 `order` 而不改 `layer_intro_page()` = 层首页表格还是旧首位**: 两处原本各调一次
  `chain_order()`, 已实测过「逐页对了、全景页表格第一行还是别人」。所以必须抽 `_ordered()` 两处共用, 再重出。
  只改册子不改生成器 = 下次重出又回去。
  验收(每次重出都跑): 页数 91 不变 · 段内位次 == 1..N 连续 · 前 N 位名称逐条比对 · **层首页表格首行 == PIN_HEAD[0]**。
- **不要**为了顺延去改其它锚点的 pos, 也别去动 `chain_order()` 的算法或画布坐标 —— 用户前几轮钉好的位置会被一起打乱。

## 歧义先判: 画布位次 还是 册子页位次

用户说「X 放到 Y 层第 1 位」时, **先看上一句他盯的是什么**:
刚说完「打开 PPT / 重启 ppt」⇒ 指的是方案册页序。此时去改画布坐标 = 白做且被明确制止(「没让你改画布」)。
画布坐标、册子页序是两套东西; 已经改错就立刻用备份还原并在回复里说明已还原。

## 改完先跑一次只读核对再重出 PPT

```bash
./gui-venv311/bin/python - <<'PY'
import sys; sys.path.insert(0,'tools'); sys.path.insert(0,'src')
import l2_chain_pages as L
nodes,l2,links = L.l2_nodes(); order,_,_ = L.chain_order(l2,links)
print(len(order)); [print(i, n, nodes[n]['name']) for i,n in enumerate(order,1) if 18<=i<=24]
PY
```

## 不等重出: 直接改现有册子的页序 + 位次重编号

用户要"现在就看到"时, 重出整个册子太慢、且可能冲掉别的改动。可以只动那一段页:

1. 关掉开着这份 PPT 的 LibreOffice(否则它退出时写回内存版)。
2. 备份 `cp -p <deck> /tmp/ppt_backup_$(date +%H%M%S).pptx`。
3. 段定位: 标题正则 `(认知层\s*·\s*第\s*)(\d+)(\s*/\s*18\s*位)`, 首末命中页即整段。
4. 移动: `pr.slides._sldIdLst` 上 `remove(el)` → `insert(s0, el)`(版式/图片整体跟着走)。
5. 重编号: 逐页把位次数字改成 1..N。**必须改 paragraph 的 runs**(`run.text`), 直接写 `shape.text_frame.text` 会丢格式。
6. 自检三条(缺一条就是改坏了): 页数不变 · 段内位次 == 1..N 连续 · 段内**页面内容集合不变**(按名称行比, 不按标题比 —— 标题里的位次本来就变了)。
7. 同步改生成器(见上一节), 否则下次重出回到原位。
8. 重开册子并确认窗口存在: `soffice --impress <deck>` → `wmctrl -l | grep -i impress`。

现成工具: `tools/ppt_move_mani_first.py`(dry-run 默认, `--apply` 才写盘), 自带上述三条自检。

## 构建入口写的不是用户打开的那份 (两份副本会分叉)

`tools/build_solution_deck.py` 顶部的 `SRC_DECK` / `NEW_DECK` 才是真输出路径: `NEW_DECK` 常指向
`docs/1-天枢-产品边界/deliverables/2-机器人方案/`, 而用户窗口里开的那份常在 `zmax_data/deliverables/<日期>/` ——
两份是**独立文件**(md5 不同, 不是软链)。

- 重出前先 `grep -n "NEW_DECK\s*=\|SRC_DECK\s*=" tools/build_solution_deck.py`, 核对"它写哪儿"与"你刚编辑的是哪儿"。
- 重出后 `md5sum` 两份; 不一致就 `cp -f` 覆盖到用户那份, 回复里给出两边相同的 md5 与各自绝对路径。
- 构建脚本打印的 `58 PASS / 0 FAIL` 只证明它写进了 `NEW_DECK`, **不证明用户那份变了**。
- 重出前确认生成器已带同一条前置规则, 否则整册重出会把手改过的页序冲回原位。

## 用结构指纹判断一页是哪版生成器烧的

看不了渲染图时, 挑可数的结构量当版本指纹:

| 指纹 | 旧版 | 新版(三段正交) |
|---|---|---|
| 节点页 connector 数 | = 输入条数 + 输出条数 | = 3 × (输入 + 输出) |
| 中心节点框高 | 1.16 in | 1.30 in |

指纹显示旧版、而生成器源码明明已改 ⇒ **先怀疑验的不是构建真正写的那份文件**, 再怀疑 `__pycache__`:
`inspect.getsource(LC.node_page)` 能确认新代码已在进程里, 单页直调 `node_page()` 数 connector 也能对上。

## 功能框图可读性 (用户会直接说"线画清晰、别罗列堆叠、每个节点别堆在一起")

`node_page()` 的输入/输出列 = 两列小框 + 中间节点框, 几条硬规则:

- **不要斜线扇入**: 一条"框缘 → 中心锚点"直连, 7 根线在 0.7 in 内交叉成刷子。改三段正交:
  水平出框 → 阶梯竖直 → 水平入中心框; 同侧竖线按 0.055 in 逐根错开(`xm = CX - 0.26 - step*(n-1-i)`), 否则全叠成一条。
- **框高与间距**: `pitch = min(0.52, band/n)`、`bh = min(0.34, pitch*0.78)`; 旧值 0.28 in 框高配 9.6pt 字 = 挤成一排。
- **独立锚点**: `spread = min(NH-0.12, max(0.30, 0.175*n))`, 相邻锚点 ≈12.6pt, 每根线各落一点。
- **名字别截太狠**: `_cut(name, 18)`; 13 字符会把语义截掉一半。
- **自检(程序化, 不靠眼睛)**: 同列框两两不重叠且最小间隙 ≥0.06 in; connector 数 == 3 × 条数。
- ⚠️ `node_page()` 被**基础层 30 页 + L3 5 + L4 18 + L5 11 共 ~64 页共用**, 改一处全册都动 ⇒ 验收抽查多层, 不只被点名那层。

## 坑

- 🔴 **按全文搜节点名会匹配到邻居页**: 别的节点页正文里会引用「流形引擎」这类名字, 于是 `NAME_KEY in 全文` 命中的是上一页,
  挪错一页用户立刻看出来。判据 = 用**名称行**(版面 `0.82,0.48` 的 21pt 大标题 = 第一个不匹配位次正则的文本行)匹配。
- 🔴 **母版层页的计数会陈旧**: 画布删/加节点后不重跑 `tools/build_layer_nodes.py`, 方案册的 L2 连线页仍印旧数,
  verifier 报「L2 连线页 · 内部连线 FAIL」而画布其实完全正确。判据 = `l2_wiring.counts()['l2_edges']` 与页上数字逐位比,
  别先去翻画布。
- 🔴 **页数 = 19 + N + 1(节拍页)**, N 随画布节点数变 (31 节点 ⇒ 51 页, 删 1 个 ⇒ 50 页)。
  任何判据/文档里写死页数都会在下次增删时假红; 用关系式 (`l2 页数 == len(l2_nodes)`) 断言。
- 🔴 **LibreOffice 开着时重建 = 用户看到旧版**: 文件被替换但窗口不会刷新 ⇒ 必须关窗 → 重出/改 → 再打开,
  并在交付话术里说清"已重新打开"。
- 页序只在**构建期**生效 (烧进页标题), 改 `PIN_POS`/前置规则后不重出 PPT 等于没改。
- 无中间件壳的节点在页上照实写 `PURE 直通` + 实现文件, 别为了好看改成"真算"—— 用户会拿这页当验收依据。
