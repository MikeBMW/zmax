# PPT 原生图表：让图表真的能改

判据：用户要「图表能编辑」时，**PNG 一律不合格**，连「标签没烧进图」也不算合格 —— 图本身就是一张位图，
他改不了数据范围、改不了配色、删不掉一行。凡数据图一律 `add_chart`（每个图表内嵌一份 XLSX，右键「编辑数据」
真能改）；凡没有数据表可编辑的判断图（2×2 矩阵、分档清单）一律形状 + 文本框。

## 类型映射

| 需求 | XL_CHART_TYPE | 备注 |
|---|---|---|
| 横条排名（公司榜） | `BAR_CLUSTERED` | 类别要**反序**传入，否则第 1 名沉到底部 |
| 竖柱（分类计数） | `COLUMN_CLUSTERED` | |
| 折线/趋势 | `LINE_MARKERS` | 只要折线用 `LINE` |
| 四维/五维能力 | `RADAR` | |
| 定性分档（绿/橙/灰） | `BAR_STACKED` | 每行只有一个系列有值，见下 |

## 骨架

```python
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import (XL_CHART_TYPE, XL_LABEL_POSITION,
                             XL_LEGEND_POSITION, XL_MARKER_STYLE)
from pptx.oxml.ns import qn

cd = CategoryChartData()
cd.categories = list(reversed(cats))       # 横条：反序
cd.add_series("值", list(reversed(vals)))  # 某项没有值时传 None（不要填 0）
gf = s.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED,
                        Inches(x), Inches(y), Inches(w), Inches(h), cd)
ch = gf.chart
ch.has_legend = False
ch.has_title = False          # 标题用页面上的 textbox，不用图内标题
ch.font.size = Pt(8); ch.font.name = "微软雅黑"
# 中文要另设 a:ea，否则字形回落 —— 遍历 a:defRPr 补 <a:ea typeface=…/>

pl = ch.plots[0]
pl.gap_width = 40
pl.vary_by_categories = False  # 必须先关，否则逐点分色被主题色覆盖
pl.has_data_labels = True
dl = pl.data_labels
dl.number_format = "0"; dl.number_format_is_linked = False
dl.position = XL_LABEL_POSITION.OUTSIDE_END

for i, c in enumerate(reversed(colors)):        # 逐点分色
    pt = ch.series[0].points[i]
    pt.format.fill.solid(); pt.format.fill.fore_color.rgb = c
    pt.format.line.fill.background()
```

坐标轴统一收一遍：`va.format.line.fill.background()`、`va.major_gridlines` 浅灰、`va.minimum_scale = 0`、
类别轴 `tick_labels.font.size`。不然每张图默认样式不一致，十几页拼起来很脏。

## 坑（每条都真的踩过）

- **无量类目传 `None`，不要填 0**：0 会画一条贴轴的零长条，`None` 才是空行（如某公司估值未折算）。
- **对数轴 python-pptx 没有属性**，只能插 XML：`c:scaling` 下 `<c:logBase val="10"/>`，**必须紧跟
  `c:orientation` 之后**（顺序错 PowerPoint 会报文件修复）。跨度超过两个数量级的指标（例：单台估值
  18.6 亿 vs 967 万）不取对数，小柱必不可见。
- **对数轴下 `OUTSIDE_END` 数据标签会被算到类别轴附近，压住类别名**。改 `INSIDE_END` + 白色粗体，
  标签落进柱内右端。
- **雷达图的刻度数字会叠在第一个轴标签上**。`va.tick_labels.number_format = ";;;"`
  （同时 `number_format_is_linked = False`）把数字隐藏，网格环保留。
- **`LineSeries` 没有 `marker_format`**（`AttributeError`）。用 `ser.marker.style` / `ser.marker.size`，
  marker 填色包 try/except 保障；线本身用 `ser.format.line.color`，并关掉 `ser.smooth`。
- **图例位置只有几个固定档，压到结论条时没法微调**：页面级手绘图例（色块 + 文字，2×2 排列
  `_lx = 8.60 + (i % 2) * 1.66`）比 `ch.has_legend` 可控。
- **交付前数一遍 embeddings**：`unzip -l out.pptx | grep -c 'embeddings/'` 必须等于图表数。
  少一个说明那张图没带工作簿，「编辑数据」会报错。文件体积从 MB 掉到几百 KB 是图片消失的正常征兆。

## 定性分档（绿/橙/灰）用堆叠

单系列无法逐档配色，而图例要表达「档位」含义。取巧但干净的做法：**每行只有一个系列有值**，
堆叠后条长即档位高低。

```python
cd.categories = list(reversed(cats))
rev = list(reversed(groups))          # groups[i] ∈ {1,2,3}
for k in (3, 2, 1):                   # 高档在前，堆叠才从 0 起算
    cd.add_series(names[k], [k if g == k else None for g in rev])
# ...BAR_STACKED...
ch.plots[0].gap_width = 45
ch.plots[0].overlap = 100
ch.legend.position = XL_LEGEND_POSITION.BOTTOM
ch.value_axis.visible = False          # 档位不是量，藏掉数值轴
```

代价：改数据时要**同时清空旧系列、填新系列**，否则一行叠出两根条 —— 交付时提醒用户一句。
嫌麻烦就退回单系列 + 逐点颜色，代价是丢掉图例。

## 判断图用形状画，不要硬塞 chart

2×2 矩阵、分档清单没有「数据表」可编辑，用 chart 反而束手束脚。4 个矩形 + N 个椭圆 + 文本框，
可直接拖、改色、改字。数据坐标 → 英寸写成小函数，改位置只改数据：

```python
def qpt(dx, dy):
    return QX + dx / 10.0 * QW, QY + (1 - dy / 10.0) * QH
```

标签**不要压在点上**：右对齐的标签盒右边界取 `px - 0.18`、左对齐取 `px + 0.19`，盒宽固定 1.38，
再 `align="r"/"l"`。只调 offset 不锁盒边，右对齐的长文字会盖住圆点。
`add_shape` 的圆点/色块要连 `p:style` 一起删，否则 LibreOffice/WPS 照渲主题阴影。

## 达标判定

```bash
unzip -l out.pptx | grep -c 'charts/chart'      # 图表数
unzip -l out.pptx | grep -c 'embeddings/'       # 内嵌工作簿数，应相等
```

同时确认：表格是 `add_table`、文字是 textbox、`**` 加粗已拆成 run（不是字面量）、页数等于声明的 TOTAL。
