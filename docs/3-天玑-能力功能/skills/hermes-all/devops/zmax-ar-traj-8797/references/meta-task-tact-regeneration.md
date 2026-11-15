# 元任务 / 节拍: 真源 vs 生成物

适用: 改插口数、改料盘/检测点位、重算节拍与 UPH、修正 `/api/ar/meta` 上的元任务台账。

## 真源与生成物的分工

- **段表是真源**: `zmax_data/runtime/traj/sim_insert.json` —— `holes`、`mods_per_cycle`、`tact_steady_s` 都在这里。
- **元任务台账是生成物**: `data/database/zmax/sources/config/tasks/ar_meta_tasks.json` / `tasks.json`, 由 `tools/ss_meta_task_ar.py` 生成; 另有一份旧快照常驻 `zmax_data/deliverables/*/01_元任务/`。
- 改孔数/节拍 **要改真源 + 重跑生成器**, 不手改生成物。手改的会被下一次生成覆盖, 而且与段表对不上。
- 重跑后必回读校验四件: `holes` 数、`mods_per_cycle`、`tact_steady_s`、`flow` 文案。任意一件没变就是漏了。

## 两份 cycle_plan 与本份硬编码文案

- 点位真源是 `config/points/cell_points.json`(mm, `frame=sim_base`)。
- `src/lerobot/engineering/nodes/cycle_plan.py` 与 `src/lerobot/middleware/nodes/impl/cycle_plan.py` **两份都读它** ⇒ 坐标只改一处即可。
- **但硬编码文案要两份都改**。`flow` 里写死的"预插 孔1→2→3→4"不会随 `holes` 变 —— JSON 已是 2 孔, 页面还在写 4 孔。改成按 `HOLES` 动态拼接, 以后改孔数才不用再手改。
- 改完重跑 `cycle_plan.write()` 后, 直接读回 JSON 打印 `flow` / `holes` / `tact` 三行确认。

## 点位坐标取哪个数

- **示教实测优先**: `data/skills/l2_atomic/taught_points.json` 是真机直录, 优先于仿真 `cycles_data`。
- 两者差往往是系统性的, 不是噪声: 实测见过整列槽位 x 偏小一百多毫米、z 偏高数毫米。发现"整列同向偏差"就是坐标源选错了, 不是标定精度问题。
- 用户要求"用相机感知调点位"但相机**无 base 外参**(`real_cam_calib.json` 的 `T_base_cam` 未标定) 时, 像素反投影不出 base 坐标 —— 明确说不能用, 改用示教真值并注明来源。编一个"感知得到"的数字比不做更坏。
- 无实测值的列(如第二列槽位)用第一列 x + 列间距推导, 并在数据里标清是推导值。

## 两套 UPH 口径不许混算

| 口径 | 分母 | 用途 |
|---|---|---|
| 仿真产线 | 整轮全部段 / 全部件数 | 规划上限、双臂并行 |
| 回放 | 单条轨迹 / 单件 | 单件复现节拍 |

- 回放节拍必须是**当前执行方式下的实测**, 不是录制时长, 也不是仿真推算。
- **录制时长 ≠ 执行节拍, 两者能差几十倍**: `real_traj_joints.json` 的 `dur_s`(如 215 点/42.85s)是录制时**连续运动**走完的时长; `traj_loop` 是**逐点 MoveL 独立启停 + dwell**, 每点都要走一遍加减速。同一批 215 点实测: 连续 42.85s; 逐点 speed=20% chunk=1 dwell=250ms ⇒ 10.94s/点 × 215 = 2352s(慢 55 倍)。拿 `dur_s` 当回放节拍会把 UPH 报高 55 倍。
- 元任务里要**同时**存齐: `s_per_point`(实测秒/点)、`dur_s`(实测一轮)、`cont_dur_s`(连续运动理论值, 标注仅供参考), 再加 `speed_pct` 与 `exec_mode`。只留一个 `dur_s` 会让下一个人把两个口径当同一回事。
- 实测方法: 轮询 `/api/arm/step_traj/status` 的 `cursor`, 每 6s 采一次、采十几次, 用 (点数差)/(秒差) 得 `s_per_point`, 再乘点数。改 `speed` 或改 `chunk` 后必须重测, 不许照抄旧数。
- 报节拍先写执行方式(逐点/连续、speed%、dwell)。同一个 215 点: 20% 逐点 = 1.5 UPH, 100% 连续 = 84 UPH —— 不写执行方式, UPH 数字没有意义。
- 报数时各自写清分母(多少段、多少件、窗口秒数); 把两个口径混成一个数字就是夸大。
- 回放只有单臂轨迹时, 另一臂冻结并在 UI 标出, 不要假装双臂并行。
