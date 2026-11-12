# 100D 统一状态空间 · 桌面缓冲区版（设计 + 验收）

对象：桌面缓冲工位。上料盘 → 取料 → 设备插孔 firmware loading → 拔出 → AOI 光学检测 → 下料盘 / 废料盘。
代码：`src/lerobot/policies/left_right/state_space/desktop_buffer_state100.py`
验收：`tools/verify_state100.py`（12 项数值判据，当前 12/12 PASS）

## 1. 为什么按「中间件缓冲区」建模

工位的本质是**生产者-消费者**，不是"读一堆传感器"：

```
            ┌──────────── ring buffer (容量 C, 水位 hi/lo) ────────────┐
 上料盘取料  →  [ slot ... slot ]  →  firmware 站(设备插孔)  →  AOI 检测站  →  下料盘
 producer        write_idx/read_idx      consumer1              consumer2      ↑
    ↑                 │                                                   │
    └── backpressure ─┘                                       废料盘 ← NG ─┘
```

由此得出的通道，全部是"**做判断要用**"的量，而不是"还能读什么"：
- 堆没堆满 → `ring_count / ring_fill / ring_write / ring_read`
- 该加速 / 该停 → `hi_watermark / lo_watermark / backpressure / overflow`
- 两站在制与吞吐 → `fw_qlen / fw_inflight / fw_pass / fw_fail`，`oi_qlen / oi_inflight / oi_pass / oi_fail`
- 节拍是否可对账 → `cycle_time / throughput / avg_wait`，判据 **L = λW**（队列律）
- 料废不废 → `scrap_count / scrap_ratio / slot_progress`
- 往哪儿插 / 往哪儿放 / 躲什么 → `feed/out/scrap/insert/cam_inspect_xyz`、`obstacle_vec / obstacle_dist / clearance_min`、`tcp_vel`（实际轨迹的导数）

## 2. 升级纪律（与 43→55 同一套）

1. **前 55 维语义一字不动**：老权重、老数据、老标定直接吃前 55 位。
2. **新增 45 维在末尾**：模型侧零初始化 ⇒ 上线瞬间输出逐位不变（实测零回归 5/5）。
3. **每通道必须有** 名字 / 单位 / 来源 / 判据，缺一不许进表（V1 强制）。
4. **没有来源就写 0，并如实标"沉睡"**（`awake()/asleep()`），不许编造几何。

## 3. 100D 全表

### 0:55 —— 沿用 55D（本文件不复制定义，直接引用 `unified_state55.ALL_SEGMENTS`）
TCP 位姿(3)+夹爪(1)+工件(3)+相对位移(3)+夹爪2D(2)+关节角(6)+关节速(6)+TCP旋转(9)+目标位(3)+孔位(3)+触觉(4)+预留(12)

### 55:100 —— 新增 45 维（31 个字段）

| idx | name | unit | 来源 / 判据 |
|---|---|---|---|
| 55:58 | tcp_vel | m/s | `diff(tcp_p)/dt`，实际轨迹的导数（避障/节拍） |
| 58:61 | feed_slot_xyz | m | 上料盘"当前取料槽"（生产者位置） |
| 61:64 | out_slot_xyz | m | 下料盘"当前放料槽"（良品出口） |
| 64:67 | scrap_slot_xyz | m | 废料盘槽位（NG 分流） |
| 67:70 | insert_slot_xyz | m | 设备插孔口（firmware 站目标） |
| 70:73 | cam_inspect_xyz | m | AOI 检测点 / 相机视场中心 |
| 73:76 | obstacle_vec | m | 最近障碍相对向量（障碍−TCP） |
| 76:77 | obstacle_dist | m | ‖obstacle_vec‖ |
| 77:78 | clearance_min | m | 通道最小净空（小于臂半径 ⇒ 必撞） |
| 78:79 | ring_write | 0..1 | 写指针 / 容量 |
| 79:80 | ring_read | 0..1 | 读指针 / 容量 |
| 80:81 | ring_count | 件 | 占用数（队列长 L） |
| 81:82 | ring_fill | 0..1 | count / capacity（派生，口径唯一） |
| 82:83 | hi_watermark | 0..1 | 高水位：超过 ⇒ 停止取料 |
| 83:84 | lo_watermark | 0..1 | 低水位：低于 ⇒ 允许上料 |
| 84:85 | backpressure | flag | fill ≥ hi_wm ⇒ 上游必须停 |
| 85:86 | overflow | 件 | 累计溢出（丢件必须计数，不许静默） |
| 86:87 | fw_qlen | 件 | firmware 站排队 |
| 87:88 | fw_inflight | flag | 设备占用中 |
| 88:89 | fw_pass | 件 | 加载成功累计 |
| 89:90 | fw_fail | 件 | 加载失败累计（重试或进废料） |
| 90:91 | oi_qlen | 件 | AOI 站排队 |
| 91:92 | oi_inflight | flag | 检测位占用中 |
| 92:93 | oi_pass | 件 | 检测合格累计 |
| 93:94 | oi_fail | 件 | 检测不合格累计（→ 废料盘） |
| 94:95 | cycle_time | s | 最近一件 CT |
| 95:96 | throughput | pph | 3600 / CT（派生） |
| 96:97 | avg_wait | s | 平均排队等待 W |
| 97:98 | scrap_count | 件 | 累计废料 |
| 98:99 | scrap_ratio | 0..1 | 废料 / 已处理 |
| 99:100 | slot_progress | 0..1 | 已处理槽位 / 总槽位（还剩多少件） |

配置量（**不进状态向量**，只参与派生）：`ring_capacity`。

## 4. 现场几何锚（真源：`docs/5-玉衡-指标验收/l2_300uph_closure_20261102.json`，mm→m）

```
上料盘 槽1 上方   (0.490, 0.499, 0.240)
设备插孔 孔1 孔口  (0.767, 0.228, 0.340)      孔2/3/4 y = 0.168 / 0.108 / 0.048（间距 60mm）
AOI 检测点       (0.360, -0.117, 0.654)
下料盘 下槽1      (0.490, 0.075, 0.198)      下槽2/3 y = 0.025 / -0.022（间距 50mm）
废料盘           (0.469, -0.402, 0.200)
```

**段表自身的缺陷（本次实测发现，必须修数据而不是改代码）**
- 上料盘 4 个槽的"槽N 上方"坐标**完全相同** (490,499,240) ⇒ 槽位表没区分，`feed_slot_xyz` 只能代表"上料盘区域"，不能代表具体槽。
- 废料盘点与下料盘出现过同一个坐标 (408,-408,569) ⇒ 有的段表里两个盘共用锚点。
- 结论：100D 的槽位通道口径是对的，但**槽位坐标必须补标定表**（上料 4 槽 + 下料 3 槽 + 废料 1 槽 + 孔 4 个），否则 `slot_progress` 只能是全局进度，不能做逐件避障。

## 5. 实况样例（真数据，不是造数）

取 `reports/ss_episode_latest.npz` 第 400 帧（"插入"段）：

```
100D 形状 (100,)  · 非零通道 65 · awake 28 / asleep 3
tcp_vel          [-0.0951, -0.0573, 0.0341] m/s
insert_slot_xyz  [0.767, 0.228, 0.340]
out_slot_xyz     [0.490, 0.0756, 0.198]
cycle_time 11.7s · throughput 307.69 pph · avg_wait 23.4s · ring_count 2
队列律: L=2.0  λ=0.08547/s  W=23.4s  λW=2.0000  dev≈0  ⇒ 自洽
asleep: ring_write / ring_read / overflow（这一帧没有指针与溢出源，如实为 0）
```

## 6. 验收（`tools/verify_state100.py`）

```
V1 段表覆盖 0:100 首尾相接、每字段有单位/来源/含义、新增 45 维        ✅
V2 前 55 位逐位零回归（5 组随机）                                    ✅
V3 named 重组成 x 逐位相同（‖差‖=0）                                ✅
V4 几何锚 5/5 装载，插孔口正确写入 67:70                            ✅
V5 队列律自洽 dev=0；给不自洽数据如实报 ok=False（dev=2.58）         ✅
V6 throughput=3600/CT=300.00、ring_fill=6/8=0.7500                  ✅
V7 未注册通道/维度不符 全部抛错（fail-closed）                       ✅
结果: PASS 12 / FAIL 0
```

## 7. 下一步（数据侧，不动 100D 口径）

1. 补槽位标定表（上料 4 / 下料 3 / 废料 1 / 孔 4），写进工位配置 JSON，锚从配置读，不硬编码。
2. 用现场 db3（123 包，含 `/realsense/color|depth` + `/joint_states` + `/robot/force_torque`）按时间戳与 9.1Hz 遥测对齐，生成逐帧 (图像, 55D, 几何真值)。
3. 环缓冲/两站计数的真源接到执行链（每插一件 +1，AOI 判定回写 pass/fail），让 78:100 从"构造值"变成"链路值"。
