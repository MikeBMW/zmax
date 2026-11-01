# 🏷 控制台顶栏标题 = 产品标识 · 调试同源判据

来源: 老倪 2026-10-15 原话 ——「控制台 最上边框 显示 的 XSpace Studio的一行字 改成 XSpace ZMAX 550A 或者 根据配置中心
产品配置, 显示 具体的 550B 或 550C  左侧边栏 保留 v5.50.730的版本显示; 不用特意显示 非调试模式, 但是你要保证,
当我用 vscode debug模式调试时, 打开的也是同一个版本; 如果保证不了同一个版本, 则关闭已经打开的模式, 重启进入调试模式」

## 标题

* **标题 = `XSpace ZMAX <产品号>`**, 产品号 ∈ {550A, 550B, 550C}。
* **产品号真源 = 配置中心「产品配置」同一份** `config/platform/zmax_product.json` 的 `active_product`
  (同文件还有 `products` 字典 + 各产品参数)。切产品写的就是这一份 ⇒ 标题与配置中心天然同源, 不是两处各写一份。
* **标题不含版本号**, 也不含 `[W-01]` 机位号与「非调试模式」。
* **版本号只留侧栏品牌位** `QLabel("Z-MAX vX.Y.Z")` (+ 状态栏 / 关于框)。改标题时**不许**顺手删侧栏版本
  (老倪明确「左侧边栏 保留 v5.50.730的版本显示」)。
* **单一出处**: 标题只经 `_console_title()` / `_active_product_id()`; 任何地方 `setWindowTitle("XSpace ZMAX 550B")`
  写死都是错的 (产品号一改, 那处就成了假显示)。真源读不到 → 先明报一行再退回 `550A` (不静默)。
* **标题跟随真源**: `_title_watch` QTimer 每 3s 探一次真源 mtime, 只在变了才 setWindowTitle ⇒
  在配置中心切产品**不必重启控制台** (实测 0.5s 跟到)。

## 窗口匹配串 (改格式的最大陷阱)

统一用 `XSpace ZMAX` (跨产品号稳定)。已收口的调用点 —— 全都要同步改, 否则静默失灵 (不报错, 只是永远找不到窗口):

| 位置 | 用途 |
|---|---|
| `tools/zmax_open.py` `WIN_CONSOLE` | 打开/激活控制台窗口 |
| `tools/gui/launch_studio.sh` `xdotool search --name` | 已有实例 → 激活窗口 + 弹配置中心 |
| `tools/gui/simulink_module.py` (3 处 `"XSpace ZMAX" in _ln` + 标题基名 fallback) | wmctrl 几何解析 / 保存恢复原标题 |
| `verify_no_autostart.py` · `verify_station_button.py` · `verify_task_scene_matrix.py` · `verify_3d_follow.sh` · `verify_3d_geom_fix.sh` · `verify_3d_scene_episode.sh` | 等窗口就绪 / 几何比对 |

改标题格式后必跑: `grep -rn 'XSpace ZMAX\|wmctrl\|xdotool' --include='*.py' --include='*.sh' tools/` 逐条确认。

## 调试档与运行档必须同源

老倪硬要求: 「用 vscode debug 调试时, 打开的也是同一个版本」。

* **判据 (可证伪)**: 本实例的 `studio.py` 与 `.vscode/launch.json` 里 F5「🚀 全新调试进程」的 `program`,
  **md5 必须相等** ⇒ 调试开的和眼前看的是同一份文件、同一个版本 (版本号/产品号都从同一份真源读)。
* 一致 ⇒ **一个字的提示都不打**。旧版做法是把「⚠️ 非调试模式 — 断点不会生效」写进窗口标题 + 状态栏,
  老倪要求「不用特意显示 非调试模式」⇒ 已下线 (提示改为只放进侧栏版本 QLabel 的 tooltip)。
* 不一致 ⇒ 状态栏 + stdout **明报**两边的路径与 md5 (那才是真会调试到另一个版本)。
* 启动时自动做 (studio.py `_maybe_warn`; F5 启动 2s 后握手已完成, 不会误判)。
* 残余风险点: 旧 worktree 里的陈旧 `studio.py` 副本 (如 `external/lerobot-smolvla-lew/tools/gui/studio.py`)。
  若哪天它的 `.vscode/launch.json` 指向自己, F5 就会开旧版 —— 所以 verifier 里有一条专门扫全仓
  `{external,zmax_data}/*/.vscode/launch.json`, 断言没有第二条指向**别的** `studio.py` 的调试配置。

## 一键复核 (要证据就跑这个)

```bash
cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/verify_console_title_product.py --follow
```

9 条 (全部读真源/读真窗口, 不读代码印象):

1. 产品真源可读且合法 (`active_product` ∈ 550A/550B/550C)
2. 标题单一出处 `_console_title()`, 无硬写字面量, 老标题硬串 0 处
3. 标题模板读真源而非写死产品号
4. 侧栏品牌版本在位且与 `update_checker.CURRENT_VERSION` 同号
5. **F5 调试目标 == 在役 studio.py (md5) ⇒ 调试同一版本**
6. 全仓无第二条指向别的 `studio.py` 的调试配置
7. 实机窗口标题 == `XSpace ZMAX <active_product>` (wmctrl/xdotool 读真窗口)
8. `--follow`: 真源切 550A → ≤8s 标题跟过去
9. `--follow`: 真源还原 + 回读 + 标题跟回 (带字节备份, 测完必还原)

## bump 版本时

* `tools/bump_version.py` 对标题**只做断言** (断言不许回退成「XSpace Studio — Z-MAX vX.Y.Z」的老写法), 不再替换 —— 标题里没有版本号可替换。
* `tools/verify_version_sync.py` 的「窗口标题」两处同步点已下线; 版本号同步点剩: 侧栏品牌 QLabel · changelog 前缀 ·
  `update_checker.CURRENT_VERSION` · 状态栏/关于框字面量。标题↔产品真源归 `verify_console_title_product.py` 判。
* 窗口标题相关改动**不**触发版本号变更 (老倪: 版本号不自主升级, 只按他指定)。
