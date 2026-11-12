# 追加页与自检: 配方与坑

## 1. 幂等追加 (python-pptx)

```python
BASE = 7                       # 已有页数, 追加页从 BASE+1 起
pr = Presentation(DECK)
while len(pr.slides._sldIdLst) > BASE:      # 反复迭代不会堆页
    sid = pr.slides._sldIdLst[-1]
    pr.part.drop_rel(sid.rId); pr.slides._sldIdLst.remove(sid)
... 画页 ...
pr.save(DECK)
```

注意: `drop_rel` 只掉关系, 页部件仍留在包里(文件会慢慢变大), 但页数与内容正确; 真要瘦身就用一份干净底稿重跑。

## 2. 版式与几何自检

- 画完遍历 `slide.shapes`: 断言 `left>=0 and top>=0 and left+width<=slide_width and top+height<=slide_height`。
- 横线/竖线分开写: vline(x,y0,y1) 与 hline(x0,x1,y)。把 hline 的三参误传给 vline 会画出跨页高的竖线(实测 9.18 in, 越界但肉眼只看到一条淡线)。
- 泳道底色块(如稳态循环高亮)插到底层: `sh._element.getparent().remove(sh._element); slide.shapes._spTree.insert(2, sh._element)`, 否则盖住条形。
- 表格页行高 `min(0.40, (底-顶)/行数)`, 行数 15~16 时约 0.38 in, 配 6.4 pt 两行可容; 一页放超过 16 行就该拆页。

## 3. 渲染自检 (不依赖视觉模型)

```bash
soffice --headless --convert-to pdf <deck>.pptx >/dev/null 2>&1
pdfinfo <deck>.pdf | awk '/^Pages/{print $2}'          # 页数对不对
pdftoppm -f 6 -l 7 -r 70 -png <deck>.pdf /tmp/chk/p     # 只渲目标页
```

```python
from PIL import Image; import numpy as np
a = np.asarray(Image.open('/tmp/chk/p-06.png').convert('RGB'))
n = lambda rgb, tol=26: int((np.abs(a.astype(int)-np.array(rgb)).max(2) < tol).sum())
print('非白占比 %.1f%%' % (100*(a.min(2)<245).sum()/(a.shape[0]*a.shape[1])),
      {k: n(v) for k, v in {'teal':(15,118,110),'blue':(29,78,216),'purple':(124,58,237),
                            'green':(21,128,61),'orange':(180,83,9),'gray':(148,163,184)}.items()})
```

判据: 每个泳道色几千~几万像素 = 条形真画上; 非白 >10% = 不是空页; 某色 0 而本该有条 = 画错层/画到页外。

也可以用取点验证「底色块是否只在窗口内」: 换算 `x = x0_in + t/total*W_in`, `y = y0_in + lane*rh`, 取 `a.getpixel((x/13.333*Wpx, y/7.5*Hpx))` 比色。

## 4. 节点清单页: 从工程真源抓, 不手写

来源两处, 各管一半:

1. **清单与分层** ← 画布 `data/database/zmax/sources/canvas/state_space_obs.json`。按 `row_bg` 节点的 `y/h` 定义层带, 再按 `y` 落带:

```python
BANDS = [(2972,3266,'L2 记忆'), (3406,3824,'分段感知'), (3964,4258,'感知融合'),
         (4398,4692,'分段控制小模型'), (4832,5126,'状态机决策'), (5266,6106,'原子技能+收口'),
         (6196,6490,'执行层')]                      # 从 row_bg 的 y 与 h 现算, 别硬记
band = next((b for b in BANDS if b[0] <= n['y'] < b[1]), None)
```

2. **名称/功能/PURE/实现位置** ← `src/lerobot/middleware/nodes/_index.py` 把节点 id 映到 `n_*.py`, 再从该文件正则抽:

```python
name   = g(r"NAME\s*=\s*['\"]([^'\"]+)")
desc   = g(r"'desc'\s*:\s*'([^']*)'")                       # 功能原文, 去掉 "[基础·分段小模型]" 前缀
source = g(r"^SOURCE\s*=\s*['\"]([^'\"]+)", re.M|re.S)     # 真实现文件
pure   = g(r"^PURE\s*=\s*(\S+)", re.M|re.S)                 # True=真算 False=只走数据面
portin = g(r"PORTS_IN\s*=\s*\[([^\]]*)\]")
```

坑:

- **行锚点必须带 `re.M`**: `^SOURCE`/`^PURE` 只用 `re.S` 会全空, 看起来像"节点没登记"。
- `SOURCE` 可能是空串(n_skills/n_muscle/n_inspection 这三个), `PARAMS.desc` 也可能缺: 这时去实现文件头取功能句(`plan_impl.py` / `exec_dispatch_impl.py` / `n_muscle.py` 的 docstring 第一段就是准确职责), 并在表里注明"文件头原文", 不要留空或编。
- **环境实体不算逻辑节点**: `🌍 物理世界` 这类直接从清单里排除, 页注写清"已排除"。
- 分层归属用画布 y 带, 功能分栏可以按语义归组, 两者不一致时在图注写一句"分栏按功能归组, 子层位置见表", 免得用户交叉核时以为算错。

## 5. 交付目录卫生

- `*.pptx` 留在 .gitignore; 脚本 + 数据源 json 入库。
- 数据源 json 命名 `<主题>_数据源.json`, 与 deck 同目录, 内容含 `source`/`cfg_sha`/窗口参数/每根条起止/节点清单字段, 让"复核"变成读文件而不是重跑。
