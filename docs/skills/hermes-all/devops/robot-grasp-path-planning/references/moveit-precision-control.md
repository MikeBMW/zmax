# 用 MoveIt 精确控制真机: 口径核对 → 分段执行 → 闭环

适用: 现场问「为什么不用 MoveIt 规划 / 能不能改成 MoveIt 执行」, 或要把 plan-only 的轨迹真正落到臂上。
**先读本文件前三节, 再谈代码**: 口径错一层, 后面全白算。

## 1. 三句话回答"谁在规划"

```
方向键 / 空间点 / 号位回点 → /ctl/move → l2_cmd.fifo → l2_daemon → SDK 腿     ← 不规划
空间点 = l2_daemon 把「点位 + 规矩」展开成 3~4 段(竖直抬到该点 z+40 → keep_z 纯水平 → 竖直下落)
MoveIt 只在 /station/plan: plan_req.json → 容器 moveit_plan_live.py → live_plan_latest.json (只出计划)
```

硬判据: `grep -c moveit tools/l2_daemon.py` == 0。不要凭架构图答"都经过 MoveIt"。

## 2. 口径核对 (零风险, 只读真值)

| 比较 | 实测(154 个 50Hz 样本, 跨全天工作区) | 结论 |
|---|---|---|
| `FK(tool0 法兰)` vs 真机 TCP | 259.2 mm | 不是几何错, 是拿法兰比夹爪尖 |
| `FK(tool1 夹爪尖)` vs 真机 TCP | 3.05 mm (中位 3.07 · 95% 3.76 · 最大 3.78) | 同源 |
| 姿态 | 3.66° (95% 3.69 · 最大 3.71) | 同源, 剩常值偏置 |
| 误差向量 (base 系) | 均值 (+0.1, +1.6, +2.5) mm · std (0.5, 0.5, 0.1) | 均值≫std ⇒ 常值偏置可标定 |

配置来源(一行定位):

```
config/moveit_xms5/config/<robot>.srdf   <chain base_link=... tip_link="tool0"/>
urdf                                     joint_tool1 origin z = 0.2587  (法兰→夹爪尖 259.8mm)
tools/moveit_plan_live.py                d0 = dist(fk(sj)[:3], rq["tcp"])   ← 法兰 FK 比夹爪 TCP
```

工具:

```bash
python3 tools/fk_check_tool_frame.py            # tool0 / tool1 对拍 + 差值来源
python3 tools/fk_urdf_vs_real.py --every 120    # 整天 tcp_direct_*.jsonl 批量统计
```

**判定顺序**: ①tip/tool 坐标系 ②base_frame 与真值坐标系 ③差常值偏置 ⇒ 拟合 tool 偏移 ④残余随位形变 ⇒ 才拟合 6 个关节零位。
**姿态一律符号无关**: `2·acos(|dot(q1,q2)|)`; 不取 abs 会得到 137° 这种假差异。

## 3. 为什么不能直接把 MoveIt 轨迹丢给控制器

```
live_plan_latest.json 实测: plan_time_s = 12.76  · n_points = 129 · plan_code = 1
我们这边下发口: 只有单点 move-abs / move-rel (无轨迹流)
```

- 12.7s/次 与"按一下要秒回"冲突 ⇒ 抽稀后目标 ≤3s。
- 逐点流式下发会绕过 `guard_box` 逐段包络闸与"到位即停"语义 ⇒ 必须**按段**过闸 + 段间真值核对。
- MoveIt 只保证模型内可行; 控制器仍可能 `50102/50113/rc=6` 拒 ⇒ 必须有整条回退到固定分段的路径。

## 4. 执行设计 (可直接照做)

```
静止判据: |v|<0.2mm/s 且 jpos 极差<1e-4 连续 6 帧  ⇒ 才规划 (否则起点漂移)
抽稀: 关节最大步长 ≤2°/段 或 TCP 位移 ≤5mm/段 (取严) ⇒ 预计 15~40 段
每段: move-abs(joint) → 过 guard_box / z_floor / 天花板 / VL 快层 / 抬升闸(>100mm 要 allow_climb_mm)
段间: 真值核对 ≤1mm 且 ≤0.5°, 超差立刻停 + 写台账(段号/目标/实测/残差), 不续发
到点: |err|≤0.5mm 完成; ≤3mm 补偿一次(goal' = goal+err, 重发末 1~2 段); >3mm 停, 报口径异常
开关: ZMAX_PLAN_ENGINE=legacy|moveit, 默认 legacy; 任一段被拒 ⇒ 回退 legacy
```

首次真机试跑: 第一段限 2mm / 0.5°(speed 相当于 1.5mm/s), 确认方向对再放长。

## 5. 验收梯度 (前两级零风险)

| 级 | 内容 | 判据 |
|---|---|---|
| V1 离线标定 | 全天 tap 拟合 tool1 修正 + 残差统计 | 位置 ≤1mm · 姿态 ≤0.5° |
| V2 影子规划 | 50 个历史目标只规划不执行, 与 legacy 分段比 | 耗时 ≤3s · 无越限 · 路径长 ≤legacy×1.3 |
| V3 空载单点 | space1/space2, 1.5~3mm/s, 逐段盯真值 | 到位 ≤1mm/0.5° · 全段闸通过 |
| V4 精度统计 | 3 点 × 10 次 | 平均 ≤1mm · 最大 ≤2mm · 重复性 ≤0.2mm |

## 6. 回答口径

- 说清 MoveIt **不提高绝对精度**: 它管可达/碰撞/关节限位/平滑; 精度来自口径统一 + 分段执行 + 真值闭环。
- 给"能改 + 代价"时同时给三档: 只做准入预检(1~2h) / 规划+分段执行(4~6h+真机验证) / 全轨迹流式(要厂家接口)。
- 任何"改了 MoveIt"的结论都要带一条**同源残差数字**, 否则等于没验。
