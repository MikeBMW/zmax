# 桌面缓冲区统一状态空间: BufferGraph 层设计 (2026-11-13)

## 0. 一句话结论

**不是"把缓冲区塞进 SU(2) 节点"**。SU(2)≅S³ 只有 3 个转动自由度, 槽号/料盘归属/队列/时间戳/各向异性容差
都不是转动, 塞进群元素会丢信息(有界映射在饱和区多对一)。正确分工是四层:

| 层 | 承载什么 | 实现 |
|---|---|---|
| ① 事实层 (真源) | 逐槽节点: 槽号/料盘/区域/SE(3) 位姿/度规/四态/入队时间 | `buffer_graph.py::BufferGraph` |
| ② 压缩投影 | 17 槽 → 100D 状态向量 (占用/四态计数/水位/UPH/废料率) | `aggregate()` → `DesktopBuffer100.fuse()` |
| ③ 群层 (判据/朝向) | 每槽朝向 U_slot、对位误差 θ=2·arccos\|w\|、场景层合成 | `su2.SU2Element` / `compose_scene` |
| ④ 度规/势场 (执行约束) | 区域相关的 M: Δξ = −α·M⁻¹∇V | `MetricTensor` → 流形引擎 |

SU(2) 节点(`ssobs`)最合适的位置是 **③ 判据与出口层**, 不是 ①的容器。

## 1. 数据模型

`BufferNode` = 一个物理槽位(空槽也发布, 状态 EMPTY, 供调度预留):

```
node_id / parent_tray_id / zone_type(0 in,1 flash,2 out,3 scrap,4 inspect)
t ∈ ℝ³ (m)      U ∈ SU(2)         ← 位姿 = SE(3), 不拿群装坐标
target_t / target_U
metric: MetricTensor(σ_radial, σ_axial, axis)
slot_state: EMPTY(0) / UNPROC(1) / PROCESSING(2) / DONE(3)
t_in / t_out  ← 时间张量 τ, UPH 与排队论的输入
```

现场默认拓扑 17 槽: infeed 8 · flash 1 · outfeed 6 · AOI 1 · scrap 1
(几何锚取自 `l2_300uph_closure_20261102.json`, mm→m)。

## 2. 各向异性度规 (核心算法)

定义: 刚度张量 `M = (1/σ_ax²)·nnᵀ + (1/σ_rad²)(I − nnᵀ)`, 引擎步长 `Δξ = −α·M⁻¹∇V`,
`M⁻¹ = σ_ax²·nnᵀ + σ_rad²(I − nnᵀ)`。

- 插入区 `σ_radial = 0.3mm`, `σ_axial = 6mm`, 轴 = 插入方向 ⇒ **径向步长 0.090×, 轴向 36×** (各向异性 400×)
- 自由区 `σ = 1mm` 各向同性 ⇒ M = I, 与老行为逐位一致
- 实测 `max|M·M⁻¹ − I| = 0.00e+00`

**动态度规的硬边界 (纠正原方案 4.3)**: "UPH 落后就放宽 σ_radial 换速度" 只允许在自由区,
且倍数 ∈ (1,2]。插入区 σ_radial 锁死 —— 放宽 = 拿刮擦换节拍, 与 0 刮擦目标直接冲突。
`relax_metric()` 对 flash 区 fail-closed 返回 `ok=False`。

## 3. 时间张量与异步双工

- 逐槽 `age = now − t_in`; `wait_times()` 给均值 W; `cycle_time()` 取完成间隔中位; `uph()` 用 60s 滑窗
- 队列律自检 `L = λW` (`queue_law()`), 偏差 > 0.5 件即口径错
- 调度意图 (只出意图, 不出轨迹): PAUSE > RETRY_FLASH > UNLOAD > **PREP_NEXT** > LOAD > THROTTLE > IDLE
  - **PREP_NEXT**: 设备在刷时把下一件搬到待插位 ⇒ 结构上禁止 `robot_wait=1`
  - `insert_inserts_done()` = 插完立刻结算并给出下一条意图 (双工的关键一跳)
  - 刷写失败 → 回 UNPROC 并进重试队列(插队, 不排尾)

## 4. DDS 传输

不新建 IDL 类型 —— 仓库既有 `SSNodePort(topic, ts, json)` 用 JSON 承载值域, 加字段不改 IDL、不重建类型。
`to_payload()` 一次给全: `all_slots`(17 节点) + `aggregate` + `wait` + `queue_law` + `intent`;
实测序列化 **9,650 B < 64KB**, 10Hz 广播无压力。`from_payload()` 回灌只恢复节点事实,
统计窗口必须靠真实事件重放(不许伪造成熟)。

## 5. 验收 (可复跑)

```
PYTHONPATH=src ./gui-venv311/bin/python tools/verify_buffer_graph.py   # 54 项
PYTHONPATH=src ./gui-venv311/bin/python tools/verify_state100.py       # 27 项 (零回归)
```

覆盖: 拓扑/锚 · M·M⁻¹=I · 径向 0.090×/轴向 36× · SE(3) 位置 mm + 姿态物理角(非 S³ 半角) ·
U=I⇔对位 · 双覆盖 d(q,−q)=0 · 状态机 fail-closed(5 类非法转移全抛错) · 时间张量 2.500s ·
双工 PREP_NEXT/UNLOAD 无 WAIT · 重试插队 · 队列律 dev=0.000 · 100D 前 55 位逐位零回归 ·
插入区放宽被拒 · DDS 往返 17/17 · JSON 9.6KB。

## 6. 未接通的 (如实列出, 不许当已交付)

1. **画布节点接线**: `ssobs` 节点还没读 BufferGraph。要真接需改节点 + 重启画布回路
   (`zmax-ss-canvas-loop`), 重启须用户点名。
2. **引擎度规注入**: `MetricTensor.step_matrix()` 已是引擎可直接乘的形式, 但引擎
   `gradient_flow` 目前用标量/各向同性度规; 真注入要改 `manifold_engine` 的步长那一行 (需真机验证)。
3. **槽位坐标标定**: 段表上料盘 4 槽坐标完全相同 ⇒ 现在按 `tray_y_pitch=0.05` 人工展开,
   属**代理值**, 真值待现场标定表。
4. **DDS 实际广播**: 载荷已就绪, 但未挂到 10Hz 回路; 现为库层(可被任何进程调用)。
