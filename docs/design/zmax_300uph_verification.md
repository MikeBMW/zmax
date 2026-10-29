# 300UPH 状态空间驱动验证（2026-10-29 实测）

## 结论

**状态空间驱动下实测达标**，且驱动链路同步误差 75ms 以内。

| 口径 | 数值 | 说明 |
|---|---|---|
| 累计节拍 | 10.21 s/件 | 51.06s 出 5 件（follow 后两段窗口合计） |
| 折算 UPH | **344** | 10.21 s/件 折算 |
| 窗口值 | 288 ~ 415 | 25s/26s 离散采样，件数少相位抖动大 |
| 驱动同步误差 | **−0.075s** | ARCMD.elapsed_s 增量 vs 页面 simT 增量 |
| 良率 | 10 ok / 0 ng | 全程无 NG |
| 真机下发 | **false** | 8793 未授权，real_send=false |

对标回放标杆 11.42 s/件（314 UPH），本次 10.21 s/件略快 —— 差异来自离散窗口，不是真实加速。
**保守口径取段表节拍 11.47 s/件 = 314 UPH，仍高于 300 目标。**

## 验证方式（可复现）

```
1. 引擎常驻：systemctl is-active zmax-ss-engine-loop → active
2. 确认执行信号在推进：/api/ar/mode 里 ar_scene=true；页面 ARCMD.seq / elapsed_s 递增
3. 页面拨接入 + 跟随：ssFollowStart()   （= 左栏「🧠 状态空间」拨开 + ▶ 跟随）
   关键判据：PLANT.local === false   ← 只有 false 才是状态空间驱动，true 是本地时钟
4. 读增量：
   simT_delta         页面仿真时间增量
   ARCMD.d.elapsed_s  状态空间执行器时间增量
   units_delta        产出件数增量
   UPH = units_delta / (simT_delta / 3600)
```

实测原始数据（两段连续窗口）：

```
段1: window 25.04s  units +2  ARCMD.seq 32→  mod 7   elapsed 71.59  右臂「检测 侧面点2」左臂「待命(料仓满)」
段2: window 26.02s  units +3  ARCMD.seq 6 →  mod 10  elapsed 104.6  同步误差 -0.075s
```

## 与「本地时钟模式」的区别（重要，别混口径）

| | 本地时钟模式 | 状态空间驱动 |
|---|---|---|
| 触发 | 点「🏭 全流程 UPH」 | 拨「🧠 状态空间」+ ▶ 跟随 |
| `PLANT.local` | `true` | **`false`** |
| 时间源 | 页面 simT 自走 | `ar_cmd.json` 的 elapsed_s |
| 节拍 | 307 UPH（58.7s / 5 件） | 344 UPH（51.06s / 5 件） |
| 驱动同步 | 无（不连） | 误差 −0.075s |

两种模式读的是**同一份段表**（sim_insert 392 段 + sim_transport 112 段），
所以节拍量级一致；区别在于状态空间模式的时间由引擎执行器给，断了就停在最后一帧（不偷退本地仿真）。

## 双臂状态（状态空间驱动下）

- 右臂：`sim_insert.json` 392 段，按 seq/u 走帧 → 横幅显示「搬运/插拔」「检测 侧面点2」等
- 左臂：`sim_transport.json` 112 段（14 槽 × 8 段），`TRANS.playing=true`，状态「待命(料仓满)」
- 料仓 14/14，产出由 `ARCMD.d.mod` + 轮次累加给出

## 仍然存在的口径问题（如实）

1. 段表 392 段的 `arm` 字段仍是 `none` —— 左右臂没有在同一张表里标注归属，
   而是两张表并行各自播放。要严格证明「同一条流水线上两臂协同」，需要给段加 arm 标签。
2. `units_delta` 在短窗口内有相位抖动（mod 跳变），单窗口 UPH 误差可达 ±60，
   长窗口或累计口径才稳。报告里必须注明窗口长度。
