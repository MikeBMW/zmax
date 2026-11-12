---
name: uph-throughput-verification
description: "Use when 做到目标 UPH、双臂不动、或 action 链断。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [uph, action-chain, dual-arm, state-space, zmax]
    related_skills: [state-space-canvas-engineering, integration-level-audit, dispatch-chain-integrity]
---

# UPH 吞吐验证与 action 链体检

## When to Use

- 被要求"达到 N UPH""节拍提上去"，需要给出可信数字
- 模型/节点"有输出"但执行侧不动、action 恒 0
- 双臂只有一侧动，或点击按钮反向（开了立刻关）
- 要判定某个节点是"真跑"还是"直通"

不适用：只查单节点算法精度（用 surface-defect-vision-detection）。

目标型任务（"达到 300UPH""左右臂都动"）最常见的失败不是模型不行，而是链路断了却显示正常。本技能给判据和体检顺序。

## 1. 先定口径，再报数字

三种 UPH 数字，含义完全不同，混报就是撒谎：

| 口径 | 怎么算 | 能说明什么 |
|---|---|---|
| 段表节拍 | `tact_steady_s` → `3600/t` | 轨迹规划的物理上限，与谁驱动无关 |
| 本地时钟窗口 | 播放器自播，读 `units/simT` | 只证明播放器能跑，不证明链路 |
| 状态空间驱动 | 引擎执行器给时间，读 `ARCMD.elapsed_s` 增量 | 证明执行链真在推进 |

- 必须看 `local` 标志：`local===true` = 浏览器自己跑表（假接入）；`false` = 吃外部信号。这是区分"真驱动"和"看起来在动"的唯一硬判据。
- 短窗口不能报 UPH：20s 窗口出 1 件算出来 180，出 2 件算 360，误差超过 100%。至少跨 50s / 5 件，或用累计口径 `units/(elapsed/3600)`，并注明窗口长度。
- 同步误差是驱动链健康的量化证据：`ARCMD.elapsed_s` 增量 vs 页面 `simT` 增量，差小于 100ms 才算真同步；差几百毫秒说明有一侧在本地补帧。

## 2. action 链四类断链（按出现频率）

### 2.1 状态字典没人写（最隐蔽）
现象：模型输出有值、日志漂亮、执行侧恒 0。
体检：`grep -rn '_SS_STATE\["u"\] *=' src/` —— 如果零命中，就是上游只把结果落盘、从不写运行时状态。
修法：在模型节点出口写回 `_SS_STATE["u"]`，同时保留落盘（落盘给人看，状态给下游用）。

### 2.2 PURE 双闸
每个 middleware 节点有两道闸，只开一道等于没开：
1. `PURE = False` 模块常量 → 整段实现不执行
2. 实现 `return True` / `return bool(...)` → 壳层判"非 dict" → 当直通过滤

体检：`grep -n 'PURE = ' src/lerobot/middleware/nodes/n_<x>.py` 和 `grep -n 'return True' src/lerobot/engineering/nodes/<x>_impl.py`。
修法：PURE 改环境变量默认开（`ZMAX_<X>_OFF=1` 回退），返回值改业务 dict。

### 2.3 重复事件绑定
现象：按钮点了反向操作（开了立刻关）。
根因：以为没绑定就补一条 `addEventListener`，而原有绑定还在 —— 第一条 start，第二条看到 `on=true` 就 stop。
体检顺序：先 `grep -n "b<X>" page.html | grep -iE 'addEventListener|onclick'`，确认原绑定用的是哪个函数名（可能叫 `plantToggle` 而不是 `plantStart`），再决定是否补。
修法：删掉自己加的那条，别改原有逻辑。

### 2.4 段表未加载就启动
现象：播放器在跑（`simT` 递增）但 `units=0`、臂不动。
根因：启动函数不负责取段表，段表由另一个 toggle 异步 fetch。
体检：直接读 `INSP.plan.length`、`TRANS.data.segs.length`，为 0 就是没加载；对照 `curl /api/sim_xxx` 确认服务端有数据。

## 3. 冷启动 vs 热态，别把加载算进节拍

首拍慢往往是一次性成本，拆开测才知道能不能达标：

```
ensure_aligner   3744ms   ← 权重加载
env.reset          12ms
env.render        224ms   ← 首帧着色器编译, 之后 11ms
detect_3d_meta   1155ms   ← cuDNN 预热, 之后 15ms
```

热态合计 38ms。报性能必须报热态，冷启单独注明；否则会误判"模型太慢需要优化算法"，实际只需预热常驻。

另一类假慢：远端不可达。HTTP 抓图超时默认 1s，服务离线时每拍白等 1s。修法：0.25s socket 探活 + 失败后 60s 冷却，不为一个离线服务付每拍代价。

## 4. 双臂要动的三个必要条件

1. 每个臂都有自己的段表（常见是两张独立表并行，不是一张表带 `arm` 字段）
2. 两张表都真加载（读 `plan.length`，别信按钮高亮）
3. 播放器接外部信号（`local=false`）或本地时钟，两者只能选一个，混用会出现"看着在跑但不动"

要严格证明协同，段表得带 `arm` 归属；两张表并行只能证明各自在动。

## 5. 差多少、靠什么补（拿到 UPH 数字之后的第二步）

只报"现在 200 UPH"没有用，要拆成"固定开销 + 距离/速度"再谈怎么补：

- 对 move 段拟合 `实测 = c + 距离/v`。c 是段边界的加减速/到位判定，短段上往往占一半以上；v 常常已接近控制器上限，**所以"把速度调快"没用，要减少每段停下重新加速的次数**（相邻段混合下发、并检、合并工位）——这一类才是真杠杆。
- 实测时长必须**逐段同源**：每段用台账里同一个 label 的实测均值。拿 kind 均值去乘/除计划均值，会把 17 mm 短移和 619 mm 长移按同一慢速比缩放，数字凭空变好或变坏。
- 台账里的 `plan_t` 常被写成"最后一条样本的计划时长"，随引擎每段漂；**不能拿它当分母**（同一份数据能算出 150 和 200 两个 UPH）。要么逐段匹配 label，要么冻结快照。
- 台账是活数据：出页面/交付件时把 kind+labels 一起冻结进快照，页面与自检读同一份；只冻 kind 均值而口径改成 label 的话，页面和自检会各算一套。
- 目标型汇报给组合不给单项：任何单一动作都到不了 300 时，写清"三项合计 X UPH 仍差 Y"，把没在真机验证过的杠杆标成"未兑现"，并给验收判据（段边界速度不归零 / AOI 占用降到 X s / 连续 50 件累计口径）。

## 5b. 段表只有位置 = 姿态没有判据 (2026-11-02 补)

判「节拍/链路」时容易漏掉一条: 传统段表只有 a/b 两点, **没有姿态字段**。后果不是"慢", 是"歪了也算到位":

- 到位判定 `wait_arrive(tol_mm)` 只比位置, 四元数从头到尾没参与 ⇒ 姿态走歪照样报到位。
- AR 渲染里的工件朝向常常是**写死的常量** (如 module_calib_ref 的 quat), 不是段表也不是真机 ⇒ 画面不能当姿态证据。
- 真机姿态的旧口径是"保持当前/示教姿态"三条来源 (段显式 quat / 点位库 quat:"taught" / 现读真值), 全开环。
- 免手眼的板坐标系定位只解板平面 x,y (射线∩板平面), 不解孔轴朝向; 绕孔轴的转角要另找真源 (料盘槽几何)。

修法 (已落地口径): 段表逐段带 `quat=[x,y,z,w]` + `quat_src`(in1显式/point示教/start保持); 到位判据改
**位置且姿态** (姿态容差 `ZMAX_ARRIVE_TOL_DEG`, 默认 0.5°, 连续两次); 姿态真值读不到 ⇒ 默认 fail-closed
报 `unverified` 不认到位 (`ZMAX_ARRIVE_ATT_FAILOPEN=1` 才按位置放行, 且仍标未验); AR 用 `R_calib⁻¹·R_GRASP`
映射把段表 quat 接到已认可的抓取姿态上, 并在页脚标"姿态源 + 与死值差 X°"。

现场落地顺序: 先 `ZMAX_ARRIVE_TOL_DEG=2` 跑一轮看日志里姿态残差分布, 再收紧到 0.5; 判据改了必须重启 daemon 才生效。

## 6. 收口清单

- 证据归档：live 快照 + 节点 I/O + 执行器日志尾（大 log 只留 tail，别整份入库）
- 文档写三样：口径定义、实测数值带窗口长度、未闭环项
- 未闭环项必须如实列（条件注入标志、段表归属、离线服务），不许用"基本达标"盖过
