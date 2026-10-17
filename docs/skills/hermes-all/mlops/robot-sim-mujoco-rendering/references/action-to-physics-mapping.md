# 动作 → 物理 映射口径 (引擎 u ↔ metaworld/MuJoCo)

用来回答「XX 的速度/指令是不是直接进 MuJoCo」。先分清是哪条仿真路 —— 两条路的物理推进完全不同, 数据不可混用。

## 1. 两条仿真路

| 路 | 入口 | 物理推进 | "速度"是什么 |
|---|---|---|---|
| 真物理路 | `RealStateSpaceSim` → `src/lerobot/engine/runtime.py` → metaworld env | `env.step(act)` → MuJoCo | 名义量, 物理上是 mocap **位置目标** |
| 解析路 | `src/lerobot/engine/sim.py` | 纯 numpy, **无 MuJoCo** | 真状态变量: `v ← v+(u−v)·dt/τ (τ=0.08)`, `x += v·dt` + 解析接触力 |

## 2. 真物理路的完整链路

```
u_ff (m/s)                      前馈加速器/策略输出
  → sched 融合 / safety.saturate(0.6) / executor.execute() (恒等)
  → act[:3] = clip(u[:3] / K_ACT, ±1)          K_ACT 默认 0.5
  → env.step(act)                              gymnasium MujocoEnv
  → metaworld set_xyz_action: data.mocap_pos += act × action_scale
  → MuJoCo: mocap weld (eq) + 关节执行器 mj_step → 臂真的动起来
```

要点:
- `action_scale` 默认 `1/100 = 0.01 m`，即 act=1 → mocap 目标每步 +10mm。
- **qvel 全程由 MuJoCo 动力学给出, 代码里没有任何一处外部写它**。所以"速度"不是被塞进 MuJoCo 的量, 而是「每步位移目标 ÷ 步长」派生出来的。
- 模型直驱通道 (`_direct_act`) 跳过 `K_ACT` 换算直接 `env.step`, 但终点仍只是 mocap 目标, 不是 qvel。

## 3. 唯一真正直接写 MuJoCo 状态的地方 (物体, 不是臂)

| 写入 | 位置 | 语义 |
|---|---|---|
| peg free body `qpos` + 清 `qvel` | 来料干扰/转向注入 | 把件搬到指定位姿 (绕开动力学, 必须同时清 qvel, 见 SKILL §4) |
| 件 `qvel = 0` | 钉件/吸附等效刚性夹持 | 防自由落体累积 |

这两个都不是「前馈速度」。把它们的读数当控制速度会得出完全错误的结论。

## 4. 标定口径偏差 (实测表, `peg-insert-side-v3`)

`action_scale=0.01` · `frame_skip=5` · `timestep=0.0025` ⇒ 每步 **12.5ms** 物理。
稳态段测 (跳过 servo 爬升):

| act | 指令 u = act×0.5 | 稳态末端位移 | 真实物理速度 (÷12.5ms) | 对指令 | 若错按 0.1s 折算 |
|---|---|---|---|---|---|
| 0.24 | 0.120 m/s | 2.40 mm/步 | 0.192 m/s | **1.60×** | 0.024 m/s (0.20×) |
| 0.50 | 0.250 m/s | 4.99 mm/步 | 0.399 m/s | **1.60×** | 0.050 m/s (0.20×) |
| 1.00 | 0.500 m/s | 6.68 mm/步 | 0.535 m/s | 1.07× (臂饱和) | 0.067 m/s (0.13×) |

机制: `K_ACT=0.5` 隐含「`action_scale/dt = 0.01/0.02`」, 而真实 dt 是 12.5ms ⇒ 20/12.5 = **1.6×** 的系数差; act 越大 mocap 目标超前越多, 臂跟不上时实际位移饱和到 <10mm/步, 系数回落。
- 注意 **mocap 目标位移永远精确** = act×action_scale (实测 2.400mm), 偏的是「末端能不能跟上」。所以拿 `data.mocap_pos` 的变化量算速度会得出错的乐观值, 必须量 `get_endeff_pos()`。

## 5. 对齐口径的两种改法 (改完用同一 seed 出 A/B)

1. **改标定**: `K_ACT = action_scale / (frame_skip×timestep)` = 0.01/0.0125 = **0.8** —— 不动 env, 只修正速度语义。
2. **改步长**: `env.frame_skip` 5 → 8 ⇒ 每步 0.02s = 引擎 50Hz, `DT_ENV` 同步改 0.02 —— 让「一步」在两边真的是同一个时长。

任选其一后再重跑 §4 表, 中小段系数应回到 ≈1.0; 若仍偏离, 先查是不是拿 mocap 目标而不是末端实测。

## 6. 怎么量

```bash
MUJOCO_GL=egl ./gui-venv311/bin/python scripts/probe_action_mapping.py    # 本 skill 自带
```

判读: ① mocap 每步位移是否 = act×action_scale (校验 action_scale/换算通) ② 稳态末端位移/真实 dt 是否 ≈ 指令 ③ 关节 qvel 每步变化非零 = 动力学在跑 (我们没写它)。

解析路的速度则直接看 `v` 状态与 `x` 的差分, 不要跟真物理路的 "mm/步" 直接比 —— 前者是一阶伺服收敛后的稳态速度, 后者是每步位置目标+伺服的合成结果。
