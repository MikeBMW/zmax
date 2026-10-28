---
name: optical-module-grasp
version: 1.0.0
author: 静静
license: MIT
description: Use when 抓光模块/盯住模块记关系/夹爪点了没反应 — 视觉盯模块 + 夹爪真值留证 + 三动作极简抓取。
metadata:
  hermes:
    tags: [robot, grasp, gripper, handeye, vision, zmax]
    related_skills: [real-arm-motion-control, real-machine-vision-servo-loop, human-in-the-loop-robot-teaching]
---

# 光模块抓取：盯住 → 留证 → 三动作

## When to Use

- 要用臂相机盯住光模块、记录它和 tool1 的位置关系（含边动边记）；
- 点「关闭夹爪/打开夹爪」没反应，或要确认夹爪是否真的夹住；
- 要在真机上把光模块抓起来，且不想重复人工示教那些多余动作。

现场真机（珞石 xms5 + D405 臂相机）。目标：知道模块和 tool1 的关系、确认夹爪真的夹住、用最少的动作抓起来。

## 判据（不看"已下发"，只看真值）

| 事实 | 真值源 | 合格值 |
|---|---|---|
| 夹爪夹住模块 | `/gripper_pos` (Float32) 或 `/gripper_srv` 回执 curr_pos | 174~185；开≈1000；空爪闭合≈21 |
| 走过去了 | 8793 `/pose` 实测位移 | ≥0.9×目标 |
| 模块跟工具走 | 模块在 tool1 系的位置标准差 | 大幅移动臂后 std ≈1~2mm |

## 三动作抓取（`tools/grasp_opt.py`）

```
./gui-venv311/bin/python tools/grasp_opt.py --dry          # 先算：直进/合爪/抬起
./gui-venv311/bin/python tools/grasp_opt.py                # 真抓
```

1. **接近**：沿 tool1 的 +x 一次直进（默认 110mm，实测 tool1→模块前向距离），`move-abs` 姿态不变
2. **合爪**：POST 8793 `/ctl/move` `{skill:"L2.grip_close", arm:1}` —— 授权/快层闸门/夹持力都走这条，脚本里**不要**另开 ROS 通道
3. **抬起**：`move-rel` base +z 30mm

人工示教时中间那些反复小步蹭、来回修正、抓前又抬一下，算法里一律不做——几何上就是一次直进。

## 盯模块（`tools/opt_box3d.py` + `tools/opt_track.py`）

```
./gui-venv311/bin/python tools/opt_track.py --sec 600 --hz 3 --tag move
```

每条采样记：TCP/ABC · 模块 base 坐标 · 模块在 tool1 系坐标 · 距离 · 2D 框 · 可见高度 · clipped · 置信。
页面叠加：`http://127.0.0.1:8797/ar?cam=arm` 的 `🔍 光模块3D框`（`/api/module3d`，只读、1.5s 缓存）。

## 几何不变式（老倪定义，最高优先级）

**`tool1` TCP 原点 = 光模块头顶中心**。不是端点框中心、不是视觉反推的模块中心。
任何“模块在哪”的换算直接吃 TCP 真值；视觉只负责回答“头顶落在哪一像素”。
标定固定相机时这条尤其关键：3D 侧用 TCP（硬真值），2D 侧用绿拉环质心≈头顶中心。

## 放回槽位 = 反向复现抓取(2026-10-18 实测通过)

夹住模块后爪与模块是刚体 ⇒ **回到"当初夹住那一瞬"的 TCP/ABC, 模块就回到原位**。

1. 姿态按 ≤4°/步 转过去(32.4° 实测分 9 步, 终态姿态差 0.00°)
2. 位移按 ≤35mm/步(111mm 分 4 步, 位置差 1.0mm)
3. 松爪走 **`zmax_data/l2_cmd.fifo`**(l2_daemon 的原子技能通道): `{"skill":"L2.grip_open"}` ——
   **不要**写到 `zmax_data/rokae_sdk/cmd_arm.fifo`(SDK 腿只管 move-abs/move-rel, 不认 skill ⇒ 回`未知命令: grip`, 夹爪一动不动)
   实测: 写对通道后 1s 生效(GripperSrv target_pos=1000 → curr_pos=196 → 几秒后 1000)
   夹爪三态真值: 合住 174 · 半开 196 · 全开 1000
4. 张爪真值 `/gripper_pos` **>700 才算张开**(合住=174, 空爪闭合≈21), 没张开不要退
5. 沿 tool1 −x 退 110mm 回抓取起始位

坑:
- **两条 FIFO 分两扎**: `rokae_sdk/cmd_arm.fifo` 只跑运动; `l2_cmd.fifo` 才跑原子技能(夹爪/升降)。写错通道的典型症状: 夹爪不响应但不报错
- **`grasp_opt.G.send()` 等回执靠 `zmax_data/rokae_sdk/logs/agent_YYYYMMDD.jsonl`, 那个文件可能根本不存在** ⇒ 动作实际执行了但脚本 90s 后判 TIMEOUT 停手。用 `tools/arm_raw.py`(写FIFO + /pose 轮询), 实测 3.2s 到位、残差 0.0mm
- **纯姿态(位移 0)的 move-abs 被控制器静默忽略**: 回执 PASS / Δ=0 / 姿态一动不动 ⇒ 每步带 ±1mm z 抖动才真动
- `G.pose()` 姿态是**弧度**, 目标按度写 ⇒ 必须换算(3.1rad 当 3.1° ⇒ 47° 假姿态差/命令发错)
- `PowerState.estop` 期间所有 move 直接 ABORT(前置条件不满足), 与授权无关, 要先人工解除急停

位姿唯一依据: `taught_points.mod_slot_return`(0.6533,0.2107,0.2202 / ABC 143.2,−85.58,37.74)、
`mod_slot_approach`(0.6466,0.2056,0.1105); 脚本 `tools/place_back.py` + `tools/place_back_finish.py`。

## 坑（都踩过）

0. **`pkill -f 脚本名` 会杀掉自己那条命令**：命令行里就包含这个字符串，`pkill -f` 把自己 shell 一起 TERM（exit -15，后面的命令全不执行）。后台任务的 pid 就是 terminal 返回的 `pid`，用 `kill <pid>`；要停进程只按 pid 文件 + `/proc/<pid>/cmdline` 判定。
0b. **50120 / 50113 奇异区拒动**：`move-abs` 默认走笛卡尔 MoveL，沿路径进奇异区就报「[奇异规避]使用奇异规避，沿路经无法到达终点」或「路径中改变的姿态最大值超过阈值」，回执是 `CHECK` 而不是 `PASS`，机器人一动不动。实测 60~280mm 的单步都可能被拒。两个解：① 每段拆 ≤60mm；② 直接发 `"motion": "J"` + `"allow_movej_retry": True`（关节空间 MoveJ，目标仍是笛卡尔位姿）——这条最有效。

1. **夹爪服务名会变**：2026-10-12 是 `/gripper_driver`，2026-10-18 实测是 `/gripper_srv`。预先固定名字 ⇒ `ros2 service call` 卡在 "waiting for service to become available"，25~30s 后报 `rcl node's context is invalid`，现场表现就是「点关闭夹爪没反应」。⇒ 运行时探一次（`ros2 service list | grep ^/gripper`）并缓存。
2. **`/gripper_pos` 同 topic 挂两个类型**（Float32/Float64）⇒ `ros2 topic echo` 直接报 `contains more than one type`，必须显式给类型：`ros2 topic echo /gripper_pos std_msgs/msg/Float32 --once`。
3. **远端 `ros2` CLI 的 daemon 会坏**（xmlrpc 错）⇒ `ros2 service list` 返回 0 条。加 `--no-daemon` 立刻正常；别据此判断"服务没起"。
4. **检测框会短一截**：YOLO 只盖住壳体，实测框到 y=118/124 而模块到 y≈156（头部漏掉）⇒ `_refine_extent()` 用 HSV（金属低饱和高亮 | 绿色拉环）行剖面从框内向外扩，允许 ≤3 行空洞。
5. **框贴边 = 被画幅裁**：此时「框高 ÷ 件长」反解的距离必然偏大（实测贴边中位 180mm vs 不贴边 157mm）⇒ 标 `clipped`，沿用 15s 内上一次未裁距离，不重新反解。头部在画外时，3D 框角点 y<0 是正常的（框伸到画外），页面上用箭头标「头部出画」而不是假装框住。
6. **无反解深度时的方向核验**：D405 depth publisher=0 时距离靠件长反解（±30mm）。判断"接近方向对不对"看画面表观高度变化，而不是绝对值。
7. **重启守护会消费 FIFO 残留旧命令**：重启 `l2_daemon` 后实测被消费了一条旧 `L2.lower`，臂非请求地动了 20mm。重启前先看 FIFO 有没有排队命令；出现非请求动作要如实写进留证。
8. **连续性闸（老倪明确要求：「光模块不可能突然变化很大的，它是一个连续的模块」）**：同一支模块相邻两帧的画面高度/宽度不可能翻倍或减半；越界就说明这一帧算错了（遮挡/裁切/误检）⇒ 沿用上一次可信距离，并标 `continuity.jump`，不许“看着像”就画。活例：61px 的小头按长轴反解出 365mm，而真值是 155mm。
9. **扩框必须有硬上限**：只按“行剖面够宽”向外扩，遇到大片同色背景会扩到画面边缘（实测 58px 的框被扩成 0~479 = 整幅）。必须四条一起收口：±px 上限 / 行宽不得超过框宽 1.6× / **颜色连续性**（行内均色与框内均色差 ≤45，绿拉环额外 25px）。
10. **被纵向裁切时换轴反解距离**：可见高度≠整支长度（只剩小头时 61px），按长轴反解必然偏大；改用短轴（头部宽 13.4mm）反解，实际 155mm。
11. **实时画面不要用 `<img src>` 换帧**：每换一次 src 浏览器先清空再解码（实测 30% 采样点拿到 0×0），现场表现就是“一会黑屏一下”。改成 `<canvas>` + 预加载 Image，**只有新帧解码成功才 drawImage**，失败继续显示上一帧；同时把“帧龄”标在界面上。
12. **fork-per-request 的服务里，不要在请求里跑推理**：子进程会**重新装载权重**（实测 969ms/请求，其中 ~900ms 是装载），且多个子进程并发推理会卡死（实测请求 25s 不返回，页面直接没框）；实例级缓存也永远不命中。正确做法：**父进程起一个常驻检测线程**（~6Hz），结果写 `/dev/shm/*.json` + 原帧写 `/dev/shm/*.jpg`，请求只读文件（实测 12~20ms）。
13. **画面与标注必须同源同时刻**：分开请求“取帧”和“取框”时，两边年龄不同 ⇒ 现场看着就是标记滞后。改为一个请求返回“被分析的那一帧 + 对应的框”（`?img=1` → base64），页面一次画完。
14. **抓着模块时距离是刚性的**：老倪“你的光模块别扩大啊” —— 相机在腕上、模块被夹住，两者距离不应变；可见高度变多/变少（只露小头）只是成像假象。对距离加变化率上限（~3mm/s），不要让框跟着可见高度胀缩。
15. **只看得到一段（被画幅裁）时的三条硬规则**（老倪连续三次：“有点大”→“又太长了”→“好了，记住了”）：
    - **绝不外扩**：被裁时检测框下方紧邻的是台面/背景亮面，按颜色连续性也会跳缝隙扩进去（实测 58px→92px）⇒ 直接用检测框原样。
    - **宽度按物理值收口**：模块宽 13.4mm、刚性距离 159.2mm ⇒ 画面里就该是 `fx×13.4/159.2 ≈ 32px`；可见掩膜常把背景亮面圈进来（实测 68px）⇒ 超过 1.25 倍就按物理宽度重建框。
    - **不做尺寸反解**：被裁时长轴（365mm）和宽度（77.7mm）反解都不对，真值 159mm ⇒ 直接取刚性参考距离。
16. **别丢目标：三级保障**（老倪“稳住，别丢光模块”；实测只剩小头时 YOLO 连丢 13 帧，conf<0.25）：
    - 一级 **模板匹配**：把上一次成功框内的灰度图存成模板（`/dev/shm/*_patch.png`），在 ±0.6 尺寸的搜索窗里 `matchTemplate`（TM_CCOEFF_NORMED ≥ 0.55 就接住）。实测相似度 1.00，框正确。
    - 二级 邻域放大 2× 重检（对小目标有时有效；本例无效，仅作保障）。
    - 三级 **沿用上次框 + stale/detect_lost 标注**，画面继续更新（不冻住），但页面必须明说“沿用上次框（连续 N 帧未检出）”。

## 留证文件

- `zmax_data/ar_rs/opt_track_<ts>_<tag>.jsonl` — 全程观测量
- `zmax_data/ar_rs/grasp_process_<date>.json` — 夹前/夹后统计 + 夹爪事件 + 独立校验
- `zmax_data/ar_rs/grasp_ref.json` — 抓取参考位姿与几何差
- `zmax_data/ar_rs/grasp_run_<ts>.json` — `grasp_opt.py` 每次运行的逐步判据

## 安全红线

- 动作授权只从 8793；脚本前置必查 `motion_armed / automatic / idle / estop / has_error`，任一条不满足就一条都不发。
- 接近距离有上限（默认 160mm）、目标 z 有下限（默认 40mm）、离基座 ≤900mm，超限拒发。
- 客户端超时 ≠ 动作没下发：判完成只看位姿真值，**绝不重发**。
