# 状态空间 43→55→100 升级与「级联缓冲」工位建模

## 升级纪律（三次升级同一套，不许破例）
1. **前 N 维语义一字不动**：老权重/老数据/老标定直接吃前 N 位。
2. **新增维只在末尾**，且模型侧零初始化 ⇒ 上线瞬间输出逐位不变。
3. **每段必须有** name/unit/source/note，`validate_layout()` 强制首尾相接、覆盖 0:DIM、无重名。
4. **无来源就 0 + 标沉睡**：`awake()/asleep()` 如实列；不许用默认坐标顶替缺失几何。
5. 零回归判据：同一份前 N 维灌进去，`np.array_equal(x[:N], base)` 必须 True（多组随机，不只 1 组）。

## 55D → 100D（桌面级联缓冲工位）
- 模块：`src/lerobot/policies/left_right/state_space/desktop_buffer_state100.py`
- 验收：`PYTHONPATH=src ./gui-venv311/bin/python tools/verify_state100.py`（27 项，全 PASS 才算完）
- 55D：`unified_state55.py` 的 `ALL_SEGMENTS` 是唯一布局；`fuse()` 里按命名物理量切片再拼回（调试器可读）。
- 100D：0:55 原样 + 55:100 共 45 维，8 组：
  5 个几何锚（infeed/loader/outfeed/insp/scrap）×3 · infeed/outfeed 占用+占用率(4) · 高低水位(2)
  · 槽位四态计数(3) · FIFO/重试(3) · 刷写站状态机(3) · 机器人状态/双工重叠/实测节拍/断供堵塞(8) · UPH 与余量(4) · 背压/全局暂停/废料率(3)
- 配置量 **不进状态向量**：`N`、`M`、`uph_target`、`t_flash`、`stall_max`（走 fuse 的 kwargs）。

## 级联缓冲的核心判据（别只背概念）
- 串行 CT = t_load + t_flash + t_unload；双工 CT = max(t_flash, t_load+t_unload+t_travel)。
- 双工成立前提：机器人总动作 ≤ t_flash；否则瓶颈从设备转到机械臂（`uph_model()['bottleneck']`）。
- 缓冲需求：`N_need = ceil(stall_max / CT_duplex) + 1`（停机不断供）。
- 调度优先级（`schedule()` 实现）：Outfeed 满/设备 ERROR → PAUSE；重试队列 → RETRY（插队，不许排尾）；DONE → UNLOAD→STORE；IDLE+有料 → PICK→LOAD；RUNNING → 去伺候 Outfeed/AOI（**绝不允许 robot_wait=1**）；到高水位 → THROTTLE。
- 槽位四态：EMPTY / OCCUPIED_UNPROCESSED / PROCESSING / OCCUPIED_PROCESSED；逐槽明细用 2bit/槽 位图（≤32 槽），进向量只放四态计数。

## 踩过的坑（务必先看）
- `self.filled` **必须每拍重置**：否则上一拍的派生量（fill/UPH/背压）会让下一拍静默为 0，验收里表现成"派生量不生效"。
- 派生量口径唯一：fill=count/cap、UPH=3600/CT、backpressure=fill≥hi、global_pause=outfeed满|ERROR——只在一处算，调用方不许各算各的。
- 未注册通道/维度不符必须抛错（fail-closed），不许静默补 0。
- 现场段表的钉点会退化：上料盘 4 个槽坐标完全相同、废料盘与下料盘共用坐标 ⇒ 只能做区域级，做逐件避障必须先补槽位标定表。
- 运行中的画布回路会用启动时的内存覆盖 `data/database/zmax/sources/canvas/state_space_obs.json`（手工加的端口声明 out3 会被回退）；要生效必须重启回路，而重启须用户点名。
- 900 UPH 的硬前提：AOI（≈5.1s/件）必须并行化，否则串行上限就是 313 UPH（现场实测 200.6）。

## 现场真值锚（mm→m）
`docs/5-玉衡-指标验收/l2_300uph_closure_20261102.json` 的 rows[].a：
infeed (490,499,240) · loader 孔1 孔底 (767,228,278) · outfeed 下槽1 (490,76,198) · insp 金手指 (360,-117,654) · scrap (469,-402,200)
抽取函数：`anchors_from_segment_table(path)`，抽不到就返回 missing，不猜。
