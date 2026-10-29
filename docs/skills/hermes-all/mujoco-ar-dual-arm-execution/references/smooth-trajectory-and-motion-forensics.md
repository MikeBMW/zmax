# 平滑轨迹回放 + 运动取证 (仿真双臂闭环)

目的: 让执行端运动像“回放轨迹”一样连续, 同时保留闭环精度; 并在下结论前能分清
「指令台阶 / 采样别名 / 物理过冲」三种“看着不连续”。

## 1. 先量真值刷新率, 再谈不连续

- `/state.json#truth` 的刷新率 = 渲染站 `--hz` (解耦后 = `--phys-hz`)。`--hz 8` ⇒ 125ms 一帧。
- 期望每帧位移 = `v_cap × 刷新周期`。例: 350mm/s × 0.125s = **44mm**。
- 用 25~30Hz 采样去量 8Hz 真值, 算出来的“峰值速度”= `44mm / 37ms = 1.2~1.9 m/s`, 纯属别名。
- 规则: 采样率 ≥ 2× 真值刷新率; 结论用 **位移/刷新周期**, 不用位移/采样间隔。
- 典型误判: 把它当 PD 过冲去调 kp/kv, 白改一轮 (实测 kp=300/kv=20 跟得住, `cmdΔ ≈ actΔ`)。

## 2. 指令流取证 (分清指令 vs 物理)

在 `/control` 里累计并暴露到 `/state.json#ctl`:

| 字段 | 含义 | 判读 |
|---|---|---|
| `n` / `hz` | 下发次数 / 频率 | 应 ≤ 1/dt; 明显更大 = 连发 |
| `dmax` | 单次最大关节变化 (°) | ≤0.7° 且 `nfast=0` ⇒ 指令连续 |
| `nfast` | 单次变化 >1.2° 的次数 | >0 ⇒ 指令在跳, 查 seed/rate |
| `gapmax` | 相邻下发最长空档 | 大 = 步间等待, 不是轨迹 |

单次下发跨度大时的下一步排查顺序: ① IK 是否带 `seed`(无 seed 不削幅); ② 循环是否在“追帧”连发;
③ 是否另有一个控制环在同时下发 (见 §5)。

## 3. S 曲线 (由 L2 节点发出)

```
s(τ) = 10τ³ − 15τ⁴ + 6τ⁵            τ = k·dt/T, s∈[0,1], 首末速度=0 (C2)
峰值速度 |v|max = 1.875·L/T
峰值加速度 |a|max = 5.7735·L/T²
T = max(1.875L/v_cap, sqrt(5.7735L/a_max), 8·dt)
pts[k] = p0 + (p1−p0)·s(τ)     vel[k] = (p1−p0)·(30τ²−60τ³+30τ⁴)/T
```

- `v_cap` 取该段标定 (段速度上限), `a_max` 默认 2.0 m/s² (标定允许到 10)。
- 实测: 550mm、v_cap 0.35、a_max 2.0 → T=2.95s、149 点 @20ms、峰速 350mm/s、峰加速 0.37 m/s²。
- 返回 `{ok,T,dt,n,L_mm,v_peak_mm_s,a_peak_m_s2,pts,vel,src}`; 端点非法/零位移要显式 `ok:false` 或`n=1`。

## 4. 回放执行伪代码

```python
traj = smooth_traj(tcp_now, target, v_cap=stage_v_cap, a_max=2.0, dt=0.02)
cap = v_cap * dt * 1.5              # 单拍位移上限
t_start = monotonic(); k = 0
last_deg = prev_step_deg            # ⭐ seed 跨步骤保留, 段首第一拍也不换分支
while k < traj.n:
    want = t_start + k*dt
    if monotonic() < want: sleep(want - monotonic())
    behind = int((monotonic() - t_start)/dt)
    if behind > k + 1: k = min(behind, n-1)      # 不追帧: 丢过期点
    pt = traj.pts[k]
    tcp = read_truth(); if |target-tcp| <= tol: reached; break
    cmd = pt + clip(K*(pt - tcp), ±corr_mm)      # K≈0.35, corr≤4~6mm
extra = clip_norm(cmd - prev_cmd, cap)          # 安全: 单拍位移截断
    ik = /ik?side=&x=&y=&z=&rate=<deg>&seed=<last_deg>
    if not ik.ok: ik = /ik?...&rate=<deg*3>       # 只小步升档, 绝不直接解段目标
    last_deg = ik.deg; /control(...); k += 1
# 收尾逼近: 20ms 小步 (≤3mm/拍, rate 2~3°) 补 PD 静差, 时限 3~6s
```

## 5. 关节 rate 换算 (最容易搞反的一步)

- `rate` 的单位是**度/次下发**, 不是 mm/s。
- `deg_per_cmd ≈ v_tcp_target · dt / 力臂`; 力臂按 0.5m 估。
- 350mm/s @20ms → **0.7°**; 2.5° = 125°/s ≈ 1.1m/s @0.5m (这是“猛冲”的常见来源)。
- 改 rate 前先实测服务端真在削: `/ik?seed=<6角>&rate=1.0` 返回 `rate_clipped:true` 且 `seed_gap_deg≈0`。
- 无 `seed` 时服务端**不削幅**, 所以段首那一拍必须是带上一步关节角作 seed。

## 6. 指标口径 (同口径对比, 改前改后各跑一次)

| 指标 | 怎么算 | 合格线 |
|---|---|---|
| 大跳次数 | 单次位移 >100mm | 0 |
| 单点最大位移 | max Δ | ≤ v_cap × 刷新周期 × 1.2 |
| 台阶数 | 前拍 <0.2mm 且本拍 >2mm | 越少越好 (段间等待会贡献) |
| 峰速 | Δ / 刷新周期 | ≈ 段 v_cap, 不应数倍 |
| 闭环 | 到位步数 / 总时长 | 全到位且不比旧链慢 |
| 指令 | `ctl.dmax` / `ctl.nfast` | ≤0.7° / 0 |
