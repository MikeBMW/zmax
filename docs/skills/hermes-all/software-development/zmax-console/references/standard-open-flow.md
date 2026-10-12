# Z-MAX 标准打开流程 (老倪 2026-10-12 定稿) — 两步 + 一条命令 + 一个按钮

老倪定义: 第一步 打开/加载 zmax 项目并弹出配置中心; 第二步 在配置中心确定配置, 然后统一打开工程。

## 两条路, 一段代码

```
# 第一步: 起控制台(没跑就拉) → 工程状态自恢复 → 弹配置中心 → 打配置摘要
cd ~/zmax && gui-venv311/bin/python tools/zmax_open.py step1
# 第二步: 确定配置(可选 --activate) → 应用场景 → 统一打开 画布·3D场景·信号分析 → 回配置中心选中任务行
gui-venv311/bin/python tools/zmax_open.py step2 [--task TID] [--activate]
gui-venv311/bin/python tools/zmax_open.py auto      # 一步到底 (开机/无人值守)
gui-venv311/bin/python tools/zmax_open.py status    # 只读现状
```

界面同源: 配置中心任务表下方**独立一行**的按钮「🚀 确认配置 · 统一打开工程」→ `veh6_config_page._open_all_clicked`
→ 回调 `studio._open_all_cmd` (页面没回调时退回命令通道写 `open_all`)。命令通道 `echo open_all > /tmp/zmax_nav_cmd` 同一执行体。

## 外部核验口径 (别信自述)

- `/tmp/zmax_console_state.json`: `page`(当前页) · `task` · `scene` · `last_action=open_all` · `open_all_ok` · `open_all_steps[]`
- `wmctrl -lG`: `XSpace Studio — Z-MAX…` / `3D场景` / `📈 实时监控 · Graphic 信号分析`
- 真源: 任务 `config/ss_task_binding.json`; 配置参数 `outputs/config_sheets/配置单_<TASK>_latest.json`

## 界面入口 (2026-10-12 二次追加: 双击图标 → 配置中心; 三列 + 右下角启动按钮)

- 桌面图标 `~/Desktop/XSpace-Studio.desktop` → `tools/gui/launch_studio.sh`; 脚本导出 `ZMAX_BOOT_PAGE` (默认 config),
  新实例由 studio.py `QTimer.singleShot(3200, _on_nav(bp))` 跳页; **已有实例**则把 `$ZMAX_BOOT_PAGE` 写进
  `/tmp/zmax_nav_cmd` 再 `xdotool windowactivate` ⇒ 双击图标永远落到配置中心、不起第二个进程。
- 任务配置表列: 任务ID/类型/**工程**/**3D场景**/**实时监控**/工艺步骤/… —— 工程=工程名+项目启动文件真名真路径
  (tooltip 给绝对路径, 判据会 `os.path.isfile` 校真); 实时监控=`#hex 场景 ×N` + `基础/未分类 白 #ffffff`
  (真源 `config/topics/scene_tags.json`); 3D场景=场景名+场景ID (`插拔场景 · SCN-01-FW`)。
  三列内容/上色都从真源算, 没绑场景的任务如实写「未绑场景」。
- 右下角按钮「🚀 启动工程 · 信号 · 场景」(表格下方右对齐) = 确定配置→应用场景→开 画布+3D+信号分析,
  与 `zmax_open.py step2` 同一执行体。
- 表宽坑: 列多时用 `ResizeToContents` + 只给「工艺步骤」`Stretch`; 两行单元格要
  `verticalHeader().setDefaultSectionSize(46)` + `resizeRowsToContents()`, 否则第二行被裁。
- 启动页判据不要只看代码: 重启后**不发任何命令**, 看 `/tmp/zmax_console_state.json` 是否自己写成 `page=配置`。

## 坑 (都实测踩过)

1. **状态文件跨进程残留**: 重启控制台后旧文件还在, 只判 `page==配置` 会把上次的当本次 → 判据必须带
   `epoch >= 发命令时刻 - 2`; `status` 里 age>120s 标「陈旧(上一进程残留)」。
2. **延迟开窗 vs 立即回执**: `open_all` 里 3D/信号分析是 `_oneshot(700/900ms)` 开的, 回执先落
   → 驱动必须**有界等窗口到齐再报**, 否则把"还没开出来"假报成"窗口不在"。
3. **按钮不许塞进满排**: 任务表那排 10 个按钮已占 1416px, 再加 197px 会被挤出可视区(老倪红线: 界面不许挤/字不许截断)
   → 单独一行 + 判据在 1280/1400/1920 宽真渲染断言 `width>=sizeHint` 且右边缘 ≤ 页宽。
4. **命令通道只认在跑进程里的词**: 新词 (`open_all`) 只有重启后的控制台才认 → 驱动要带回退路径
   (老版本: `ss_canvas`+`ss_3d`+`monitor` 三连), 并在输出里写明用了哪条路。
5. **安全边界**: 本流程零运动下发; 判据里加"安全门"(扫描 move_joint/move_pose/target_relative_joint/
   gripper_driver/robot_stop 等词), 出现即红。真机动作仍只从 8793 授权窗走。

## 判据

`gui-venv311/bin/python tools/verify_zmax_open_flow.py` → 27/27 PASS
(接线 / 按钮+选中行 / 驱动四入口 / 安全门 / 真起页选中 TASK-06-TRAY / 有回调与无回调两条点按钮路径 /
 窄窗口不挤 / status 真跑 / 端到端回执 5 步)。
