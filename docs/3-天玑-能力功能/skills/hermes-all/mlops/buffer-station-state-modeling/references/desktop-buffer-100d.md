# 100D 桌面缓冲区状态空间 (55 之上再加 45 维)

落地: `src/lerobot/policies/left_right/state_space/desktop_buffer_state100.py`
验收: `tools/verify_state100.py`(12 项) · 设计文档: `docs/5-玉衡-指标验收/state100_desktop_buffer_design.md`

## 55:100 的 45 维 (31 个字段; 55 之前一字不动)
| idx | name | unit | 来源·判据 |
|---|---|---|---|
| 55:58 | tcp_vel | m/s | `diff(tcp_p)/dt`, 实际轨迹的导数 |
| 58:61 | feed_slot_xyz | m | 上料盘当前取料槽 |
| 61:64 | out_slot_xyz | m | 下料盘当前放料槽 |
| 64:67 | scrap_slot_xyz | m | 废料盘槽位 |
| 67:70 | insert_slot_xyz | m | 设备插孔口 (firmware 站) |
| 70:73 | cam_inspect_xyz | m | AOI 检测点/相机视场中心 |
| 73:76 | obstacle_vec | m | 最近障碍相对向量(障碍−TCP) |
| 76:77 | obstacle_dist | m | ‖obstacle_vec‖ |
| 77:78 | clearance_min | m | 通道最小净空 (<臂半径 ⇒ 必撞) |
| 78:82 | ring_write/read/count/fill | 0..1/件 | 写读指针、占用、占用率 |
| 82:86 | hi_wm/lo_wm/backpressure/overflow | 0..1/flag/件 | 水位与溢出(丢件必须计数) |
| 86:90 | fw_qlen/inflight/pass/fail | 件/flag | firmware 站队列与在制 |
| 90:94 | oi_qlen/inflight/pass/fail | 件/flag | AOI 站队列与在制 |
| 94:97 | cycle_time/throughput/avg_wait | s/pph/s | 节拍, 满足 L=λW |
| 97:100 | scrap_count/scrap_ratio/slot_progress | 件/0..1 | 废料与盘面进度 |

配置量不进向量: `ring_capacity`(只用于派生 fill)。

## 现场几何锚 (真源 = L2 300UPH 闭合段表, mm→m)
`docs/5-玉衡-指标验收/l2_300uph_closure_20261102.json` 的 `rows[].label` / `rows[].a`:
```
上料盘 槽1 上方  (0.490,0.499,0.240)   插孔 孔1/2/3/4 (0.767, y=0.228/0.168/0.108/0.048, 0.340)
AOI 检测点      (0.360,-0.117,0.654)   下料 下槽1/2/3 (0.490, y=0.075/0.025/-0.022, 0.198)
废料盘          (0.469,-0.402,0.200)
```

**段表缺陷(实测): 上料盘 4 个槽坐标完全相同; 废料盘点曾与下料盘共用同一坐标。**
⇒ 槽位通道口径没问题, 但必须补槽位标定表(上料 4 / 下料 3 / 废料 1 / 孔 4),
否则 `slot_progress` 只能做全局进度、做不了逐件避障。处理方式: 报数据缺陷, 不改代码去凑。

## 验收 12 项 (数值判据)
布局覆盖 0:100 首尾相接 · 每字段有单位/来源/含义 · 新增维数 = 45 · 前 55 位零回归(5 组随机) ·
`named` 重组成 x 逐位相同 · 锚 5/5 且插孔口写进 67:70 · 队列律自洽 dev≈0 且假数据如实 `ok=False` ·
`throughput = 3600/CT` · `ring_fill = count/capacity` · 未注册通道/维度不符全抛错。

## 真数据样帧 (episode 第 400 帧·插入段)
100 维 · 65 通道非零 · awake 28 / asleep 3(ring 指针与 overflow 该帧无源) ·
`tcp_vel = [-0.0951,-0.0573,0.0341] m/s` · `insert_slot=[0.767,0.228,0.340]` ·
`cycle_time 11.7s → throughput 307.69 pph` · `L=2.0, λ=0.08547/s, W=23.4s, λW=2.0000, dev≈0`。

## 数据侧下一步 (不动 100D 口径)
1. 槽位标定表进工位配置 JSON, 锚从配置读, 不硬编码。
2. 现场 ROS2 db3(含 `/realsense/color|depth`, `/joint_states`, `/robot/force_torque`)按时间戳与遥测对齐,
   生成逐帧 (图像, 55D, 几何真值)。
3. 环缓冲与两站计数接执行链(每插一件 +1, AOI 判定回写 pass/fail), 让 78:100 从构造值变成链路值。
