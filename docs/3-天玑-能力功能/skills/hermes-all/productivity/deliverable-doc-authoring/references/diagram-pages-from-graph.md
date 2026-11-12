# 从 nodes+links 真源生成连线图页（层内拓扑 / 层外邻居）

适用：用户说「加一页 X 层的连线，以及跟 X 层有连接关系的节点」（画布、架构图、网络拓扑、调用关系图）。
铁律：**节点集合与每一条连线都来自真源的 `nodes` / `links`**，不改向、不合并、不手绘；页面上写不清的部分另起一页，不在一页里省。

## 1. 取集合：主层 + 邻接闭包

```python
d = json.load(open(CANVAS))                 # state_space_obs.json 等
N = {n['id']: n for n in d['nodes']}
main = [n for n in d['nodes'] if n['band'] == 'L2']          # 主层
edges_main = [(l['src'], l['dst']) for l in d['links'] if l['src'] in mids and l['dst'] in mids]
ext_nodes = {x for e in d['links'] for x in e if (x in mids) != (other in mids)}   # 与主层有边的层外节点
```

- 成员按真源的**分组带**（`bands` / `row_bg` 的 `y..y+h` 区间）取，不要用自己猜的 y 区间。
- 层外邻居按**层分组**上色；被连到的层外节点可能只在左列出现（单侧连），如实画箭头方向。
- 一页画不下时按语义拆两页：**层内连线** 一页、**跨层/层外邻居** 一页 —— 拆页比压字号好，字号低于 5.4pt 在投影上已经不可读。

## 2. z 序：先画线，后画框

python-pptx 按 `add_*` 调用顺序叠放，**没有 z 序属性可改**。所以：

```python
draw_wires(s, edges, pos)      # 先把所有 connector 加进去
for nid, (x, y, w, h) in pos.items():
    add_box(s, nid, x, y, w, h)   # 再画节点框 —— 线自动落到框下面
```

长线会穿过多行，压在框下就**不会盖住节点名**，不需要给每条线绕障。反之（先框后线）会出现一条价 0.75pt 的线横穿文字，肉眼很难看出但用户一眼就能看到。

## 3. 走位路由：带间沟 + 车道偏移

- 同带、相邻（列号差 1）→ 一条水平短线；其忶 → 三段折线（竖-横-竖）走**带间空隙**，不要穿行内部。
- 多条线走同一道沟时按索引给 `lane = gap_center + (i % k - (k-1)/2) * pitch`（pitch ≈ 0.035 in），否则几十条线叠成一条粗黑带。
- 每条折线的段都要单独 `add_connector(MSO_CONNECTOR.STRAIGHT, x1,y1,x2,y2)`（不能一笔画折线）；段数在页脚标出来，方便回核（如 65 条边 → 172 段 = 22 条直连 + 43×3 + 7×3）。
- 颜色按语义分：主层内一色；跨层下行实线一色、上行反馈虚线一色（`ln.dash_style = MSO_LINE_DASH_STYLE.DASH`）。

## 4. 端点断言：贴框边 **或** 与另一段端点成对

多段路由的中间接头落在带间沟里，**不在任何框边**；按「每个端点必须贴框」验会报一堆假失败（实测 22 条）。正确规则：

```python
pts = [p for seg in segments for p in (seg.p0, seg.p1)]
bad = [p for p in pts if not on_box_edge(p, tol=0.06) and not paired_with_another(p, pts)]
assert not bad          # 孤儿端点 = 真画漏了 / 坐标写错
```

`paired_with_another` 用网格取整（0.01 in）比 key，容差内算同一个接头。

## 5. 标题框必须先画

标题 / 副标题 / 页脚注的 textbox **在画任何内容之前** `add_textbox`。后加的话它排在最上层 —— 视觉上看不出，但：
① 按「第一个有文字的 shape」取页面标题（大纲导出、`pptx_read --outline`、自检脚本都这么取）会取到**带域标签**（「L3 层（3）」而不是「L2 层连线 · ...」）；
② 任何「首框就是标题」的回读都得错。标题形状多时给 `shape.name` 统一前缀（`TITLE_`）并按名取，不要靠顺序。

## 6. 计数单一来源：build 与 verify 共用 `counts()`

```python
def counts():
    ...            # 真源现算: l2_edges / l3_edges / l3_nodes / ext_nodes / ext_edges
```

- 页脚写「L2 内部连线 65 条 · L3↔L2 7 条」「层外节点 29 个 / 连线 53 条」，**数字来自 `counts()`**；
- verifier 也调 `counts()` 再断言这串在册里（同一函数 ⇒ 两边不会漂）；
- 页数断言、`check_deck_fit.py` 溢出为 0、`pdftoppm` 量墨比（密集图页 10~13% 正常；>20% 就拆页）。

## 7. 名称处理

- 名字逐字取 `n['name']`（含 emoji），生成器里不写简称。
- 真源里顺序不一定是流程顺序（画布按网格排，技能节点编号乱跳）。**可以按逻辑重排位置**（如 `SK01→SK08`），但必须在回复里向用户说明「顺序按流程重排，名称未改」——否则他会问为什么顺序变了。
