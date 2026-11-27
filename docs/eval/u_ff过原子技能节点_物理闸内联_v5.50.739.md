# u_ff 过「原子技能节点 + 物理闸」再给仿真器 — 落地与 A/B（v5.50.739 · 2026-10-16）

> 老倪原话：「u_ff经过 接近 对位 等原子技能节点，再给仿真器，可以么」→「按照你的建议 改」

## 一、改了什么（画布上早画好了，缺的是引擎照图执行）

画布 `flows/state_space_obs.json` 本来就画了这条链：

```
🧭 动作调制器 → 🛡 安全执行边界 → ①..⑧ SK01-08 → ⚖ 物理约束·惯性/质量率闸
                                                     ├→ 🧪 状态校正器 (小偏差)
                                                     └→ 📡 融合定位建图 (大偏差)
```

但**引擎代码没照图跑**：`cognition.ActionModulator.decide()` 里只有一句 `STAGE_V_CAP` 等比缩放。
本次把收口点搬到原子技能闸（真件 = `physics_constraints.InertiaLimiter.limit`，五条约束，真源
`config/calib/zmax_skill_physics.json`），并接线到两条仿真路：

| 文件 | 改动 |
|---|---|
| `state_space/cognition.py` | `ActionModulator` 加 `limiter/gate_dt/gate`；`decide()` 里「阶段限速」改成：有闸 ⇒ `InertiaLimiter.limit()`（五条约束，单点削），无闸 ⇒ 旧的等比缩放（逐位零回归） |
| `engine/sim.py`（解析引擎） | 构造 `InertiaLimiter` 挂到 `sched`；tr 新增 `gate_why/gate_err/gate_vcap/gate_big/gate_on` 与 `stage_u`（本拍**实际按哪一段**削的）；状态校正器改成**内联闸偏差优先**，无闸才读派发服务文件；`_publish_gate()` 以 5Hz 写 `zmax_data/ss_live/skill_gate.json` |
| `engine/runtime.py`（metaworld 真物理） | 同上接线 + 日志明示 `Δt`；`_publish_gate()` 同一份 JSON（`provider=metaworld 真物理`） |
| `middleware/nodes/gate_truth.py`（新） | 关键路径真值读口：帧龄 >5s 或闸未接 ⇒ 返回空，**绝不假 0** |
| `middleware/nodes/n_skill1..8.py`、`n_constraint.py` | 画布上 ①..⑧ SK 节点 + ⚖闸节点显示**同一次调用**的关键路径真值（原来读派发服务旁路副本） |
| `state_space/physics_constraints.py` | 诊断开关：`ZMAX_GATE_SKIP`（逐条约束消融）、`ZMAX_GATE_JERK_X`（jerk 上限倍率）。默认空/1.0 ⇒ 行为逐位不变 |

开关：`ZMAX_L2_GATE=0|1`（**默认 0 = 不接，现场行为零改变**）、`ZMAX_GATE_DT`（闸 Δt）、
`ZMAX_GATE_SKIP`、`ZMAX_GATE_JERK_X`。

**Δt 口径**：闸的 Δt 默认取**标定口径 0.1s**（真源 `zmax_skill_physics.json` 的 `dt`，表里
`s_step = v·dt` 就是按 0.1s 算的）；`ZMAX_GATE_DT=0.02` 可切「物理真实时间步」口径（五条约束整体收紧 5 倍）。

## 二、判据一：解析引擎（确定性，`tools/ab_l2_inline_gate.py`）— 4/4 PASS

| 臂 | 拍数 | 仿真时长 | 走完 | 末端距目标 | 削因 | 单拍 P50/P95 |
|---|---|---|---|---|---|---|
| A 旧链（等比缩放） | 369 | 7.36 s | 8 段含完成 | 65.954 mm | — | 0.032 / 0.353 ms |
| **B 新链（闸，Δt=0.1s）** | 370 | 7.38 s | 8 段含完成 | **65.902 mm** | 速度7·加加速度3（共 10 拍） | 0.031 / 0.388 ms |
| B′ 新链（闸，Δt=0.02s 物理口径） | 393 | 7.84 s | 8 段含完成 | 65.738 mm | 速度13·加速度77·加加速度266（356 拍）·大偏差 112 拍 | — |

- ① 逐段实际速度 ≤ 本段 `v_cap`：**PASS**（8 段 0 超限；`u_sat` 峰 对位 0.0965≤0.12、下降 0.0900≤0.09、抓取 0.0400≤0.04、转移 0.2203≤0.35）
- ② 闸单拍开销 **P50 22.2 µs / P95 25.3 µs**（判据 ≤10 ms）：**PASS**（余量 ~400×）
- ③ 削因不翻倍：闸调用 370 == 拍数 370（每拍只削一次）：**PASS**
- ④ 任务不回退：4/4 段全走完、末端 65.902 vs 65.954 mm（略好）、时长 7.38 vs 7.36 s：**PASS**

Δt=0.02 口径下也 PASS，但**慢 6.5%**（393 vs 369 拍），削因集中在加加速度（266 拍）。

## 三、判据二：metaworld 真物理（`tools/ab_l2_inline_gate_real.py`，3 seed × 2 臂，500 步上限）

| seed | 旧链 A | 新链 B（Δt=0.1s） |
|---|---|---|
| 104 | **done · 插深 64.3 mm · 横向 2.5 mm** | **未 done · 插深 −2.3 mm（没进孔）· 横向 10.2 mm** |
| 11 | 未 done · −15.0 mm | 未 done · −3.8 mm |
| 105 | 未 done · −15.4 mm | 未 done · −16.0 mm |

①②③ PASS（闸 P50 23.8 µs；闸调用 == 拍数），**④ FAIL：seed104 回退**（唯一旧链能成功的 seed 被打破）。
物理口径 `ZMAX_GATE_DT=0.02` 同样在 seed104 失败（`ab_l2_inline_gate_real_dt20ms.json`：A done / B 未 done，7 段），
即回退不是 Δt 选大选小造成的，是约束本身（下面消融定位到③）。
⚠ 注意：判成功只看项目自己的几何真值 `ss_insert_metrics`（沿孔轴 depth_mm / 横向 lateral_mm），
不要用 `tr["mani_rem"]` —— 那是性能流形的 d_axial，不是插深。

## 四、消融：真凶是③加加速度闸（`tools/ablate_l2_gate_real.py`，seed104）

| 配置 | 完成 | 拍 | 插深 mm | 横向 mm | 削因 |
|---|---|---|---|---|---|
| 旧链（闸 OFF） | ✅ | 348 | 64.3 | 2.5 | — |
| 五条全开 | ❌ | 500 | −2.3 | 10.2 | 速度21·加加速度31·位移3 |
| **跳过加加速度** | ✅ | **348** | **64.3** | **2.5** | 速度18 |
| 跳过加速度 | ❌ | 500 | −2.3 | 10.2 | 同全开（加速度本来就 0） |
| 跳过位移 | ❌ | 500 | −2.3 | 10.2 | 速度21·加加速度31 |
| 跳过速度 | ❌ | 500 | −1.8 | 10.1 | 加加速度30·位移20 |
| 跳过加加速度+加速度 | ✅ | 348 | 64.3 | 2.5 | 速度18 |

跳过加加速度后与旧链**逐位一致**（348 拍 / 64.3 mm / 2.5 mm）⇒ 回退 100% 由 ③ 造成。

## 五、jerk 上限倍率扫描（seed104，其余四条全开）

| `jerk_max` × | 完成 | 拍 | 插深 mm | 横向 mm | 加加速度削拍 |
|---|---|---|---|---|---|
| ×1（现标定） | ❌ | 500 | −2.3 | 10.2 | 31 |
| **×2** | ✅ | 349 | **64.9** | 2.5 | 2 |
| ×4 | ✅ | 348 | 64.3 | 2.5 | 0 |
| ×8 / ×16 / 关掉 | ✅ | 348 | 64.3 | 2.5 | 0 |

**结论：标定的 `jerk_max`（接近 15 / 对位 5.14 / 下降 3.86 / 抓取 2.25 / 插入 3.64 m/s³）偏小 2~4 倍。**
毫米级插孔需要的微修正，加速度变化率恰好卡在 `jerk_max·dt` 上被抹平 → 伺服变"迟钝" → 对不上孔口。
×2 即可恢复任务且闸仍真削（2 拍）；×4 起该条约束对这种任务透明。

## 六、结论与下一步

1. **接线成立**：`u_ff → ①..⑧ SK 段包络 → 五条物理约束 → 安全限幅 → 仿真器` 已在两条路上真实执行，
   单点削、闸开销 ~25 µs、画布 ①..⑧ 与 ⚖ 节点显示的就是关键路径同一拍的真值。
2. **默认档不切**（按 09-12 定的门槛「未证明提升不得进默认档」）：`ZMAX_L2_GATE` 默认 **0**，
   现场行为逐位零改变。解析引擎零回退（4/4 PASS），真物理 seed104 回退（插深 64.3 → −2.3 mm）。
3. **打开方式（已验证可用）**：
   ```bash
   ZMAX_L2_GATE=1 ZMAX_GATE_JERK_X=2 ./gui-venv311/bin/python <入口>
   #   → seed104: done · 349 拍 · 插深 64.9mm · 横向 2.5mm（优于旧链 64.3mm）
   ```
4. **要切默认档的正路**：把 `jerk_max` 按实测重标定（建议 ×2，`tools/skill_physics_calib.py --set`），
   再跑 `ablate_l2_gate_real.py` + 多 seed 复验；同时把「请求速度按各段包络发」一起修
   （上一轮 L2 全测：上游统一请求 120 mm/s，下降/抓取/插入/完成 4 段每拍被削，反馈恒等 cap，测不出延迟）。

## 七、复现

```bash
cd /home/ubuntu/zmax
./gui-venv311/bin/python tools/ab_l2_inline_gate.py                       # 解析引擎 A/B + 四条判据
./gui-venv311/bin/python tools/ab_l2_inline_gate_real.py --seeds 104,11,105 --steps 500   # 真物理 A/B
./gui-venv311/bin/python tools/ablate_l2_gate_real.py --seed 104 --steps 500              # 逐条约束消融
./gui-venv311/bin/python tools/sweep_l2_gate_jerk.py --seed 104 --steps 500                # jerk 上限倍率扫描
./gui-venv311/bin/python -c "import sys;sys.path.insert(0,'src');from lerobot.middleware.nodes import gate_truth as g;print(g.one_line())"
```
落盘：`zmax_data/eval/ab_l2_inline_gate.json`、`ab_l2_inline_gate_real.json`、
`ablate_l2_gate_real.json`、`jerk_sweep.json`、`ss_live/skill_gate.json`（5Hz 关键路径真值）。
