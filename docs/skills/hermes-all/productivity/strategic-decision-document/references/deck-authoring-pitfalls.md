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
3. 像素：逐页 PNG 交给独立目检（按页给设计契约，只要客观缺陷）。
   几何过了仍然会剩三类：标签压在数据点上、图被表格盖住、文字被色块边界裁。
4. 改一次布局就重跑 2 和 3 的全部页面 —— 修一处会把碰撞推到隔壁一格。
