# 脚本生成 pptx：能一次做对的写法与验收

只记会导致返工的东西。工具 API 本身看 bundled `powerpoint` 技能。

## 1. 插图：contain + 夹进页面

`add_picture(w, h)` 同时给 w 和 h 会**拉伸**。只给 w 推 h，竖图（ar < 0.8）会算出
`y + h > 页高`，图底被页边裁掉。

```python
PAGE_W, PAGE_H, FOOTER_Y = 13.333, 7.5, 6.88   # 16:9 英寸

def pic(slide, path, x, y, w=None, h=None, margin=0.35):
    iw, ih = Image.open(path).size
    ar = iw / ih
    if w and h:                 # 给了框就 contain，绝不拉伸
        h = min(h, w / ar)
        w = h * ar
    elif w:
        h = w / ar
    else:
        w = h * ar
    k = min(1.0, (PAGE_W - x - margin) / w, (FOOTER_Y - y) / h)
    w, h = w * k, h * k
    slide.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))
```

### 图源本身也要管比例

`bbox_inches="tight"` 会把画在坐标轴外的标注算进边界。一个远处 annotate 能把
12×2.55 的横图拉成 1203×1392 的竖图；contain-fit 之后宽度只剩 4.6 英寸，
下面的表格正好盖住条形的下半段和 x 轴。

- 图例放 axes 下方同理：`bbox_to_anchor=(0.5,-0.7)` 会把 2.5in 的横图撑到 5.4in，
  按宽度插图后直接压住下面的表格。图例放 axes 内，或干脆去掉图例、改成段内双行标注。
- 要填已知框的图：`ax.set_ylim(...)` 锁死，`savefig` **不要** `bbox_inches="tight"`。
- 出图后立刻量：`Image.open(f).size` → 打印宽高比，和版式里预留的宽高比核对。

## 2. 读回几何，证明没有溢出

比逐页看图便宜且不漏：

```python
W, H = prs.slide_width / 914400, prs.slide_height / 914400
for i, s in enumerate(prs.slides, 1):
    for sh in s.shapes:
        if None in (sh.left, sh.top, sh.width, sh.height):
            continue
        r = (sh.left + sh.width) / 914400
        b = (sh.top + sh.height) / 914400
        if sh.name.startswith("Rectangle 1") and (b < 0.2 or r >= W - 0.05):
            continue                       # 全幅装饰条/封面底色：合法贴边
        if r > W - 0.09 or b > H - 0.04:
            print("OUT", i, sh.name, round(r, 2), round(b, 2))
```

顺便打表格底边与页脚的距离，确认 ≥0.2 英寸（表格行高是最容易悄悄吃掉底部空间的东西）。

## 3. 中文与格式化

- 字体：`run.font.name` 只写 `a:latin`。中文要另外在 `rPr` 上挂 `a:ea`（和 `a:cs`）。
- 格式化：文案里出现 `%` 时不要用 `"...%d..." % args`。
  `25%（加 25% 权重）` 会被当格式符，抛 `ValueError: unsupported format character '?'`。
  混百分号的段落用 f-string，或把字面 `%` 写成 `%%`。崩了之后要扫全文所有 `" % ` 站点，
  因为它是逐个字符串才触发的。

## 4. 渲染与预览

```bash
soffice --headless --convert-to pdf --outdir . deck.pptx
pdftoppm -r 110 -png deck.pdf preview/s     # → preview/s-01.png ...
```

服务端做预览给界面用（网页/控制台里翻页看，原文件仍可下载编辑）：

- 子进程跑 soffice，带超时；UI 进程不解析 pptx。
- 缓存键 = `(文件名, mtime, size)`，附一个 `meta.json` 记页 PNG 清单。
  只按文件名缓存，重生成之后永远看到旧图。
- 文件名走「扫描目录后按名字查」+ 严格 basename 白名单，不要直接拼用户输入。
- soffice/pdftoppm 缺失要**报错**，不是给一个空画廊。

## 5. 验收顺序

1. 结构：读回页数、每页 `has_table` 行列、图片数、全部文本、notes —— 确认对象是原生可编辑的。
2. 几何：上面的越界脚本，零告警。
3. 像素：逐页 PNG 交给独立目检（按页给设计契约，只要客观缺陷；20 页以上按 §8 拆给多路）。
   几何过了仍然会剩三类：标签压在数据点上、图被表格盖住、文字被色块边界裁。
4. 改一次布局就重跑 2 和 3 的全部页面 —— 修一处会把碰撞推到隔壁一格。
5. 跑 §7 的交付闸，七项全过才发。

## 6. 三个只在渲染后才暴露的对象坑

- **占位图必须是真图片对象，不能是画的矩形。** 交付说明写「右键 → 更改图片」，
  而 autoshape 上没有这个命令 —— 指示本身就是陷阱。每个图位插一张纯色占位 PNG，
  上面只叠一行提示字；替换图片后只剩一个 textbox 要删。
  产品图**不要去爬官图或用模型生成**：版权与时效都不牢，而且换图这活本人比你快。
  给可替换图位 + 一份「文件名 → 公司/型号」对照表，在汇报里明说「图位是占位、需换实拍图」。
- **`shadow.inherit = False` 去不掉阴影。** `add_shape` 自带主题 `<p:style>`，其中的
  `effectRef` 会让每张卡片在 LibreOffice/WPS 下带一层脏投影。设完 fill/line 之后把
  `<p:style>` 整个摘掉：

  ```python
  from pptx.oxml.ns import qn
  sh.shadow.inherit = False
  st = sh._element.find(qn("p:style"))
  if st is not None:
      sh._element.remove(st)
  ```

- **`vertical_anchor` 收的是 `MSO_ANCHOR.*`，不是整数。** 写 `tf.vertical_anchor = 2` 直接
  `ValueError: 2 is not a valid MSO_VERTICAL_ANCHOR`；表格 `cell.vertical_anchor` 同理。

## 7. 交付闸：一次跑完的七项

生成器旁边放一个 `verify_*.py`，任何一项不过就 `exit 1`。它比人眼便宜，抓的又恰好是人眼
最容易放过的东西：

```python
n = len(prs.slides._sldIdLst)
assert n == TOTAL                     # 页数：页面 helper 漏开页只有这里能抓
ntab = sum(1 for s in prs.slides for sh in s.shapes if sh.has_table)
npic = sum(1 for s in prs.slides for sh in s.shapes if sh.shape_type == 13)
# 1) 页数 == TOTAL       2) 表/图数量与设计稿一致
# 3) `**` 字面量残留 0    4) 豆腐块字符（✗ ✘ ✔ □）0
# 5) 最小字号 ≥ 6pt      6) 正文关键短语里的「N 家」与 JSON 对数
# 7) 每个占位图都在位（图片数 == 图表数 + 卡位数）
```

第 6 项最容易漏也最值钱：它同时抓住「手写计数漂移」和「改了数据脚本没重跑 JSON」。
写法是把关键短语连数字一起查 —— `"只有 %d 家有数据痕迹" % expected`，命中说明文案与数据源同步过；
只查数字等于没查，因为同一个数在别处也出现过。

再加一项：**标题框只够一行**。24pt 标题装在 0.5in 高的框里，超过约 36 个等效字符就换行，
闸报「文字溢出 … 需 0.83in / 有 0.50in」。修法是把后半句挪到副标题，**不要缩字号** ——
各页标题字号必须一致，缩一页比截断更难看。

## 8. 承用别人的模板：先量，再写

用户丢一个 `模板.pptx` 过来时，版式就是需求。别配色凭感觉，直接量：

```bash
soffice --headless --convert-to pdf --outdir /tmp/tpl 模板.pptx
pdftoppm -r 60 -png /tmp/tpl/模板.pdf /tmp/tpl/s     # s-1..s-6.png
# 再用 PIL 统计每页前 3 主色（reshape(-1,3) + np.unique return_counts）
```

- 抽前 3 主色 → 定品牌色（实测 `#045898` 深蓝 + `#FEC923` 金 + 白底）；量色带位置与厚度
  （顶部 0.075in 细条贯穿全宽）→ 定每页 `rect()` 的常量。
- 量标题位置/字号（实测 26pt 粗、top 0.42in）、页脚写法（20pt 页码 → `n/18`）。
- 写成一个 `TOKEN` 块（`BLUE/GOLD/INK/RULE` + `ML/MR/CW/FOOT`），每页只引 token；
  改色只改一处，也不会出现「第 7 页的蓝跟第 2 页不一样」。
- 模板 6 页不代表成品 6 页：它是**版式母版**，内容按需扩到十几页。

## 9. 出血检查的裁切量按「抗锯齿」算

- 顶部 0.075in 的条在 110dpi 渲染后实测吃到 **~0.16in**（色块 + 抗锯齿 + 1px 边缘线）
  ⇒ 按 0.11in 裁仍报 `R0/T0` 出血，看着像有东西出界。
- 定式：裁切量 = 设计厚度 **+0.1in**；或对全幅条按 **shape 名白名单**排除，宁白名单不含糊阈值。
- **封面不要整页跳过检查**：跳过的那页往往带全幅底色，恰好是唯一有真出血的；它若真有 1px 边缘线，
  就删掉那张全幅白底 rect（页面本来就是白的），而不是放宽闸门。

## 10. 价格/分成表的算数自检（几何与目检都拓不住）

表里的数字是以字符串拼进 pptx 的 —— 越界检查、目检、OCR 全都看不出「取错了档」。
每张对比表加一道算术：

```python
for col in cols:                       # 一列一个价格包
    assert abs(sum(row[i] for row in minus_rows) - pool[col]) < 0.02   # 逐行相减 == 池值
    assert abs(pool[col] / 3 - each[col]) < 0.02                       # 池值 ÷3 == 三方各得
```

典型错法：用 `rows[0]` 取档，把 20 台档的包 C 和 50 台档的 A/B 并排，表内毛利池 39.1 而标题写 43.6
—— 文字与表格自相矛盾，只有算数能拓住。

## 11. 长文档的并行目检分工

20 页以上不要一个人从头看到尾：上下文会被前几页的细节吃掉，后面几页草草放过。拆给子代理：

- 3 路 × 每路约 11 页，每路一个固定的 JSON schema（页号 / 位置 / 现象 / 严重度），
  明确「只报缺陷，不改文件」。
- 每张图都要真调 `vision_analyze` 看，不许按文件名猜；报告必须能定位到「第 N 页 · 右栏第 3 张卡」。
- 收回来先分层：**数据性错误（数字 / 口径 / 家数）优先于版式** —— 版式改一次就没了，
  数字错了是要在会上被问倒的。
- 期望产出不是「一切正常」，是几十条具体缺陷。只报两三条的那一路，通常是没真看。

## 12. 没有视觉模型时怎么目检

交付环境不一定有 `vision_analyze`。三件便宜的替代，按顺序跑：

1. **OCR 逐页读字**：`tesseract page-02.png - -l chi_sim --psm 4`。同时拓两件事：中文没渲出来
   （豆腐块/乱码）和整行缺失（截断）。标题、表头、图注都必须读得出来。
2. **ASCII 降采样看区块**：`Image.open(p).convert("L").resize((100,36))` 后按灰度打 `" .:-=+*#%@"`。
   给出的是版面结构 —— 哪块是色带、表格几行、图占多大、底部有没有大留白，比数字更能看出
   「整页偏空」「图被表压住」这类问题。
3. **裁一块放大复核**：OCR 在 `--psm 4` 下会**吞掉标题中间的字**（实测一句「合理的 ——」整段消失），
   看着像渲染截断。先 `crop(...).resize(×2)` 那一条再用 `--psm 7` 读；读全了就说明是 OCR 的锅，
   别去改已经正确的文案。图里 8~9pt 的小字在整页 `--psm 4` 下同样会读成成串乱码
   （「按件 0.12 元/只」读成「es全号 元」），看着像字被裁了；判「图注/文案被裁」之前，
   必须按区域 `crop` + `resize(×1.8)` + `--psm 6` 复核一次。

三者都过再加一句墨密度（`(arr<245).mean()`）保障：<8% 基本是空白页，>45% 是压满了。

## 13. 改一个参数要扫全文旧字面量

改单价/倍数/口径之后，旧值会残留在四处，且都只在成品里看得见：

- 生成脚本里的**副标题与图标题**（`make_figs.py` 的 `set_title` 也是文案，不是图的一部分）；
- `data.json` 这类数据块里的**散文型字段**（如 `routes[].invest = "24.8~29.8 万"`、`headline.one_line`）；
- 结论页卡片与表里手写的「N 倍 / N 万」；
- README / MANIFEST 的汇总表。

定式：参数改动后 dump 全部 slide 文本（含表格单元格）+ grep 旧字面量（旧价、`4.4 倍`、`0.09`），
命中即修；再跑一次算数自检（§10）确认池值与倍数与模型一致。只 grep 生成脚本一定会漏掉 JSON 里的散文。

## 14. 换框架（结论口径变了）时怎么改稿

用户把前提换了一个量级（例：从「年销 500 台」改成「5 年 1000 台 / 100 场景」），不是改几个数字，
是换一套页：该删的页删、该补的页补（例：执行摘要后插一页「三口径对齐」、加一页「
1000 台 = 场景数 × 每场景台数」），而不是往后追加。做法：

- 生成脚本按段落注释切开，保留 helper 块（色板/`header`/`footer`/`table`/`card`/`pic`），
  只重写页面构建区：`head = t[:t.index("# ══ 02")]` + 新页面块 + `t[t.index("prs.save"):]`。
- 结论页的卡片与判断表全部从新模型重算，不手改字符串；封面 KPI 也跟着换（常被忘）。
- 改完先跑 §13 的旧字面量清扫，再跑§10 算数自检，最后才渲染。

## 15. 拿上一份成品当母版（跨文件复用）

同一版式的第二份、第三份 deck 不要重写生成器 —— 把上一份的 `make_deck.py` 当母版，
只写新页面：

```python
head = open(PREV).read()
head = head[:head.index("# ══ 01 封面")]     # token 块 + new/txt/rect/card/table/bullets/pic
head = head.replace(OUT_OLD, OUT_NEW)
tail = open(PREV).read()
tail = tail[tail.index("prs.save(OUT)"):]
open("make_deck.py","w").write(head + open("pages.py").read() + "\n\n" + tail)
```

新 `pages.py` 只写页面构建，母版的 helper 一个都不重复定义。三条硬约束：

- **新 data.json 必须带齐 head 读过的全部键**。少一个就在导入期 `KeyError`，而报错行指向母版里的
  老代码，看着像「母版坏了」。做法：从上一份 `data.json` 整份复制，再追加本期独有的块。
- **新页只能用 head token 块里已定义的颜色**。缺一个色（例如要紫）就在 head 的 token 区补一行，
  或在新页顶部自己定义；直接引用不存在的常量是 `NameError`，只在构建到那一页时才炸。
- 拼出来的 `make_deck.py` 仍是交付目录里**唯一**的生成器（签名闸照样适用）；`pages.py` 只是
  一次性输入，别让它变成第二份唯一依据。

## 16. 整版插图的宽度由「可用高 ÷ 宽高比」反推

`w = COL_W * 0.99` 这种贴着栏宽的写法，会算出一张把副标题和页脚一起盖住的图：
12.4×6.6 的画布按 0.99 栏宽放下是 4.93in 高，从 1.36 起 ⇒ 底边 6.29，比页脚低、
又压住 1.06~1.40 的副标题框（闸报 `图片压住内容 0.20 in²`）。

定式是先算可用高、再换算宽、最后夹到栏宽：

```python
ar = iw / ih
w = min(COL_W, (FOOTER_Y - y - 0.06) * ar)
```

## 17. 图内字号按「放置缩放比」反推，不按画布看着舒服

matplotlib 的字号是 pt，落到页面上会被 `slide_width_in / figsize_in` 缩放：
12.4in 画布上 8.6pt 的字，放进 9.7in 宽的图位只剩 **6.7pt** —— 在 PNG 里看着正常，
投影上没人读得出来，而几何闸和墨密度都不报警（像素级的字还在，只是小）。

定式：先定成品里要多少 pt（正文级 ≥9pt、注释 ≥8pt），再倒推画布尺寸，
或者干脆**缩小画布**——坐标是 0~100 归一化的，`figsize` 从 12.4×6.6 收到 10.6×5.7 再把字号
抬到 9.4~10.6pt，一行坐标都不用改，放到 0.80 栏宽上刚好 ~9pt，比在原画布上加大字号省事得多。
