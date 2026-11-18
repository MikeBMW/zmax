---
name: zmax-real-traj-215-autorun
description: Use when 跑/查真机215点轨迹(停住点·帧号口径·点位台账·授权档)。
---

# 真机 215 点全流程自动执行 + 授权两档

## 链路（只有一条，别造第二条）
```
入口 src/lerobot/engineering/start.py    ZMAX_AUTO_TRAJ=1
  └─ state_space/real_traj_flow.py      RealTrajFlow.tick()  每轮 chunk 点(默认 1)
       └─ POST 8797 /api/arm/step_traj  {n, start, speed, dwell_ms, dry, grip}
       └─ GET  8797 /api/arm/step_traj/status   进度 cursor/done
```
- 🔴 **chunk 的实际值只认运行进程的 env**: `.vscode/launch.json` 里的 `ZMAX_TRAJ_CHUNK` 会覆盖 `start.py::_debug_defaults()` 的 setdefault, 代码默认值不作数 ⇒ 核对用 `tr '\0' '\n' < /proc/<pid>/environ | grep TRAJ_CHUNK`。默认必须是 1: chunk=10 时断点/Shift+F5 冻不住已派出的段, 臂会把剩下 9 点走完(用户会问"我都在断点了怎么还在动")。
- 轨迹真源 `tools/web/real_traj_joints.json`（215 帧关节角真值）；夹爪动作另由 `real_traj_grip.json` 计划给（录制未记夹爪事件）。
- 游标 `zmax_data/rokae_sdk/traj_step_state.json`；撞 30° 跳变闸返回 `stage=jump` ⇒ POST `{"align":true}` 把游标挪到真机最近点再继续。
- `dry:true` 时 8797 跳过授权与跳变闸，且**不推进 cursor** ⇒ 客户端必须自己按 `start+done` 推进并把 `start` 显式传回去，否则同一段会无限重发（实测刷了 33 轮才发现）。
- cursor 到末端要先 `{"reset":true}` 才能再跑整轮；`ZMAX_TRAJ_KEEP=1` = 续跑不重置。

### 要**循环跑**（边跑边采数据/教模型）时的三件事

- 🔴 **`RealTrajFlow` 默认只重置一次**: 内部 `_reset_tried` 一旦置 True, `cursor>=total` 就进 `DONE` 不再回来
  ⇒ “跑完一圈就停”是设计行为, 不是 bug。连续循环必须显式开关(`ZMAX_TRAJ_LOOP=1` 把重置闸打开并把
  `rounds` 递增), 否则你会以为它在循环, 实际早停了。
- **回起点不需要大位移**: 示教轨迹本身就是闭环 —— 实测首点 `[665.3,-26.8,296.9]` vs 末点 `[664.2,-29.1,294.0]`
  只差 **5.7mm**, 而当时臂已停在别处时看起来像要横移几百毫米。先算首末点距离再决定要不要 `{"align":true}`;
  能直接 reset 就走 reset, 别默认触发离路对齐。
- **用轻量驱动脚本, 不起 GUI**: 只要一个 1Hz 循环调 `flow.tick()` 的独立入口(本项目 `tools/traj_loop.py`),
  它不加载 L3/L4 模型 ⇒ 不占显存, 可与相机探针/VLM 标注并行。进度落一份小 json(轮次/游标/授权一句话)
  给页面读, 别去碰 `traj_flow.json` 免得与 GUI 那条抢写。
- **ETA 标尺**: 20% 速度下每点约 4~5s ⇒ 一轮 215 点约 **16 分钟**; 判定“它在真跑”看
  `GET /api/arm/step_traj/status` 的 `running=True / dry=False / cursor` 在涨, 不要只看日志行数。
- **边跑边采的探针要按 cursor 对齐**: 记录里带上 `cursor` 才能回答“哪几个点位能检到目标、哪几段本来就空”。
  轨迹上大部分点是转场, 只有取放件那几个点位画面里才有目标 —— 把“全程 N 帧有检出”报成检出率是误导。
- 驱动分工：连续档用 1Hz 守护线程 `zmax-traj-flow`（引擎一次全量 pass 几十秒，拍子带不动）；单步档必须由每拍 hook 驱动，**不许起线程**（单步模式会把线程内联成死循环）。
- 对外进度只两处：`zmax_data/ss_live/traj_flow.json` 与 8797 `GET /api/arm/traj_flow`。

### 🔴 「我运行了, 你看着」= 先判真机有没有被派单 (三件取证, 30 秒出结论)

- **引擎在 tick ≠ 真机在跑**: 引擎侧 `ss_live/action.json` 每拍在写(`ts` 龄 <1s)、`skill_calls.log` 在涨, 而真机一条指令都没收到。
  实测过: 页面横幅「第 125/215 点」是 **39 小时前**那轮留下的 `traj_flow.json`, 同刻 8797 是 `running=false · cursor=0/215`。
  ⇒ 判"在跑"只认 8797 status 的 `cursor` 在涨, **不认** `traj_flow.json`/页面横幅(它可以是几十小时前的残影)。
- 三件全只读一起看: ①`/api/arm/step_traj/status` 的 `running/cursor/done` ②`zmax_data/l2_cmd.fifo` 的 mtime +
  `l2_daemon.log` 最后一行(**停在启动横幅那行 = 开机以来零命令**) ③SDK 桥连采 10~40s 真值位移恒 0。
  三者都静止 ⇒ 不是闸门/授权/网络的问题, 是**根本没派人**; 别去翻授权和网线。
- 🔴 **`ZMAX_SS_IDEAL=1`(理想档) 会让通道闸逐拍否决, 真机永远零派单**: 观测取理想值, 与真机位姿差几百 mm ⇒
  `skill_calls.log` 每拍 `why="通道·越界"` + `cor.dev_mm` 两三百 mm(半径 80mm)、或
  `无 3D 坐标(trace_live 缺/过期, 或它是仿真坐标系) ⇒ 本拍不过通道`。要真机跑必须关掉这一档并重启引擎
  —— 重启会抢 `zmax_start` 锁, **让他自己停/自己 F5**, 别抢锁。
- 判"能动"的最小探针(实测标定): `POST 8793 /ctl/move {"skill":"L2.lower","d_mm":5,"arm":true}` ⇒ 回执 `已下发(真动)`,
  `speed 8 → 0.7mm/s`, 5mm 约 **16s** 走完、实测到位 **4.0mm**(余下 1mm 是 `TOL_DEG=0.6` 的到位容差), x/y 零漂。
  这一发同时证明设备/授权/通道全好; **探针动了就把这 4mm 明说并问是否复原**, 别默默把臂留在低位。

## 授权两档（唯一真源 tools/ctl_auth.py）
- `mode="window"`：until=since+1800，到点自动失效；`mode="debug"`：until=0、left_s=None，无时间限制，只有 revoke 结束。`armed = debug or until>now`。
- **任何地方都别自己算 `until-now`**：调试档 until=0 会被当成未授权（8797 的 step_traj / exec_plan 就踩过）。统一走 `ctl_auth.check()` / `info()`。
- 撤销：`until=0 + revoked_at + epoch+1` ⇒ 在途/排队命令作废（命令带旧 epoch 一律拒发）。
- 8793 页面：授权按钮旁加时长下拉（⏱30 分钟 / 🔧 调试·无限制），两步确认不变；显示 `mode` 才能分清“无限”与“剩 N 分”。
- 入口第一件事打授权：`start.py::_auth_probe()` 输出 ✅/⛔ + epoch/ip/mode，并在 hook 里检测变化（撤销要当场可见）。

## 点位语义: 第 126 / 152 点 = 金手指点1 / 金手指点2 (老倪 2026-11-17 口述)

- **126 = 金手指点1、152 = 金手指点2**(AOI 金手指观察位); 这两点也是 `traj_adj.json` 里唯一的两个修正点。
- 126 与 `data/points/金手指点1.json` 坐标逐位对得上: pos `[0.480004, 0.13749, 0.692463]` = 480.0/137.5/692.5 mm,
  该文件 desc 写明「当前位置=金手指点1, 同时作为回放轨迹第126点的修改点」。
- **点位台账真源 = `reports/aoi_points/<name>.json`**(`aoi_teach_point.py` 写同一处), 派生配置(`config/tasks/tasks.json`
  与 `config/ss_task_binding.json` 的 `pt.*`/`pthist.*`)只由 `tools/task_build.py` 生成, **禁手改**。
- ✅ **`金手指点2` = 整点重教, 位置和姿态都是它自己的**(现场重教后更正; 此前"位置抄点1、姿态留点2"是**数据错误**, 不是规格):
  pos `[0.481023, 0.1370705, 0.69484]` m · quat `[0.0104285, 0.6727, 0.003596, 0.739833]` ·
  abc `12.077, 84.441, 11.523`° (点1 是 `173.605, -87.697, 5.125`, 两者明显不同) ·
  与录制帧关节角最大差 **4.68°** ⇒ 姿态也动了, 不能按"纯平移"处理。
  落地: `gui-venv311/bin/python tools/record_point_sdk.py --record <点名> --json`
  (采样 6 帧静止校验, ≈0.35s, 一次写 L2 技能库 + `reports/aoi_points/` 台账)。
  🔴 **它不保证重建配置中心** —— 实测连录两点都只写了两个库, `config/tasks/tasks.json` 还是旧值,
  体检当场报 `⛔ 配置里的值与台账不符`。定式: 每记一个点后**自己补跑**
  `gui-venv311/bin/python tools/task_build.py`, 再跑 `tools/verify_points_consistency.py`;
  体检出「✅ 全部一致 · 问题 0」才算完成。别拿回执里的 `overwrote=true` / `ok=true` 当落地证据。
  验收: `tools/verify_points_consistency.py` 全点一致 · 问题 0。
- 🔴 **判"整点重教 vs 平动补偿"看 `dq_deg` 最大角**: ≈0° 才是纯平移(可用 IK 解关节角); >2° 就必须记**当前实测关节角**,
  别再走 IK 平动 —— 同一位姿 IK 有多解, 猜出来会大幅翻转(实测 j4 能差 133°)。
- 🔴 **「跟 X 的位姿一样」先分三层再动手**: ①只位置 ②只姿态 ③位置+姿态全同。一句话里口径改很正常,
  **只改他这次点名的量**, 其余留原值; 抄成全同要能自查——位姿全同时 `quat` 逐位相同, 只位置相同时 `quat` 必须不同。
  改错方向的版本留 `.bak_*` 并在 history 里写一行「按纠正回退」, 别把两份都当有效值。
- ⚠️ **`traj_adj.points["152"]` 必须与台账同值**: 重教后帧修正值 = `481.023/137.070/694.840`, `j_new_rad` = 当前实测关节角;
  485.2/129.7/701.4 已作废, 593.6/−51.6/652.7 更早的历史值只在 history.jsonl。
  顺序固定: 先 `record_point_sdk.py` 记台账 → 再把同一组值写进 `traj_adj.json`; 反过来会被旧值覆盖。

### 点1 ⇄ 点2 是「翻面」不是平移 (实测几何, 排轨迹/算节拍直接用)
- 两点**姿态夹角 179.8°**, 旋转轴≈基座 −X (`[-1.000,-0.001,-0.027]`) ⇒ 近乎正反面对翻。
- TCP 位置相同(0mm), 但法兰(link6)从 `259.7/142.9/833.8` 绕到 `277.5/126.4/530.1`: 弦长 **304.7mm**;
  腕心→TCP 半径 **261.8mm** ⇒ 翻转过程扫过**弧长约 820mm**(扫掠直径 524mm)。不能直线插补, 只能关节插补或「抬起→翻→再下」。
- 关节层: j4 要 **+220°**(等价 −140° 到 −143.9°, 行程短一半多), j1 +55.7° · j3 −50.1° · j5 −32.5° · j6 −46.7° · j2 +10.4°。
  报现场时两条路都给: +220° 要确认控制器接受超 ±180° 表示(点2 存的就是 216°), −140° 要确认 j4 负向限位。
- 扫掠包络(直径 524mm, 圆心在 TCP 附近)会越过料盘/压条上方 ⇒ 中间高度须现场确认; 没有障碍物模型时只给包络, 不要断言「能过」。

### 页面「单点走」只有仿真臂动 ⇒ 真机腿没接到单 (一行判据)
- 画面三条臂: **右臂_真机**(关节来自 `zmax_data/rokae_sdk/tcp_out/latest.json`, age<1s 才算活) ·
  **右臂_仿真**(紫色, 跑段表/幽灵臂) · **左臂**(纯仿真, 固定在右臂世界系 Y+500mm, **真机没有第二台臂**; 轨迹回放时按设计冻结)。
  ⇒ 「只有右臂在动」是正常现象: 单点走动的是右臂_仿真, 左臂就不该跟。
- 「真机也走」复选框 **默认 checked**; 勾着才是 仿真钉第 i 点 → 停 1s → `POST /api/arm/step_traj {n:1,start:cursor}` → 真机走。
- 🔴 判「真机到底接没接到单」看 **`zmax_data/rokae_sdk/traj_step_cmd.json` 的 mtime 是否推进**, 不看页面动画:
  不推进 = 8797 就拒了(最常见: `cursor` 已到 `total`, 再点等于要第 N+1 点)。
  处置: 先 `{"align":true}` 把游标落到真机当前点, 要重跑整轮再 `{"reset":true}`。
- 🔴 **给点位定关节角: 优先复制实测值, 别用 URDF IK 猜** —— 同一末位姿 IK 会给出大幅翻转的另一组解
  (实测 j1 差 55°、j4 差 133°, 从当前姿态过去要大幅摆动)。台账写法/FK 自检/IK 口径见**另一个技能**
  `dispatch-chain-integrity` 的点位库参考文件 §6~§8(本技能不自带这份文件)。
- 报点位一律用「第 N 点(金手指点K)」双写, 只说数字现场要回头查表。

## 停住点全清单 + 帧号口径 (报数前必读)

### 轨迹里"停住做事"的点一共 5 个, 来自两个文件

| #帧号 | 动作 | 停留 | 真源 |
|---|---|---|---|
| #9   | 夹爪 close | hold 2000ms | `tools/web/real_traj_grip.json` |
| #125 | 金手指点1 | AOI 10082 | `tools/rokae/arm_step_traj.py::AOI_ON_ARRIVE` |
| #151 | 金手指点2 | AOI 10082 | 同上 |
| #172 | 表面检测 | AOI 10083 | 同上 |
| #205 | 松开分拣 | hold 2600ms | `real_traj_grip.json` |

- 现场口径的"4 个停止点"通常指**去掉起点合爪 #9** 那四个 (#125/#151/#172/#205) —— #9 是"起点已夹住模块"的第一帧, 臂本来就在那。
- 凑清单 = `real_traj_grip.json` 的 `grip[].i` + `AOI_ON_ARRIVE` 的 keys。只报 AOI 那三个会漏夹爪。
- 别把 `real_traj_grip.json` 的 `candidates.static_frames` 当停住点 —— 那是"相邻点几乎不动"的候选 (全轨迹只有 111~113 一处真停顿), 不是程序在等外部动作。
- 报状态用 `cursor > i` 判"已过", `i - cursor + 1` = 还差几帧。

### 🔴 `#N` 就是 `frames[N]` —— 别换算成 1-based 再回答

- 页面状态行、`RTRAJ.fi`、`rtrajStepIdText()` 全是 **0 基帧号**, `#163` = `frames[163]`。
- 服务端 `cursor` = "已走完的帧数" = **N+1** ⇒ 页面 `#163` 与 `cursor=164` 是**同一个位置**, 不是差一个点。
- 用户说"现在是 163 点吧"时按 1-based 回成"第 164 点"会被当场纠正(页面显示 163)。**统一用 `#N` 回答**; 必须说 1-based 时写成"第 N+1 点(#N)"。
- 判到位: 页面 `#N` 的 X/Y/Z 与 `/api/tcp` 实测比, Z 差 2mm 属到位容差(`TOL_DEG=0.6`), 不是漂移。

### 🔴 `frames[].p` 是**米**, `traj_adj.p_mm` 是**毫米** —— 同一份 frames 里两种单位并存

- `real_traj_joints.json` 每帧 `p` = `[0.5059, 0.1063, 0.6925]` (米); 被 `traj_adj` 覆盖过的 126/152 读出来却是毫米 `[481.023, …]`。
- 直接混算会得出 **861776 mm** 这种荒谬距离(实测踩过)。统一规则: 若 `max(|p|) < 10` 就当米 ×1000, **逐帧判, 不要整表一个假设**。
- 关节角 `j` 没有这个问题, 只 `p` 有; 做任何几何统计/距离前先归一。

### 🔴 `traj_adj` 的 key 与 `AOI_ON_ARRIVE` 的 key 差一帧

- `traj_adj.points["152"]` 覆盖的是 `frames[152]`; `AOI_ON_ARRIVE[151]` 触发在 `frames[151]`。两者都写"152"但不是同一帧。
- 现场说"第 152 点"时先分清是**修正表口径**还是**AOI 触发口径**; 报点位一律带帧号 `#152`。
- 现在没出问题是因为 `frames[151]` 与 `frames[152]` 只差 4.39°, 且 AOI 触发早已跑过。要对齐就把 `AOI_ON_ARRIVE` 的 151 改成 152 —— 改完必须重启 8797。

### 点位重教后"能不能继续走"的三项预检 (30 秒)

1. 当前 `/api/tcp` 与新点位距离: `<0.5mm` ⇒ 就在点上, 不需要先回退; 差得多就先 `↩ 回退 1 点` 归位。
2. `cursor` 与物理位置是否一致: `cursor-1` 应是"最后执行的那帧", 位姿要与它重合。
3. 下一点与当前关节角的最大差: 读 `frames[cursor].j` 逐轴比, `<40°` 才会过跳变闸; 同时报出距离 mm 让现场有量感。

## 夹爪链: 一次开合 82.9s → 0.95s (2026-11-17 改造)

- **真因**: 8797 每次开合都 ssh 到 Orin 冷起 ros2 CLI 三次(读位置 25s + service call 30s + 回读 25s),
  而且 `_GRIP_SRV` 默认写的是 `/gripper_srv`, 现场真身是 **`/gripper_driver`** ⇒ 夹爪从来没真动过
  (`grip_events.jsonl` 里 ok=false, pos_after 恒 70.0)。
- **改法**: Orin 上 `grip_svc.py` 常驻持有 rclpy 节点(订 `/gripper_pos` + client `/gripper_driver`),
  HTTP :39062 出参 —— `GET /health|/pos|/grip?act=close|open&force=40&wait=8`。systemd 单元 `zmax-grip-svc`(enabled)。
  8797 侧 `_grip_pos`/`_grip_send` 优先走 HTTP, 失败回落 ssh 老路(ev 里记 `fallback`)。
  只读端 `GET /api/grip/pos`(8797) 实测 3~17ms。
- **实测**: close 0.95s / open 0.49s / 读位置 0.02s; 含合爪的整轮 step_traj 12.7s(原 82.9s)。
- **部署坑**: systemd 重启必须先确认 39062 已释放 —— 旧进程占着时 `server_bind` 失败 ⇒ 循环重启,
  而旧进程的 rclpy context 已坏 ⇒ health 报 `rcl node's context is invalid`(极度误导, 不是 ROS 环境问题)。
  脚本已加 SIGTERM 优雅退出; 手工清理: 按 `ss -ltnp | grep 39062` 的 pid `kill -9` 后再 `systemctl start`。

## 单步走真机 (ar3d ⏭ 单步 +1 点) 的坑 (2026-11-17 实测)

- **按钮混淆**: `⏭ 同步操作`只动仿真不下发真机; `⏭ 单步 +1 点`才是仿真走一步+真机走一步。
  「只有仿真臂在动」先确认点的哪个; 前者已改名 `⏭ 同步操作(只仿真)`。
- **off-by-one**: stepRealFollow 旧代码 POST `{n:1,start:cur}`(cur=已走计数=i-1) ⇒ 真机落后一帧;
  正解 `start:i`(要走的帧索引), 走完 cursor=i+1。验收: 画面 #N 与真机 jointPos 逐轴 ≤0.12°。
- 游标 215/215 时单步必拒 ⇒ 先 `POST {reset:true}`; 本轨迹首尾姿态差仅 1.2°, reset 后直走不会被跳变闸拦。
- 🔴 **`stage=jump` 有两种成因, `{"align":true}` 只治第一种 —— 先分清再动手**:
  ① 游标与真机脱节(真机被人推走/上一段没跑完) ⇒ align 对;
  ② **轨迹本身在这一段就 >30°**(本轨迹 `frame[19]→frame[20]` 是 **31.0°**, 全 215 帧 214 段里唯一一处 >30°, 次大只有 21.5°) ⇒
  align 把游标挪到"最近点"也解决不了, 再点还是同一段, 看起来像"点了完全没反应"。
  一秒判种: 算 `max(|frames[i].j - frames[i-1].j|)` 全表, 若游标那一段本来 >30° 就是②;
  再看目标帧与"真机贴合的帧"是否相邻(`_nearest` 的返回值), 相邻 ⇒ 本来就该走, 是闸太粗不是位姿不对。
- 🔴 **姿态自交会让 `_nearest` 指到很远的帧, 提示语把现场带偏**: 本轨迹 `frame[19]` 与 `frame[87]` 的关节角只差
  **0.1° / 0.11°**(同一姿态在轨迹里出现两次) ⇒ 只取唯一最近帧时报"真机最接近第 88 点", 而游标在 20,
  `|20-87|>1` 于是照拒。正解 = **把所有差 <5° 的帧都算进来**, 任一个与游标相邻就放行。
- ✅ **已落地的修法(8797 `/api/arm/step_traj` 首点预检)**: 30° 闸不再一刀切 return ——
  先算 `_near5 = [i for i in range(len(frames)) if max|frames[i].j - live| < 5°]`,
  若 `any(|start - i| <= 1 for i in _near5)` 则打印一行 `相邻帧大跨步 … ⇒ 放行给执行器插补` 并继续下发;
  非相邻(游标被挪过/真机被推走)照旧拒。**插补交给执行器做**: `arm_step_traj.py` 本来就会把超上限的一段
  拆成 `k = ceil(jump / (MAX_JUMP_DEG*0.6))` 段并打印 `prep{n_mid, seg_deg}` ⇒ 31.0° 实际拆多段走, 实测 32.6s 到位、
  `err_deg 0.11`, 不需要动闸阈值也不需要改轨迹。**别为了过闸把 30° 抬到 40°** —— 那个闸是防瞬移的, 放宽会一起放过真误发。
- 🔴 判"单步有没有真下发"看 `traj_step_cmd.json` 的 mtime, 不看页面动画(已在上一节); 判"下发后被谁拒"看
  8797 的 `zmax_data/tcp_ar_server_restart.log` 有没有 `POST /api/arm/step_traj` 那一行 ——
  只有 `GET /status` 在刷 = 请求根本没发出(前端 busy 卡住/按钮点错), 有 POST 却是 200 而机器人没动 = 服务端闸拒(看返回体 `stage`)。
- 8797 的请求日志在 `zmax_data/tcp_ar_server_restart.log`: 只有 GET /status 在刷 = 从未下发。
- **验按钮不看截图, 用 JS 触发 + 读回页面内部状态**: canvas 重页面上按坐标点击可能落空(元素在、可点、事件不触发),
  所以在控制台里 `document.getElementById('bTrajStep').click()` 直接走 handler, 然后读回 `RTRAJ.fi` / 状态行 /
  `GET /status` 三样。判“按钮本身好不好”就看 `.click()` 后 `RTRAJ.fi` 是否推进 —— 推了就是好按钮, 剩下的是坐标/遮挡问题。
- ✅ **夹爪慢这件事已治: 一次开合 0.95s**(原 ssh 冷起 ros2 三次 ⇒ 82.9s, 见下面「夹爪链」一节)。
  现在含合爪的整轮 `step_traj` 实测 `elapsed_s=12.7`。判「夹爪链又退回去了」看两处:
  `GET 8797 /api/grip/pos` 回 `ms` 应在 20ms 内、`via=grip_svc(Orin:39062)`; `grip_events.jsonl` 末条应是 `"via":"grip_svc"`。
  若又出现 80s 量级 `elapsed_s`(而 `step.secs` 只有几秒) ⇒ 常驻服务没在跑, 8797 回落到了 ssh 老路, 不是「卡死」。
  这期间 8797 判 busy ⇒ 再点单步被当「上一轮还在跑」只动仿真, 看着就是「怎么不跟着走了」。
  页面轮询超时保持 200s(原 60s 会在回落时误报), `elapsed_s>10` 时提示「含夹爪开合, 别急」。
- **页面 fi 初值是 0 不是 null**(页面初始化就设了) ⇒ 刷新后首点永远走 frames[1], 真机本来就在附近 ⇒
  位移≈0 看着「没反应」。修法: 首次单步先读 /status.cursor 把基准钉到 cursor-1, 走 frames[cursor](用 `_synced` 只做一次)。
- 🔴 **前端 `STEPREAL.busy` 卡死一次 = 之后每一下都「只动仿真」, 而且不报错**: 那个 700ms 状态轮询的
  `.catch(function(){})` 是**空的** ⇒ fetch 失败(8797 一重启就必踩)被静默吞掉、busy 永不复位;
  旧代码 busy 时只写一句"本次只动仿真"就 continue ⇒ 连点几下**仿真跑到真机前面好几个点**, 现场只说"怎么又不跟着走了"。
  三件定式一起上(缺一件就会复发): ①catch 里计失败次数, 连续 6 次就 `clearInterval` + 复位 busy 并在状态行报原因
  ②`STEPREAL.bt=Date.now()` 记开始时刻, busy 超过 **250s** 无条件自愈(busy 是纯前端变量, 任何异常路径都能把它晾在那)
  ③**busy 时整步都不动手** —— 勾了『真机也走』就在 `rtrajStep` 改 fi **之前**拦下并 `return`,
  保持「仿真一步 = 真机一步」; 让仿真先走、真机跳过 = 错位累积, 比直接拒绝难查得多。
- 🔴 **刚打开页面显示「#— · 未开始」而游标已在第 N 点 = 画面与真机脱节(不是没通步)**: 轨迹帧是**懒加载**的
  (`ensureTrajJoints()` 只在点击时才去读页面末尾那个 `<script id="rtrajData">`), 所以页面初开 `RTRAJ.frames` 为空、
  `fi=0`; 而服务端 `/api/arm/step_traj/status` 的 `cursor` 可能早就 42。判据: 控制台读 `RTRAJ.fi`(0) 与
  `RTRAJ.frames.length`(0) + 页面「游标 N/215」, 两下一比就知道是脱节而不是真机没走。
  定式 = 页面加载后 ~1.5s 自动读一次 cursor, 把 `RTRAJ.fi` 钉到 `cursor-1` 并把 `PREV.q` 刷到那一帧
  (**纯只读, 不下发任何动作**), 状态行写「已按真机游标接上: 走过 N 点 · 画面 #N-1 · 点单步走第 N+1 点」。
  验收: 刷新后不点任何按钮, `RTRAJ.fi == cursor-1` 且状态行是 `#42 · X.. Y.. Z..`(不再是「未开始」)。
- **单步会跳视角**: rtrajStep 里的 `vrFitBox()` 加随后的 `mjPushQ/larmFreezeOn` 会改写 `VR.dist/VR.tgt`(改成 MuJoCo 机位),
  锁必须在 **rtrajStep 函数第一行**设(`if(!window.VR_CAM_LOCK) VR_CAM_LOCK={...}`), 并在 `drawVR()` 每帧钉回;
  锁晚一行就锁到被改后的值。
- 🔴 **解锁点必须覆盖所有会改视角的入口**, 漏一个用户就报「视角怎么转换不了了」: 滚轮 · 中键平移 ·
  **左键拖动旋转(pointerdown 的旋转分支 + pointermove 的旋转分支两处都要)** · `vrFitBox()`(🎯对准/双击)。
  只挂滚轮+中键时, 左键一拖 `drawVR` 每帧把 yaw/pitch 写回锁定值 ⇒ 手感就是「死住、转不动」。
  自检(控制台, 不用手拖): 先置 `window.VR_CAM_LOCK={...}` → `dispatchEvent(new PointerEvent('pointerdown',{clientX:400,clientY:300,button:0,buttons:1,bubbles:true}))`
  → 读 `!!window.VR_CAM_LOCK` 应为 false → 再 `pointermove` 移 80px, `VR.yaw` 应变化 ≈0.8rad。

### ↩ 回退 1 点: 服务端**不挡后退**, 同一条通道反着走

- `rtrajStep(-1)` 原设计只退仿真(注释: 不让真机倒走)。要真机也退, 用**同一个 `stepRealFollow(帧号)`**, 只是 `start` 比当前游标小。
  实测可行: `arm_step_traj.py` 只有 `MAX_JUMP_DEG=40` 跳变闸, **没有任何"禁止 start < cursor"的逻辑**。
- 实现定式: 先 `rtrajStep(-1)` 退仿真并重画 → 读回 `RTRAJ.fi` 确认真的退了(没变就报"已在第 0 点") →
  若勾了『真机也走』且 `STEPREAL.busy` 为假, 再 `stepRealFollow(RTRAJ.fi)`; 真机在忙就**本次只退仿真**并提示等到位再点。
- **往返验证法(可照抄)**: 退 1 点 → 等到位 → 再前进 1 点 → 量两次坐标是否回到**逐位相同**。
  实测 485.02/129.75/702.84 → 退到 486.68/148.33/700.54 (frames[151] 486.77/148.49/699.01, 误差 ~1.5mm) → 前进回 485.02/129.75/702.84,
  `ok_all=True "全部 1 点走到位"`。**往返回到原值 = 无累积漂移**, 这比单看一次到位硬。
- 🔴 **倒走的风险与前进不对称**: 相邻点最大跳变 31° 能过闸, 但倒走等于把走过的路径反着再走一遍; 中间若有夹爪开合/工件已放入孔内,
  回去撞上的可能**判断不了** ⇒ 第一次用建议先**不勾真机**纯仿真确认画面和点位对得上, 再勾。别把"前进安全"直接推给"后退也安全"。

### 🔴 用户说「你别动 / 我要自己操作」= 立刻切成只读, 一行按钮都不许点

他亲手动真机(单步/回退/拖拽示教)时, 你唯一合法的动作是**只读轮询**:
`GET /api/tcp` + `GET /api/arm/step_traj/status` + 读 `traj_step_state.json`。
- **不许**点页面按钮、**不许**用 `console` 驱动 `rtrajStep`/设 `RTRAJ.fi` —— 那是**和他抢同一条真机通道**, 而他的眼睛盯着臂。
- 🔴 **点复选框后必须读回 `checked`**, 不能假设点成功了。实测连点两次『真机也走』仍为 `true`(被别处重置),
  当时若接着用 JS 推进帧就可能在“以为只动仿真”的情况下真派单 —— 正确做法是先 `document.getElementById('cSyncArm').checked` 读回,
  只有在确认为 false 之后才能碰轨迹帧; 读回不一致就**停下来告知**, 不要用 JS 强设了事。
- **监看时要能说出“这一笔是不是他点的”**: `status` 里 `start`/`n`/`done` 能反推。实测我看到 `start=152 n=1 done=1`,
  而我自己的操作是设到 frames[126] ⇒ 立刻能判定是**他**在单步。汇报时把 `start/n/done` 原样给出, 别用“好像动了一下”。
- 他问“我现在是第 N 点么? 下一个就是修改点吧?”时, **不要顺着他的话确认**, 按真数报:
  游标 `cursor` 是“已走完的点数”, 下一点 = `frames[cursor]`。实测他说 151 而 `cursor=153`, 两个修正点(126/152)都已走过去 —— 这种“他记错一位”很常见,
  顺着答会把后面的判断全带偏。真机位姿要和 `frames[cursor-1]` 对, 偏差 >5mm 就说位姿与游标不一致(可能被人推过)。
- 被问“能不能前进”时, 判据是**刚走过的那一段有没有异常**, 不是“应该没事”: 回退留了 1.5mm 内、关节无跳、`ok_all=True` ⇒ 可以前进; 任何一项不满足就先把数字摆出来让他定。

### 🔴 报位姿: `/api/tcp` **没有姿态角**, abc 必须取 station 口径

- `GET /api/tcp` 只给 `x/y/z`(米) + `quat` + `joints`, **没有 rpy/abc 字段**。
  用 `d.get('rpy_deg') or [0,0,0]` 这类兜底会**静默报出 A=0 B=0 C=0 的假零值**(实测踩过,
  同刻真实姿态是 `116.956 / -67.000 / 55.417` 量级)。要给用户报数值时, **取不到就报取不到**, 不要用"缺失即默认值"。
- 自己用 ZYX 公式把 quat 换成欧拉角, 与页面/示教器的 **ROKAE 口径不是一回事**: 同一姿态手算得
  `116.956 / -67.000 / 55.417`, station 显示 `24.201 / -82.579 / 153.522`。
  ⇒ 姿态一律取 **8793 `/station` 右栏「🎯 实时位姿」卡片**(5Hz, SDK 直采 `endInRef`, 与示教器同口径,
  点一下可复制六值); 要程序化就调 `tools/pt_pose.py::abc_deg` 那份唯一实现, 不要现场推导。

### 「我要自己动机器人」的三句标准回答

- **位姿在哪看**: 8793 `/station` 右栏「🎯 实时位姿」卡片 —— 不是按钮, 打开即跳, 5Hz。
  ar3d 页面**没有数字位姿 HUD**, 只有三维画面 + `Δ` 偏移; 要数字只能看 station。
- **ar3d 两个"跟随"别混**: `🎯 跟随真机`(右下, 持续按 `/api/tcp` 每拍重画, 代码 `rtrajFollowOn()`)
  vs `⟲ 同步真值`(一次性重画后停住, 用于"仿真演完画面停在最后一帧"时校正)。要实时跟随点前者。
- **动手前四项就绪一次取全**: `GET 8793 /station/status` 的 `ctl` 子对象比逐接口问快 ——
  `ctl.motion_armed` · `ctl.robot.power=="on"` · `ctl.robot.operation=="idle"` · `ctl.robot.mode=="automatic"`,
  外加 `estop/collision/has_error` 必须 false。`ctl.robot.last_alarm` 常是几十小时前的陈旧告警,
  只要 `has_error=false` 就不拦。授权界面写"剩 0s"= 已过期, 必须先重授, 否则方向键点了不动。
  ⚠️ `tcp` **不在** `/station/status` 里, 别在那儿找位姿。

## 轨迹段语义核验: 用「逐点耗时累计 + 几何真值距离」, 不用点数均分(实测把「扫码」错标成「插入孔内」)

- **段表真源 = `tools/ss_meta_task_ar.py` 的 `_REPLAY_SEGS`(带色)**, 由 `tools/task_build.py` 重建到
  `config/tasks/ar_meta_tasks.json`(`long_horizon.replay.gantt`) 和 `config/tasks/tasks.json`。
  `tools/replay_derive.py::SEGS` 与 `tools/rokae/arm_step_traj.py::GANTRY_SEGS` 是**同界副本 ⇒ 改一段要四处同步**,
  改完跑 `./gui-venv311/bin/python tools/task_build.py` 重建(别手改两份 json, 会被重建覆盖)。
  8797 是**实时读** `ar_meta_tasks.json` ⇒ 改完刷新页面即生效, 不必重启。
- 用户报「MT 33.1s」这类时钟读数, **先换算成点号再谈语义**: 逐点实测耗时真源是
  `zmax_data/runtime/traj/replay215_timing.json` 的 `points[].secs`(215 点 MoveAbsJ 实测), `Σ` 累计才知道 33.1s 落在第几点。
  累计表直接跑 `scripts/traj_point_table.py`(打印 点号/t/TCP/离孔距/单点s/累计s)。
- **判段语义三把尺**(缺第三把会把「抓取」认成「插入」): ①该点 TCP 到关键真值(孔口/插到位/示教点)的距离
  ②单点耗时 ③**本站/本帧在孔轴上的行进方向**(沿 +x 递增 = 插入, 递减 = 拔出)。
  离孔 >100mm 就不可能是插孔, 不必问人; 单点明显偏长(如 4.08s 而邻居 1~2s)= 停在那里做事。
  实测: 第 17 点 y=70.8 而孔 y=229.8(差 159mm、离插到位 194mm) ⇒ 那一段不是插入;
  第 16~19 点四个点共 10.27s ⇒ 那是在扫码(腕部相机对码), 不是插孔。
- 🔴 **只靠「离孔近」定不了插入**: 料盘与孔在同一工位时, 抓取位和孔下口可以只差几十毫米
  (实测第 20 点 `762.6/228.1/190.1` 离孔下口 49mm、离插到位 3mm 都"像插入", 而它实际是**抓取光模块**的落点)。
  ⇒ 判"这一段到底是插还是抓"必须看**这一段自己走的方向与幅度**(23 点 x 从 762 单调增到 811 = 插入),
  或者直接问现场动作顺序 —— 他不会说错顺序, 只会说错名字。
- 拆/改段时 `dur_s` 必须由 `points[].secs` **重算**(不是按点数均分), `pct` 按 `_total_s` 重算,
  节点字段要齐 `name/i0/i1/n/dur_s/pct/per_pt_s/color` —— 只补 `name/dur_s` 会在页面上丢颜色和点数。
- **画面级复核**: 臂相机取帧真源是 Orin `http://192.168.23.66:8794/frame.jpg`(备 8792),
  **不要从 8791 的 `*.mjpg` 流里抠帧**(读 400KB 也取不到 JPEG 边界);
  L5 理解用 `./gui-venv311/bin/python tools/ar_l5_understand.py --jpg <帧> --hint "<要判的问题>"`。
  L5 对「有没有二维码/扫码枪/孔口」这类细节会含糊且耗时 60s+, 只能当旁证 —— 定语义仍以几何+耗时为准。
- 段名要按实测改, 不要让"上一版名字"继续在 `tasks.json`/甘特图/对外文档里传播: 改完回读四个位置并报累计时间轴。

### 现役 16 段定案(按现场动作顺序核过, 直接引用别重推)

```
 0–9    抓取(合爪#9)      10–15  过渡/举升        16–19  扫码(对码)
20–40   抓取光模块       41–90   举升/转运        91–113 插入·松开·退回·抓环
114–119 拉环解锁·拽出    120–144  扫码(举高段)     145–149 过渡
150–160 金手指检测       161     过渡            162–193 表面检测
194–197 过渡            198–204  下放入盘        205     松开分拣(#205)
206–214 回位
```

### 91–113 与 114–119 各是**多步合一**, 不是一个动作 (现场口述过的真实工艺)

- **91–113 = 插入到位 → 松爪(件留孔内) → 退回 → 回来抓拉环** 四步。判据看游标所在点的 TCP 在孔轴上往哪走:
  游标 95 是 `X776.2 Z193.0`(孔内, 761.3→811.6 之间 = 插入中); 游标 106 是 `X819.0 Z223.0`
  (X 已越过插到位 811.6, Z 比插到位高 30mm) ⇒ **退出来了, 正贴在孔口上方抓环**。同一段里 TCP 先单调进、再退出抬高,
  所以「这段是插入还是拔出」不能用段的起止两点判断, 要看**当拍那一点**的位置与 Z。
- **114–119 = 拉环解锁 → 拽出**, 两个动作。绿色拉环是光模块的机械锁扣: 不解锁直接沿轴拽会伤金手指。
  ⇒ 别把它写成「沿轴拔出 47mm」一个动作, 报节拍/写文档都要拆成解锁 + 拽出。
- 🔴 **FW Loading 刷写是并行的工艺时间, 不占这 215 帧**: 插到位后件留在孔内通电刷写, 机械臂松爪撤走;
  它只体现为墙钟时间。算 UPH / 单件节拍时必须把它计入, **只按轨迹 11.28s/件 算会虚高**。
  用户在跑的时候口头报的阶段(「松开了, 正在退回」「在 FW Loading」「夹爪去拉环解锁」)就是这几个子步,
  **他每报一句都是在给段名做规格修正**, 直接按它对齐段表与面板, 别当成闲聊或反问待确认。

- 🔴 **「插入孔内」与「拔出模块」曾经被标反了位置**: 旧表写 `20–40 插入孔内` / `91–113 拔出模块`,
  而真机跑到游标 95 时 TCP 是 `X776.2 Y228.0 Z193.0` —— 正落在 2# 孔插入区间(下口 761.3 → 插到位 811.6)之间 ⇒
  那一段就是**插入**, 现场看到的是「明明在插入, 节拍却显示拔出」。
  ⇒ 段名与真机现场动作冲突时,**以"当前游标所在点的 TCP 落在哪个物理区间"为准**, 别拿上一版段表自证。
- 改段名要**四处同源**: `tools/ss_meta_task_ar.py::_REPLAY_SEGS`(带色, 是段表真源) ·
  `tools/replay_derive.py::SEGS` · `tools/rokae/arm_step_traj.py::GANTRY_SEGS`(真机跑批逐段上报的 seg 名) ·
  以及重建产物 `config/tasks/ar_meta_tasks.json`(跑 `tools/ss_meta_task_ar.py` 或 `tools/task_build.py` 生成)。
  验收: `grep -c '旧段名'` 全为 0 且新名出现在生成物里 —— 只改一处会让甘特图与真机 `_cap.segs` 两名并存。
- 🔴 **第五处是历史值，改了段名它也不会变**: `GET /api/arm/step_traj/status` 里 `steps[].seg` 是**上一次跑批时
  就写进日志的**，不是现算 ⇒ 改完段表回读它还是旧名，很容易被当成「段表没生效」又去改一遍。
  判"段表改成了没"只认源码 + 重建产物（上面四处）；新名字要等**下一次启动跑批**才进 status。
  现场看到旧名时主动说明这一点，否则他会以为你改了个空。
- 📌 **到点触发 AOI 的完整 request 契约**（三个路由的先后、`/last_result` 字段语义、0 基帧号、
  过了检测位还没触发怎么退游标重走）见 `references/aoi-on-arrive-contract.md`。
  动 `AOI_ON_ARRIVE` 之前先读它 —— 那三条路（触发/判决/取图）弄错任何一条，表象都是“轨迹跑完了、日志里也有图，
  但检测从来没跑过”，而且全 200、不报错。

### 节拍/MT 面板必须按**真机游标**判阶段, 不能按仿真时间空转

症状: 真机停在插入段(TCP 在孔内), 页面节拍却显示「MT-02 拔出」。
- 真因: `mtNow()` 里 `PLANT.on` 那条分支用 `PLANT.simT % cycle_s` **自由跑时间轴**, 与真机完全脱钩 ⇒
  只要页面开着播放, 它就会自己走到下一个元任务。时间轴只能当**兜底**, 有游标时必须让位。
- 定式: 先取 `SYNCUR.cursor`(即 `/api/arm/step_traj/status` 的 cursor), 非空且 >0 就按游标分档返回该 MT 的时间点,
  `src` 写「真机游标 N → MT-xx」, 让页面自己标出判据来源(用户一眼能看出是游标还是空转)。
  分档与段表同源: `≤113`(抓取/举升/插入) ⇒ MT-01 · `114–119` 拔出 ⇒ MT-02 · `≤197` AOI ⇒ MT-03 · 其余放盘/回位 ⇒ MT-04。
- 验收: 面板文本里出现「真机游标 95 → MT-01」并显示右手 `MT-01 上料槽取模块 → 插入目标孔`;
  不是「MT-02 拔出」。游标区间与段表一改, 这个分档必须同步改 —— 它是段表的**第二个副本**。

## 回放修正表 traj_adj.json 与真机执行链 (2026-11-17 实测)

- **修正表原本只给页面看**: `tools/web/traj_adj.json` 只被 8797 的 `GET /api/traj_adj`(注释写「页面加载后覆盖内存帧」)读到;
  真机腿 `arm_step_traj.py` 的输入口径是 `real_traj_joints.json` 的 `frames[0:N].j` ⇒ **真机跑的是未修正帧**,
  而表里那句「回放/单步/真机执行全走修正后的帧」当时并未落地。判据: 全仓 `grep -rn traj_adj` 只命中 tcp_ar_server.py 两行。
- **接法(已落地)**: 在 `/api/arm/step_traj` 组装 `_cmd` **之前**按 `points[*].j_new_rad` 覆盖 `_fr[i]["j"]`,
  并在 `_cmd` 里带 `"adj_points": sorted([...])`;磁盘 raw 215 帧一字节不动。改完**必须重启 8797**(裸进程)。
- **零动作验法**: `POST {n:1,start:i,dry:true}` → 读 `zmax_data/rokae_sdk/traj_step_cmd.json` 的 `frames[0]`
  与 `j_new_rad` 逐位比,并看 `adj_points`。真跑验收看 `traj_step_out.log` 里该点的 `target_deg` 是否等于修正值
  (原值在同一文件里有大量历史命中, 别把旧行当本次)。

🔴 **段末 `traj_step_state.json` 可能不更新 ⇒ 续跑脚本盲读 cursor 会重派同段、被跳变闸拒**
实测: 204~208 段跑完(n_done 5, why 全部 5 点走到位), 状态文件里仍写 `start=204 done=0 cursor=204`,
续跑脚本按它又派 204 段 ⇒ 真机已在第 209 点, 报「第 205 点离真机当前姿态 54.4°(>30°) ⇒ 拒发」。
处置: ①续跑前先 `POST {"align":true,"dry":true}`, **按它返回的 cursor** 派下一段, 不要只信状态文件;
②分段脚本的完成判据用 `GET /api/arm/step_traj/status` 的 `running=false` + `n_done`, 不要用 `state.cursor` 推下一步;
③收尾核对末点: 真机关节 vs `frames[last].j` 每轴 max ≤0.12° 才算到位(实测 0.12° = 容差)。

## 8793 / 8797 的重启姿势
- 这两个是**裸进程，不在 systemd**（用 `ss -ltnp` 拿 pid），别猜 unit 名。
- 正确重启：读 `/proc/<pid>/cmdline`+`cwd`+`environ` → SIGTERM 等退出 → `Popen(argv, cwd=..., env=env, start_new_session=True)`，这样 `--ctl-motion`、`--port 8793`、ZMAX_* 都不会丢。
- 页面是 `Cache-Control: no-store` ⇒ 改完只需普通 F5 一次；已开的 tab 不会自动换 DOM。
- 先判断是否真需要重启：改 HTML 不用；只有服务端 Python（新端点、authorize 签名、授权网关）才需要。

## 夹爪怎么"跟真轨迹一样"(录制没记夹爪事件时)
- 事实: `real_traj_joints.json` 只有关节角/`p`, 录制那段没有夹爪事件 ⇒ **动作点必须由轨迹几何给**, 不许编也不许只发一次装样子。
- 推导法定式: 拿 `frames[].p` 的 TCP 高度剖面 + 真停顿段
  ```bash
  python - <<'EOF'
  import json, numpy as np
  fr = json.load(open('tools/web/real_traj_joints.json'))['frames']
  z = np.array([f['p'][2] for f in fr]) * 1000                      # mm
  step = np.r_[0, np.linalg.norm(np.diff(np.array([f['p'] for f in fr]), axis=0), axis=1)] * 1000
  print('z min %.1f@%d  max %.1f@%d' % (z.min(), z.argmin(), z.max(), z.argmax()))
  print('停顿段', [(i, s) for i, s in enumerate(step < 2.0) if s])   # 连续几帧才动作
  EOF
  ```
  读法: 第一个最低位 = 落下夹持; 大幅抬升段 = 搬运(手里有件); 抬升后的最后一个最低位 = 放件位, 之后几帧再松。
  写进 `tools/web/real_traj_grip.json` 的 `grip`(`i` 是 0 基绝对帧号, 可负数; 服务每次启动都读, 改完即生效), 并在文件里留 `_derived` 说明推导依据。
- 🔴 **该文件里的 `grip` 可能是占位默认值**(如 `i=1 close` / `i=-2 open`, 语义上就是"开跑就夹、最后才松"), 别拿来当结论:
  按高度剖面重算并把 `_derived` 写清; 同时把 `_default_note` 里"推定默认"那类措辞跟实际值对齐, 否则下一个人会继续用旧值。
- 全程只有 1 处真停顿(`step<2mm` 连续帧)时**别指望用停顿定位**: 那份轨迹中位步长近 30mm, 基本连续运动, 判据只能是 z 剖面的极值(最低点/最高点)。
- 改这个 json 用**定点替换 + 回读**, 别整文件覆盖: 覆盖后必须 `grep -n '"i"' tools/web/real_traj_grip.json` 回读确认新值真落盘(实测出现过"写完了文件还是旧内容")。
- 分段下发不影响: 服务按 `start <= i < start+n` 把绝对帧号映射到本轮, 所以夹持点落在第几段都算得到; 臂到点后原地停 `hold_ms` 等夹爪动作完。
- **真通道自测(Orin, 必做一次再开跑)**: 只 source `/opt/ros/humble/setup.bash` 会报
  `The passed service type is invalid` —— 必须再 source **厂家工作空间** 并显式 domain:
  ```bash
  WS=/home/tashan/zl/tashan_robot_so_*/install/setup.bash
  ssh tashan@192.168.23.66 "source /opt/ros/humble/setup.bash; source $WS; export ROS_DOMAIN_ID=0; \
    ros2 service call /gripper_driver interfaces/srv/GripperSrv \
    '{target_pos: 0.0, target_speed: -1.0, target_force: 30.0, target_acc: -1.0, target_push_length: -1.0, target_push_speed: -1.0}'"
  ssh tashan@192.168.23.66 "source /opt/ros/humble/setup.bash; source $WS; export ROS_DOMAIN_ID=0; \
    ros2 topic echo /gripper_pos std_msgs/msg/Float32 --once"      # 闭=0.0 张=70.0
  ```
  `target_pos` 单位 mm(0=闭合, `ZMAX_GRIP_OPEN_MM` 默认 70)。**开跑前 `/gripper_pos` 读到 1000.0 是上电初值, 不是故障**;
  判成功只认回证到位(`|pos-target| <= max(3mm, 15% 行程)`), 服务返回 200 不算。

## action ⇄ 真机对账(断点里怎么比才不被骗)
`action` 是工程唯一输出(位姿口径)。用户会拿它和机器人屏幕上的 x/y/z/a/b/c 逐位对, **对不上时先分清是哪种差**, 别急着改算法:

- **落盘文件在暂停时不更新**: `zmax_data/ss_live/action.json` 只在画布 tick 时写。断点/暂停期间它就是上一拍(实测陈旧 169s), 拿它比正在动的臂必然差几个点。判陈旧看 `ts`(>3s 即旧), 用 `python3 tools/action_check.py` 现算一份再比。
- **判执行点只认派单事实**: `exec_index()` 取 `start + done`, 不用"位姿最近点"。215 点在空间上会来回经过同一片区域 ⇒ 最近点会跳错(实测第 71 点在跑, 最近点同时匹配 70 和 51)。最近点只作参考, 不作判据。
- **轮间空档取 last_sent**: 容器刚退出、游标已 +1 而还没派下一点时, 用 `cursor` 会显示成**下一个待发点**。`real_traj_flow._mark_sent()` 每次派单成功写 `zmax_data/rokae_sdk/last_sent.json`, `exec_index` 空档优先取它(300s 内有效)。
- **换口径必须前移到执行器**: 执行器 `src=ss`(实测+u·dt) 而节点层因直驱闸未放行换成 215 点 ⇒ 断点里的 `action` 是**被扔掉的那份**。`RobotExecutor._effective()` 在执行器里就换成真正下发的那份(`ZMAX_EXEC_EFFECTIVE=0` 可退回旧行为)。改这一处必须同步判据 `t_act_dim` / `t_act_pass` 认 4 维(直驱速度)/6 维(215点关节), 否则自检由绿变红。
- **2~3mm 的恒定残差是到位容差, 不是错位**: `tools/rokae/arm_step_traj.py:38 TOL_DEG=0.6`, 只要 `err<=TOL_DEG 且 operationState=idle` 就换下一点; 0.1°×臂展~1.4m ≈ 2.4mm。判"对上了"看**关节差**(约 0.1°)与 `i == 最近点`, 不看毫米。要压小就改 `TOL_DEG`(0.1 ⇒ 1mm 内, 每点多等 0.3~0.5s), 别去改轨迹。
- **断点停在语句执行前**: 断在 `self._print_action(...)` 那行看不到打印(它还没跑); 要看到就停在下一行 `return action` 或按 F10。停在上游节点(如 `skills/atomic_skills.py clamp` ← `cognition.skill_step`)时执行器整拍不跑, 三个执行器断点都不会命中 ⇒ 用 `sudo py-spy dump --pid <pid>` 看真实栈再判断。
- 终端打印行: `execution.py::_print_action()` 在 `return action` 之前, 每拍一行 `[action] i=/src/目标/实测/Δ/夹爪/下发=直驱|215点`; `ZMAX_ACTION_PRINT=0` 关闭。回退档带 `回退` 标记。

## 运行中采数据 / 轨迹分状态（只读，零下发）
用户会一边 F5 跑 215 点一边要"你去采数据"。采的姿势和判据都有坑：
- 采集形态：2Hz 拉 `http://192.168.23.66:8794/frame.jpg` + 读 `zmax_data/rokae_sdk/traj_step_state.json` 的 cursor + `tcp_out/latest.json`，逐帧落 `manifest.jsonl`（file / pose_mm / joint_deg / pose_age_s / cursor / ts）。现成脚本 `tools/run_capture.py`。
- 🔴 **停止判据不能用 `running=false`**：派单是逐点串行的，轮与轮之间 `running` 会短暂为 false（实测据此只采到 13 帧就退，而游标正从 173 走到 183）。判据 = `running=false` **且 cursor 连续 25s 未变**。他长时间停在断点仍会触发，采完查 cursor 是否到 215，没到就补采一轮。
- 分工序只用三样可取证的东西，不猜：示教点邻近（<40mm，`data/skills/l2_atomic/taught_points.json`）+ 夹爪计划（`tools/web/real_traj_grip.json` 的 `grip[].i/act`，注意是 `grip` 不是 `events`）+ TCP 高度剖面。
- 现成工具：`tools/traj_phase_segment.py` → 19 细段 + 工序层 + CSV（`zmax_data/reports/traj_phases_*.csv`）。
- **判"取件是哪一槽"要三路合证**，缺一路就明写"推断"：① 全轨迹最低 z 点 + 夹爪 close 帧；② 该位姿到 7 个 slot 示教点的距离（最近与次近应差 ≥5 倍才算无歧义）；③ 该 cursor 的运行帧用 YOLO 低阈值 0.15 检 peg，box 在相邻帧稳定出现。
- 实测基线（同一场地，可直接复用做回归）：i=9 合爪 @ 649.2/252.7/114.9 ⇒ **slot6**(647.4/255.9/110.1) 差 6.1mm、次近 slot7 47.4mm；插入两段 20~44 与 91~115（`insert_pose` 0.8mm）；AOI 观察 163~185（侧面点0~3）；抬升转场 128~152 到 z=999mm；开爪 i=205 @ 650/-141/220（附近 143mm 内无示教点 ⇒ 放件位没示教过）。
- 🔴 夹爪中段全程是"合"（只有 i=9 / i=205 两个事件）⇒ 抓与放只能靠这两点定位，别指望段内出现状态变化。

## 急停/中断后的复检清单(再按 F5 之前逐条读)
```
pgrep -af 'engineering/start[.]py'                 # 无输出才能启动
pgrep -af 'ss_canvas_loop[.]py'                    # 有 PPID=1 的实例 = GUI 看门狗在替你 tick, 必须清掉再启动
fuser /tmp/zmax_start.lock                         # 空 = 无人持有; 文件里残留的 pid 已死就 :> 清空
curl -s 127.0.0.1:8797/api/robot_state             # estop=False · op=idle · power=on; op=jogging/drag ⇒ 执行腿必拒发
curl -s 127.0.0.1:8797/api/arm/step_traj/status    # running/cursor/done
python -c "..."  对比 tcp_out/latest.json 的 joint 与 frames[0]['j']   # 每轴差 ≤2° 才算"已回初始位置"
```
- 🔴 **引擎可能不在你的入口里跑**: GUI 看门狗会拉起 `tools/ss_canvas_loop.py`(PPID=1), 与 `start.py` **并行** tick 同一张画布 ——
  两套 10Hz 各写各的状态, 页面上数字会跳、断点也不命中。现在两个入口共用 `flock(/tmp/zmax_start.lock)`:
  `start.py` 持锁时被拉起的引擎会打印 `⛔ 已有工程入口在运行(pid=…)` 并退出 3, 这是**正常保护**, 不是崩溃。
  顺序: 他先 F5 拿到锁 → 你再 kill 掉老的独立实例; 反过来 kill 完看门狗立刻重生, 锁还空着就又变成它在跑。
- `op=idle` 是执行腿唯一硬条件; `mode=manual` 不影响下发(建议切自动但不必拦), 报警历史里挂着上次`急停触发` 也不影响。
- 「回初始位置」= 与 `frames[0].j` 逐轴比(不是看 TCP 毫米值), 报每轴差 + 最大值; 演示器手动摇回去也算, 别自己发运动指令去"补"。
- 拒发要看真因: 日志 `state_before{power:on, op:jogging}` ⇒ 是 **op 闸**(他在示教/拖拽), 不是代码坏了; 别改代码。
- 🔴 真要**立刻停臂**就杀执行容器: `sudo docker kill $(sudo docker ps --format '{{.ID}} {{.Image}}' | grep humble | grep -v -E 'moveit|tap|agent|sampler' | awk '{print $1}')`。段在容器里跑, 停 `start.py`/挂断点都只管住派单方; 杀完按 `/proc/<pid>/stat` 的 `Z` 把 `traj_step_state.json` 清成 `running=false pid=0`(僵尸会卡住下一次派单)。
- 复位三件套: `POST /api/arm/step_traj {"reset":true}` 把游标打回 0; 把 `zmax_data/ss_live/traj_flow.json` 刷成 `phase=IDLE, cursor=0`(否则页面横幅还挂着旧的"第88/215点", 他会以为在跑); 删掉 `/tmp/zmax_stop_at_<tag>` 自停触发器(留着就是每拍停=看起来卡死)。

## 验收清单
```
curl -s -o /dev/null -w '%{http_code}' 127.0.0.1:8797/api/arm/step_traj/status     # 200
curl -s 127.0.0.1:8793/ctl/arm -X POST -d '{"on":false,"note":"自检"}'            # 回 mode/debug 字段 = 新代码在跑
python tools/ctl_auth.py info                                                      # armed/left_s/mode
演练 ZMAX_AUTO_TRAJ=1 ZMAX_TRAJ_DRY=1 → ▶ 第1~10点 → 第11~20点 → … → 215/215 DONE
演练后把 traj_step_state.json 还原成原 cursor（别改现场游标）；全程确认零真机指令
```

- 🔴 **不许在他的终端前台跑 `start.py`**: 入口有单实例 `flock(/tmp/zmax_start.lock)`, 你前台跑一次就把他下一次 F5 挡成
  `⛔ 已有工程入口在运行` + `exit 2`, 他的终端还被你的输出淹没(他会说"你抢夺我的光标")。要验就只在**只读**面验
  (进程表 / `flock` 持有者 / HTTP 状态 / ss_live json), 或由他按 F5 后你再看; 真要占锁跑证明, 先确认他没在跑并当场告知。

## 与单步全链并存
- `ZMAX_STEP_MODE=1` + `ZMAX_SINGLE_THREAD=1` + OMP/MKL/TORCH_NUM_THREADS=1：`engineering/step_mode.py` 把线程改内联、拒绝节点发起的 .py 子进程并点名（`python -c` 库探针要放行，否则 metaworld/aligner 初始化被误杀）、关掉引擎快车道 ⇒ 一拍一趟，每个节点都能停。
- 节点里的死循环 worker（AOI 巡检等）必须先拆 `_xxx_once()` 单轮 + `thread_policy.spawn_or_inline`，否则“内联死循环”会挂住整拍。
