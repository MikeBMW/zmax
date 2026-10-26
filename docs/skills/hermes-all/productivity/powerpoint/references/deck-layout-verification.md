# 中文 PPT 交付前的自动版式校验（无视觉模型也能验收）

生成 .pptx 后不要只看「文件能打开」。装 python-pptx + PIL + LibreOffice 时，下面四道检查能用纯代码抓住 90% 的版式事故。

## 1. 文字溢出（最重要）
字体替换是隐形杀手：脚本里写 `微软雅黑`，Linux 渲染会换成 Noto Sans CJK，度量不同。
用**存在的那款字**量宽度，并留 5% 余量：

```python
from PIL import ImageFont
F = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
def text_w(s, pt, face=F):
    f = ImageFont.truetype(face, max(8, int(round(pt*96/72))))
    return f.getlength(s)/96.0          # inches
# 贪心按字回退换行 → 行数 × pt × line_spacing × 1.05 / 72 ≤ 框高
```
判据：`需要高度 > 框高 * 1.0` 就报错。别用 1.06 的松阈值 —— 两行字刚好压住下一行卡片标题，
肉眼看是「字粘在一起」，代码看是「刚好通过」。

典型案例：五宫格 KPI 卡里 `1.39 / 1.67 / 1.94 年` 在 17.5pt、2.02in 框里量出 2.09in → 折行 →
压住下面的标签。修法不是缩字号，是**去掉单位**（单位写进标签）。

## 2. 图片压内容
matplotlib 图按宽等比缩放，很容易盖住下方的表或注。必须用几何交叉检查：
对每个 picture 与其他「有文字的形状 / 表格」做矩形相交，面积 > 0.02 in² 就报错。

坑：python-pptx 每次 `slide.shapes` 迭代都新建代理对象，`o is pic` 永远 False，
必须比 `o._element is pic._element`，否则满屏「图片压住自己」。

## 3. 表格行被撑高
表格里 `row.height` 只是最小值，文字多了 PowerPoint 会自动撑高，把页脚顶出画面。
逐 cell 量：`行数 × pt × 1.25 / 72 > row_h * 1.12` 就报错（中文字宽按 1em 估，比英文更能撑高）。

## 4. 渲染后逐页验
```bash
soffice --headless --convert-to pdf --outdir . deck.pptx
pdftoppm -r 110 -png deck.pdf page
```
- 每页墨迹 bbox 的右/上/下留白 ≥ 4–6px（左侧竖条、封面深色出血是有意的，按 x 裁掉再算）。
- 墨密度 15%–55%：低于 15% 说明页面内容不足或有空白段，高于 55% 说明挤。
- 全页底部到页脚距离应一致（差 1–2px），突然变大说明某页内容提前结束、排版没对齐。

## 5. 中文是否真渲染（防豆腐块）
tesseract 带 chi_sim 时，抽 3–4 页 OCR，看标题字串能不能读出来：
```bash
tesseract page-02.png - -l chi_sim --psm 6 | head
tesseract --list-langs | grep chi_sim   # 没有就先装 tesseract-ocr-chi-sim
```
标题读得出来 = 字体正常；全是 `口口口` = 字体缺失。
注意：OCR 会对页边的装饰竖条/横线产生固定「乱码行」，别当成多余文字，
要确认请看 pptx 里 `shapes` 的 text_frame 清单。

## 6. 结构约定
- 数字全部放一个 `data.json`，图表脚本与 PPT 脚本都读它 → 改价改数只改一处。
- 生成脚本、图表、pptx、pdf、逐页 png、校验脚本放同一个交付目录，附 README 写口径与重跑命令。
- 表格与文字用原生对象（不要截图贴图），客户要改数才能改。
