# Z-MAX 标准打开流程 (2026-10-12 老倪定的规矩)

老倪原话:
> 「现在确定一下 zmax 项目的标准打开流程, 第一步, 打开, 加载 zmax 项目;
>   第二步, 弹出配置中心的窗口, 在配置中心, 确定配置, 然后统一打开工程」

结论: **两步**, 一条命令行 + 界面一个按钮, 两条路走的是同一段代码 (`studio._open_all_cmd`)。

────────────────────────────────────────
零、双击桌面图标 = 直接落到配置中心 (2026-10-12 追加)
────────────────────────────────────────
老倪: 「双击启动图标后, 先打开配置中心, 在配置中心, 可以配置任务, 信号分析, 3D场景。」
· 桌面图标 `~/Desktop/XSpace-Studio.desktop` → `tools/gui/launch_studio.sh`;
· 新实例: 脚本导出 `ZMAX_BOOT_PAGE=config` (可覆盖), `studio.py` 界面建好 3.2s 后自动 `_on_nav("config")`;
· 已有实例: 脚本把 `config` 写进命令通道 `/tmp/zmax_nav_cmd` 并把窗口激活 ⇒ **双击图标永远落到配置中心** (不重复起进程)。
· 实测: 重启后**我一条命令都没发**, 状态文件自己写成 page=配置 nav=config (pid 625994, 帧龄 52s);
  再双击一次, 通道内容 2.9s 内被吃掉 + page=配置 (进程号不变 ⇒ 没新起实例, 只是导航)。

配置中心 · 任务配置表 (首屏) 新增三列 + 右下角启动按钮:
| 任务ID | 类型 | **工程** | **3D场景** | **实时监控** | 工艺步骤 | … | 模型 | 活跃 | 状态 |
· **工程**: 工程名 + 项目启动文件真名真路径 —— 例 `状态空间工程 · 主工程` / `reports/projects/SS_主工程_任务配置.zmaxproj`;
  悬停给出**绝对路径**(校验过文件真存在)+ 启动文件时间 + 画布真源 + 节点/连线 + md5。
  (一个工程承载全部任务 ⇒ 该列各行相同, 这是真值不是偷懒。)
· **实时监控**: 该任务会加载的信号**颜色 + 条数** (真源 `config/topics/scene_tags.json`):
  `#2e8b57 插拔场景 ×5` / `#1f6feb 摆盘场景 ×3` / `#8957e5 AR场景 ×176` + `基础/未分类 白 #ffffff`;
  没绑场景的任务如实写「未绑场景 · 信号走未分类白」; 单元格**同色上屏**(与 3D 场景按钮/信号分析同一套色)。
· **3D场景**: 场景名字 + 场景ID —— `插拔场景 · SCN-01-FW` / `摆盘场景 · SCN-06-TRAY` / `AR场景 · SCN-07-AOI` …(原「场景」列改名, 不重复占列)。
· **右下角启动按钮**「🚀 启动工程 · 信号 · 场景」: 表格下方右对齐, 一键 = 确定配置 → 应用场景 → 同时打开
  工程(状态空间画布) · 场景(3D 场景视图) · 信号(📈 实时监控·Graphic 信号分析); 与 `zmax_open.py step2` 同一执行体。

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
判据 ①`tools/verify_zmax_open_flow.py` → **43/43 PASS**
  ① 接线在位 (执行体 / 命令通道 open_all / 导航写状态 / 页面拿到回调 / 按绑定真源 / 走 ss_scene_switch)
  ② 配置中心: 右下角按钮「🚀 启动工程 · 信号 · 场景」+ 三列 (工程 / 3D场景 / 实时监控) 表头与真内容 +
     按钮连 `_open_all_clicked` + `select_task_row` + 无回调退回命令通道
  ③ 驱动四入口 + step2 走 open_all 且能回退三连 (老版本控制台)
  ④ 安全门 (零运动词)
  ⑤ 真起配置中心页: 三列真内容 (工程列含项目启动文件真名 + **绝对路径真存在** os.path.isfile 校真 /
     3D场景列含场景名 · SCN / 实时监控列含场景色 #hex, 且两列同色) + 真渲染按钮在 1280/1400/1920 宽下**在右下角且不挤不截断**
  ⑥ 真点按钮(有回调): 回调收到 task/activate/page, 页内日志逐条结果
  ⑦ 真点按钮(无回调): `/tmp/zmax_nav_cmd` 真被写成 `open_all`
  ⑧ 驱动 `status` 真跑 (退出码 0, 真读到绑定真源与窗口)
  ⑨ 端到端回执 (控制台重启到含本流程的版本后才验, 否则如实"跳过"而不是假绿)
  ⑩ 双击图标 → 配置中心: studio.py `ZMAX_BOOT_PAGE` 接线 + 启动脚本导出 + 已有实例写通道 + 桌面图标指向本脚本

判据 ②`tools/verify_task_scene_matrix.py` → **46/46 PASS** (配置 × 任务 × 场景 × 信号实时监控 自动测试)
  对 TASK-01-FW(插拔绿) / TASK-06-TRAY(摆盘蓝) / TASK-07-AOI(AR紫) 逐轮真激活 → 切场景 → 统一打开, 每轮核 6 项真值:
   ① 绑定真源 `active_task` == 该任务   ② 画布 `ssdata.src_state` == 该场景
   ③ 控制台回执 (epoch 必须晚于发命令时刻 + task 匹配, 防跨轮残留假绿)   ④ 3D 窗标题带本轮场景名 (真切场景)
   ⑤ 信号分析窗**自己的内容**里三场景色真上屏 (绿 7895 / 蓝 365 / 紫 756 px; `scrot -u` 抓焦点窗 + 尺寸/OCR 自证)
   ⑥ 配置中心该行两格文字与颜色 == 该场景
  收尾自动还原测试前的活跃任务与数据源; 报告 `reports/task_scene_matrix_<ts>.{json,md}` + 每轮信号窗截图 `reports/shots/`。
  两条实测教训 (都写进判据了): (a) 3D 窗的场景推送必须**排程时定值**, 且在延迟回调里读画布会把上一轮的值推过去;
  (b) 抓信号窗**不能**用"全屏截图按 wmctrl 几何裁剪" —— 控制台压在它上面时量到的是配置中心的像素, 而配置中心
      任务表本来就有绿/蓝/紫格子 ⇒ 会假绿; 现在用 `scrot -u` 抓焦点窗 + 尺寸==窗尺寸 + 顶部 OCR 自证。

代码留痕:
  · `tools/gui/studio.py`: `_open_all_cmd` (含 3D 场景对齐数据源) / `_ss3d_push_scene` / `_src_state_now` /
    `_write_console_state` / 命令通道 `open_all` / `_on_nav` 写状态 / 页面回调注入 / 开机默认页 `ZMAX_BOOT_PAGE`
  · `tools/gui/veh6_config_page.py`: 右下角「🚀 启动工程 · 信号 · 场景」按钮 + `_open_all_clicked` +
    `select_task_row` + 三列 (`_proj_cell`/`_proj_tip` · `_scene_cell` · `_monitor_cell` + 双列同色)
  · `tools/gui/launch_studio.sh`: 双击图标 → 配置中心 (新实例跳页 / 已有实例写通道 + 激活窗口)
  · `tools/zmax_open.py` (新): 标准流程驱动 (step1 / step2 / auto / status)
  · `tools/verify_zmax_open_flow.py`: 上述 43 条判据 · `tools/verify_task_scene_matrix.py` (新): 三任务矩阵 40 条
