# AR 场景 300UPH 的元任务编排 + Plan 节点

用户口径：「用 TASK-07-AOI，按照 AR 场景编写元任务的组合；这些组合形成长程任务，发给 Plan 节点执行，
能实现 AR 场景的 300UPH；通过元任务组合我能看到清晰的机器人要执行的任务」。

## 元任务怎么来的（归纳，不是手写）
从 `sim_insert.json` 的 392 段按**段模式**切，不是凭印象编。切法 = 找每种动作的起始段 + 固定段数：

| 元任务 | 起始判定 | 段数 | 次数 | 段小计 |
|---|---|---|---|---|
| MT-01 取料并插入一个模块 | `move` + 含"槽"+"上方"+ 不含 拔/下料盘/废料盘 | 9 | 14 | 126 |
| MT-02 从孔内拔出模块 | `move` + 含"上方(拔)" | 5 | 14 | 70 |
| MT-03 AOI 五点检测 | `move` + 含"金手指点" | 10 | 14 | 140 |
| MT-04 良品放回下料盘 | `move` + 含"下料盘"+"上方" | 4 | 12 | 48 |
| MT-05 NG 放废料盘 | `move` + 含"废料盘"+"上方" | 4 | 2 | 8 |

126+70+140+48+8 = **392** ✅。

🔴 两个踩过的坑：
- MT-01 的 "含槽+上方" 会把 **下料盘 下槽N 上方** 也吞掉（"下槽"含"槽"）⇒ 必须同时排除 下料盘/废料盘，否则后续段全错位。
- 段表里还有第 5 类 **废料盘(NG)**，只看前 4 类会在第一颗 NG 件处切不动（报"不匹配任何元任务起始"）。
  归元任务前先把 `(kind, 去掉数字的label)` 去重列一遍，能一次看全 24 种模式。

## 段数/批次口径（别混）
- `plan[].k` = **搬运批次** 1..8，不是件号。每批段数不同：**首批 36（4×MT-01）/ 稳态批 56 / 收尾批 38**，
  36+5×56+2×38 = 392。用均值 28 去反推件数必错。
- 件数真源 = `cycles_data`（14 条）+ 各条 `t_work` 累加 → 每件完成时刻。
- UPH 几何能力 = `3600/tact_steady_s` = **315~316**（目标 300 ⇒ 12s/件）。

## 轮模板不要手写
按批次把元任务序列聚类即可（`collections.OrderedDict` + tuple key）。实测聚出 5 种：
`MT-01×4` / `MT-02+MT-03+MT-04 + MT-02+MT-03+MT-04 + MT-01×2`（4 批）/
含 `MT-05` 的 NG 变体（1 批）/ 两种收尾 `...只拔不插`（各 1 批）。段表一变它就跟着变，不会撒谎。

## 交付物（可复用）
- `tools/ss_meta_task_ar.py` —— 归纳 + 逐段重建校验 + 次数守恒 + 写配置。**只读段表**，不改 `sim_insert*.py/json`。
- `sources/config/tasks/ar_meta_tasks.json` —— 元任务库（含 `prompt` 固化提示词）+ `long_horizon`（轮模板 + sequence_prompt）。
- `sources/config/tasks/tasks.json` 的 `TASK-07-AOI` 新增 `meta_tasks` / `long_horizon` 两个字段。
- `src/lerobot/engineering/nodes/plan_long_impl.py` —— Plan 节点实现（registry key `ss_plan_long`），
  读元任务组合 → 按轮模板展开成段（逐段与段表校验，不一致就拒跑）→ 每段带 `mt_id/mt_i/batch` → 节拍推进 → 写 ar_cmd。
- 画布节点 `ssplan` 🧩 长程元任务编排器 (Plan)，住数据源行带 (60,440)，`ssdata.out2 → ssplan.in1`。
- **常驻驱动** = systemd `zmax-ss-canvas-loop`（`ZMAX_CANVAS_ONLY=ssplan` · `ZMAX_UPH_AR_PUB=1` · 10Hz ·
  每拍写 `canvas_loop.json` 心跳）。换驱动节点只改 unit 的 `ZMAX_CANVAS_ONLY` 再 daemon-reload + restart；
  多个节点同时写 `ar_cmd.json` 会互相抢，白名单里只放一个。

## 校验必须做到的 5 条（缺一条不算交付）
1. 覆盖 392/392 段 2. 逐段重建 kind/label/t 全等 3. `MT-01 次数 == insert 段数`、`MT-02 == pull`、`MT-03 == golden`、
`MT-04+MT-05 == release - insert` 4. `Σ(次数×段数) == 392` 5. 轮模板段数合计 == 392。

## 🔴 AR 开关 1800s 过期 ⇒ 双臂「不工作」（已有根因修复，别只手工重发）

`zmax_data/ss_live/exec_switches.json` 有 `AR_SW_FRESH_S=1800`: 控制台只在**点开关那一刻**写一次,
过一夜 age 上万秒 ⇒ `/api/ar/mode` 返回 `raw_ar_scene=true` 但 **`ar_scene=false`** ⇒ 页面 `ARMODE.on=false`
⇒ 状态空间指令即使 fresh 也不接管(页面回落自播)，表现为「动画在动，但机器人不跟指令」/`PREV.ssOn=0`。

- 排查顺序: `curl /api/ar/mode` 看 `age_s`/`raw_ar_scene`/`fresh` → 手工重发 `set_ar_switch.py`/`pub_exec_switches.py`
  → 再验 `fresh=true`。别误判成 Plan 节点没出数(同一时刻 `/api/ar/cmd` 可能一切正常)。
- **根因修复 = 常驻画布循环里续期**: `tools/ss_canvas_loop.py` 的 `keepalive_switch()` 在 `prj.step()` 之后,
  文件龄 > `0.6 × SW_FRESH_S` 就重写一次并打日志。
  🔴 **只续 `ar_scene`，`real_auth` 永不自动续** —— 真机授权必须人点，自动续等于自己拆掉安全闸门。
  实测: 把开关改成 2000s 前 → 重启循环 → 日志「🔄 AR 开关续期 (原龄 2000s)」→ `/api/ar/mode` age 4.9s、fresh=true。
- 任何让画布循环停过的事(进化/迁移/重启服务)完成后，**必须重查** `/api/ar/mode` 与 `/api/ar/cmd` 帧龄,
  再对用户说「双臂在工作」。

## 判据（页面实测口径）
`ARMODE.on=true` + `PREV.ssOn=1` + `PREV.ssMt` 显示「MT-xx 名称 (i/n · 第k批)」+ `PREV.ssSeq` 单调推进
+ `/api/ar/cmd` 的 `mt_id/mt_i/mt_n/batch` 齐全且 `age_s < 0.2`；同时 `real_auth=false`（真机零指令）。

## 页面右侧「🧩 元任务」面板（让用户看见每个任务依次执行）

用户口径：「元任务的配置、AR 场景也写到 /ar3d 右侧面栏，我能看到每个任务的依次执行，要能驱动动画仿真」。

- **服务端** `tools/tcp_ar_server.py`: `MT_ARM` 映射(MT-01 左臂摆盘 / MT-02..05 右臂) + `_ar_meta_payload()`
  + 路由 `/api/ar/meta`(返回 5 个元任务: id/名称/手臂/prompt/次数/段数/耗时 + 轮模板摘要)。
  🔴 `_ar_cmd_payload()` 必须**显式透传** `mt/mt_id/mt_name/mt_i/mt_n/batch` —— 白名单式 payload 会把新字段静默过滤掉;
  改完 `systemctl restart zmax-traj-ar` 才生效(.py 改动不重启无效, 同服务的 html 是热读的)。
- **页面** `tools/web/tcp-ar.html`: 右侧「⏱ 生产节拍」顶部 `#mtBox`, `renderMetaTasks()` 渲染 N 行
  (当前行蓝底高亮 + 进度条 + 当前动作), 底部轮次摘要(392 段 / 159.43s / 11.42s 每件); HUD 另加一行 `元任务 <b id="uphMt">`。
  数据 = `/api/ar/meta`(静态清单) + `/api/ar/cmd`(当前 mt/进度)。
- 🔴 **`const ARCMD = …` 不挂 `window`**: 页面里读全局必须写 `typeof ARCMD !== 'undefined' && ARCMD && ARCMD.d`,
  写成 `window.ARCMD` 恒为 undefined ⇒ 面板永远不高亮/不刷新(看着像后端没数据)。
- 判据(浏览器实测, 别只 curl): 采样 ≥5 次看到 `PREV.ssMt` 在 MT-0x 之间**切换**(如 MT-02(32/56)→MT-03(33/56))、
  当前行高亮、`units` 在涨、`/api/ar/cmd` 帧龄 0.01~0.07s。只验「接口有数据」不算交付。

## 相关
- 配置中心（北斗七星）UI 契约 —— 写元任务/AR 参数进 TASK 前必读: `references/config-center-ui-contract.md`
