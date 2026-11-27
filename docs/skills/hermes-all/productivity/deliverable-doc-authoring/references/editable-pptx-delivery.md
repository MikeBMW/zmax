# 可编辑 PPTX 交付件 + 控制台预览

把分析/汇报内容做成**用户能自己改的 .pptx**，并让它在控制台（或网页）里能直接翻页看、
同时原文件可下载可编辑。适用于“分析报告、竞品格局、验收汇报”这一类对外交付。

## 1. 目录与单一真源

```
deliverables/<topic>_<ver>/
  X.pptx              # 主交付，可编辑
  X.pdf               # 只读快照，用于核对渲染
  preview/s-NN.png    # 逐页预览
  roster.json         # 结构化数据 = 唯一真源
  <topic>_roster.py   # 台账 → json + 统计
  <topic>_figs.py     # 出图
  make_pptx.py        # 出 deck
  README.md           # 改哪里、怎么重算、口径、控制台入口
```

单向流动：**数据 → JSON → 统计 → 图 → 版面**。生成脚本里不写死数字，改一个值只改 JSON 再重跑，
否则同一个数在表格、图、正文会各说一套。

## 2. 可编辑性（对方会打开 PowerPoint/WPS 改）

- 标题正文 `add_textbox`，明细 `add_table`，每页 `notes_slide` 写数据口径与出处。
- 图里只放图形；公司名/数值这类“对方可能要改”的字放文本框或表格，**不烧进 PNG**。
- 中文要设两面，`run.font.name` 只写 `a:latin`：

```python
from pptx.oxml.ns import qn
def set_font(run, size=14, bold=False, color=None, ea="微软雅黑", latin="Arial"):
    f = run.font; f.size = Pt(size); f.bold = bold; f.name = latin
    if color is not None: f.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {}); rPr.append(el)
        el.set("typeface", ea)
```

## 3. 版面三道闸（出片前全跑）

**① 图的比例是版面契约。** `bbox_inches="tight"` 会把画在坐标轴外的 `annotate`/注脚一起扩进画布，
横版 `figsize=(9.4, 3.9)` 可能存成竖版（实测 1203×1392）；contain 进幻灯后被压成窄条，
底部被下面那张表的表头盖住。定式：锁死 `set_xlim/set_ylim` 留足标签位置、文字留在轴内、
存图不带 `bbox_inches="tight"`，并用 PIL 断言：

```python
w, h = Image.open(fig).size
assert abs(w / h - expected_ar) < 0.05, (w, h, expected_ar)
```

**② 碰撞三类都要比**（只比 text↔text 会漏两类）：
1. text↔text：`t.get_window_extent(renderer)` 两两 `overlaps()`；
2. text↔marker：散点 offset 经 `transData` 转显示坐标，扩成 ~8px 框再与标签框求交；
3. text宽↔patch宽：段内标签估算宽（字号×字数）vs 条/色块像素宽。
单单位段（例如 24 家里只有 1 家的类别）装不下多字标签 ⇒ 段内只写家数，类别名抬到条外用引线。

**③ 留白要配平。** 色块/卡片高度由文字块推（`行数 × 字号 × 行距 + 2 × pad`），不拍脑袋；
表格底部到页脚 > 约 0.9 in 就抬 `row_h`，**不要塞废话填空**。

插图函数必须 contain + 夹页内：

```python
PAGE_W, PAGE_H, FOOTER_Y = 13.333, 7.5, 6.88

def pic(slide, path, x, y, w=None, h=None, margin=0.35):
    iw, ih = Image.open(path).size; ar = iw / ih
    if w and h: h = min(h, w / ar); w = h * ar      # contain，不拉伸
    elif w:     h = w / ar
    else:       w = h * ar
    k = min(1.0, (PAGE_W - x - margin) / w, (FOOTER_Y - y) / h)
    w, h = w * k, h * k
    slide.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))
```

## 4. 回读自检（比目检可靠）

```python
W, H = prs.slide_width/914400, prs.slide_height/914400
for i, s in enumerate(prs.slides, 1):
    for sh in s.shapes:
        if None in (sh.left, sh.top, sh.width, sh.height): continue
        r = (sh.left+sh.width)/914400; b = (sh.top+sh.height)/914400
        if sh.name.startswith("Rectangle 1") and b < 0.2: continue   # 通顶装饰条
        if r > W-0.09 or b > H-0.04: print("OUT", i, sh.name, round(r,2), round(b,2))
```

通顶装饰条/封面底色一定报“越界”，按 **shape 名白名单**跳过；不要把阈值放宽到真溢出也能溜过去。
同时打 `6.88 - (top+height)`（表格底距页脚），< 0.2 in 就要抬行或减行。
另可回读 `has_table` 的 row×col、pictures 数、`notes_slide` 文字，确认“真是原生对象而不是图”。

## 5. 服务端预览（pptx → 页图）

- 子进程转：`soffice --headless --convert-to pdf --outdir <cache> <pptx>` → `pdftoppm -r 110 -png`，带 timeout；
  UI 进程里不解析 pptx。
- 缓存键 **(文件名, mtime, size)** + 一份 `meta.json` 列页 PNG：deck 一改自动重转，不会拿旧图糊人。
- 只读原文件；文件名用 `^[^/\\][^/\\]*\.pptx?$` 白名单 + 每次重新扫目录查表，不把用户串拼进路径。
- 原 pptx 以 `application/vnd.openxmlformats-officedocument.presentationml.presentation` 附件下载 ——
  “下载/本地打开”必须拿到可编辑文件。
- 缺 `soffice`/`pdftoppm` 是**要报出来的错误**，不是空画廊；页面写清原因。

挂到已在跑的 web 服务上（同源、手机也能开），懒加载模块不影响主服务：
`/eval/ppt`（画廊页）· `/eval/ppt/list` · `/eval/ppt/meta?f=` · `/eval/ppt/slide?f=&n=` · `/eval/ppt/file?f=`。
画廊页支持 `?f=<名>` 直定位，供控制台按钮带参打开；页面用原生 fetch + 网格缩略图，点开大图。

## 6. 控制台入口（PyQt 只做薄壳）

- 面板：下拉列交付件（`QComboBox` 的 `itemData` 放整条 dict）+「在控制台查看 / 用本机程序打开 / 复制路径 / 重新扫描」。
- “查看” = 独立窗口内嵌 `QWebEngineView` 指向 `<svc>/eval/ppt?f=<name>`；不可用时退回系统浏览器（不静默失败）。
  `QtWebEngineWidgets` 要在 `QApplication` 之前 import（宿主程序模块级已保证），窗口实例化时再 import 不会炸。
- **预览只读，编辑走原文件**：`QDesktopServices.openUrl(QUrl.fromLocalFile(path))`，让对方改唯一真源，不是缓存页图。
- 失败把原因写进面板状态行（路径 + 报错），不显示假 0 页。

## 7. 视觉复检循环（每页都会被人看时）

1. 渲染 ≥110 dpi；低 dpi 会把半个字高的裁切看成“字体问题”。
2. 交给独立视觉复核，问题清单**窄且枚举**：溢出/裁切、文字重叠、表格行高、列宽断词、色块内标签出界、豆腐块；
   允许逐页回 `Pn: OK`，并明确“没看出问题就说 OK”，否则会凑问题。
3. 要像素量化（“下留白 114px vs 上留白 48px”可执行，“有点挤”不可执行）。
4. 改完只复检**改动过的页**，并告知改了什么，让对方判修复而不是重推意图。
5. 判渲染后的页，不判源图；源图正确照样可能撞在 deck 里。

## 8. 生效与交付口径

- 重出 pptx 后控制台**不用重启**：缓存键带 mtime，下次打开自动重转；但要重启一次才生效的是 GUI 代码本身，
  重启后回读进程 + 启动日志无 traceback + 用 offscreen 建一次那个页面验证控件真的读到文件。
- 交付汇报带：绝对路径、页数、真表格数量、图数量、“改数据重算”的两三条命令、控制台入口、口径与待核实项。
- 凡“未公开/口径不可比”的样本（美元市值 vs 人民币一级估值、两份信息源冲突的公司）**单列并不进合计**，
  在口径页写明“合作前须核实”——不要为版面整齐把它们混进分母。

## 9. page builder 骨架（页数会静默少掉的那类 bug）

一个接收当前 slide 往里画的 helper 是隐形的页数吞噬器：调用方把上一页的 `s` 传进去，几页内容叠在同一页，
`len(prs.slides)` 比声明值少（33 → 29），**不抱任何异常**，存在的那几页单看全对。

```python
TOTAL = 33

def page(kick, title, n, sub=None):          # 只收内容参数
    s = prs.slides.add_slide(prs.slide_layouts[6])
    header(s, kick, title, n, sub)
    return s

def findings_page(n, kick, title, items, color, concl=None):
    s = page(kick, title, n)                 # helper 自己建页
    ...
    return s

assert len(prs.slides._sldIdLst) == TOTAL, len(prs.slides._sldIdLst)
```

同一个 `TOTAL` 要嗂给页脚函数（`"%d/%d" % (n, TOTAL)`），否则页码也会跟着说谎。

## 10. 版面几何配方

**表格行高预算。** `add_table` 的 row height 是**最小值**：需要三行的单元格会把行撑高、把表推进页脚。
先算 `(footer_y - table_y - head_h) / n_rows`，再按这个高度限定每格行数：16:9 上 15 行表在 6.7pt 下
约 0.32 in/行（每格两行字），10 行密集表在 6.4pt 下约 0.48 in/行。单元格 margin 给 0.05 in 会贴格线，0.085 in 才干净。

**卡片网格。** 一行 N 张卡会把下半页留空：改 2 列 × 3 行、左图右文，`cw=(12.09-0.19)/2`、`ch≈1.56`、
图位 `1.24×(ch-0.22)`、文字从 `x+1.48` 起。图位做成填充矩形 + 目标文件名（小灰字），对方可右键换图不动版面。

**雷达图。** `bbox_inches="tight"` 会裁掉外侧极坐标刻度标签（标签画在 axes patch 之外）。这类图存图不带 tight、
用 `subplots_adjust` 留边，2×3 网格 `hspace≈0.58`，轴名用短词。

**卡片的脏投影。** `add_shape` 带主题 `effectRef`，`shadow.inherit = False` 在 LibreOffice/WPS 下清不掉，
要摘整个 style 节点：

```python
from pptx.oxml.ns import qn
sh.shadow.inherit = False
st = sh._element.find(qn("p:style"))
if st is not None:
    sh._element.remove(st)
```

## 11. 30 页以上的复检要并行

顺序 `vision_analyze` 30 页比生成还贵。把页图区间切成三段，并行派三个**只读**子代理（不修文件），
要求回 `页码｜位置｜缺陷｜严重度`，并强制干净页写 `OK`（只问“有什么问题”的子代理会凑问题）。
任务文本里把七项检查写死：出框/裁切、元素重叠、豆腐块、孤字、表格压页脚、表头与内容语义错位、
同页数字自相矛盾。三路全回后一次性批量修。
