# xCoreSDK 力控原语地图 — 当产线 `/lissajous_force_search` 不在图上时的备选

⚠️ **状态: 力控通道已在真机跑通（`fcInit → setControlType(1) → setCartesianStiffness → fcMonitor → fcStart → setCartesianDesiredForce` 全程 `ec=0`，能读出接触力）,
但**插入本身仍未成功**（多轮均只前进 0.4~2.2mm 就顶住/超阈停手），不要当成"已验证配方"。**
调到这条路的结论: 先校平工具 Z（见 SKILL.md §2）、`K_z` 不许给 0（见 SKILL.md §5）、力阈值在运动中判。

stub 位置: `zmax_data/rokae_sdk/xcoresdk_python/Release/linux/xCoreSDK_python/__init__.pyi`
(`Cobot_6` / `xMateRobot` 基类; 含逐接口中文文档 —— 判接口在不在只看它, **别用 `dir()` + 关键字筛**, 会漏)。

## 力控对象

```python
fc = robot.forceControl()          # → PyForceControl5/6/7(按轴数), 与本机 6 轴对应 PyForceControl6
```

| 方法 | 签名要点 | 作用 |
|---|---|---|
| `fcInit(frame_type, ec)` | `FrameType.tool` / `FrameType.base` | 选定力控参考系 |
| `fcMonitor(enable, ec)` | bool | 开/关力监控 |
| `fcStart(ec)` / `fcStop(ec)` | — | 进/出力控模式 |
| `setCartesianDesiredForce(v6, ec)` | `[Fx,Fy,Fz,Mx,My,Mz]`, N / Nm | 期望力(**沿工具 Z 压入 = `[0,0,F,0,0,0]`**) |
| `setCartesianStiffness(v6, ec)` | 产线口径 `[6000,6000,0,300,300,100]` | 某轴刚度 0 ⇒ 该轴不做位置保持(由力环驱动) |
| `setCartesianMaxVel(v6, ec)` | 产线口径 `[0.1,0.1,0.01,5,5,5]` | 力控下的最大速度上限 |
| `setForceCondition(rng6, isInside, timeout, ec)` | 力/力矩区间 | 判“力到位/接触”而不是凭时间 |
| `getEndTorque(ref_type, joint_torque_measured, external_torque_measured, cart_torque, cart_force, ec)` | 出参 `cart_force[3]` 单位 N | **读真实接触力**(验收用) |
| `startOverlay/stopOverlay/pauseOverlay/restartOverlay(ec)` | — | 力控叠加层控制 |
| `reset()` | — | 复位 |

`robot.calibrateForceSensor(all_axes, axis_index, ec)` 是**常规前置**(每轮运动前标一次), 不需要安全密码;
标定前必须静止且末端无外力。工具负载/质心不对会报 `#41447 力矩传感器与模型偏差较大`。

## 找孔用的轨迹原语

```python
MoveSPCommand(target, r0, rStep, angle, dir, speed)   # 螺旋: 起始半径 r0, 每圈增量 rStep, 总角 angle, 方向 dir
```
下发方式与其它运动命令同一条链路: `robot.moveAppend([cmd...], PyString(id), ec)` → `robot.moveStart(ec)`。
⇒ 经典 peg-in-hole = 力控压住 Z + XY 螺旋/李萨如小偏移搜孔; 位移上限由 `setCartesianMaxVel` + 搜索盒双重收口。

## 真机实测坑（SDK 直连, 按出现顺序）

- **`PyTypeVectorDouble` 不能下标**: 用 `.get()` / `.content()` 取值（包一层 `_vals()`）, `v[0]` 直接报错。
- **`calibrateForceSensor` 在力控模式下报 `ec=-19 control mode (position/force) unsupported operation`**: 只能在进力控前调;
  进不去就别纠缠, 改"静态读数扣重力" —— 读回 toolset 的 `load_mass`/`load_cog`/`end_trans` 做补偿。
- **力基线必须收敛**: `fcStart` 后立刻读力是 −0.15/+0.15/−16.06N 这种乱跳; 判据改为**连续两次差 <1N** 才采信。
- **自动负载估计会被接触污染**: 在"已经顶着东西"时取的静态读数会反解出 0.2kg 级假质量 ⇒ 基线仍要人工确认量级。
- **被中止的 `MoveLCommand` 留在队列里**, 下一次 SDK 会话自己接着跑（实测 6s 后自移 4.68mm）⇒ 收尾一律 `moveReset()`。
- **`speed` 参数不是 mm/s**: 实测 `speed=30` ≈ 13.6mm/s、`speed=6` ≈ 0.6mm/s（同会话内标定, 别信文档换算）。
- **李萨如幅值单位是力/力矩量级**（文档写 Nm）: 按毫米填 6.0/4.0 只得到 0.43mm 位移 + 19.6N 尖峰 ⇒ 找孔微动给 1~2N 级,
  口径没确认前不要叠加下压。
- **像素↔毫米不必标相机**: 同姿态抓图 A → 沿 base 单轴走 2mm → 抓图 B → `cv2.phaseCorrelate`（Hann 窗）得像素位移;
  尺度 = 2.0/|shift|, 方向映射直接从图像位移读出（实测 base −Z ↔ 图像 +x, 2mm→2.43px ⇒ 0.82mm/px）。

## 只读侧(不需要碰力控就能拿的证据)

- `tools/rokae/ft_direct_sampler.py` — 同一 SDK 会话里 `forceControl().getEndTorque(...)` **只读**采样落盘,
  不调 `fcStart`/`setCartesianDesiredForce`、不进制控、不发运动。做“插入前后的真实 Fz”取证用它。
- ⚠️ **别为试探力控另开 SDK 会话**: 位姿真值采样器占着那条会话, 抢掉 = 断掉全场唯一真值源。
  真要开必须先把采样器停干净、并提前讲清“位姿真值会断多久”。
- SDK 是 `cpython-310` ⇒ 跑在 `ros:humble-ros-base` 容器里(host 网络, 挂 `/sdk`), 不是系统 python。

## 产线侧对照(有服务时优先用服务, 别自己写环)

`/lissajous_force_search`(笛卡尔力控 + 李萨如叠加搜索) · `/rokae_insertion_force_search`(搜索 + press 压入 + 终检)。
参数真源 = 产线状态机配置 `resource/config/<项目>/state_machines/抓取放置/motion/尝试插入第一次.yaml`
+ 同一目录 `state_machine.yaml` 的 `fixture_insert_desired_force`。
