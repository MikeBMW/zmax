# 🧹 首页 hero 「右上角按钮排」只有 📱 分享 (2026-10-15 老倪)

老倪原话: 「主控制台, 右上角的 按钮 smolvla_lew, 升级等, 就保留一个分享功能, 其余按钮都删掉
(如果功能还有用, 则备份一下)」

## 现状 (基线, 不要往回加)

`studio.py::HomeWidget._hero()` 的标题行 (`row.addStretch()` 之后) **只允许一个** 📱 分享按钮
(`_show_share_qr`)。已删的 7 个: ● smolvla_lew · 🔄 同步到GitHub · ⬆ 升级 · 🌐 Z-MAX · 📦 版本同步 ·
📋 解决方案v1.0.4 · 📊 PPT汇报。以后要加任何新按钮, **先问老倪** —— 他的口径是首页极简。

## 删按钮前必须做的两件事

1. **逐个核“还有什么别的入口”** (删按钮 ≠ 删功能)。本仓的既有入口: 菜单「📤 上传修改」(同步到GitHub) ·
   菜单「关于 → 🔄 检查更新」(升级) · 首页「产品大屏」卡 (官网) · 首页「版本同步」卡 ·
   菜单「文档 → L2·方案层文档 → 解决方案 MD (v1.0.6)」(比按钮里的 v1.0.4 更新) ·
   菜单「文档 → 品牌·竞品参考 → 品牌注册材料 PPT」。真有唯一入口的 (那个 `● smolvla_lew` 仓库链接),
   就改挂到菜单再删按钮 —— 不能不声不响地丢能力。
2. **逐字备份 + 写清恢复位置**: 备份放 `zmax_data/backups/studio_hero_buttons_<日期>.py`,
   含头部「功能去向表」与 `HERO_BUTTONS_SOURCE` (原样可贴回 `row.addStretch()` 之后、分享按钮之前)。
   工作函数 (`_sync_to_github` / `_open_spec_doc` / `_show_share_qr` / `open_ppt_with_libreoffice`) **不删**,
   否则备份也接不回去。

## 判据 (要证据, 不看源码印象)

```bash
cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/verify_hero_buttons.py
```

离屏建**真控件树** (`studio.HomeWidget()._hero()`), 5/5: ① hero 行按钮文本枚举 == `['📱 分享']` ·
② 7 个被删标签一个不残 · ③ 分享 `clicked` 有接收者 (不是删剩的死按钮) · ④ 7 个功能的替代入口都在 ·
⑤ 备份件在位且含全部被删按钮。

⚠️ 两个坑: (a) `HomeWidget()` 构造会拉起硬件采集 `QThread` ⇒ 脚本末尾必须 `os._exit()`(否则退出卡在 join);
(b) 离屏跑 Qt 会刷 `Unknown property cursor` (QSS 里的 `cursor` 不是合法属性) —— 判据行用 `grep` 过滤。

## 现场取证 (视觉/像素, 老倪会把画面当结果)

* 该窗口可能开在**第二块屏** (eDP-1 1920x1200 @+0+0 与 HDMI-1-0 1920x1080 @+1920+0):
  别用 `xdotool search ... | head -1` 拿到的 id 去截图 (会匹配到 Qt 的隐藏窗口, 截出来是错的);
  用 `wmctrl -lG | awk '/XSpace ZMAX/{print $3,$4,$5,$6}'` 的 `X Y W H` 喂 `scrot -a X,Y,W,H`。
* 纯色 pill 的**像素计数**比 OCR 可靠: 各按钮底色 C_PURPLE #bc8cff (分享) / C_GREEN #3fb950 (同步) /
  C_ORANGE #d29922 (升级·版本同步·解决方案·PPT) / C_CYAN #39d2c0 (官网)。hero 行只应出现一个紫色 pill。
* 小字 pill OCR 技巧: 裁 pill 区域 → 转灰度 → `ImageOps.invert` → 放大 6x →
  `tesseract --psm 7 -l chi_sim+eng` (emoji 会读成噪声字, 中文标签能读出来)。
