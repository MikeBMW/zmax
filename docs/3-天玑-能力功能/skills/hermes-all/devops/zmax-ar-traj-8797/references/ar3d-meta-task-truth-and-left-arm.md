# ar3d 元任务 · 点位真源分层 · 左臂冻结 · UPH 双口径

改 ar3d 页面「元任务 / 插口数 / 料盘位置 / 点位 / 回放时左臂」时的唯一依据链与坑。

## 1. 元任务是一条单向生成链，别手改产物

```
config/points/cell_points.json          ← 点位真源 (frame=sim_base, mm)
        ↓  src/lerobot/engineering/nodes/cycle_plan.py  (同内容另一份: middleware/nodes/impl/cycle_plan.py)
zmax_data/runtime/traj/sim_insert.json  ← 段表 (392 段), 运行时生成物
        ↓  tools/ss_meta_task_ar.py
ar_meta_tasks.json + tasks.json 的 TASK-07-AOI     ← 元任务定义
        ↓  tools/tcp_ar_server.py  GET /api/ar/meta  (字段白名单)
页面右侧元任务区
```

- **改点位** → 改 `cell_points.json` → 重跑 `cycle_plan.write()` → 重跑 `ss_meta_task_ar.py`。跳一步就会得到「页面显示的」和「段表算的」不一致。
- **改元任务（增删条、改节拍口径）** → 只改 `tools/ss_meta_task_ar.py` 的 `MT = [...]` 表 + `long_horizon` 构造，然后重跑。直接改 `ar_meta_tasks.json` 会被下次生成覆盖。
- 生成器自带守恒校验（`Σ(次数×段数) == 段数`）；不在段表里的元任务必须写 `in_392=False` + `pred=None`，否则校验必失败、不写盘。
- 「N 个插口」这种文案由 `describe(seq)` 从段表连续相同项自动压缩得出（`MT-01×2`），**不是手写常量**。看到 `MT-01×4` 说明产物是旧段表生成的 ⇒ 重跑生成器，不要去改产物里的字符串。
- `sim_insert.json` 的 `flow` 文案必须按 `HOLES` 长度生成；写死「孔1→2→3→4」是 4 孔时代的残留，现场只有 2 孔时会自相矛盾。
- `/api/ar/meta` 有一层**字段白名单**（只透 `uph_target/tact_s/segments_total/round_total_s/meta_count/verified/hands/rounds/replay` 之类），新增的 long_horizon 子键要同时加进白名单，而且**白名单是代码 ⇒ 必须重启 8797 才生效**。
  `meta_tasks` 是每请求热读文件 ⇒ 那部分不重启就能看到。交付时把这两件事分开说，别让用户以为整套都没生效。

## 2. 点位真源分三层，混用就错 100 多毫米

| 文件 | 坐标系 | 单位 | 谁写 | 用途 |
|---|---|---|---|---|
| `config/points/cell_points.json` | `sim_base` | mm | 工程配置（仿真段表真源） | 段表/仿真规划 |
| `data/skills/l2_atomic/taught_points.json` | 真机 base | **米** | 现场示教直录（人机在环/点动调试） | **物理真值** |
| `tools/web/real_traj_joints.json` | 录制真值 | m + rad | `real_traj_joints.py` 从 poses.jsonl 导出 | 回放 |

- 两者不一致时**以示教实测为准**：曾出现 `cell_points` 的槽位 x=490~494 而示教实测 647~649，系统性偏小 ~156mm（z 还偏高 ~8mm）。这种整列同向偏移 = 坐标真源用错了，不是单点录错。
- 第二列（无实测）按「第一列实测 x + 列间距」推导，并在 `src` 字段写明是推导值，不要冒充实测。
- 槽位真值核对一条命令：读 `taught_points.json` 的 `slot1..slot7` 的 `pos`（米）×1000，对段表 `cycles_data[].slot`。
- 工位点位（金手指点1/2、侧面点0~3、插拔准备/到位/插口）用 `aoi_points/*.json` + 215 点轨迹**最近邻匹配**确定落点（距离 <30mm 才算落地）。
  这个匹配能纠正拍脑袋的猜测：曾把 `插入口_拖拽1020b`(1.7mm) 误当金手指检测位，实际金手指检测在 z≈650 的另一段。
- `golden` 单键是 `cycle_plan.py` 依赖的兼容键，加「金手指点2」时**新增 `golden1/golden2/goldens`，不要改 `golden` 的语义**。

## 3. 回放时左臂必须冻结（只有右臂轨迹数据）

页面左臂默认**照抄右臂**：

```js
let Lq = LARM.q ? conv(LARM.q) : (Rq ? Rq.slice() : null);   // ← 空 q 就跟右臂
const LMAP = LARMFK || LINKM;                                 // ← 渲染同理
```

所以只推 `PREV.q`（回放）时，左臂会跟着一起跑。修法是加冻结态：

- `LARM.freeze / holdQ / holdFK` 三个字段；
- `larmMap()` 返回 `freeze ? holdFK : (LARMFK || LINKM)`，替换**每一处** `LARMFK || LINKM`（取景 `pts.push` 和 `drawUrdf` 两处都要改，漏一处就有一条臂在动）；
- `larmFreezeOn(srcQ)`：有关节角存关节角 + `urdfFK`，否则 `JSON.parse(JSON.stringify(LARMFK||LINKM))` 深拷贝当前链矩阵；
- 回放开始 `larmFreezeOn(LARM.q)`，走完/停止/`rtrajStop` 三处都要 `larmFreezeOff()`，否则回放结束后左臂永久冻住；
- `mjPushQ` 里 freeze 时只推 `holdQ`（无关节角则推 null），**绝不推 Rq** —— 这一路是喂 8802 MuJoCo 的，漏了左臂在仿真里还是会动。

验收口径（必做，别只看代码）：回放跑几秒，取两次 `larmMap()['tool1'].t` 对比 —— **必须逐位不变**，同时右臂 `urdfFK(PREV.q)['tool1'].t` 要变。只验 `LARM.freeze==true` 不算验过。

## 4. 反向单步会被 jump 保护拒绝，别硬来

`POST :8797/api/arm/step_traj {"start":N,"n":1}` 只能往前。想让机械臂「退回」某个更小的点号会收到：

```json
{"ok":false,"stage":"jump","cursor":172,"near":194,
 "err":"第 173 点离真机当前姿态 161.9°(>30°) ⇒ 拒发, 防瞬移",
 "hint":"真机现在最接近第 195 点 · 点『◎ 对齐当前位置』把游标挪过去再走"}
```

这是**安全设计，不要去绕**。要验证某个靠前的点只能等下一轮回放走过去（提前算好 ETA 告诉用户），或用页面「◎ 对齐当前位置」把游标挪到真机当前位置。

## 5. 一个 8797 上跑了两个 traj_loop ⇒ 看起来像「卡死」

症状：日志只有启动三行（轨迹点/授权/版本）之后再无 `📤 派单`，cursor 在原地踏步。
根因：新旧两个 `traj_loop.py` 抢同一个 8797，`step_traj` 一直回 `busy`。
判据：`pgrep -af traj_loop.py` 应只有**一对** bash 包装 + python 本体；出现两组就是重复。
清法：按精确 pid kill 旧的（`pkill -f` 会匹配到自己的 shell 命令串）。

## 6. 215 点轨迹的流程分段（夹爪是骨架）

夹爪真源 `tools/web/real_traj_grip.json`，**只有两个动作**：

```
#9   close  保持 2000ms   ← 抓住光模块
#205 open   保持 2600ms   ← 分拣放下
```

⇒ `#10~#204` 全程夹着模块走完所有工序。按位置特征分段：

```
#0-9      初始 → 抓取位            #9 close
#10-40    插拔区(准备点#15→插入到位#23→插入口#30)      插入
#41-90    转移(含 y 负区 #50-69)
#91-113   插拔区第二次(#93 口拖拽→#104 插入点)         拔出
#120-144  x<300 + z>850(最高 999、最左 255)            扫码
#150-160  金手指点1/2 附近 z≈650                       金手指检测
#162-193  侧面点0/1/2/3 (#171-180 驻留)                表面检测
#198-204  下落到 z<200
#205      open                                        分拣
#206-214  回位
```

要点：
- **插拔是两趟**，中间隔着 #41-90，不是一趟。
- **扫码在插拔之后**（只有 #137-144 举到 z>850 且 x 到 255）；料盘 `plane_z=110mm`，那个高度不可能是放料。
- 落在某区域 ≠ 停在该区域。判断「检测位」要看**驻留簇**（连续几点挤在 20mm 内），不是「经过该区域」。

## 7. UPH 两套口径，禁混算

| 口径 | 来源 | 数字 |
|---|---|---|
| 仿真产线 | 392 段 / total_t / mods | ~319 UPH（稳态 11.28s/件，双臂并行） |
| 真机回放 | `real_traj_joints.json` 的 `dur_s` / 1 件每条轨迹 | 42.85s/件 ⇒ ~84 UPH |

- 回放的 `dur_s` 是**录制时真机按 100% 速度走完**的时间（已压缩静止空档），不是仿真推算。
- 一条 215 点轨迹 = **1 件**（`#9` 闭合 → `#205` 松开）。
- 报 UPH 时必须写明是哪套口径；`long_horizon.replay` 就是给回放单独留的结构化字段。
- 回放跑 `speed=20%` 时实测约 6s/点 ⇒ 一轮 ~21 分钟，这是**调试速度**，不能当节拍报。
