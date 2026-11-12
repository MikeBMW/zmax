# 全系统贯通: L5→L4→L3→L2 由后向前发理想值, 再验 300UPH

用户口径: 「按 L2/L3/L4/L5 由后向前, 让节点先发出理想值, 看是否达到 300UPH, 保证所有状态空间工程的节点都联通、有效」。

## 分层真源 (照画布 `row_bg`, 不改名)

`data/database/zmax/sources/canvas/state_space_obs.json` 的 `type=='row_bg'` 给出带与 y 区间, 节点按 (x,y) 落带:

| 层 | 带 id | 节点数 |
|---|---|---|
| L5 大模型层 | `ssbg5` | 14 |
| L4 专家自主 | `row_mem_l4` + `ssbg7` | 2 + 14 |
| L3 高级自动 | `row_mem_l3` + `ssbg_vlm` | 1 + 3 |
| L2 基础辅助 | `row_mem_l2` `ssbg0` `ssbg1` `ssbg2` `ssbg3` `ssbg_skill` `ssbg4` | 2+6+2+5+2+12+2 = 31 |
| 旁路 | `ssbg_data` / `ssbg8` 验证层 / `ssbg9` 可视化 | 6 / 1 / 7 |

id → 模块名: `src/lerobot/middleware/nodes/_index.py` (正则按 id 取模块)。

## 跑法 (本仓已落 `tools/fullstack_ideal_chain.py`)

1. **只跑 4 层, 由后向前**: L5 → L4 → L3 → L2; 每层内部按该层子图的连线做拓扑排序 (`links` 里两端都在本层的)。
2. **每层先发理想值** (只给语义, 不伪造传感器读数):
   - L5: `{task:'TASK-07-AOI', uph_target:300, cycle_s, tact_s, batch:4, deadline_s:12.0, craft_steps}`
   - L4: `{allow:true, v_max_mm_s:1000, a_max_mm_s2:4000, safety:'pass', world_model:'ideal'}`
   - L3: `{plan_n:112, plan_src:'geo_ideal', progress, batch:4}`
   - L2: 43 维理想观察量 (见下)
   注入规则: 该节点在本层**没有任何上游给出值**时, 才把理想值灌进它全部 `PORTS_IN` (否则用上游真实值)。
3. **判据三个, 分开报**: ①每层 `有效 = 端口真发出非空值` 的节点数 ②核心连线里"上游真发出值"的条数 ③UPH。
4. **UPH 用工艺动作表算, 不用理论峰值**: 循环 45.05s / 4 件 → 11.264 s/件 → 319.6 UPH, 门槛 12.000 s (300UPH) 余量 +0.736 s。
   同期须报「段表理论值 vs 真机实测」的差别, 不把模型值说成保证。

## 43D 理想观察量 (统一状态空间发理想值的口径)

通道划分与 `su2.py::obs43_geometry` **同一口径**, 单位 **米** (段表是 mm, 生成时 /1000):

```
[0:3] 手位置 · [3] 夹爪开度 · [4:7] 光模块位置 · [7:11] 光模块四元数(w,x,y,z)
[11:18] pad×7 (无读数就 0, 不造)
[18:36] 上一帧 18D (没有上一帧就填本帧前 18 维)
[36:39] 孔位/目标点 · [39] grasp · [40] contact · [41][42] 方向单位分量
```

几何误差 `e = (光模块头 − 孔位)` 由 `su2.obs43_geometry` 现算, 生成器不碰。
`SU2Element` 只有 `__slots__ = (w,x,y,z)`; 取群元素就报这四个标量 (`theta()` 是方法, `getattr(g,'theta')` 会拿到 method 并
`float()` 报 TypeError)。

## 判定数字 (本仓实测)

- 修 `非 dict 被吞` 之前: 65 个核心节点只有 6 个真发出值, "有效"却报 31/31 (端口壳子)。
- 修之后: L5 13/14 · L4 7/16 · L3 2/4 · L2 8/31 (共 30/65); 连线 171 条里 72 条上游真发出值。
- 剩下 35 个全是同一原因: `实现执行` 但输出空 —— 需要真帧 / 力信号 / 权重 (VLM 的 InterpolationMode ImportError、
  流形引擎 readout 未就绪)。**灌理想值也返回空, 不算有效**, 报告里逐条列"它缺什么"。
- 常驻循环与这套离线跑法不同: 重节点/外网节点不许进 10Hz 拍子, 见 `resident-daemon-debugging`
  「节点全打开后循环卡死」一节。
