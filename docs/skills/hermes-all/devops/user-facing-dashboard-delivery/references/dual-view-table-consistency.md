# 双视图一致性 + 表格面板落地做法

适用：一个界面里有**两个视图**展示**同一批信号**（如 CANoe 式的 Trace 与「信号分析」树），
用户要求「Tx/Rx 要同步」「固定行别跳」「数值也要一致」。

## 1. 归属下沉成一个模块

```
middleware/attribution.py          # 只此一份，两个视图都 import
  key_of(topic, field)  -> 归一后的信号键（含单位口径，保证两窗口键可比）
  layer_of(key)         -> L2/L3/L4/L5/SYS
  tx_of(key)            -> 发送方（真节点名；无节点则进程名 + 括号说明）
  rx_of(key)            -> 接收方/数据来源
  fmt_value(v, key)     -> 显示字符串（统一换算 + 有效数字）
  display_unit(key, u)  -> 显示单位
```

TX 取值顺序（有据才写，不可跳到下一档自行编名）：
1. 工程库/画布里的节点显示名（`node_rows()` → `name`）；
2. 无节点 → 生成该文件的进程名 + 括号里的功能（`gravity_trace_pub.py (万有引力表进程)`）；
3. 外来数据 → 真实来源（`/robot/tcp_pose (50Hz)` / `旁路 JSON` / `本机真值流`）。

验收：
```python
left  = {attribution.key_of(t,f): (attribution.layer_of(k), attribution.tx_of(k), attribution.rx_of(k)) for ...}
right = {...}                       # 另一个视图
assert not (set(left) - set(right))  and not (set(right) - set(left))
assert all(left[k] == right[k] for k in left)   # 逐字段，不只比键
```
某一轮实测：面板 506 个键，交集 506、归属不一致 0。

## 2. 行序稳定（固定行模式）

```python
# ✗ 错：帧龄/更新时间参与排序 ⇒ 每拍重排，用户说"信号在跳"
rows.sort(key=lambda r: (r["age_s"], r["layer"], r["topic"]))

# ✓ 对：只按常量
LIVE = {"zmax/ss_state": 0, "zmax/ss_engine": 1, "zmax/ss_torque": 2}
LAYER_ORD = {"L2": 0, "L3": 1, "L4": 2, "L5": 3, "SYS": 4}
rows.sort(key=lambda r: (LIVE.get(r["topic"], 9), LAYER_ORD.get(r["layer"], 9), r["topic"], r["signal"]))
```

判据：
```python
snap1 = [row_key(r) for r in table.rows()]
time.sleep(1.5)
snap2 = [row_key(r) for r in table.rows()]
assert snap1 == snap2, sum(a != b for a, b in zip(snap1, snap2))   # 期望 0
```

## 3. 数值/单位同口径

- 显示换算只做一次：`v * 1000`（m/s→mm/s）、`.4g` 有效数字；两个视图调同一个 `fmt_value`。
- 判据仍用原始值：行里同时留 `raw`（float）与 `text`（显示串），跳变检测读 `raw`。
- 不要用重排后的显示串去比上一帧，否则一次单位改动会被判成一次跳变。

## 4. PyQt5 列宽记忆 + 列头过滤

```python
# 列宽：全部 Interactive，宽度存 QSettings
hv = table.horizontalHeader()
for i in range(table.columnCount()):
    hv.setSectionResizeMode(i, QHeaderView.Interactive)   # 留一列 Stretch 就拖不动
s = QSettings("ZMAX", "studio")
w = s.value("sig/tree_cols")
if w:
    for i, px in enumerate(w): table.setColumnWidth(i, int(px))
hv.sectionResized.connect(lambda *a: s.setValue("sig/tree_cols", [table.columnWidth(i) for i in range(table.columnCount())]))
```

```python
# 列头点选过滤：点表头 → 弹该列取值+条数 → 选中即过滤，可叠加
FMAP = {"Name": 0, "Layer": 1, "Signal": 2, "Value": 3, "Type": 4, "Tx": 5, "Rx": 6}
FILTERS = {}      # 列名 -> 值

def on_header_clicked(col):
    name = NAME_BY_COL[col]
    vals = {}
    for it in walk(tree):
        txt = it.text(col)
        if txt: vals[txt] = vals.get(txt, 0) + 1
    m = QMenu(tree)
    m.addAction("全部").triggered.connect(lambda: (FILTERS.pop(name, None), rebuild()))
    for v, n in sorted(vals.items(), key=lambda kv: -kv[1]):
        act = m.addAction(f"{v}  ({n})")
        act.triggered.connect(lambda _=False, v=v: (FILTERS.__setitem__(name, v), rebuild()))
    if FILTERS: m.addSeparator(); m.addAction("清除所有列的过滤").triggered.connect(lambda: (FILTERS.clear(), rebuild()))
    m.exec_(tree.horizontalHeader().mapToGlobal(QPoint(px, py)))

def header_text(name):            # 表头自证当前过滤
    return f"{name} ▾ {FILTERS[name]}" if name in FILTERS else f"{name} ▾"

def row_ok(it):                   # 过滤在"填表后"也要再套一次，重建表不丢
    return all(it.text(FMAP[k]) == v for k, v in FILTERS.items())
```

要点：`Value` 列的值每拍都变，**别把 Value 作为可过滤列**（菜单会炸成几百项）；过滤条件存在模块级 dict，
重建树后重新应用；子行全隐藏的分组要连标题一起隐藏。

## 5. 判据脚本骨架

`tools/verify_<面板>.py` 跑 6~20 条断言，每条形如 `ck("描述", 条件, 实测值)`：

1. 两个视图键集合相同（差集 0）
2. 逐键 `(Layer,Tx,Rx)` 完全相同
3. 行序隔 1.5s 两次快照相同（0 变动）
4. 抽查 5 个信号：单位一致、数值同量级（比值 < 1.5）
5. 每列宽度 > 0 且来自 QSettings（拖过后重开仍是那个值）
6. 列头过滤实测行数（`Layer=L2` → N 行，再叠 `Type=…` → M 行）
7. 全部单元格无 `…`（`ElideMode == ElideNone`）
8. 窗口/页签图标非空
9. 终端噪声三类各 0 条（启动 + 运行 8s 后的 stderr）

跑法统一：`./gui-venv311/bin/python tools/verify_xxx.py`，失败项打印实测值而不是 "FAIL"。
