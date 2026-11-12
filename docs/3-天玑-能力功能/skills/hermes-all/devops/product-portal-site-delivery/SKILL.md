---
name: product-portal-site-delivery
description: Use when 建/改对外产品门户站并上线 (产品向·非技术页).
version: 1.0.0
author: hermes-agent
license: private
metadata:
  hermes:
    tags: [website, portal, landing-page, nginx, deploy, marketing]
    related_skills: [live-service-change-discipline, popular-web-designs, deliverable-doc-authoring]
---

# 对外产品门户站：设计 → 上线 → 回读

## When to Use
- 「更新 datadrive.world 的内容」「重新设计官网」「对标特斯拉/主流科技网站」「首页不要偏技术，要包装成专业科技公司」
- 站点源码不在本机（ECS `/www/wwwroot/<domain>` 这类 bt 面板目录），只能在线改
- 要在保留原技术站的前提下，新做一个产品向首页

## 硬规则
1. **首页产品化，不堆参数。** 顺序固定：品牌主张 → 产品阵容 → 应用场景 → 平台/进化 → 成果数字(≤4 个) → 公司 → 预约 → 页脚。技术细节全留给技术站。
2. **原技术站一字不改地留着，但它不占 `/tech.html`。** 旧 `index.html` 先按时间戳备份（`index_backup_<YYYYmmdd_HHMM>.html`），再原样复制成 **`/tech-legacy.html`**（只加一个「← 返回官网」fixed pill）；`/tech.html` 归新的技术中心门页（见下节）。所有技术子页 URL 保持原路径可访问。三个入口的关系写死在页脚与门页卡片里，别让旧首页和新门页抢同一个 URL。
3. **文案只用站上已有的事实 + 用户确认过的数字。** 精度/良率/节拍/UPH/产线型号/专利数可以沿用旧站原文；**不编电话、不编邮箱、不编客户名**，联系按钮用站上已有的电话做 `tel:` 链接。
4. **版本号只用用户给的号**（例：5.50.770），只出现在「平台」段一行和页脚，不要伪造产品型号。
5. **手机优先。** 390px 宽不许横向溢出，首屏文字不被装饰图压住，导航折叠成 logo + 主 CTA。
6. **零外部依赖。** 不引 CDN 字体/JS/图标库，用系统字体栈 + 内联 SVG，国内网络与弱网都能秒开。

## 页面骨架（单页 + 锚点，够用且好迭代）
- 固定 nav：logo / 产品 / 场景 / 平台 / 公司 / 技术中心 / 主 CTA（滚动后加深）。
- Hero：eyebrow + 一句主张（第二行用 dim 灰）+ 一句副文案 + 2 个 CTA + 4 个品牌数字条；右侧抽象视觉。
- 产品阵容：2 张卡片（旗舰 / 基线），每张 = 图形区 + tag + 标题 + 2 行说明 + 3~4 个能力 chips + 箭头。
- 场景：6 个小卡 + 1 条横条（真实产线 / 工序数）+ 一个跳技术页的按钮。
- 平台：L2→L3→L4 三块 + 进度条 + 「当前平台版本 X.Y.Z · 端侧在线升级」。
- 成果：4 格数字条（大字号 + 小标签）。
- 公司：浅色段（#f5f5f7）形成节奏对比，3 条事实 + 一行资质。
- 预约：居中大标题 + 两个按钮；页脚放版权 / 体系文件号 / 版本号。

## 制作与本地自验（必须过再上线）
```python
# browser_exec：单文件本地预览
new_tab("file:///.../newsite/index.html"); wait_for_load()
cdp('Emulation.setDeviceMetricsOverride', width=1440, height=900, deviceScaleFactor=1, mobile=False)
js("window.scrollTo({top:1980,behavior:'instant'})"); time.sleep(1.2); capture_screenshot()
cdp('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=2, mobile=True)
js("document.documentElement.scrollWidth > window.innerWidth")   # 必须 False
```
- **逐段截图**（首屏 / 产品 / 场景 / 平台 / 成果 / 公司 / 页脚），不要只看首屏就发布。
- 改完再截一轮：每次改 CSS/SVG 都用截图确认，不要靠读代码判断好不好看。

## 部署（备份 + 原子替换）
用 paramiko（托管 venv 缺 pip 时先 `python -m ensurepip --upgrade` 再 `python -m pip install paramiko`）：
1. `cp -a index.html index_backup_<stamp>.html`
2. 读远端旧 `index.html` → 改 title → 注入返回 pill → 写 `tech-legacy.html`（旧首页副本）；`tech.html` 另传新版门页
3. 上传到 `index.html.new_<stamp>` → `mv -f` 覆盖（避免半截文件被访问到）
4. `nginx -t` + 远端 `curl -s -o /dev/null -w '%{http_code} %{size_download}' http://127.0.0.1/`
5. 线上 `https://<domain>/` 再跑一遍桌面/手机截图回读。

## 坑（都踩过）
- **绝不用 IntersectionObserver 给全页内容加 `opacity:0` 入场。** 段落还在视口外时就是全黑，截图、快速滚动、JS 被拦都会看到空白页；营销页内容不能依赖滚动触发。要动效只给首屏做 CSS keyframes。
- **没有产品实拍就别硬画机器人线稿。** 几笔 stroke 缩到卡片里就成乱码线条。改用抽象母题：同心环 + 蓝图式光模块（金手指细线）+ 巨大 ghost 型号字 + 刻度/尺寸线。
- 站点根目录的 `frame*.jpg` 多半是 64×64 推流缩略图，**先看尺寸再用**，别把缩略图当首图。
- ghost 型号字（SVG `<text>` 130px+）基线太低会被卡片上沿切掉；字号 ~100、`y` 留足 ascent。
- 产品卡正文会挤爆固定 `min-height`：用 `display:grid; grid-template-rows:1fr auto` 让正文决定卡片高度，别用 `align-items:flex-end` + 固定高。
- 中文 Windows 下 `curl -o /dev/null -w '%{size_download}'` 可能回 0B（exit 23）；改用 `curl -sI | grep -i content-length` 或远端 `127.0.0.1` 回读。
- 老站若带登录闸（`auth.js` / login overlay），`tech-legacy.html` 保留原样即可；返回 pill 要 `z-index` 拉满 + `position:fixed`。

## 技术中心统一视觉（老站几十个自研页）
老站常有 100+ 个自研页（3D 场景、看板、控制台），**不要逐页重写皮肤**——它们各自有 canvas/iframe/固定控件，重排必坏。做法分两层：
1. **新做一个 `/tech.html` 技术中心门页**（与门户同一套 tokens/nav）：分类卡（产品本体/场景产线/数据平台/研发体系/工程运维/演示控制台）+ 关键词搜索（前端过滤，`count` 实时回显）+ 每卡显示真实路径。旧首页原样存成 `/tech-legacy.html`，页脚与「经典技术站」卡片都指过去。
2. **给老页注入统一品牌浮标**：`<div id="zmax-dock">` 固定在左下角（两个 pill：← 官网 / 技术中心，`z-index:2147483647`、`backdrop-filter`），插在 `</body>` 前。**只加 fixed 图层、不改任何布局**，全屏 canvas 页也不会坏。注入前先 `grep id="zmax-dock"` 防重复，并把原页 `cp` 进 `_dockbak_<stamp>/`。
- 注入脚本用 paramiko 逐页 `get → 改 → put`（60 页≈1 分钟），别用 sed 一锅端；抽查 3 个不同形态的页（3D 场景 / 看板 / 纯文档）截图确认浮标不挡关键控件。
- **窄屏下 nav 的第二个按钮会溢出**：`@media (max-width:680px){.nav .right .btn-primary{display:none}}`，只留「← 返回官网」。改完必须 390px 重截图看右边缘有没有被裁。

## 公开规则页（把内部评分表改写成社会可读的赛制页）
触发：手里有一份内部评分表（xlsx/Word，含否决项、分项权重、指标尺度），要对外发布成参赛者能照着准备的规则页。

页面结构（按此顺序，读者不需要技术背景）：① 这是什么比赛（4 类活，用行业外的词说清场景）→ ② 一票否决（3~5 条，不占分但决定能否计分）→ ③ 总分构成（3 个大数字块）→ ④ 基础项拆成 N 个「动作单元」表（编号 / 考什么 / 满分条件，每单元独立可练、独立计分、赛前可声明放弃）→ ⑤ 泛化项 → ⑥ 成本口径（把公式写出来：`16×(最低价÷本方价)`）→ ⑦ 及格线 / 等级 / 排名并列规则 → ⑧ 备战顺序（先稳→再准→再顺→最后抗）。

**脱敏红线（用户明确要求「对外大范围宣传，不要公布我们的技术」）**：
- 不出现：工艺段划分、客户与产线名、自研精度/良率/UPH 等能力数字、模型名与权重、内部条目数（元任务 N 条、段表、节点数）。
- 只留赛事判据：现场公布的作用力上限、允许的摆放偏差、各单元限时——这些是考核条件，不是我们的能力。
- 内部元任务翻译成大众动作词：识别定位 / 取放 / 搬运交接 / 对准插入 / 拔出回收 / 检测分拣 / 异常处置 / 换型自标定 / 记录追溯 / 节拍稳定；保留「可单独训练、单独计分」的元任务本质，不解释内部实现。
- 评分框架继承原表（100 = 基础 60 + 泛化 20 + 成本 20；及格 = 基础项 ≥36；A≥90 / B80~89 / C70~79 / D<70；同分依次比基础→泛化→成本；一位小数），只改表述不改口径。

**新页上线后要把入口接进现有 nav**：对 `index.html` 与 `tech.html` 各做一次字符串替换插 `<li>`。
- 🔴 锚点串必须与目标页真实写法一致——同一段 nav 在门页里带 `style="color:#fff"`、在首页里不带，硬编码任一种都会「anchor not found」**静默跳过**。改完各页 `grep -c 'challenge.html'` 必须都是 1。
- 小标签（`赛项一` 这类 chip）在窄屏会被拆成两行：`.card .t i{white-space:nowrap}` + 680px 下 `.card .t{font-size:14px}`。

## 对外“元任务 / 挑战赛规则”页 + PDF/Excel 导出
把内部评分表改成社会可读的公开版时，固定结构：**先定义（是什么）→ 场景（在哪考）→ 规则（怎么算分）→ 十个元任务（逐条可展开）→ 泛化/成本/等级 → 怎么准备**。导航标签用「元任务」（用户口径），不要写成内部术语如“元任务预测/状态空间”。
- **元任务的大众定义四问**：输入是什么 / 输出是什么 / 什么算完成 / 怎么证明完成。每项给“定义·考核点·满分条件·证据”四行，用 `<details>` 手风琴（默认开第一项）。
- **脱敏红线**：不写工艺段、客户/产线名、自研精度良率 UPH、模型名、内部元任务条数；只保留赛事判据（现场公布的作用力上限、允许偏差、单元限时）。
- **派生件必须可下载**：PDF（元任务定义）+ Excel（评分表）由同一份 Python 数据表生成，页面顶部与底部各放一对下载按钮（`/downloads/<名>.pdf|.xlsx`）。
  - PDF：reportlab + `TTFont("CN", r"C:/Windows/Fonts/simhei.ttf")`；表格用 `Paragraph` 包单元格才会自动换行。**© 在 simhei 里取不出字形**（抽取文本变 \u0000），改成「版权所有」。
  - Excel：openpyxl 四页（评分表 / 元任务定义 / 一票否决 / 使用说明）；黄色输入格 + `=SUM` 小计 + 总分/及格/等级公式。**等级公式必须引用“总分”那一行**——在循环里用 `r+2` 算行号会指到自己，先把 `total_row = r` 存下来再拼公式。
  - **真实比赛用表要做成「元任务 × 场景」矩阵**（横向 MT-01..MT-10，纵向四个赛项），每格 0~6，不适用的格填「—」而不是 0；行得分 = 该行数值平均（`AVERAGE` 自动忽略「—」与空），基础任务 = 四场景得分均 ×10（0~60）。配套页：②适用矩阵 ③泛化+成本+汇总（`='①矩阵评分表'!B11` 跨表引用）④一票否决 ⑤定义 ⑥操作说明（赛前/赛中/赛后 12 步）。
  - **公式必须用 LibreOffice 实算验证，不能只读公式串**：本地 openpyxl 填一组已知分值 → base64 传到有 soffice 的 Linux 机 → `soffice --convert-to xlsx` 重算 → 从解包 `xl/worksheets/sheetN.xml` 里取 `<v>` 回读。实测口径：全 5 分 ⇒ 基础 50、总分 90、A 级；全 6 分 ⇒ 基础 60。
  - 坑：`openpyxl` 清空输入时不要把存放公式的单元格一起 `=None`（曾把成本小计的公式格当成输入格清掉，结果小计只剩一项，看着像公式错）。
  - 导出物验一遍：`pypdf` 抽文本核页数与十条定义是否齐；`openpyxl` 回读公式串确认引用正确（不是只看文件大小）。
- 旧路径（如 `/challenge.html`）改成 302 式跳转页（`<meta http-equiv=refresh>` + 可点链接），避免已发出去的链接失效。

## 验收口径（全过才算完）
- 线上 `/`、`/tech.html`、`/tech-legacy.html` 都 200 且 Content-Length 正确；技术子页抽查 ≥5 个仍 200。
- 桌面 1440 + 手机 390 各截图确认：无空白段、无横向溢出、无被裁文字。
- 回复里报出：域名、版本号位置、备份文件名。不叙述过程。
