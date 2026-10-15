# 控制台 hero 按钮精简 (2026-10-15 老倪: 「右上角按钮 smolvla_lew/升级等，就保留一个分享功能，其余按钮都删掉(如果功能还有用，则备份一下)」)

## 现状 (基线)
首页 hero 行右上角**只准有「📱 分享」一个按钮**。要再加按钮先问老倪。

## 删掉的 7 个 + 功能去向 (一个都没丢)

| 原按钮 | 现入口 |
|--------|--------|
| ● smolvla_lew | 菜单「关于 → 🧪 GUI 工程仓库 (smolvla_lew)」(`act_lew_repo`) |
| 🔄 同步到GitHub | 菜单「📤 上传修改 (推送到 GitHub)」(`_sync_to_github` 函数保留) |
| ⬆ 升级 | 菜单「关于 → 🔄 检查更新」(`check_updates`) |
| 🌐 Z-MAX | 首页「产品大屏」卡 (另有 CICD 页) |
| 📦 版本同步 | 首页「版本同步」卡 |
| 📋 解决方案v1.0.4 | 菜单「文档 → L2·方案层文档 → 解决方案 MD」(`_open_spec_doc`) |
| 📊 PPT汇报 | 菜单「文档 → 品牌·竞品参考」(`open_ppt_with_libreoffice`) |

- 备份(含原样可贴回代码块 + 去向表): `zmax_data/backups/studio_hero_buttons_20261015.py`；
  入库副本 `docs/notes/studio_hero_buttons_backup_20261015.py` (zmax_data/ 被 gitignore)。
- 恢复: 贴回 `HomeWidget._hero()` 里 `row.addStretch()` 之后、分享按钮之前。
- 判据: `tools/verify_hero_buttons.py` (离屏建真控件树枚举 hero 行按钮 + 检查 7 个替代入口都在 + 备份件在位)。
  收尾必须 `os._exit(...)`: HomeWidget 构造会拉起 `_HwFetcher` QThread，正常退出会 join 卡住。
