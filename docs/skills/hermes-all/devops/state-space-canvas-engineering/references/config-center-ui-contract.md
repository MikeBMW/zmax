# 配置中心 UI 契约 —— 改配置数据前先看谁读它

配置中心（北斗七星阵）不是独立的展示层，它是 `sources/config/*.json` 的**严格消费者**。改数据形状 =
改 UI 契约。用户看不到堆栈，只看到「你把我的配置中心结构改了 / 北斗七星的设计没了」。

## 铁律：run_cfg 的每个值必须是 {"label": str, "checked": bool}

`data/database/zmax/sources/config/ss_task_binding.json` 的 `run_cfg` 是 UI 契约，不是自由字典：
`tools/gui/veh6_config_page.py` 对 `run_cfg` 的**每个 value** 直接取 `v["checked"]`（汇总复选数、渲染开关行）。

往 run_cfg 里塞裸 int / str（例如 `"uph_target": 300`）⇒ `TypeError: 'int' object is not subscriptable`
⇒ `ConfigCenterPage.__init__` 抛异常 ⇒ 北斗七星整页构建失败。

**新参数放独立键**（`task["ar300"] = {...}`），绝不污染 `run_cfg` 形状。
写这类配置的生成器脚本里把这条写在注释里，防止下一个人（或下一次的自己）重犯。

## 判据：改完必须跑北斗七星 21 项

`tools/verify_config_center_seven_stars.py` 真起 `ConfigCenterPage` 实渲染（不是看代码），21 项：
左树 7 项次序 == 北斗次序 / 页签恰好 7 个且次序一致 / 七页阵图条各自对应 /
星图 7 颗且恰好一颗亮 / 点星点树真跳对页 / 两种窗宽（1600×900、1120×700）文字不截。

改 `sources/config/` 下任何文件后跑一次；全绿才算「没改坏」。

## 已经污染就还原，不要手改字段

`tools/restore_config_center.py`：从 `_bak/` 取原格式还原 `run_cfg`，把新增参数挪到独立键，
并恢复被流水线改掉的 `active_task`。

还原后**必须同步修生成器**（例如 `tools/ar300_config.py`），否则下次重跑又写回裸值 —— 治标不治本。

## 改完不用重启 GUI

配置中心每次打开都 `reload_from_source()` 直读磁盘，且每 3s 比对 sha256 自动对齐。
真源修好后用户重新点开即恢复。**用户禁反复重启 GUI** —— 不要因为界面没刷新就重启控制台。

## 行数变化要主动说明，别等用户问

功能表条数会因新登记功能变化（如平台支撑组追加两条）。用户会把「多两条」读成「你改了我结构」。
交付时主动给：数量差 + 归属分组 + 一句「要不要撤」的选项。

## 流水线会顺手改 active_task

`tools/evolve_550abc.py` 这类进化/全流程脚本跑完会把 `active_task` 切到本次任务。
跑完检查并恢复用户原来选中的任务，否则用户在配置中心看到状态变了，归因为「界面又被改了」。

## 相关

- 元任务写进配置中心 TASK-07-AOI 的做法：`references/ar-meta-task-plan.md`
- 550C 迁移与档位真源：见 `zmax-product-dev-profiles/references/ar300-550c-migration.md`
