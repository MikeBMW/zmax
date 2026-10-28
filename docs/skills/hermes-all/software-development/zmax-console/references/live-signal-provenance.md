# 实时监控(信号分析)页: 一个信号的唯一依据/topic/场景色 怎么定位

老倪常问形式: 「X 场景, 实时监控页面, <节点> 的输出 topic 是哪个?」——他问的是**页里那一行叫什么** +
**值从哪来**。答不了或答错方向 = 他不认。流程只有 5 步, 后两步最易漏。

## 5 步定位法
1. **画布唯一依据找节点**: `flows/state_space_obs.json` 里按 `name` 找节点 → 取 `id` 与
   `params.source` / `source_symbol` (唯一依据函数)。例: 「🧭 动作调制器」= id `sssched`,
   `src/lerobot/policies/left_right/state_space/cognition.py :: def decide`。
   (画布节点只有 `out1` 这类端口名, 端口名**不是**页里的信号名, 别照抄。)
2. **信号名 = 写入者代码里的键名**: `grep -rn '<键名>' --include='*.py' tools/ src/` 找写它的那一行。
   例: `动作调制_mps` 只在 `tools/gui/ss_dreamview.py` 的 3D 面板逐帧导出里写 ⇒ 它属于 3D 回放路。
   ⚠ 排除代码库 changelog 注释行的假命中 (`studio.py` 里的 `# v5.x` 长注释会淹没 grep)。
3. **页里显示名 = 数据源前缀 + 键名** (`tools/gui/canoe_graphic.py` 的 `HOST_SOURCES`):
   `sstrace.` = `zmax_data/ss_live/trace_live.json`(状态空间实况) · `ar.` = `zmax_data/ar_live/*`
   (AR/AOI, 单一写入器 `tools/ar_aoi_bus.py`) · `ds.` = 全局数据空间总线 · 真机 = Orin ROS2 采样器。
4. **场景色**: `config/topics/scene_tags.json` 的 `signals`。`tools/sig_scene_tags.py --tag <名>` 是**只读**
   (只打印解析结果), 要新增/改写只能编辑 `overrides`(优先级最高) 再 `--build --from-runs`。
5. **报答案必须带唯一依据文件 + 帧龄**, 并说清是哪条路 (见下)。只报信号名不算答完。

## 两条路不可混 (报「实时值」前先确认来源)
- **3D 回放路** `zmax_data/ss_live/trace_live.json`: 由 3D 面板/回放导出 (`ss_dreamview.publish_trace_live`,
  10Hz 节流) —— **只有播放/回放 3D 场景时才刷新**, 不播放时可能是几十分钟前的快照 (页里有帧龄列)。
- **常驻引擎回路** `zmax_data/ss_live/engine_latest.json`(`--hz 10`; 挂 VLM+管线后实测 5~8Hz) 的
  `action`/`action_norm` + `torque_live.json`(驱动扭矩张量)。
- 两条都答一次, 并明确「这条是回放、那条是常驻」; 把回放旧值说成常驻实时值 = 被当场戳穿。

## trace_live.json 是摆盘/插拔共写的唯一快照 ⇒ 共用量会被留白
- 两个 3D 面板 (SS-TRAY-PLACE 摆盘 / SS-EPI-CORNER 插拔) 都写这一个文件, 载荷带 `scene` 字段 +
  「另一场景快照 <3s 新鲜时不抢写」防串台规则 (防的是一次实测的事故: 摆盘帧数被插拔那路覆盖)。
- 因此 `末端_x` · `动作调制_mps` · `安全边界_mps` 这类两场景**共用的量, 打标工具按设计留白**(未分类=白),
  **不是漏做**。要它绿: 写进 `overrides` 钉场景 (与已有 `ins_depth_m` 同一机制) 后 `--build --from-runs`,
  并在交付说明里如实讲「该量在另一场景同样出现」。
- 场景唯一依据只有三条: 插拔场景(绿 #2e8b57, SCN-01-FW) · 摆盘场景(蓝 #1f6feb, SCN-06-TRAY) ·
  AR场景(紫 #8957e5, SCN-07-AOI); `config/topics/` 是**符号链接**(不在代码库内), 改了不出现在 `git status`。

## 已核实的一条样例 (口径要对齐)
动作调制器输出 = 页里 `sstrace.动作调制_mps` (= ‖u_fuse_vec[:3]‖, m/s); 上下游同名口径:
`前馈速度_mps` = u_ff(前馈加速器) → **`动作调制_mps` = u_fuse(动作调制器, 前馈+反馈相加后按阶段限速)** →
`安全边界_mps` = u_limit(安全执行边界饱和限幅后)。3D 画面同一帧也打「动作调制器 x.xxx m/s」⇒ 页与 3D 同源同值。
常驻路的对应出口是 `zmax/ss_engine` 的 `action`(4 维) / `action_norm`。

> 插拔场景空间智能链本身的接线(渲染图→VLM、多层管线、元任务台账、判据)见
> `manifold-engine-energy` 技能的 `references/fw-chain-integration.md`。
