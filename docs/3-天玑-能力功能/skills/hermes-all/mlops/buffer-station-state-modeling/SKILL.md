---
name: buffer-station-state-modeling
description: Use when 把工位/产线按缓冲区中间件建模并扩状态向量 (55→100 类升维).
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [state-space, buffer, queue, middleware, dimension-upgrade, verification]
    related_skills: [state-space-55d-upgrade, su2-unified-state-space, uph-throughput-verification]
---

# 用"中间件缓冲区"给工位建模, 再把状态向量扩到新维度

## When to Use
- 用户描述一个**物料流**工位(上料盘 / 插孔设备 / 检测站 / 下料盘 / 废料盘), 要求"观察到每个目标与障碍、按实际轨迹避障"
- 要把统一状态向量从 N 维扩到 M 维 (43→55→100 这类), 且不能让在役权重/数据失效
- 要回答"给引擎/策略的数据到底是什么、每维是什么物理量、有多少是空的"
- 用户抱怨"数据不好也不够", 需要分清是口径问题还是采集/对齐问题

已落地的实例(45 新增维、几何锚、验收 12 项、真数据样帧)见 `references/desktop-buffer-100d.md`。

## 一、先翻译成生产者-消费者, 再谈通道
工位 = 生产者 → 环形缓冲 → 一级消费者站(刷写/装配) → 二级消费者站(检测) → 良品出口 / NG 旁路。
先把这条链写出来, 再为它出通道。**不要**从"还能读什么传感器"倒推维度 —— 那样得到的向量没人用得上。
每类通道对应一个"做判断要用的问句":
- 堆没堆满 ⇒ 写/读指针、占用数、占用率
- 该加速还是该停 ⇒ 高/低水位、背压 flag、累计溢出
- 两站在制与产出 ⇒ 每站 排队数 / in_flight / pass / fail
- 节拍能否对账 ⇒ cycle_time / throughput / avg_wait (队列律 `L = λW`)
- 往哪插往哪放 ⇒ 上料/下料/废料/插孔/检测点 的世界坐标
- 躲什么 ⇒ 最近障碍相对向量 + 距离 + 通道最小净空
- 轨迹本身 ⇒ 已有 tcp_p 的, 补 `tcp_vel = diff(tcp_p)/dt`

## 二、扩维的铁律 (与 43→55 同一套)
1. **前 N 维一字不动**, 新增全在末尾, 零初始化 ⇒ 上线瞬间输出逐位相同 (用 `np.array_equal` 多组随机证明, 不是"看起来没变")。
2. **每通道四元定义**: 名字 / 单位 / 来源 / 判据, 缺一不许进表; `validate_layout()` 断言首尾相接、覆盖 0:M、无重名, 断档直接抛。
3. **消费端按名取**(`SLICE[name]` / `get(name)`), 不许任何调用点数下标。
4. **配置量不进状态向量**(如容量 capacity): 只参与派生, 另行传参。
5. **没有来源就 0, 并标"沉睡"** (`awake()/asleep()`): 0 表示"没有数", 不等于"物理量是零"。

## 三、`fuse()` 里必守的四个实现点 (每个都曾静默错)
- **每拍重置"有无来源"**: 开头 `self.filled = {f.name: False ...}`。不清空则上一拍的 awake 漏进这一拍,
  派生量随后算成 0 而无人报错。
- **派生量口径唯一**: `throughput = 3600/cycle_time`、`fill = count/capacity` 只在 fuse 里算一次;
  调用点各算各的 ⇒ 同一个量两个值, 对账时互相打脸。
- **通道名 fail-closed**: 未注册名字、维度不符一律抛错。静默补 0 = 编造数据。
- **能用真值就别开口子**: 有段表锚就装载, 有 `tcp_prev + dt` 就差分; 不要求调用方手填几何。

## 四、几何锚只从真源取
- 现场段表/任务表里通常已有标签化航点(`rows[].label` + `rows[].a`, 单位常是 **mm ⇒ /1000**)。
  写 `anchors_from_segment_table(path)`, 只认真实标签, 抽不到就返回 `missing` 列表。
- 锚必须能被**读回验证**: 例如 `insert_slot_xyz` 落在 `x[67:70]`, 断言 `allclose`。
- **槽位退化是数据缺陷, 不是代码问题**: 若不同槽的坐标完全相同(或两个盘共用同一锚点), 照实报"槽位表未区分,
  进度只能做全局"; 补标定表后再逐件避障。不许用默认坐标或平均坐标去凑。

## 五、验收 (真跑, 报数值)
`tools/verify_state100.py` 这类脚本要覆盖: 布局覆盖/四元定义齐全/新增维数正确/前 N 位零回归/`named` 重组成向量逐位相同/
锚装载与写入位置/派生量算式/队列律自洽且**给不自洽数据必须如实报 False**/未注册通道与维度不符全部抛错。
- 跑法: `PYTHONPATH=src ./gui-venv311/bin/python tools/verify_state100.py`。
  **不要 `python -m src.lerobot...`**: gui-venv 里没装 lerobot 包, `lerobot/__init__` 会 `ModuleNotFoundError`。
- 队列律 `|L − λW| > 0.5 件` 视为口径错(典型: throughput 用单件 CT 推, W 取自别的时间窗)。
- 汇报只给数值与失败项, 不说"通过"。

## 六、数据侧比口径更常是瓶颈
向量设计对了仍可能"数据不好也不够": 图像/遥测/episode 三条时间轴各自独立(常见 30Hz / 9Hz / 77Hz),
从没按时间戳配过对 ⇒ 拿不出逐帧 (观测, 真值)。先量三条流的时间跨度与采样率, 再谈训练。
