# PPT 版式实测坑 (python-pptx 手写 deck)

三个都是「生成成功、PPT 里看着坏」的坑, 都靠渲染回看才发现。

## 1. 表格列宽必须自己求和到内容宽

`add_table(width=...)` **不约束列宽**, 列宽由 `columns[i].width` 决定。
各列相加 > 内容宽 ⇒ 表格直接撑出页面右侧, 而 `prs.save()` 不报错。
实测: 内容宽 11.78", 列宽 `[3.05,1.05,2.55,1.05,4.87]`(=12.57) ⇒ 右边界到 13.35", 超出 13.333" 页面。

```python
cols = [2.30, 1.45, 2.35, 2.40, 3.28]      # sum == CW 才对
assert abs(sum(cols) - CW) < 1e-6
```

## 2. 右对齐页脚给足宽度, 否则折两行
实测 `"5.50.D-P1 · 2026-11-10"` 在 1.2" 宽框里折成两行 (需 ≈1.45"), 折下去那行压到页脚线下面。
给 ≥2.4" 并右对齐, 或日期单独一个框。

## 3. 验收: 面积墨量查四边

```python
# soffice --headless --convert-to pdf  再 pptx_render.py 出 PNG
import numpy as np; from PIL import Image
a = np.asarray(Image.open(png).convert("L"))
ink    = (a < 200).mean()*100
right  = (a[:, -6:] < 200).mean()*100
bottom = (a[-6:, :] < 200).mean()*100
```
判读: 内页 `right/bottom > 1.5%` ⇒ 内容溢出。**深色封面 `ink≈98%` 是正常背景**,
判断前先看 `ink` 是否 >90, 否则会把封面报成异常。

## 4. 中文字体每个 run 都要设东亚字型
`run.font.name` 只管拉丁字型, 中文会回落。必须同时写 `a:ea` 和 `a:cs`:

```python
rPr = run._r.get_or_add_rPr()
for tag in ("a:ea", "a:cs"):
    el = rPr.find(qn(tag))
    if el is None: el = rPr.makeelement(qn(tag), {}); rPr.append(el)
    el.set("typeface", "微软雅黑")
```

## 5. 改版后跑禁用词扫描 (含表格)
用户要求「不写技术缩写」时, 光看图不够 —— 表格单元格里的字图上看不全。
对最终 pptx 把所有 `shape.text_frame.text` **加** 表格 `cell.text` 拼起来跑黑名单,
只读 slide 文本会漏掉表格里的层级缩写。
