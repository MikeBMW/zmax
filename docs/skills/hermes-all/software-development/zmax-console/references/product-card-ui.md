# 产品档位卡 (VEH.6.01/02/03) 自绘 UI

触发: 改「产品配置」页那三个档位选择控件 (550A/550B/550C)、调它们的观感,
或判据要量「选中是否一眼可见 / 文字有没有被裁」。

## 观感口径 (他说过"要绚丽", 复审后又改口 "内敛" —— 以后者是终稿)
- 档名大数字 **16pt** (21pt 被点名"太大了"), 卡 **252×104**; 编号 8pt / 中文后缀 9pt / 底行 9pt。
- 三档主色**低饱和 + 压暗**: 550A `#6E6AC8` · 550B `#3D8CA0` · 550C `#4A8F72`
  (原来的紫/亮青/荧光绿 = "太高调亮丽, 对比度太强")。
- 选中 = **深色卡 + 素白字** (`#E9F1F4`, 渐变 `a.darker(175/232/268)`);
  未选 = 更暗一档 (`a.darker(455)`) + 淡字。**选中感交给三件事**: 1.8px 浅色细边 +
  浅色「✓ 当前」小标 + 同卡明暗差 ≥40%。不要把选中卡做成"亮卡" —— 它会成为画面里最亮的块,
  复审会说"还是刺眼"。
- 对比度: 选中卡文字 9.6~10.6:1 (深底白字天然高, 他嫌的是亮卡刺眼, 不是白字);
  未选卡编号提到 ~6:1 (4.4:1 太淡)。
- 标题里**不要放 emoji**: Consolas 无字形时渲染成怪符号, 复审会当成游离脏东西。

## 版式 (single source)
- 常量只在 `_ProductCard` 类上写一份 (`W/H/PAD_L/PAD_R/BAND_CODE/BAND_BIG/BAND_SUB/PILL_W/PILL_H/*_PT`);
  `paintEvent` 与 `verify_product_card_ui.py` 都读 `V._ProductCard.*` —— 判据里再抄一份数字必然一红一绿。
- 绘制顺序: 两圈很淡的外光 → 斜向渐变底 → 顶部高光 → 描边 → 编号 (+选中时浅色小标) →
  大号档名 + 中文后缀 → 底行 → 焦点虚线框。QSS 只给 `background:transparent;border:none;`。

## 底行 = 版本号 · 运行位置 (全系统统一版本)
- 标签是「版本号」, 不是「版本段」; 值读 `update_checker.CURRENT_VERSION` (现 v5.50.751),
  **三档同一个号** —— 550A/B/C 只是产品配置标识, 不是版本号。bump 版本后界面自动跟。
- 底行第二段是 **运行位置** `products.<id>.runtime.label` (不是 `dev_profile.role`):
  `v5.50.751 · 本地运行` / `· VSCode 标定` / `· Intel 端侧`。
  唯一依据 `runtime` = `{location, label, host, host_ip, models, realtime}`; 三档语义:
  A=本地运行(本机) / B=VSCode 标定(本机) / C=量产·部署在 Intel 边缘机·全部模型·远程端侧实时。
  `dev_profile.deploy` 是同一件事的人话版, 两处要一起改。
- 旧口径不再用 role 做底行: role 与档名后缀同词时 (550C「量产版」) 会重复; 切到 runtime.label 后
  这个撞车自然消失, 但 ⑥b2 那条判据留着盯同类问题。
- 产品页只读值多一行「运行位置」(拼 `label · host (host_ip) · 模型 · 实时`, 可复制, tooltip 指回
  `products.<id>.runtime`)。**界面不许拿档位自己推主机/IP** —— 依据未写明就显示缺。

## 铁律 (踩过)
1. **必须仍是 `QRadioButton` 子类**: `verify_product_ui` 读 `_prod_btns[pid].text()/isChecked()/objectName()`
   和 `_prod_group.exclusive()`; 换 QPushButton 会一片红。
2. **判据/取证里 `setChecked` 会真写唯一依据**: `toggled → _on_product_pick → 原子写 active_product`。
   批量 setChecked 前对每张卡 `blockSignals(True)`, 跑完还原视觉状态再 `blockSignals(False)`,
   并断言跑前跑后 `zmax_product.json` sha256 不变。
3. 互斥组不能 `setChecked(False)`: 量"未选"外观就换另一张卡 setChecked(True) 当基线。
4. **像素判据用区域均值, 不用单像素** (单点会落在抗锯齿/光热点上); 比"小标 vs 卡面"这类局部特征时,
   参考块必须与目标块在**同一条横带** (渐变让左上/右下天然差 60)。
5. 选中/未选只能**同卡对比** (三色绝对亮度不可比): 阈值按内敛口径 ≥40%, 实测 +48%。
6. 排版用同口径常量复算: 断言底行与档名留白 ≥4px、每段文字右界在卡内 (卡宽 - 内边距)。
7. 卡固定 252×104 ⇒ 1280/1600/3200 窗宽都不裁不重叠; 三卡 + 「🔄 重新读取唯一依据」一行 ≈800px。

## 判据取证坑 (通用 Qt, 全都会造成"假红/假绿")
1. **没切过去的那一页根本没有布局**: 产品配置不是首屏时, 卡停在默认 640 宽 (只有 maxHeight 生效),
   判据会量到"640 宽 / 严重重叠"。判据先 `setCurrentIndex(产品配置页)` + `processEvents()` 再量。
2. **`setCurrentIndex` 索引没变不发 `currentChanged`**: 靠信号刷新的联动 (左树对号) 不会更新;
   设完初始页要显式调一次刷新函数。
3. **"初始状态"要在建页那一刻快照**: 判据后面会切来切去, 检查项里再读"当前页"量到的是最后一页,
   不是用户打开时看到的那一页。
4. **周期刷新会重建单元格**: 只在建卡那遍设置的 tooltip/高亮, 第一次静默刷新就全丢 ——
   这类装饰必须写在 `_fill()` 里 (建卡和刷新同一入口)。
5. 判据读表要按**列名**取值, 不按列序号: 表格加了列 (如 A/B/C 姿态) 后旧判据 index 全错,
   表现为"功能坏了", 实际只是判据过期。
6. 离屏图 OCR 读不全**不等于**字被裁: 先裁剪 + 3x 放大再 OCR (9pt 小字在 2x 图上会整行漏读),
   并靠"右界 ≤ 卡内宽"的字体度量断言保障。

## 判据命令
```bash
cd /home/ubuntu/zmax
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_product_card_ui.py   # 14/14
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_product_ui.py        # 47/47 不回归
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_config_center_seven_stars.py  # 21/21 (含 ⑳ 默认页/对号)
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_config_page_product_sync.py   # 8/8
```
`verify_product_card_ui.py` 14 项: ①自绘类/尺寸/编号 ②不重叠 ③文字不截断+底行留白 ④同卡明暗差≥40%
⑤浅色"✓当前"只选中卡有 ⑥a 档名同源 ⑥b 底行=版本号+runtime.label ⑥b2 底行不重复档名后缀
⑥c 三档版本号同一个且 == CURRENT_VERSION ⑥d 三档运行位置==唯一依据(.50/.50/.70, C 必须 edge+全部模型)
⑦选中卡文字对比度≥4.5:1 ⑧只读不写盘。
供复审的实渲图: `/home/ubuntu/.hermes/cache/scratch/render_cards.py` → `/tmp/prod_cards_now.png` (2x)。

## 实机验收
- 改完必须重启: 先 TERM 旧 pid, 再 `systemctl --user start zmax-studio.service`, 就绪靠
  `xdotool search --onlyvisible --name "XSpace ZMAX"`, 再 `printf 'config\n' > /tmp/zmax_nav_cmd`。
- **现场截图取不到时不要抢焦点**: 用户的浏览器长期压在最上层, `windowraise` 抬不上来,
  `xdotool` 点击会真的落到他的窗口里。改用离屏 `render_cards.py` 导 2x 图 + OCR 当证据,
  并在回报里直说"现场图未取/为什么"。
