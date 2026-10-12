# Z-MAX 标准打开流程 (2026-10-12 老倪定的规矩)

老倪原话:
> 「现在确定一下 zmax 项目的标准打开流程, 第一步, 打开, 加载 zmax 项目;
>   第二步, 弹出配置中心的窗口, 在配置中心, 确定配置, 然后统一打开工程」

结论: **两步**, 一条命令行 + 界面一个按钮, 两条路走的是同一段代码 (`studio._open_all_cmd`)。

────────────────────────────────────────
一、第一步 · 打开并加载 zmax 项目 (弹配置中心)
────────────────────────────────────────
命令:
    cd ~/zmax && gui-venv311/bin/python tools/zmax_open.py step1

它依次做四件事 (每件都有真值回执, 不靠自述):
  ① 控制台在不在: 真窗口 `wmctrl` 里找 `XSpace Studio — Z-MAX`; 没在跑就 `tools/studio_ctl.sh start` 拉起并等到窗口出现 (上限 600s, 期间打心跳)。
  ② 工程状态自恢复: 控制台启动第一步从工程文件 `.zmaxproj` 的 `debug_state` 回填 **场景真源 / 画布数据源 / 活跃任务**
     (老倪要的"加载 zmax 项目"就是这一步; 生产者 `tools/proj_state.py`)。
  ③ 弹出配置中心: 写 `/tmp/zmax_nav_cmd` → `config`, 然后等控制台自己写的状态文件
     `/tmp/zmax_console_state.json` 里 `page` 变成「配置」才算真的到了 (25s 上限)。
  ④ 打印配置摘要 (真源 = `outputs/config_sheets/配置单_<TASK>_latest.json`, `tools/config_sheet.py` 生产):
     活跃任务 / 任务名 / 配方 / 场景+场景色 / 场景ID / 站点 / ss_mode / 工艺 N 步 / 适用段 / 档位 / 参数覆盖 /
     画布工程(节点·连线·启用数) / 参数注册表 / 标定真源 / 点位台账 / 缺口 / 配置单时间。

实测 (2026-10-12 19:5x, 工位机):
    活跃任务 TASK-01-FW · 任务名 FW Loading + EEPROM 写/读校验 · 配方 插拔+固件校验 · 场景 插拔场景 #2e8b57 (SCN-01-FW)
    站点 SITE-A.ST11 · ss_mode insert · 工艺 9 步: 取料→扫码→翻转→对位→插入→异步测试→拔出→AOI飞拍→分拣
    适用段 8 · 档位 6 · 参数覆盖 6 · 画布 89 节点/184 连线/启用 52 · 参数注册表 710 项 · 缺口 缺站点几何 3 项

────────────────────────────────────────
二、第二步 · 确定配置 → 统一打开工程
────────────────────────────────────────
命令:
    gui-venv311/bin/python tools/zmax_open.py step2            # 用绑定真源的活跃任务
    gui-venv311/bin/python tools/zmax_open.py step2 --task TASK-06-TRAY --activate

界面: 配置中心 → 任务表上方 **「🚀 确认配置 · 统一打开工程」** (加粗那个按钮), 先点一下任务行再点它。

它依次做五件事:
  ① 确定配置: 任务 = 选中行 (或 `--task`) 否则 = 绑定真源 `config/ss_task_binding.json` 的 `active_task`;
     `--activate`/按钮选中行时会走 `tools/ss_task_bind.py --activate <TID>` **真激活** (写绑定真源 + 台账, 回读校验)。
  ② 应用场景到画布: `tools/ss_scene_switch.py --task <TID>` (幂等; 数据源/场景色/信号分组一起切换)。
  ③ **统一打开工程**: 状态空间画布 → 3D 场景 → 信号分析 (`📈 实时监控 · Graphic 信号分析`), 顺序固定, 同一份真源。
  ④ 回到配置中心并选中该任务行 (老倪"确定配置"那一步在界面上看得见)。
  ⑤ 逐条结果进状态文件 + 状态栏 + 日志: 每条 ✅/❌ + 说明, **有失败绝不报成功**。

外部核验口径 (谁都能查, 不用信我说):
    · `/tmp/zmax_console_state.json` → `last_action=open_all` · `open_all_ok` · `open_all_steps[]` (逐条 name/ok/detail)
    · `wmctrl -l` → 真窗口: `XSpace Studio — Z-MAX…` / `3D场景` / `📈 实时监控 · Graphic 信号分析`
    · `python tools/zmax_open.py status` → 一屏现状 (控制台/page/task/scene/三个窗口/配置摘要)

────────────────────────────────────────
三、一步到底 (开机 / 无人值守)
────────────────────────────────────────
    gui-venv311/bin/python tools/zmax_open.py auto        # = step1 + step2
    gui-venv311/bin/python tools/zmax_open.py status      # 只读, 不改任何东西

────────────────────────────────────────
四、安全边界 (写死)
────────────────────────────────────────
· 本流程只做「启动控制台 / 写导航命令 / 打开窗口 / 写任务绑定」, **不下发任何运动指令**。
· 真机动作仍只从 **8793 授权窗** 走 (`motion_armed`), 与本流程无关。
· 判据 ④ 是安全门: `tools/verify_zmax_open_flow.py` 会检查驱动脚本与 `_open_all_cmd` 里**零运动下发词**
  (move_joint / move_pose / target_relative_joint / gripper_driver / robot_stop …), 出现即判据红。

────────────────────────────────────────
五、判据与留痕
────────────────────────────────────────
判据: `tools/verify_zmax_open_flow.py` → **24/24 PASS**
  ① 接线在位 (执行体 / 命令通道 open_all / 导航写状态 / 页面拿到回调 / 按绑定真源 / 走 ss_scene_switch)
  ② 按钮 + 选中行 + 无回调退回命令通道
  ③ 驱动四入口 + step2 走 open_all 且能回退三连 (老版本控制台)
  ④ 安全门 (零运动词)
  ⑤ 真起配置中心页: `select_task_row("TASK-06-TRAY")` 真选中那一行
  ⑥ 真点按钮(有回调): 回调收到 task/activate/page, 页内日志逐条结果
  ⑦ 真点按钮(无回调): `/tmp/zmax_nav_cmd` 真被写成 `open_all`
  ⑧ 驱动 `status` 真跑 (退出码 0, 真读到绑定真源与窗口)
  ⑨ 端到端回执 (控制台重启到含本流程的版本后才验, 否则如实"跳过"而不是假绿)

代码留痕:
  · `tools/gui/studio.py`: `_open_all_cmd` / `_write_console_state` / 命令通道 `open_all` / `_on_nav` 写状态 / 页面回调注入
  · `tools/gui/veh6_config_page.py`: 「🚀 确认配置 · 统一打开工程」按钮 + `_open_all_clicked` + `select_task_row`
  · `tools/zmax_open.py` (新): 标准流程驱动 (step1 / step2 / auto / status)
  · `tools/verify_zmax_open_flow.py` (新): 上述 24 条判据
