---
name: aoi-quality-chain-wiring
description: Use when 质量检测/AOI 端口有值但下游不生效或判 NG 拦不住产线。
version: 1.0.0
author: 静静 (Hermes)
license: MIT
metadata:
  hermes:
    tags: [aoi, quality-gate, async-node, 10082, 10083]
    related_skills: [l2-node-signal-linkage, zmax-aoi-service, dispatch-chain-integrity]
---

# AOI 质量检测链路的接法与坑

## When to Use

- 画布上 `ssaoi` 连着下游但判决不影响执行
- 质量门 "接了" 但判 NG 停不下来
- AOI 节点一开就拖死 10Hz 动作循环

## 三个必踩的坑

### 1. 节点同步跑必拖死循环，但不能因为怕拖就 `PURE=False`

单拍实测 1.3~3.0s（2×HTTP 10082 + 1×HTTP 10083 + 1 次 YOLO），引擎是 10Hz（100ms/拍）。
同步 ⇒ 卡死；`PURE=False` ⇒ 检测永远不上总线（等于没做）。

**正解**：异步 worker + 非阻塞读快照。worker 自己按 `ZMAX_AOI_MIN_INTERVAL_S`(2.0s) 循环，节点每拍只读最新快照，实测节点自身开销 **1.4ms/拍**（10Hz 连打 100 拍墙钟 10138ms = 只睡了 10s）。
首轮未完成返回 `warming` + `pass=None`，**不造 0**；快照带 `seq/age_s/stale`。

### 2. `pass=False` 不等于工件 NG

`AOIQualityChecker.check()` 的 `verdict` 是**取像体检**（ok/overexposed/too_dark/gaps_washed），取像不健康时它也会返回 `pass=False`。
若直接 `pass is False ⇒ 拦截`，产线会因为**相机参数**而不是**工件**被停。

**正确口径（四态）**：

| 工况 | 判定 |
|---|---|
| 无载荷 / 未出判决 / 快照过期 | 门不可用，**不拦**（信息不全不许拦产） |
| `verdict != ok` | 门不可用，**不拦**（这是相机问题） |
| `verdict == ok` 且 `pass is False` | **真 NG，拦** |
| `verdict == ok` 且 `pass is True` | 放行 |

依据：参数错的帧上谈缺陷判定没有意义。

### 3. 质量门被当 `contact_p` 读（最隐蔽）

`ssaoi.out1 → sssched.in5` 标签是「质量门」，`safety_limit_impl` 却写成
`_pick("in5", ("contact_p","p","score"))` —— AOI 载荷里没有这三个键 ⇒ 取不到 ⇒ 这条边**端口有值却等于没接**。
空口（None）能扫出来，这种不能。

**排查**：把上游真实 payload 的键集合与下游候选键做集合差，交集空 = 伪接通。

## 链路拓扑（画布实连）

```
ssyolo.out1   → ssaoi.in1        检测区域
ssaoi.out1    → sssensor.in4     外观质量门  → 并入融合输出 aoi 字段(不进 obs43, 保维度语义)
ssaoi.out1    → sssched.in5      质量门      → safety_limit_impl 硬否决 (kind=quality_veto)
```

**为什么质量判定不进 obs43**：obs43 = 39D 视觉 + 4D 触觉，有固定的维度语义。把质量塞进去会破坏下游所有对 43 维的假设。质量是**独立观测**，随融合结果下发，由调度层否决、界面展示良率。

## 验证脚本

- `tools/probe_aoi_chain.py` — 逐环节真值（取帧/check/信号/三路旁路）
- `tools/probe_aoi_async.py` — 异步零阻塞 + 首轮 warming + 快照帧龄
- `tools/probe_aoi_chain_e2e.py` — 三件事：AOI 真出 / sensor 真读 in4 / 质量门六工况口径

**必测反例**：断开 in4 时应显示「in4 未连/无值」—— 若仍出数，说明是内部回填不是真读端口。

## 三路旁路

| 路 | 源 | 口径 |
|---|---|---|
| `gold.py` | 10082 `/last_result` | 搬运工控机判决，不重算（本机无 960 权重）；404 = 判决 2(未检)，**绝不填 0 冒充 OK** |
| `gold_yolo.py` | 10082 `/picture?kind=origin` + 本机 `yolo_gold_v2.pt` | **默认只观测不判决**（权重自蒸馏、泛化未验），判决须 `ZMAX_GOLD_YOLO_GATE=1` |
| `surface.py` | 10083 同帧 → 本机 `SurfaceOpticalQuality` | 与交付判据图同一 `surface_judge`，不另写口径 |

产线不通时三路都应降级为 `unavailable` 并有 60s 冷却（不拖节拍），这是正确行为不是故障。

## PURE 转正的前提

把 `n_inspection.PURE` 置 `True` 的**前置条件是实现层非阻塞**。若把 `ss_aoi.py` 改回同步实现，必须同时退回 `PURE=False`，否则 10Hz 动作循环会被 AOI 拖死。
