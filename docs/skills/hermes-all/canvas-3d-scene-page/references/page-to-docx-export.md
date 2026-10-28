# 页面工艺卡 → Word(.docx) 一键导出

活页面（一页 N 张三维工艺卡）当内容唯一依据, 一键导出成能发给甲方的 `.docx`。
**不用 md→LibreOffice 那条链**: 交互页面的正文只存在于页面里, 走 md 就得抄一份, 抄一份就必然走形。

## 链路

```
页面按钮 → 收集 CARDS + 每个 canvas 的 toDataURL('image/png')
        → POST /api/<page>/docx  (同端口, JSON)
        → 服务端 python-docx 排版（只排版, 不存文字）
        → 返回 application/vnd.openxmlformats-officedocument...  + blob 下载
```

## 服务端路由（挂在既有服务上, 只重启一次）

```python
if p == "/api/autolight/docx":
    try:
        from autolight_docx import build_docx      # 惰性 import, 不拖慢服务启动
        _d = build_docx(body)                      # body = 前端 JSON
        _fn = "autolight_process_cards_%s.docx" % time.strftime("%Y%m%d_%H%M%S")
        self._send(200,
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                   _d, {"Content-Disposition": 'attachment; filename="%s"' % _fn})
    except Exception as _e:
        self.log_message("docx FAIL: %s: %s", type(_e).__name__, _e)
        self._json({"ok": False, "err": "%s: %s" % (type(_e).__name__, _e)})
```

- `Content-Disposition` 用 **ASCII** 文件名; 中文名由前端 `a.download` 定（否则要 RFC 5987 编码, 浏览器行为还不一致）。
- 失败回 **JSON 错误**, 前端才能把原因显示给用户（回 HTML 错误页前端只会说「HTTP 500」）。
- 排版模块放独立文件（如 `tools/autolight_docx.py`）, 它必须能独立跑 `python <mod>.py out.docx` 做离线自检。
- **用服务自己的解释器**（`systemctl show -p ExecStart --value <unit>` 里那个 venv）跑自检和 py_compile —— 服务端依赖装在那个环境里, 系统 python 不一定有 `docx`。

## python-docx 排版要点

| 要点 | 做法 |
|---|---|
| 中文不回落 | `st = doc.styles['Normal']; st.element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')`, 且**每个 run** 也设一次（`run.font.name` + `rPr.rFonts w:eastAsia`） |
| 页面 | A4 `Cm(21×29.7)`, 边距 `2.0 / 1.9 cm` |
| 标题 | `add_heading('',1)` 后自己 `add_run` 上色, 别用默认蓝 |
| 参数表 | `add_table(0,2)` + `Table Grid` + 首列 `_shade(cell,'F2F5F8')`, 每行 `space_after=Pt(1)` |
| 卡片分页 | 每卡前 `doc.add_page_break()`; 页数 = 1 封面 + N 卡 + 1 说明 |
| 嵌图 | `doc.add_picture(io.BytesIO(png_bytes), width=Cm(16.6))`, **只给 width**, 高度按 canvas 宽高比自动 |
| data URL | 正则 `^data:image/(?:png\|jpeg);base64,(.+)$` 取组 1 再 `b64decode`; 不匹配就当无图 |
| 页面里的 HTML | 正文含 `<b>` / `<span>` ⇒ `re.sub(r'<[^>]+>','',s)` + `html.unescape`, 否则 Word 里全是标签 |
| 图片坏了 | 每张图单独 `try/except`, 失败只加一行灰色备注, 不让整份导出失败 |

## 文档结构（按这个顺序, 甲方能直接看）

1. 封面：标题 / 版本（协议号）/ 甲乙双方 / 坐标系与关键参数一行 / 内容说明（含「示意非施工图」）
2. 工艺路线总览表：序号 · 步骤 · 阶段（一眼看全流程）
3. 节拍与性能口径：CT/UPH/OEE/仪表数量/信号方向
4. 每张卡（分页）：三维截图 + 图题 `图 N-1 …（三维窗口截图）` → 动作分解（**协议原文逐句**）→ 技术细节（项目符号，每条带条款号）→ 参数与口径表 → 关键词 → 来源条（`§2.2 第 n 步 / §2.1 / §2.3` 的具体条款号）
5. 导出说明：数据来源 / 协议依据 / **三维视图坐标约定（注明「视图约定, 协议未规定」）** / 三维说明 / 生成时间 / 导出入口

图题里不要写「坐标系同 /ar」这类视图约定 —— 图题是图的身份，不是协议结论；客户问「哪一条规定的」时答不上来。

## 前端侧

```js
function snapOne(c){                       // 重绘一次再截, 保证图上是最新状态
  const v=views.find(x=>x.card===c.n); if(!v) return '';
  v.resize(); v.cam(); v.LQ.length=0; v.TQ.length=0;
  v.scene(v,(performance.now()-T0)/1000); v.paint();
  return v.cv.toDataURL('image/png');
}
const r=await fetch('/api/autolight/docx',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({meta:{ts,url:location.href}, cards:CARDS.map(c=>({...c,img:snapOne(c)}))})});
const blob=await r.blob();
const a=document.createElement('a');
 a.href=URL.createObjectURL(blob); a.download='工艺卡_'+n+'卡_'+stamp+'.docx';
 document.body.appendChild(a); a.click(); a.remove();
```

- 按钮要**导出中… / 直接给结果**: 成功提示写清「N 张 + 文件名 + KB」, 失败把 HTTP 状态与后端 err 原文显示在页面提示条里。
- 全量按钮 + **每卡小按钮**（`data-doc` + 事件委托）都走同一个函数, `exportDocx(no?)`, 别写两套。

## 验证（交付前必做, 三步）

```bash
# ① 回读: 段/表/图片数、标题全不全
python -c "from docx import Document; import zipfile,sys; p=sys.argv[1]; d=Document(p); z=zipfile.ZipFile(p); \
print(len(d.paragraphs),len(d.tables),[n for n in z.namelist() if n.startswith('word/media')])" out.docx

# ② 转 PDF 验页数必须 == 1+N+1
soffice --headless --convert-to pdf --outdir /tmp/chk out.docx
pdfinfo /tmp/chk/out.pdf | grep Pages

# ③ 渲染一页, 确认图真的在页面上(不是空框)
pdftoppm -r 70 -f 2 -l 2 -png /tmp/chk/out.pdf /tmp/chk/p
python - <<'PY'
import numpy as np; from PIL import Image
 a=np.asarray(Image.open('/tmp/chk/p-02.png').convert('RGB')).astype(int)
 bg=(abs(a[:,:,0]-8)<10)&(abs(a[:,:,1]-13)<10)&(abs(a[:,:,2]-18)<12)   # 视图背景色
 rows=[y for y in range(a.shape[0]) if bg[y].sum()>a.shape[1]*0.5]
 print('img band rows', (min(rows),max(rows)) if rows else None, '→ cm', (max(rows)-min(rows))/70*2.54 if rows else 0)
PY
```

再核两个数：图片 band 宽度 ≈ 16.5 cm（`width=Cm(16.6)` 生效）、页面右侧留白 ≈ 2.1 cm（没超边距）。
页面本身回读 `http=200` 且 `bytes` == 磁盘文件大小; 老的 `/ar` 等页面字节数一字未变。

```bash
# ④ 溯源审计（比页数更重要）: 每卡动作分解逐字比协议原文 + 扫自拟术语
python - <<'PY'
from docx import Document
d=Document('out.docx'); ps=[p.text for p in d.paragraphs]
for i,t in enumerate(ps):
    if t=='动作分解': print(ps[i-1][:20],'||',ps[i+1])
PY
text=$(python -c "from docx import Document;print('\n'.join(p.text for p in Document('out.docx').paragraphs))")
for w in 力控 划痕 污点 IL 节拍解耦 先进先出 第七轴; do echo -n "$w:"; echo "$text" | grep -c "$w"; done
```

比对基准是**用户贴的协议原文**，不是生成脚本里的字符串；命中禁用词要么删，要么确认它是协议里本来就有的词（如「洁净型机器人」）。

## 坑

| 坑 | 症状 | 修法 |
|---|---|---|
| 服务端复制一份工艺文字 | 改了页面导出还是旧内容 | 文字只在页面 `CARDS`; 服务端只接收+排版 |
| 不设 `w:eastAsia` | Word 里中文变等线/宋体, 与页面观感两回事 | 样式和每个 run 都设 `w:eastAsia` |
| 把 `data:image/png;base64,` 整串 b64decode | `binascii.Error: Invalid base64` | 正则先取组 1 |
| 图片宽高都预先固定 | 图被拉伸, 圆点变椭圆 | 只给 `width`, 高度按 canvas 比例 |
| 无头浏览器连点导出 | 第 1 个文件落盘, 后面的不见了, 看着像功能坏了 | Chrome 拦截**无用户手势的连续下载**; 判断成功用 `fetch` 看 `status` + `blob.size`, 别拿 Downloads 目录判 |
| 只核「文件生成了」就交付 | 页数/图片数不对或图是空框 | 上面三步验证都跑 |
| 只核页数不核文字 | 页数对、图也在，但卡片里写的是自拟内容 | 跑④溯源审计：回读每卡动作分解对协议原文 + grep 自拟术语 |
| 改了排版模块没重启服务 | patch 了 `.py` 版式/图题却没变，以为 patch 没生效 | `from x_docx import build_docx` 首次请求后就进了 `sys.modules` ⇒ 改完排版模块**重启一次**再导（HTML 热读不适用于 `.py`） |
| 交付件把视图约定写成协议内容 | 图题写「坐标系同 /ar」，客户问哪条规定的 | 图题只写「三维窗口截图」；坐标系/示意比例放导出说明并注明「视图约定，协议未规定」 |
| 自检用系统 python | `ModuleNotFoundError: docx` | 用服务自己 venv 的解释器 |
