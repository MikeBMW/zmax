# 控制台数据同步与一致性 (数字不许写死 + 单库真源 + 审计)

适用范围: `tools/gui/studio.py` (1.1MB 主窗口) 及各功能页。单一真源 = `data/database/zmax/zmax_engineering.db`。

## 铁律: 界面上的数字一律从库现算, 不写字符串

- 手写过计数必然漂移 (实测: 参数中心卡写死 '162 个可改数字', 库里已 645 ⇒ 界面说谎)。
- 用 `studio._live_counts()`: 一次算好 `特征 / 子系统 / 功能 / 参数 / 参数分组 / 功能·sys0|sys1|sys2 / 画布节点 / 画布连线`,
  按**库 mtime** 做进程内缓存 (`_LIVE_CACHE`) ⇒ 库重建后自动失效, 不必重启 GUI; 库不在回退 0 并由文案兜底。
- 新卡片/页要计数时接它, 别再拼字符串。
- 改参数/真源后记得 `python3 tools/engineering_db.py build` + `check`, 否则 GUI 读到的还是旧库。

## 口径对照表 (同一句话可能有多个都对的分母, 判据/文案必须选对)

| 说法 | 真值 | 来源 |
|---|---|---|
| 画布节点 | **89** | 画布真源 `data/database/zmax/sources/canvas/state_space_obs.json` 的 nodes (含 15 条 row_bg 背景带) |
| 画布节点(库口径) | 74 | `canvas_nodes` 表 = 89 − 15 背景带 |
| 画布连线 | 184 | 两边一致 |
| 功能 | 74 全局 | `functions`; 按系统: sys2=30 / sys1=4 / sys0=27 / plat=13 |
| 参数 | 645, 7 分组 | `params`; 分组名 = 注册表 `CAT_CN` (标定/画布/代码/产品性能/运行开关/空间点/号位示教点) |
| 特征 / 子系统 | 18 / 4 | `product_features` / `subsystems` |

## 一致性体检: `tools/audit_console_consistency.py`

- 已挂进 `tools/run_gui_verifiers.sh` (条目 `console_text_sync`), 改完界面就跑。
- 它抓 GUI 源码里**带数字的文案**, 逐条对库真值; 输出真值表 + 不符清单 (`文件:行 文案 → 值 (真值 X)`)。
- 写这类审计的假阳性剔除规则见 `pyqt-gui-auto-verification/references/assertion-and-evidence-pitfalls.md` 第 6 条
  (版本历史长行 / 解释性叙述 / 合法多分母 / 演示与状态行)。
- 🔴 审计用来**找真缺陷**, 不要为了归零去放宽断言或改对的数据。

## 跑 GUI / 取证快查

- 常驻实例: `gui-venv311/bin/python studio.py` (窗口名 `zmax`) @ `DISPLAY=:0`; 截图 `DISPLAY=:0 scrot -o /tmp/x.png` (xdotool 可 `windowactivate` 先置顶)。
- 无头判据: `QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/verify_*.py`。
- 批跑超时用 `ZMAX_JUDGE_TIMEOUT` (默认 1500s); `exit=124 ❌=0` 是没跑完, 不是失败。
- 改 GUI 代码后**禁反复重启**常驻控制台 —— 攼批改完再重启一次, 重启前先问。

## 多代理并行改控制台的分工 (避免同文件冲突)

studio.py 太大且是共享文件 ⇒ 并行任务不要多个人同时改它。可用分工:
子代理只**新增独立工具/数据模块** (如 `tools/*_inventory.py`、`tools/arch_graph.py` —— 纯 CLI + `--json`, 可自验),
主代理负责把这些 JSON 接进 GUI 页面。给子代理的契约要含: 绝对路径、真值来源、固定字段名、必须真跑并贴输出。

## 其它已踩的坑 (点位)

点位的参数化接入 / 双库 / 写前哨 / 改完免重启 —— 见 `references/point-editing-param-center.md`。
