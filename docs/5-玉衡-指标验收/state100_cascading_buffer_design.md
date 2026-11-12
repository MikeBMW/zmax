# 100D 统一状态空间 · 桌面级联缓冲工位（v2 设计 + 验收）

场景：离散制造中的**级联缓冲（Cascading Buffering）**。
瓶颈：光模块**固件刷写机**（串行、一次一件，t_flash≈4s）。
快侧：桌面机械臂（上下料）。
目标：**异步双工** —— 刷写机在刷的那几秒，机械臂必须去伺候前后两个缓冲区，绝不在设备旁干等。

代码：`src/lerobot/policies/left_right/state_space/desktop_buffer_state100.py`
验收：`tools/verify_state100.py` —— **27 项判据 27 PASS**

---

## 一、物理拓扑（桌面才是缓冲区）

```
   上游送料                  Infeed Buffer (N=16, 4×4)              Outfeed Buffer (M=8)
   ┌────┐   PICK         ┌──┬──┬──┬──┐        ┌─────────┐        ┌──┬──┬──┐
   │ 料 │ ─────────────▶ │槽│槽│槽│槽│ ─LOAD▶ │ 刷写机   │ ─UNLD▶ │槽│槽│槽│ ─▶ 下道工序
   │ 盘 │                ├──┼──┼──┼──┤        │ t_flash │        ├──┼──┼──┤
   └────┘                │槽│槽│槽│槽│        │  ≈ 4 s  │        │槽│槽│槽│
                         └──┴──┴──┴──┘        └─────────┘        └──┴──┴──┘
                              │                    │                  │
                         N > M 原则                │ NG/校验失败        └─ AOI 检测站 (光学)
                         (防止设备断供)             ▼
                                              废料盘 (或重试队列, 插队回刷)
```

- **N（待刷写）> M（已刷写）**：刷写机可能卡顿/重试，前面必须多存料防止断供。当前取 N=16、M=8。
- 五个锚（真源：现场段表，mm→m）：`infeed_slot` (0.490,0.499,0.240)、`loader_slot` (0.767,0.228,0.278)、`outfeed_slot` (0.490,0.076,0.198)、`insp_slot` (0.360,-0.117,0.654)、`scrap_slot` (0.469,-0.402,0.200)。
- **槽位四态**：`EMPTY` / `OCCUPIED_UNPROCESSED` / `PROCESSING` / `OCCUPIED_PROCESSED`；逐槽明细用 **2bit/槽 位图**（`pack_slots/unpack_slots`，16 槽实测往返一致 `0x0003e555`），进状态向量的只是四态计数。

## 二、队列逻辑

| 队列 | 规则 | 状态向量里的量 |
|---|---|---|
| FIFO | 进 Infeed 按序取 | `fifo_len` |
| 重试（高优先） | 校验失败**不许排尾**、不许丢；插队首或专用重试槽 | `retry_len`、`retry_head_slot`、`flash_retry` |
| 槽位占用 | 四态位图 | `n_unproc`、`n_inflight`、`n_done` |
| 缓冲占用 | Infeed/Outfeed 计数 + 占用率 | `infeed_count/fill`、`outfeed_count/fill` |

## 三、控制策略：异步双工状态机（`schedule()` 已实现）

优先级从高到低（每一步只返回**意图**，不含轨迹；执行由 L2 收口）：

1. `Outfeed` 满 或 设备 ERROR → **PAUSE**（取出无处放会把设备一起堵死）
2. 重试队列非空 → **RETRY_FLASH**（插队）
3. 设备 DONE → **UNLOAD_FLASH → STORE_OUTFEED**（此刻机械臂必须动）
4. 设备 IDLE 且有料 → **PICK_INFEED → LOAD_FLASH**（进入刷写窗口）
5. 设备 RUNNING → 去伺候 Outfeed/AOI（**绝不允许 WAIT**；`robot_wait=1` 会被点名警告）
6. Infeed 到高水位 → 追加 **THROTTLE**（背压上游）

设计里的 A/B/C 触发-动作全部落在这套优先级里：
```
A 设备空闲  → 抓 OCCUPIED_UNPROCESSED 送进设备, 槽位置 PROCESSING
B 设备变红  → 机械臂立刻离开, 用 t_flash 去放件/取件 (时间重叠)
C 设备变绿  → 回设备取出 → Outfeed, 槽位置 OCCUPIED_PROCESSED
```

## 四、水位与防死锁

- Infeed 高水位（如 14/16=0.875）→ `backpressure=1`，上游停送；
- Infeed 低水位（如 2/16=0.125）→ `lo_watermark` 预警，`starve_time` 累加；
- Outfeed 满（8/8）→ `global_pause=1` 全局暂停（下游不来取货必须先停，不许硬塞）；
- 缓冲需求（停机不断供）：`N_need = ceil(stall_max / CT_duplex) + 1`，停机 60s、CT 4s ⇒ **N_need=16**。

## 五、UPH 那笔账（模型可跑：`uph_model()`）

```
串行（等刷完再取）  CT = t_load + t_flash + t_unload = 2+4+2 = 8s  ⇒ 450 UPH   ← 腰斩
异步双工            CT = max(t_flash, t_load+t_unload+t_travel)
   机器人 4s 全藏进 4s 刷写窗口 ⇒ CT=4.0s ⇒ 900 UPH   ✅ 兑现
   机器人多 0.5s 空走         ⇒ CT=4.5s ⇒ 800 UPH   瓶颈从 flash 转到 robot
   机器人 3+3+0.5=6.5s        ⇒ CT=6.5s ⇒ 554 UPH   够不到 900
```

**用现场段表的真实时长代入**（112 段 / 4 模块 / 合计 46.0s）：

| 段类 | 4 件合计 | 单件 |
|---|---|---|
| AOI 检测（金手指 + 侧面） | 20.5s | 5.1s |
| 插入设备（含孔口对位） | 12.2s | 3.05s |
| 取料（上料盘） | 4.0s | 1.0s |
| 放料（下料/废料盘） | 1.8s | 0.45s |
| 拔出 | 1.2s | 0.30s |
| 合计 | 46.0s | **11.49s → 313 UPH（计划）/ 200.6 UPH（实测）** |

结论（不夸大）：
- 现在冲 900 UPH **不可能**：单件纯搬运（取料 1.0 + 插入 3.05 + 拔出 0.3 + 放料 0.45）已 **4.8s > 4s**，比刷写机还慢 ⇒ 瓶颈是机械臂，不是刷写机。
- 要真上 900，三个前提缺一不可：① t_flash ≤ 4s；② 搬运压到 ≤4s（提速或双工位/双夹爪）；③ **AOI 5.1s/件 必须变成并行站**（相机对着另一工位看，不占机械臂节拍），否则串行 11.5s 只能 313 UPH。
- 现实的中间目标：纯搬运 4.8s ⇒ 750 UPH；含 AOI 串行 ⇒ 313 UPH（当前段表能兑现的上限）。

## 六、100D 表（前 55 维原样，55:100 是本工位语义）

| idx | name | unit | 来源 / 判据 |
|---|---|---|---|
| 55:58 | infeed_slot_xyz | m | Infeed 当前取料槽 |
| 58:61 | loader_slot_xyz | m | 刷写机进料口 |
| 61:64 | outfeed_slot_xyz | m | Outfeed 当前放料槽 |
| 64:67 | insp_slot_xyz | m | AOI 检测位/相机视场中心 |
| 67:70 | scrap_slot_xyz | m | 废料盘（NG 分流） |
| 70:71 | infeed_count | 件 | Infeed 占用 |
| 71:72 | infeed_fill | 0..1 | count / N（派生） |
| 72:73 | outfeed_count | 件 | Outfeed 占用 |
| 73:74 | outfeed_fill | 0..1 | count / M（派生，溢出保护） |
| 74:75 | hi_watermark | 0..1 | 高水位 ⇒ 背压 |
| 75:76 | lo_watermark | 0..1 | 低水位 ⇒ 断供预警 |
| 76:77 | n_unproc | 件 | 槽位态 OCCUPIED_UNPROCESSED 计数 |
| 77:78 | n_inflight | 件 | 槽位态 PROCESSING 计数 |
| 78:79 | n_done | 件 | 槽位态 OCCUPIED_PROCESSED 计数 |
| 79:80 | fifo_len | 件 | FIFO 长度 |
| 80:81 | retry_len | 件 | 重试队列长度 |
| 81:82 | retry_head_slot | 0..1 | 重试队首槽号 / N |
| 82:83 | flash_state | 枚举 | 0 IDLE/1 LOADING/2 RUNNING/3 DONE/4 ERROR |
| 83:84 | flash_elapsed | s | 当前件已刷时长 |
| 84:85 | flash_retry | 件 | 本件已重试次数 |
| 85:86 | robot_state | 枚举 | 0 IDLE/1 LOAD/2 UNLOAD/3 TRAVEL/4 WAIT |
| 86:87 | robot_wait | flag | 1=在设备旁干等（目标恒 0） |
| 87:88 | overlap_ratio | 0..1 | min(1,(t_load+t_unload)/t_flash) |
| 88:89 | t_load | s | 抓取→送入→退出 实测 |
| 89:90 | t_unload | s | 取出→放入 Outfeed 实测 |
| 90:91 | t_travel | s | 站间移动实测 |
| 91:92 | starve_time | s | 累计断供（设备空转） |
| 92:93 | block_time | s | 累计堵塞（取出无处放） |
| 93:94 | uph_target | pph | 承诺值 900 |
| 94:95 | uph_actual | pph | 3600 / cycle_time |
| 95:96 | cycle_time | s | 单件节拍（瓶颈决定） |
| 96:97 | buffer_margin | 件 | N_eff − N_need（负 ⇒ 必断供） |
| 97:98 | backpressure | flag | Infeed 到高水位 |
| 98:99 | global_pause | flag | Outfeed 满 / 设备 ERROR |
| 99:100 | scrap_ratio | 0..1 | 废品率 |

配置量（不进状态向量）：`N`、`M`、`uph_target`、`t_flash`、`stall_max`。

## 七、验收（`tools/verify_state100.py` → PASS 27 / FAIL 0）

```
V1  段表 0:100 首尾相接 / 54 字段 / 新增 45 维 / 每字段有单位·来源·含义
V2  前 55 位逐位零回归 5/5
V3  named 重组 == x（‖差‖=0）
V4  几何锚 5/5 装载并写入对应区间
V5  串行 450 / 双工 900 / 加 0.5s 空走 800（瓶颈转 robot）/ 机械臂太慢 554
V6  停机 60s ⇒ N_need=16
V7  fill=0.875、UPH=900、背压=1、Outfeed 满 ⇒ 全局暂停=1（派生口径唯一）
V8  调度 7 场景：DONE→取出放入 / IDLE+有料→取件送入 / 刷写中→伺候 Outfeed /
                  重试插队 / Outfeed满→暂停 / 高水位→背压 / robot_wait 被点名
V9  槽位位图 16 槽往返 + 四态计数 {EMPTY:7, UNPROC:6, PROCESSING:1, PROCESSED:2}
V10 未注册通道 / 维度不符 全抛错（fail-closed）
```

## 八、下一步（数据与产线侧，不动 100D 口径）

1. **槽位标定表**：现场段表里上料盘 4 个槽坐标完全相同 (490,499,240)、废料盘与下料盘共用过 (408,-408,569) ⇒ 必须补 N=16 + M=8 的逐槽坐标，否则只能做区域级、做不了逐件避障。
2. **AOI 并行化**：把 5.1s/件的检测从机器人节拍里摘出去（独立相机站 + 自己的缓冲），这是 313 → 750+ 的关键。
3. **实测 t_load/t_unload/t_travel**：现在用的是段表计划值；接真机后每件回写，`overlap_ratio` 才有意义。
4. **计数真源接执行链**：每插一件 `n_inflight+1`、刷完 `n_done+1`、AOI 判定回写，让 70:100 从构造值变成链路值。
