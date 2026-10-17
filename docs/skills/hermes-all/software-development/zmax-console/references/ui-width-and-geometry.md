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

- 环境变量 `ZMAX_CFG_TREE_W=240` (最优先, 不用改代码)
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

## 6. 在 1.7 万行文件里插方法: patch 别吃行尾换行

把 `old_string` 写成 `"    def load_flow(self, flow):\n"` 会把下一行拼上来 →
`def load_flow(self, flow):        self.clear()` ⇒ IndentationError, 还白改一次。
插入新方法时 **anchor 到下一行语句** 一起替换 (`def x(self):\n        body_first_line` →
新方法 + `def x(self):\n        body_first_line`), 改完看 diff 首行是否完整。
