# 控制台 UI 宽度 / 几何 (真屏判据 + 反模式)

什么时候看这个文件: 用户说某个栏/面板「太宽/太窄/拖不动/字被挡住」, 或者要给画布节点/面板加
像素级显示元素。

## 1. 量宽度必须在真屏, 不能在离屏

离屏 (`QT_QPA_PLATFORM=offscreen`) 的 `fontMetrics()` 用的是默认 DPI, 真屏 192DPI 下同一串文字
可能**宽一倍**。实测同一棵树: 离屏最长条目 128px / 需求 184px, 真屏 192DPI(10pt, 单字 16px,
行高 31px) 最长条目 246px / 需求 302px。拿离屏数字调宽度 = 调错方向。

```bash
# 真屏量 (构造函数里就算好需求宽度, 不必 show; 要量"落定后的实际宽度"才 show+processEvents)
DISPLAY=:0 ./gui-venv311/bin/python -c "
import sys; sys.path.insert(0,'tools/gui')
from PyQt5.QtWidgets import QApplication
app=QApplication(sys.argv); import veh6_config_page as V
pg=V.ConfigCenterPage(model_page=None); pg.resize(1700,1000); pg.show()
app.processEvents(); app.processEvents()
print(pg._tree_need, pg.tree.width(), pg.splitter.sizes())"
```

判据要写成 **4 种现场**: 记忆值 > 内容需求 / 记忆值 < 内容需求 / 显式 pin / 环境变量, 每种的
打开宽度都要打印出来; 改前先把 QSettings 原值存下来, 最后逐键还原 (`S.remove(k)` 对应 None/空)。

## 2. 反模式: `want = max(need, saved)`

`QSettings` 记住的宽度**只增不减**。只要用户某次拖宽 (或旧版树更长时写进去的值) 留在
`~/.config/ZMAX/Console.conf`, 之后每次打开都是那个偏宽的值 —— 表现为"我明明改小过, 打开还是宽"。

固定口径 (用户两次反馈后才定下来):

```
打开宽度 = pin(用户显式指定) > 记忆宽度(且 < 内容需求) > 内容需求
```

记忆**只许更窄, 不许更宽**; 拖宽不沿用, 拖窄沿用。记忆值必须配一份"树指纹"
(条目数 | 最长条目像素 | 最长条目文本前 40 字), 指纹不符视为旧内容留下的值。

## 3. 最小宽度不要用内容需求当硬下限

`setMinimumWidth(_tree_need)` 会让用户**根本拖不窄** (实测 302px 是地板), 于是"太宽"无解。
下限给一个能读的最小值 (`min(need, 170)`), 文字超出由 Qt 省略号处理, 全文放进条目 tooltip
(条目的 `setToolTip` 本来就有, 别删)。

## 3.5 宽度压不下去时先瘦内容, 再谈截断

默认宽度已经压到上限、用户还说宽, 说明**内容本身**占宽: 行里堆了重复信息 (例: 树行写
「1. 产品配置 · 天枢」, 而星名在顶部阵图条与条目 tooltip 里都有了)。口径顺序:

1. 先删行内冗余文本 (保留真源要求的序号/名称), 重新算需求宽度 —— 实测 302px → 224px,
   7 行**全部完整显示**, 不用省略号。
2. 再设默认上限常量 (`_TREE_W_DEF_MAX`), 打开宽度 = `min(需求, 上限)`。
3. 用户还要更窄 → 让他拖或给 pin, 不要继续改字号/截断名字。

改行文本有两个必查坑:

- **点选分派会断**: 处理函数常拿 `item.text(0)` 去正则匹配刚被删掉的片段。做法 =
  `it.setData(0, Qt.UserRole, 星key)` + `it.setData(0, Qt.UserRole+1, 全文)`, 并在分派入口
  先取 `UserRole+1` 当文本 (`Qt.UserRole` 是 0x0100, 探针里写 33 之类的值是错的)。
- **别处会把它改回去**: `grep -n "setText(0" <file>` 找所有重写该行的地方 (真源同步回调
  会重设整行文本), 每处都改成短版 + 存全文, 否则你的瘦身在上层构造完之后被静默撤销,
  表现就是"需求宽度一点没变"。

Qt 的省略号只在绘制层: `item.text(0)` 永远返回全文, 所以窄栏不影响逻辑; 但**不要依赖它**
去省掉分派需要的字段。

验收数字: `_tree_need` (需求) / `tree.width()` (实际落定) / 每条 `fm.elidedText()` 是否等于原文
(全部相等才算"没截断") + 逐个点选看页签是否切对。

## 4. 一个数就能压死 (用户自助)

用户说「我自己改宽度，数值在哪里」时，真源必须是**一个他能直接编辑的文件**，不能只给 env/QSettings:

```
config/platform/zmax_ui_layout.json        # config/ 是软链, 写仓库相对路径即可
{ "config_center_left_width": 170 }        # 120~900 px; 0 = 按内容自适应 (上限 220)
```

读取函数 `veh6_config_page.py::_tree_cfg_width()`，优先级:

```
env ZMAX_CFG_TREE_W > QSettings config_center/tree_width_pin > 上面这个 json > 更窄的记忆 > 默认上限
```

- 文件里给了数就**以文件为准**：拖分隔条当次有效，下次打开回到文件值 —— 要主动告诉他这一点，
  否则他会以为“我拖了怎么又变回去”。
- 他填的数小于下限时**必须可预期**：代码里 clamp 到下限 (如 120)，并在 json 的 `_说明` 写清范围。
  典型失望: 写 `100`/`120` 都没反应 —— 真因是代码里 `max(170, v)` 把它抬回 170，不是没读到。

### 坑: 复用页面只在构造时读一次文件

配置中心窗口是复用的 (再点不新开第二个)。宽度只在 `__init__` 读一次 ⇒ 改完 json 再点开还是老宽度，
用户看到的就是「我改成 170 / 100 / 120 都没生效」。

修法: 在 `showEvent` 里 `QTimer.singleShot(0, self._reapply_tree_width)`，重读需求宽度 + 配置 + pin，
**三者拼成签名，签名没变就不动** (否则会把他手拖的结果冲掉)。验收: 不重建页面、只改文件，
依次写 170/120/240 并调 `_reapply_tree_width()`，实际 `tree.width()` 必须跟着变 (170→169, 120→120, 240→239)。

- 环境变量 `ZMAX_CFG_TREE_W=240` (临时试值, 最优先)
- QSettings 固定值 `config_center/tree_width_pin`
- 或者直接拖分隔条 —— 拖动时把 pin 清 0, 以拖动结果为准, 且只有在比内容需求更窄时才在下次打开生效

## 5. 画布 QGraphicsItem 离屏取证的三个前提

```python
# ① scene_ref 必须给桩 (paint 会读 scene_ref.links 数入线), 否则 AttributeError 而不是"没画出来"
class _StubRef:
    links, nodes, mode = [], [], "view"
    def __getattr__(self, k): return None
# ② 用真 QStyleOptionGraphicsItem(), 不要传 None
it.paint(painter, QStyleOptionGraphicsItem(), None)
# ③ painter 必须 finally end() —— 异常时没 end 会 "QPaintDevice: Cannot destroy paint device" + 段错误
```

给所有节点加显示元素时 **包在 `paint()` 外层** (`paint` → `_paint_core` + 自己的绘制),
因为 `_paint_internal` 只覆盖 Z700 分支, 普通节点走的是 paint 主路径 —— 加在
`_paint_internal` 里实测对普通节点完全不生效。

## 6. 在 1.7 万行文件里插方法: 两个静默陷阱

**① 吃行尾换行 (IndentationError)**:
把 `old_string` 写成 `"    def load_flow(self, flow):\n"` 会把下一行拼上来 →
`def load_flow(self, flow):        self.clear()` ⇒ IndentationError, 还白改一次。
插入新方法时 **anchor 到下一行语句** 一起替换 (`def x(self):\n        body_first_line` →
新方法 + `def x(self):\n        body_first_line`), 改完看 diff 首行是否完整。

**② 同名方法重复定义 (静默死代码)**:
同一个类里已有 `showEvent` / `closeEvent` / `paintEvent` 时再插一个 **能正常编译**，
后定义的那个生效、前一个变死代码 —— 功能“改了没反应”，`py_compile` 不报，只有 LSP
或肉眼能看出来。插生命周期钩子前先 `grep -n "def showEvent\|def closeEvent" <file>` +
`grep -n "^class " <file>` 确认行号落在哪个类，把行为**加进已存在的那个**（同一个方法末尾
追加），不要新建同名方法。

## 7. 别写死像素高度/宽度 —— 按 fontMetrics 算 (192DPI 下写死必裁字)

**症状**: 按钮/标签「字只显示一半」「版本号没显示全」「黑底黑字看不见」。

**根因两类**（都实测过）:
1. **写死高度**: 某次为"压薄工具条"加了 `setFixedHeight(24)`, 而真屏 192DPI 下 `font-size:10pt`
   → `fontMetrics().height()` = **40px** ⇒ 高度 24 正好裁掉一半字。凡 `setFixedHeight/setMaximumHeight`
   的数字都要问一句"这个数从哪来、字号变了还成立吗"。
2. **写死宽度/没套样式**: `SystemSidebar.setFixedWidth(200)` → 栏内版本文本只剩 136px, 而
   `"Z-MAX v5.50.73x"` 要 154px ⇒ 裁 18px。另一类"黑字"不是配色问题, 而是**控件从没套过样式**
   (同一批 `_style_chk()` 只套给了已搬走的 6 个) → Qt 默认黑字画在 `#0d1117` 上, 对比度≈1:1。

**口径**:
```python
fm = widget.fontMetrics()                      # 真屏量, 不是离屏
h  = max(26, fm.height() + 6)                  # 上下各 3px, 不裁字
widget.setFixedHeight(h)                       # 或干脆只 setMinimumHeight
bar.setMaximumHeight(h + 12)                    # 容器跟着内容, 别反向压死子控件
need = 34 + 6 + label.sizeHint().width() + 24 + 1 + 16   # 按钮+间距+文本+留白+边框+余量
sidebar.setFixedWidth(max(200, need)); label.setMinimumWidth(label.sizeHint().width())
```
- 量 `sizeHint()` 前先 `ensurePolished()`, 否则按默认字体算 → 量小了还是裁。
- 样式表的 `font-size` 优先于 `QWidget.setFont`; 要改字号改**样式表里的 pt**,
  同时把 `padding` 一起收 (`padding:6px 12px` → `1px 8px`), 否则固定高照样裁。
- 判据(必须落在真屏): `w.height() >= w.fontMetrics().height()+2` 且
  `label.width() >= label.sizeHint().width()`; 再抓图 `tb.grab()` 看字形(黑底黑字时亮像素≈0)。

**版本号**: `tools/bump_version.py --to X.Y.Z --summary-file <一行>` 会同步 9 处
(studio QLabel/状态栏/关于框/changelog、update_checker、docs_sync ×2、version_sync、
integrity_check EXPECTED_VERSION、VERSION.md)。**先 `git tag | grep X.Y.Z`** —— 老倪报的号可能
是**已发布过的**(他看标签被裁才猜的号), 倒退版本号比多升一版伤害大。
改完必跑 `tools/ci/integrity_check.py`(五处一致性门) + 真起一次控制台打印 `windowTitle()` 与
侧栏标签 `width()`/`sizeHint()`; 最后 commit → tag → push (tag 才触发出包 CI)。

### 像素取证的输出预算(不然自己淹死自己)

逐像素 `pixelColor()` 循环 + `print` 是最容易把工具输出撑爆的一步: 越界坐标 Qt 会**每个像素**
打一行告警, 一次取证就能吐几十 KB, 还看不见真正的字形。口径:

```python
# ① 先聚合再打: 亮像素占比 / 边框行号, 只打 1~2 行数字
# ② 要看字形就画「有界的」ascii 图: 固定 x,y,w,h + step>=2, 每行截断到 ~110 字符
# ③ 坐标先 clamp 到 img.width()/height() 之内 —— 越界告警比结果还多
for j in range(y, min(y+h, img.height()), 2):
    print('   ', ''.join('#' if lum(i, j) > 150 else '.' for i in range(x, min(x+w, img.width()), 2))[:110])
```

抓图 `widget.grab()` 默认包含子控件; 判"黑底黑字"别只看 `styleSheet()` 非空 —— **空样式表**
就说明这个控件从没被套过样式 (同批控件只套了一部分), 这才是真因。

## 8. 删掉一个页面 / 删一大块代码 (按行删, 不按正则到下一个 return)

用户说「删除 X 页面」时, 一处删不干净就会留一堆死代码或半截函数:

```
① 页签表        for key, txt in (("loop", …),):        ← 只留要留的那个, 默认勾选也改
② 控件/表      tb_loop 建表 + 列宽 + hide/show + 渲染函数 _fill_loop
③ 调用点        self._fill_loop() / self._loop = _j(LOOP) / 顶部读数里的 "闭环 x/9"
④ 跨模块文案  别的模块的质量告警文本里可能还在拼这段 (dds_bus._fill_quality)
⑤ 全局引用    grep -rn "tb_loop\|<页面名>" tools/ src/ —— 别处可能还在点它的控件
```

**别用「从起点正则删到下一个 `return`」**: 中间隔着别的函数时会把后面的函数体一起删掉。
实测一次删了 173 行 (含 `return c, dot, de`), `py_compile` 照样通过 ⇒ 只有 diff 能发现。
口径:

```bash
git checkout -- <file>                         # 先回到干净版
awk 'NR>=584 && NR<=630 {printf "%d| %s\n", NR, $0}' <file>   # 看清起止行再动手
# 用行号切片删 (del L[a:b] 或 sed 区间), 而不是 anchor→return
```
删完必须 `git diff --stat` 看删除行数是否符合预期 (个位数~几十行); 一次几百行就是删过头了。

## 9. 探针读不到数据先看刷新函数的早退

GUI 的刷新函数常以 `if not self.isVisible(): return` 开头 (省 CPU), 定时器又没到点 ⇒ 探针里
`show()` + `processEvents()` 之后树/表全是 0, 看起来像"数据源没接上"。口径: show 后**显式**调一次
刷新 (`w.reload(force_tree=True)`) 再读 `_busdb` / `rowCount()` / `topLevelItemCount()`。

## 10. 给树/表加列: 列数和每个 QTreeWidgetItem 的元组长度必须同时改

给现有树/表加一列 (例: 信号表加 Tx/Rx) 不是改表头就完事, 四处必须一起改, 否则列会整体错位
而不报错:

```
① setColumnCount(n) + setHeaderLabels([...]) 必须同长度
② 每一处 QTreeWidgetItem([...]) —— 元组长度必须 == n; 少一个就整体左移一格
   (实测: 报文/节点/信号三种行各自构造, 只改了两种 ⇒ 节点行 Tx 空、Rx 显示 "发 1")
③ resize 模式与固定列宽元组 (i, w), 以及 setItemDelegateForColumn(bar_col) 的列号
④ 写值处的 setText(col, …) / setForeground(col, …) 列号 (改完 grep 一遍所有 setText(n,  )
```

判据: 读 `headerItem().text(i)` 逐列打印 + 逐行读 `item(r,c).text()` 前几列 —— 列名对齐、值落在
对的列才算过。`py_compile` 对这类错**完全不报**。

不要用"多塞一个空串去凑列数"的写法 (`[..., "", "", "发 1"]`); 先数清楚 n 再写。

## 11. 表格/树的"对齐"是三件事: 列宽够、值对位、字不硬裁

用户说「这些列要对齐/根本对应不上/字显示不全, 太乱了」时, 不要只调字号 —— 按这四条一起改,
只改一条他一定还说乱。

**① 列宽必须按"表头实测宽"算, 而且要在 polish 之后量**

```python
self.tree.setStyleSheet("... font-size:9pt;")
self.tree.ensurePolished()                     # ★ 不 polish 量到的是默认字体 ⇒ 列比表头还窄
fm = self.tree.header().fontMetrics()
mins = [max(180, fm.width(cols[0]) + 16)] + [fm.width(c) + 16 for c in cols[1:]]
```
坑: 用 `QFontMetrics(QFont(UI, 9))` 自己造字体量也不行 —— 样式表里的 pt 跟 QFont 的 pt
在 192DPI 下不等价 (实测 Value/Unit/Bar 又被裁)。**量完再对比一遍**:
`[c for c in cols if fm.width(c)+16 > columnWidth(i)]` 必须为空。
同时把长表头换短 (`Last Value Time [s]` → `帧龄`), 全称放 `headerItem().setToolTip(i, ...)`。

**② 每列一个对齐规则, 空值也要占位**

```python
ALIGN = {0: 左, 1: 右, 2: 中, 3: 右, 4: 中, 5: 左, 6: 左}   # 名/值/单位/时间/条/源/目的
for c in range(n): it.setTextAlignment(c, ALIGN[c])
```
数值右对齐、单位居中, 名字左对齐; **非本行语义的列写 `—` 而不是空串**, 否则整张表看起来
"数字和单位各在各的"。写值函数 (`_update_values`) 里也要重设 alignment, 不能只在建行时设。

**③ 省略只是显示层: 每格带 tooltip**

```python
self.tree.setTextElideMode(Qt.ElideRight); self.tree.setWordWrap(False)
for c: it.setToolTip(c, full_text)            # 表头也加 tooltip
```
汉字的物理约束: 192DPI/10pt 下一个汉字 ≈ 24px, 640px 面板里放不下 7 列中文名 —— 只能省显示,
不能省数据。给表头旁边放一行提示「列可拖动 · 悬停看全文」。

**④ 窄了就把次要列收起来, 宽了自动回来**

```python
avail = tree.viewport().width() - 2
hide = {2: avail < 820, 4: avail < 820, 3: avail < 700}   # Unit / Bar, 更窄再收帧龄
for c, h in hide.items(): tree.setColumnHidden(c, h)
# 让出的宽度: 一半给 Name(封顶 320), 其余给 Tx/Rx —— 全给 Name 会让 Tx/Rx 只剩省略号
```

`_fit_columns()` 必须在这几处都调: `resizeEvent`、`showEvent` (含 `QTimer.singleShot(0/250)`)、
树重建末尾、以及**每拍刷新开头** —— 树被分栏改宽时不一定有 resizeEvent, 只在 resize 里调会
出现"第一次量到 1687px, 后来实际 640px 却不收列"。

验收: 打印 `[(表头, columnWidth, 隐/显)]` + `表头被裁: [无]` + 数值列 alignment 值
(左 129 / 右 130 / 中 132) + 前 3 行 7 列文本; 真机 640px 与宽屏两档都要看。探针读不到行数
先看 §9 (刷新函数早退)。
