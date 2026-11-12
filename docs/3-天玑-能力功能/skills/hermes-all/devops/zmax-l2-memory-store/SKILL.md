---
name: zmax-l2-memory-store
description: Use when 要把 L2 技能定义/接口/点位/工艺卡/标杆收成单一记忆库, 或要出 L2 逐节点页与节拍测试报告。
version: 1.0.0
author: hermes-agent
license: proprietary
metadata:
  hermes:
    tags: [zmax, l2, memory, pptx, uph]
---

# L2 记忆库 (两层库 + 只读查询) + 逐节点页/节拍报告

## When to Use
- 老倪说「技能定义/接口放技能库, 点位/工艺卡放操作库, 其它节点只查询」。
- 要给方案册加「每个 L2 节点一页」「节拍测试报告, 保证 300 UPH」。
- 「L2 能独立运行吗 / 能达到 300 UPH 吗」需要给数字而不是表态。

## 记忆 → 技能 赋能连线 (画布三步, 缺一就是假接线)

1. **画布真源** `src/lerobot/engineering/flows/state_space_obs.json` (画布读写的就是它): 给记忆节点补 `inputs/outputs` 声明
   (没有声明 = 线没锚点, 画布上看着"没连线"), 再给目标技能节点加输入口 (如 `in3`), 最后加 links (`f_port`/`t_port` 必填)。
2. **壳文件** `src/lerobot/middleware/nodes/n_*.py` 的 `PORTS_IN` 要同步加口 (否则实现拿不到 ctx["in3"])。
3. **总线重建** `tools/mw_db.py sync` —— 不加这步, 节点端口有了、话题表里没有, 下游永远收不到;
   验法: `mw_topic` 表里逐口存在 `ss.node.<node>.<port>` (实测 228 连线 → 312 话题)。

落地口径 (2026-11-02): `ss_mem_l2.out1 → sssk1..8.in3`, 技能侧在**基类** `corridor_finish()` 收口时叠加记忆额度
(`mem_limits()` → corridors 代表条目, `ZMAX_MEM_EN=0` 可 A/B), 节点 `out1.mem` 带 key/r/L/节拍/标杆命中。
不要在每个子类的 `clamp()` 里各写一遍——`atomic_skills.py` 里 8 个技能各有一份 clamp 副本, 改一份等于只给一个技能开了闸。

## 库的骨架 (data/memory/l2_store/)

| 文件 | 存什么 | 写者 |
|---|---|---|
| skills.json | 技能点定义 + 功能接口 (ros/参数 schema/前置/判据/步骤) | n_l2_muscle |
| ops_cards / ops_points / ops_seq | 工艺卡 (按工单号 key, 场景号回落)、示教点位、段序列+节拍口径 | ss_mem_l2 |
| champs.json | 固化标杆 (seed\|stage → champ_u/champ_x) | ss_mem_l2 |
| ledger.json | 实测台账快照 (n/mean_t/plan_t) | ss_mem_l2 |
| traj.json | 理想轨迹 (sim_champ/taught/spline/demo_file, 带 executable 标志) | ss_mem_l2 |
| index.json | 各库 sha 指纹 + 计数 + 构建时间 | 自动 |
| corridors.json | 约束通道: 键 `起点->终点\|阶段` (槽1->孔2\|转移), r/L/s_tick/v_along/tact/axis + kind=real\|geom | ss_mem_l2 |

### corridors 库 (2026-11-02 加): 工艺点级通道
- 建法: `tools/l2_mem_build.py::collect_corridors()` — 真源 = `zmax_data/ss_live/skill_corridors.json` 的实跑机动折线 + `config/points/cell_points.json` 几何。
- 键 = 起点工艺点->终点工艺点|阶段。**阶段名不能决定点位** (实测: 对位/插入/完成 在孔上, 接近/下降/抓取 在槽上, 转移 是槽→孔)。
  早期按'阶段→固定点位'归组 ⇒ 抓取系 5 段全落进孔, end_err 62~222 mm 全错。
- 两级标注: `kind=real` (该组合有实跑机动, 轴=真实折线, end_err≈0) / `kind=geom` (无实跑, 轴=点位几何+同形段中位 z 偏置)。
  汇报时必须分开报数, 不许把 geom 说成实测。
| corridors.json | 约束通道: 键 `起点->终点\|阶段` (槽1->孔2\|转移), r/L/s_tick/v_along/tact/axis + kind=real\|geom | ss_mem_l2 |

### 桶键的粒度上限 (2026-11-02 实测, 别再试)
- `champs.json` 的 `champ_x/io` 是**归一化/相对量** (io.entry≈[0.005,0.601,0.195]), 既不是 base_link m 也不是 sim_base mm, 也不带点名 ⇒ **无法**定位到槽/孔。
  桶键只能停在 `场景|阶段` (28 桶); 要工艺点级必须用 `traj REAL:*` 的点名或 `corridors`。已给每桶标 `frame` / `points_ref=None` / `why_no_points`。
- `traj.json` 的 taught 条目已回真源算时序: `timing_src` = `t_demo_s` / `dwell_s` / `none`, 带 `dt` / `dt_list` / `duration_s` / `point_names` / `timed`。
  没有时间戳的条目 `timed=False` —— 只能说"逐点 move_line, 节拍由执行器定", 不能说"可复现节拍"。
  dwell 里的人工停顿 (如 home 200.84s) 必须先滤 >60s 再取中位数, 否则 dt 被拉爆。
- 认点用**水平距离 ≤25 mm** 就近匹配槽位/孔口/孔底 (悬停高度差不算另一个点; 用 3D 距离会把 240 mm 悬停点判成'无此点')。

- 读: `from lerobot.memory.l2_store import query, stats`；写: `put_*` 只接受 writer="n_l2_muscle"/"ss_mem_l2"，其它抛 PermissionError。
- 建库/刷新: `tools/l2_mem_build.py`（回真源现算、旧库自动备份、标杆三份收敛成一份）；自检 `tools/l2_mem_verify.py`。
- 每条 entry 必带 `src` + `sha` + `at`，自检按真源 sha 对账，改真源不重建就会报过期。

## 场景位置细胞库 (place_cells · 2026-11-09 · 「与大脑神经元的位置细胞同样作用」)

坐标不许散在各处各说各话: 工装几何在 `zmax_data/ar_rs/fences.json`(51 box), 示教位姿在
`data/skills/l2_atomic/taught_points.json`(69), 空间点在 `space_points.json`(8), AOI 活在 `ar_aoi_live.json`
(只有「末端」有全 xyz), 结构件只在 `tools/web/tcp-ar.html` 的 `CHS/TAB/FLR/TCAM` 常量里。

汇总成一张表 + 一个构建器 + 一个运行时:

- 库 `data/skills/l2_atomic/place_cells.json`(133 枚/14 类; 与 taught/space 同目录, 该目录被 `.gitignore` 的 `data/` 排除 ⇒ 数据不入库)
- `tools/scene_places_build.py` —— 从 5 个测量真源汇总, **禁止手改库**; `--check` 报 id 变化与位移(漂移闸)
- `tools/scene_place_cells.py` —— `fire(p)` 高斯场群体发放 / `contains(p)` 盒体归属 / `anchor(p)` 一次给出
  料盘+槽号+该槽抓取位姿+插孔距离 / `selftest` 12 条硬判据

单位口径: 入库一律 base_link **mm**(真源是米, 构建器换算); 细胞带 `prov{src,key,precision,measured_at}`,
precision 必须是 measured / measured_tcp / design 之一 —— 设计值冒充实测是最容易被抓的一类假。

**三个用血换来的口径**
1. 「号位」≠「槽」: 号位是抓取位姿, 比槽几何中心偏 ≈[+156, +2, −8]mm(夹爪进给方向)。7 个号位偏移
   一致性 ≤3.8mm 才判示教可信; 把两者混为一谈会得出「坐标偏了 159mm」的假结论。
2. 只有**右盘 1~7 号位**有抓取位姿; 左盘/下盘/废料盘零示教 ⇒ `grasp_pose_for()` 必须返回 None。
   曾用「同名 slotN」兜底, 把「下槽3」答成右盘 slot3(错 200mm) ⇒ 自检里必须有这条**负控**。
3. id 一物一 id, 构建时 `assert` 去重: 演示点与几何中心同名(槽1 vs 号位 slot1)会静默互相覆盖,
   于是「号位-槽偏移」全变 0、看着完美其实一条都没算。

缺口要写进库的 `gaps` 而不是藏着: 槽8~14 无号位 · 左/下盘零示教 · AOI 活数据 10 个点名只有 .x ·
箱体/桌/地面只有设计尺寸。

**入口已上 8797(2026-11-09 r91)**: `GET /api/place_cells`(热读磁盘 · `?stats=1` 摘要 · `?kind=slot` 过滤 ·
`?q=516,347,109&k=3` 查高斯发放), 页面左栏「🧭 位置细胞」层直接画库(实测 133 枚/盒 53+点 25)。
重启口径: `bash tools/restart_traj_ar.sh`(systemd `zmax-traj-ar`; SIGTERM 收不掉时脚本自己 SIGKILL,
实测 1s 停 3s 起) —— 别手 kill, 也别用 `pkill -f tcp_ar_server`(会杀到自己)。

## 接线 (其它节点只查询)
- 记忆节点 PURE=False → True 才会真算；`n_l2_muscle` 未注册实现 ⇒ 直接 import l2_store，别指望 registry。
- 消费方示例: `exec/daemon.py::_load_points()` 库优先老库补缺；`l2_ros2_bridge.py --skill <id>` / `--traj <id>` 按 id 取。

## 节拍口径 (回答 300 UPH 用这一套)
- `tools/l2_uph_measure.py`: ① `cap=l2` 独立跑七段 (done/steps/快通道帧) ② 节拍两口径 —— 计划=段表 t 求和, 实测=段表 t × (台账 mean_t ÷ 段表同类平均计划 t) ③ 按段类归因增量。
- 页面与自检都调 `compute()`, 不许各写一套；**台账是活数据, 建页时 put_ledger 冻结快照**, 否则「值变了文案没变」。
- 结论必须分开说: 计划口径达标 ≠ 实测口径达标; 不达标就点名 move/up/down/pull 的倍率与保 300 的判据 (实测回落到计划 ×1.15 以内)。

## 方案册逐节点页
- `tools/l2_chain_pages.py::add_block(pr)`, 由 `build_solution_deck.py` 在 reorder 之后调用; 插在验收页之前。
- 顺序: 画布有反馈回路 ⇒ 先 Tarjan 压缩 SCC, 再按「离源头最远」排; 第 1 页 = 最后输出端 (物理世界), 逐级往前。
- 每页版式 (老倪定稿): **标题一行 + desc 压到一行(≤70 字) + 输入输出块图 + 页脚两行 (实现/参数/链路位置)**；禁止整段 desc 文本。
  块图三列: 上游方块列 → 左母线 → 本节点方块 ← 右母线 → 下游方块列；方块两行 = `端口 名字` + 连线 label。
  连线用 `add_connector(MSO_CONNECTOR.STRAIGHT)` + lxml 塞 `a:tailEnd type=triangle` (python-pptx 无箭头 API)；每侧最多 8 块，多出折成「… 另 N 条」。
  首行字数 >18/>24 时缩字号 0.86/0.74，**不截断节点名** (自检按名字逐字核对)。
- 带 `params.ar_real_sw` 的节点 (只有机器人执行器 ssact) 在块图下方多一条**开关带**: AR 场景 / 真机 两个拨杆 (胶囊+白钮: 开=绿钮在右 / 关=灰钮在左)[0.5,5.5,0.5]状态**不手填**, 读 `zmax_data/ss_live/exec_switches.json` (ar_scene / real_auth, 5 分钟内算新鲜) 并标状态时间+刷新龄；带开关页把块图区压到 y≤4.55、开关带 4.66-6.02、页脚降到 6.12。
- 自检 (`verify_solution_deck.py`) 要求页内保留原句式 `输入（N 条连线 · 端口 ← 上游）` / `输出（M 条连线 · 端口 → 下游）`，改版式时同步改正则，否则静默 FAIL。
- 自检 (`verify_solution_deck.py`): 页数、逐节点页数、第 1 页是末端、**每页输入输出条数 vs 画布连线**、节拍页数字回 compute() 现算。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 标杆三份分叉 | 引擎读 src/data/、节点读 data/memory/ (空壳)、另一份 data/ 有 28 桶 ⇒ 节点报 n_skills=0 | 建库时取并集并同步回两份老文件 (备份 .bak) |
| 台账 live 漂移 | 页面 18.5 / 自检 24.0, 两边都对 | 冻结进 ledger.json, 双方都读库 |
| 按关键词找验收页 | 总览里也写「验收口径」⇒ 新页插到封面后 | 取最后一页; 节拍页用 `startswith` 匹配标题 |
| `git add data/...` | 报 ignored (data/ 被忽略) 但文件其实是 tracked | 改 `git add -u <path>` |
| 采集类数据入库 | 大文件/PPT 不进 git | 拷 `zmax_data/deliverables/归档_<date>/` |
| 重建时 PPT 正在 Impress 里开着 | 目录出现 `.~lock.<名>#`，用户看到的还是旧版 | 重出前提醒关窗；已覆盖就让他关掉重开，**别自己 kill GUI** |
| 块图文字溢出 | 长节点名撑成三行或压到下一块 | 建页脚本按字数缩字号；建完跑全页形状越界 + 单行字数自检 |
