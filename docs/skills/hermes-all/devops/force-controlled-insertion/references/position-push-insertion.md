# 位置推 + 被动力看门狗 插入配方（SDK 直连, 真机验证）

适用: 产线 `/lissajous_force_search` 不在图上, 且工件已顶在孔口/止口（力控模式必下电）。
主脚本: `tools/rokae/insert_sdk_fc.py`（容器内 `/repo/insert_sdk_fc.py`）, 经
`bash tools/rokae_sdk_run.sh --script insert_sdk_fc.py --mode ...` 下发。

## 三个模式

| 模式 | 用途 | 关键参数 |
|---|---|---|
| `--mode push` | 纯轴向慢推/后退（无李萨如） | `--travel-mm ±N --speed 1~2 --stop-n 30 --lat-max 6~10` |
| `--mode lissa` | 李萨如找孔 + 侧向导纳（位置空间自实现） | `--travel-mm --lissa-step 0.2 --lissa-amp 0.2~0.4 --lissa-f1 0.5 --lissa-f2 0.9 --lissa-adm-k 0.15 --lissa-adm-max 2.0 --lissa-tq-max 2.0~3.5` |
| `--mode seat` | 一步直插到示教到底点位 | `--seat-pos x,y,z --seat-rpy r,p,y --approach-mm 12 --fast-speed 6 --speed 1 --stop-n 30 --lat-max 10 --lissa-tq-max 3.5` |

三模式共用: 力控**全程不启动**; 静止取一次 `getEndTorque` 基线（连续两次差<1N）, 运动中每 20ms 比 Δ, 超阈 `stop()`+`moveReset()`;
收尾 `stop` + `moveReset` + 回 `Idle`; 每发落 CSV + JSON 证据。

## 看门狗阈值（按现场口径, 别写死）

```
轴向 Δfz   ≥ stop_n（默认 30N）        硬红线 FZ_HARD_N（命令行更大也压回 FZ_TRIP_N）
侧向 hypot(Δfx,Δfy) ≥ lat_max（6~10N）  防划伤: 6N=保守 10N=允许贴壁滑
力矩 max(|Δtx|,|Δty|,|Δtz|) ≥ tq_max（1.5~3.5Nm）  别劲/卡扣
```
力矩阈值是**唯一能抓到“姿态偏斜”的信号**, 不许关掉; 顶到 3Nm 而轴向只有 10N ⇒ 在别劲, 不是在插。
🔴 力矩阈值**必须用 Δ**, 而且基线要按当前姿态每发重取: 静止 |T| 随姿态在 0.7~9Nm 级漂（自载 × 0.2~0.3m 力臂）。
实测同一口同一天 `ty` 从 −0.66 变到 −9.10Nm 只是姿态变了, 与接触无关 —— 拿绝对值判楔紧会得出反结论。

## 本机实测标定（同会话内仍要复核）

| speed | 实测 mm/s | 说明 |
|---|---|---|
| 30 | ≈13.6 | 会一帧冲到 −27N, 只能走自由段 |
| 6 | ≈2.7 | 接近段 |
| 2 | ≈1.9 | 李萨如常规段 |
| 1 | ≈0.8~1.0 | 最后几 mm / 后退 |

每段时长 ≈ `段长 / (speed×0.45)`；`--lissa-step 0.2` + `--speed 1` ⇒ 每段约 0.2~0.25s, 一个侧向正弦周期采到 5~8 点。

## 侧向导纳（减少贴壁摩擦, 不靠加大阈值）

在每段目标点上叠一个偏置 `(ox, oy)`（工具系 X/Y, mm）:

```
ox ← clamp(ox − k·Δfx·dt, ±adm_max)      oy ← clamp(oy − k·Δfy·dt, ±adm_max)
k=0.05~0.15 mm/N/s, adm_max=1.2~2.0mm
```

效果: 侧向持续 7N 时把轨迹往减力方向挪, 实测让同一段从“侧向 6.1N 立刻停”变成“5mm 走完, 峰值 7.6N”。
导纳偏置必须随轨迹一起报给现场（`adm_offset_mm`）, 否则“位移怎么斜的”说不清。

## 判据表（拿数据说话, 不靠“感觉没到底”）

| 观察 | 判读 | 动作 |
|---|---|---|
| 轴向随深度线性涨（3.8→8.6N/10mm）, 侧向小幅 | 正常插针摩擦 | 继续分段 |
| 侧向持续 7~9N + 力矩单调上涨 | 轴没对齐 / 贴一侧壁 | 退出, 校平轴, 再推 |
| 轴向陡增、侧向不涨 | 到底（硬止口） | 停, 松 0.5mm 验卸载, 录点 |
| 力大, 松 0.5mm 后 |F| 回自由段基准 | 确认硬止口 = 到底 | 录“插入到位”点 |
| 力大, 松一点仍大 | 摩擦/楔紧 | 侧向导纳 + 更慢, 或退出重对 |
| 后退段**侧向 Δ 单调抬**（0.5→13.9N）+ 轴向 Δ 峰 25N | 卡扣/止口保持力（真阻力） | 申请一次退出许可: 侧向 20N/力矩 8Nm、沿轴直退 3mm、无横动; 判据=退后 \|F\| 回自由段基准 |
| 力矩**绝对值**大（ty≈9Nm）而 Δ 很小 | **不是接触**, 是长力臂自载重力力矩 | 只认 Δ; 别据此判“楔紧/卡扣” |
| 退出后 \|F\| 回到自由段静载基准（15.1N vs 15.2N） | 已脱离止口, 无残余压力 | 可安全移到落点或进入 seat 复插 |

## 取证与汇报（现场要的是表, 不是叙述）

- 每发 CSV: `t / x y z / fx fy fz / tx ty tz / Δfz Δlat Δtq / 沿轴推进mm`（20ms 一行）
- 每发 JSON: `verdict / adv_toolz_mm / peak_axial_n / peak_lateral_n / peak_torque_nm / adm_offset_mm / csv`
- 汇报固定格式（逐段表 + 当前位姿/累计深度 + 峰值 vs 阈值）, 例:
  `推进5.01mm · 轴向峰9.6N · 侧向峰8.7N · 力矩峰2.15Nm · done`
- 绝对值与净值分开写: `|F| 56.1N(max) / 自由段静载 24.1N / 净接触 ≈32N`。

## 代码级坑（改脚本前必看）

- **`argparse` 的 dest 是长选项名去横线**: `--lissa-step` → `a.lissa_step`, 不是 `a.lstep`;
  新增参数前先 `grep add_argument` 查重名（`--step-mm`/`--f1`/`--f2` 已被 search 模式占用, 新参数加前缀）。
- **容器里只挂了 `tools/rokae` 到 `/repo`**, `data/`、`zmax_data/` 都读不到 ⇒ 点位不要靠脚本自己读台账,
  在宿主侧读出后用 `--seat-pos/--seat-rpy` 传进去。
- **负行程的到点判据用绝对值**: `abs(adv) >= abs(travel)-0.2`, 否则后退那一发会立刻“target_reached 0.00mm”。
- 队列里残留的 `MoveLCommand` 会被下一次会话接着跑 ⇒ 每发收尾必须 `moveReset()`。
- 插入前确认**件还在爪里**: AR 锁定框 `box2d` 与实时框差几十~几百像素 = 滑了/歪了, 此时推没有意义。
