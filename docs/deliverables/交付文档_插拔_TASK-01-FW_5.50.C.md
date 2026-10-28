# 插拔作业 交付文档 · TASK-01-FW · 5.50.C

> 本文件由配置模板同源渲染 (唯一依据: 配置单 / 功能 topic 实测 / 验收报告 / 工程库), **数字不手写**。
> 场景: 插拔场景 · 站点: SITE-A.ST11 · 场景号: SCN-01-FW · 生成: 2026-10-13 14:59:38

## 一、目标与达成情况 (硬指标: 成功率 99% · 节拍 3.5s)

| 指标 | 目标 | 本次实测 | 判定 |
|---|---|---|---|
| 插入到位残差 | <2 mm (链内 `_insert_depth()<0.002m`) | 0.4532 mm | 达标 |
| 插入行程 (配置) | ins.depth | 35.0 mm | — |
| episode 时长 | — | 10.43 s (835 步) | 任务唯一依据未定义节拍目标 |
| 终态 / success | 完成 | `阶段 完成` · True | 达标 |

**明确目标**: 成功率 **≥99%** · 节拍 **≤3.15s (硬上限 3.5s)**。达成路径见 §五。

## 二、工程配置 (场景切换 · 空间点位 · 位置/角度 · 性能指标目标)

### 2.1 场景切换

| 任务 | 场景 | 场景号 | 颜色 |
|---|---|---|---|
| TASK-01-FW | 插拔场景 | SCN-01-FW | `#2e8b57` 插拔场景(绿) |
| TASK-06-TRAY | 摆盘场景 | SCN-06-TRAY | `#1f6feb` 摆盘场景(蓝) |
| TASK-07-AOI | AR场景 | SCN-07-AOI | `#8957e5` AR场景(紫) |

当前活跃任务: `TASK-06-TRAY` (唯一依据 `config/ss_task_binding.json`) · 切换器 `tools/ss_scene_switch.py`

### 2.2 空间点位 / 位置 / 角度

| 台账 | 文件 | 条数 | sha256(16) | 时间 |
|---|---|---|---|---|
| 示教点位(号位) | `data/skills/l2_atomic/taught_points.json` | 61 | `f88ac8cbde358466` | 2026-10-13 10:38:54 |
| 空间点 1..8 | `data/skills/l2_atomic/space_points.json` | 8 | `a8098b0e7a110a02` | 2026-10-12 14:02:11 |
| AOI 示教点 | `reports/aoi_points/` | 10 | `—` | 2026-10-13 10:38:54 |

标定唯一依据: `config/calib/zmax_calib.json` sha `9e4edc6f5b87f6a2`; `config/calib/zmax_manifold.json` sha `a56a3c3bf6a3988b`

站位几何: **未标定** `T_base_cam`, `plane_z`, `cell_geometry.points` ⇒ 坐标类参数标「不可信」

### 2.3 性能指标目标 (任务级)

| 目标项 | 值 |
|---|---|
| 合格率 | ≥99% |

工程配置模板: 画布工程 `状态空间工程 · 主工程` · 文件 `flows/state_space_obs.json` · 节点 89 / 连线 184 · md5 `b02ddc7c16d916c25c41e06867b09293` · 本场景启用节点 **51**

## 三、任务配置 (调用不同的工艺技能)

| 项 | 值 |
|---|---|
| 任务 | `TASK-01-FW` FW Loading + EEPROM 写/读校验 |
| 配方 | 插拔+固件校验 |
| 触发 | 来料盒就位 / 上游工位放行信号 |
| 循环 | 单件循环; 连续 2 次抓取失败停机 |
| 安全 | 继承站点 Sys-0 (急停/力阈值 Fz>5N/关节限位±3rad/光幕) — 任务不可覆盖 |
| 适用段 | 0 料源与来料状态 / 1 取件 / 2 姿态准备 / 3 识别与工位对接 / 4 放置/插入 / 5 拔出/取回 / 6 分拣与回位 / 7 节拍与循环 |
| 不适用段 | — |
| 工单规则 | 1 批 = 1 工单; 1 件 = 1 条记录 |

### 3.1 工艺步骤 (任务调用的工艺技能序列)

| t(s) | 时长(s) | 技能 | 说明 |
|---|---|---|---|
| 0.0 | 0.6 | **取料** | 左臂从归位移动到吸塑盒上方(X=2.5,Y=-0.4,Z=1.3), 夹爪闭合(力控1~5N)抓取光模块 |
| 0.6 | 1.0 | **扫码** | 右臂携带模块移至扫码枪前(X=2.1,Y=0.4,Z=1.35), 红色十字激光扫描SN二维码 |
| 1.6 | 0.8 | **翻转** | 腕部旋转180°(150°/s), 模块标签面朝下, 金手指面朝上 |
| 2.4 | 0.5 | **对位** | 视觉定位QSFP插座导向槽, 末端移动到(X=2.5,Y=0,Z=1.26), 偏差<0.1mm |
| 2.9 | 0.7 | **插入** | 沿导向槽直推35mm, 力控≤2N, 弹簧卡扣锁紧 |
| 3.6 | 50.0 | **异步测试** | PC自动下载固件→校验EEPROM→显示PASS/FAIL; R MPV可转向机台B |
| 53.6 | 0.8 | **拔出** | 夹爪夹持模块, 力控拉出≤2N, 脱离QSFP插座 |
| 54.4 | 3.0 | **AOI飞拍** | 金手指正反2面飞拍(0.5s×2)+4侧面飞拍(0.5s×4)=3.0s, 速度0.6m/s |
| 57.4 | 0.8 | **分拣** | PASS→绿色料盘(Y=0.35), FAIL→红色料盘(Y=-0.35), 行程0.4m·速度1.0m/s |

### 3.2 参数覆盖 (任务 → 能力参数, 可测量)

| 参数 | 值 | 归属能力 |
|---|---|---|
| `ins.depth` | 35.0 | — |
| `ins.force_ctrl` | Fz>1kHz, 力峰≤5N | — |
| `ins.retry` | 1 | — |
| `pull.wait_hmi` | True | — |
| `pick.close_force` | 3.0 | — |
| `sort.rule` | AOI 各站失败累计→NG | — |

档位 (运行开关): ⚡引擎快演=关 · 🚀 L3 全链(插拔+AOI)=开 · 🧠 流形 yaw 执行=开 · 🤖 L4 用 INTACT 节点执行=开 · 🎯 L4 意图 → DiT 精炼=开 · 🧩 L2 兼容 (前馈 MLP + YOLO)=开

## 四、功能清单 (每个功能: 详细描述 · 输入 topic · 输出 topic · 性能指标)

> 功能 = 能力库(BO_) + 本场景启用的画布节点。**性能指标是功能属性, 不同功能可指向同一指标** (可测量)。

### 4.1 能力层 (31 项能力字典) — 本场景覆盖

| 能力 | 域 | 方向 | 详细功能描述 | 输入 topic | 输出 topic | 性能指标 (可测量) | 本场景 |
|---|---|---|---|---|---|---|---|
| **A1 自主导航流转** | A | IN/OUT | 跨工位自主移动, 移动即工位；移动指令接口：输入目标工位与环境信息, 输出移动指令与到位状态。第三方导航方案按接口输出移动能力即可接入。 | `ss/ss2d3d/out`, `ss/ssaoi/out` | `ss/sssensor/out` | 跨工位流转成功率 ≥97% | **调用** (1 节点) |
| **A2 工位精准对接** | A | OUT | 到位定位, 对接精度 ±10mm 级；对接指令接口：输入对接目标, 输出对接位姿与完成确认。 | `ss/n_board_frame/out`, `ss/n_dsvl/out` | `ss/n_board_frame/out`, `ss/ss2d3d/out` | 对接精度 ±10mm | **调用** (1 节点) |
| **A3 举升高度调节** | A | OUT/CFG | 垂直举升 0~800mm, 覆盖多层工位；举升指令接口：输入目标高度, 输出举升指令与到位确认；高度参数可现场配置。 | `ss/n_board_frame/out`, `ss/n_intent_direct/out` | `ss/sssched/out` | 0~800mm 覆盖多层工位 | **调用** (1 节点) |
| **A4 双形态作业** | A | CFG | 固定式/移动式按需切换；形态配置接口：输入形态指令, 输出切换完成状态。 | 形态指令 (固定/移动) + 当前形态状态 | 切换完成状态 (支脚/驱动状态) | 切换 <30s | 未调用 |
| **B1 目标识别定位** | B | IN | 识别工件/孔位/托盘/料盒并给出位置；输入观测接口 (IN)：输入现场图像, 输出目标类别与位置清单。感知类模型按接口提供识别结果即可复用下游流程。 | `ss/n_board_frame/out`, `ss/ss_l5/out` | `ss/ss2d3d/out`, `ss/ssyolo/out` | 型号规格识别 100% (POC ≥98%) · 换型 ≤30min · 新型号配置/学习 ≤3h | **调用** (1 节点) |
| **B2 空间位姿感知** | B | IN | 感知目标三维位置与朝向；输入观测接口 (IN)：在识别结果上扩展空间信息, 输出目标三维位姿。 | `ss/n_board_frame/out`, `ss/n_dsvl/out` | `ss/n_board_frame/out`, `ss/ss2d3d/out` | 型号规格识别 100% (POC ≥98%) · 换型 ≤30min · 新型号配置/学习 ≤3h; 空/满/异常三态判定 100% (POC ≥98%) · 单次判定 ≤500ms · 异常态拒送并告警 | **调用** (2 节点) |
| **B3 触感感知** | B | IN | 感知接触状态与力度大小；输入观测接口 (IN)：输入触觉信号, 输出接触状态与力度。 | 触觉原始信号 (力/力矩分量, 多通道)；采样时间戳 | 接触状态 · 力度 (大小/方向) · 力度变化率 | 见 §4.2 节点指标 | 未调用 |
| **B4 自身状态感知** | B | IN/CFG | 感知关节/末端/基座状态；输入观测接口 (IN) + 参数配置接口 (CFG)：状态维度可配置, 适配不同模型。 | 关节编码 · 运动学参数 · 基座定位信息 | 关节状态 · 末端状态 · 基座状态 (按配置组装) | 见 §4.2 节点指标 | 未调用 |
| **B5 光学质量检测** | B | IN/MON | 检测金手指划痕/端面脏污/外观缺陷；输入观测接口 (IN) + 监控上报接口 (MON)：输入检测图像, 输出缺陷判定并上报。 | `ss/n_dsvl/out`, `ss/ss_l5/out` | `ss/n_board_frame/out`, `ss/ssaoi/out` | 外观缺陷检出率按 AOI 口径; 空/满/异常三态判定 100% (POC ≥98%) · 单次判定 ≤500ms · 异常态拒送并告警 | **调用** (2 节点) |
| **C1 完整作业执行** | C | OUT | 从看到做, 独立完成连贯作业；动作输出接口 (OUT)：输入现场观测, 输出完整动作序列。 | `ss/n_board_frame/out`, `ss/n_intent_direct/out` | `ss/n_l2_muscle/out`, `ss/ss_mem_l3/out` | 单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载具与产品损伤 0; 抓取成功率 ≥97%; 插入成功率 ≥99% · 头到孔底 <4mm; 自动重试 | **调用** (4 节点) |
| **C2 精细对位** | C | CFG/OUT | 亚毫米级对准, 末端 ±0.02mm 级；动作输出接口 (OUT) + 参数配置接口 (CFG)：对位目标与允许偏差可配置。 | `ss/n_board_frame/out`, `ss/n_dsvl/out` | `ss/n_board_frame/out`, `ss/ss2d3d/out` | 对位残差 ≤0.5mm · 重投影 rmse 合格 | **调用** (1 节点) |
| **C3 力控插拔保护** | C | OUT/MON | 插拔过程防损伤, 力控 ≤2N 级；动作输出接口 (OUT) + 监控上报接口 (MON)：输入力度反馈, 输出保护调整/停止, 上报保护事件。 | `ss/n_calib_mani/out`, `ss/ss2d3d/out` | `ss/ssmani_c/out`, `ss/sssk7/out` | 插拔力上限可配 · 超限即退 (MON) | **调用** (1 节点) |
| **C4 灵活翻转取放** | C | OUT | 翻转 180° 级姿态调整与取放；动作输出接口 (OUT)：输入目标姿态, 输出翻转/取放动作。 | `ss/ss_lora_l3/out`, `ss/ss_mem_share/out` | `ss/n_l2_muscle/out`, `ss/ss_mem_l3/out` | 单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载具与产品损伤 0; 抓取成功率 ≥97% | **调用** (2 节点) |
| **C5 双臂协同作业** | C | OUT | 同步/协同/接力三种协同模式；动作输出接口 (OUT)：输入协同任务, 输出双臂协调动作。 | `ss/n_board_frame/out`, `ss/n_intent_direct/out` | `ss/sssched/out` | 双臂干涉检测 + 协同节拍 | **调用** (1 节点) |
| **C6 宏微复合作业** | C | OUT | 大行程快动 + 微调精细分工；动作输出接口 (OUT)：输入作业目标, 输出宏动与微调的分工指令。 | `ss/n_board_frame/out`, `ss/n_intent_direct/out` | `ss/sssched/out` | 宏动定位 + 微调收敛, 末端重复性 ≤0.05mm | **调用** (1 节点) |
| **D1 过程预判** | D | GUIDE | 预判后续过程走向, 提前引导；引导输出接口 (GUIDE)：输入当前过程观测, 输出预判结果 (下一状态/接触概率)。 | `ss/ssintact_dec/out` | `ss/n_intent_direct/out` | IntAct 稳态 101ms · 冷启 6.7s (常驻) | **调用** (1 节点) |
| **D2 运动规律建模** | D | OUT | 建立运动规律模型, 支撑分析预测；动作输出接口 (OUT)：输入历史过程数据, 输出运动规律模型 (可查询可预测)。 | `ss/ssintact_dec/out` | `ss/n_intent_direct/out` | IntAct 稳态 101ms · 冷启 6.7s (常驻) | **调用** (1 节点) |
| **D3 决策说明** | D | MON | 说明当前决策依据, 过程可查；监控上报接口 (MON)：输入当前观测与决策, 输出决策依据说明。 | 当前观测 (图像/状态/触感) + 当前决策 (动作/阶段指令) | 决策依据说明 (要点列表) + 决策置信度 + 关联观测引用 | 见 §4.2 节点指标 | 未调用 |
| **E1 车载数据采集** | E | TRAIN | 作业过程自动采集三类数据 (数据飞轮)；训练接入接口 (TRAIN)：输入作业过程, 输出结构化采集数据 (图像/轨迹/过程)。 | 作业过程 (检测图像/操作轨迹/SN工艺数据) | 结构化数据 (图像/轨迹/过程记录, 断点续传) | 见 §4.2 节点指标 | 未调用 |
| **E2 边学边练** | E | TRAIN | 现场作业中持续学习提升；训练接入接口 (TRAIN)：输入采集数据, 输出更新后的能力。 | `ss/ss_mem_share/out`, `ss/ssskill/out` | `ss/n_eng_mem/out`, `ss/n_l2_muscle/out` | 连续自主 ≥12 盘周转盘 (硬下限 ≥6) · 单日连续运行 ≥20h · 月 ≥28 天 · 寿命 ≥3 年; 采集→训练→部署闭环可无人值守 | **调用** (2 节点) |
| **E3 上岗考核** | E | EVAL | 正式作业前先经仿真考核；评估接入接口 (EVAL)：输入待考核模型, 输出考核成绩与结论。 | `ss/ssskill/out` | `ss/n_eng_mem/out`, `ss/n_l2_muscle/out` | 采集→训练→部署闭环可无人值守 | **调用** (1 节点) |
| **F1 本地实时作业** | F | DEPLOY | 机端本地实时完成作业 (70ms 级)；部署接入接口 (DEPLOY)：输入现场观测, 输出实时作业动作。 | `ss/ss_mem_share/out`, `ss/ssskill/out` | `ss/n_l2_muscle/out`, `ss/ss_mem_l3/out` | 自动重试 ≤3 次 · 断点续作成功率 ≥95% · 错误继续执行 0 (零容忍); 连续自主 ≥12 盘周转盘 (硬下限 ≥6) · 单日连续运行 ≥20h · 月 ≥28 天 · 寿命 ≥3 年 | **调用** (2 节点) |
| **F2 远程升级** | F | DEPLOY | 作业中可远程更新模型能力；部署接入接口 (DEPLOY)：输入新模型文件, 输出更新生效状态。 | 新模型文件 (标准格式) + 版本信息 | 更新生效状态 (成功/回退) + 当前版本号 | 见 §4.2 节点指标 | 未调用 |
| **F3 多车协同调度** | F | SCHED | 多机台多车任务分配与协同；调度接入接口 (SCHED)：输入任务队列与车状态, 输出车-任务分配。 | `ss/n_board_frame/out`, `ss/n_eng_mem/out` | `ss/n_web_agent/out`, `ss/ss_mem_share/out` | 多机台/多车协同, 场景编排 | **调用** (1 节点) |
| **G1 标准模型接入** | G | IN/OUT | 按统一接口接入任意模型；标准接入契约 (IN/OUT 为主, 全接口统一)：输入标准观测, 输出标准动作。 | 标准观测 (图像/状态/触感, 按契约组装) | 标准动作 (关节目标/夹爪/移动指令, 按契约下发) | 按 Manifest + 适配器接入, 能力契约不变 | 未调用 |
| **G2 运行状态上报** | G | MON | 作业状态与结果实时上报；监控上报接口 (MON)：输入运行数据, 输出上报表/告警。 | 运行数据 (状态/成功率/节拍/力值) | 上报记录 (指标时序) + 告警事件 (超阈值/异常) | 抬升闸放开仍须慢速+警报在先 · 听「要碰撞」立即全停 | 未调用 |
| **G3 事件自动通知** | G | MON | 关键事件自动通知相关人员；监控上报接口 (MON)：输入系统事件, 输出通知消息。 | 系统事件 (作业完成/异常/报告就绪, 含详情与时间戳) | 通知消息 (含附件链接) + 送达回执 | 按 Manifest + 适配器接入, 能力契约不变 | 未调用 |
| **G4 产线系统对接** | G | MON/CFG | 对接 PLC/MES/联锁信号；产线对接接口：输入产线信号, 输出联锁状态与生产数据 (Modbus/CAN/网络)。 | `ss/n_hil/out`, `ss/n_vlm_llm/out` | `ss/ssllm/out`, `ss/ssllm_in/out` | 短提示 + 小 JSON 输出, timeout ≥300s | **调用** (1 节点) |
| **H1 现场参数可调** | H | CFG | 作业参数现场直接调整；参数配置接口 (CFG)：输入调参指令, 输出生效参数与变更记录。 | `ss/ss2d3d/out` | `ss/sscalib/out` | 写 M 幂等 · 范围校验 · 回读确认 | **调用** (1 节点) |
| **H2 方案文档交付** | H | - | 一键生成方案与能力文档；交付接口 (文档输出)：系统数据自动汇编为交付文档。 | 系统数据 (方案画布/评估结果/指标统计, 自动汇总) | 交付文档 (方案/能力清单/报告) | 见 §4.2 节点指标 | 未调用 |
| **H3 远程查看** | H | MON | 手机/网页随时查看运行情况；监控上报接口 (MON)：运行状态经远程通道展示。 | 运行状态 (实时指标/作业画面/告警事件) | 远程展示页面 (网页/手机端, 实时刷新, 权限可配) | 见 §4.2 节点指标 | 未调用 |

### 4.2 本场景启用节点 (功能实现) — 输入/输出 topic 与性能指标

| 功能 (节点) | 层 | 详细功能描述 | 输入 topic | 输出 topic | 性能指标 (可测量) |
|---|---|---|---|---|---|
| **💪 L2 肌肉记忆技能库 (光模块抓放循环)** | L2 | L2 肌肉记忆: 对准→下降→夹紧(force40)→抬起; 由 L3 序列调用, 经 l2_ros2_bridge(ROS2) 转发 Orin | `ss/ssskill/out` | `ss/n_l2_muscle/out` | 单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载具与产品损伤 0; 连续自主 ≥12 盘周转盘 (硬下限 ≥6) · 单日连续运行 ≥20h · 月 ≥28 天 · 寿命 ≥3 年; 采集→训练→部署闭环可无人值守 |
| **📐 板坐标系定位 (工序坐标系·免手眼)** | - | 真机帧 → 板检测(20点/反色/排镜像) → 模块射线∩板平面 → 模块在板坐标(x,y)mm。绕开手拖位姿精度限制; 精度~1mm(图像决定)。 | `ss/n_dsvl/out`, `ss/ssyolo/out`, `ss/ssz700/out` | `ss/n_board_frame/out` | 对位残差 ≤0.5mm · 重投影 rmse 合格; 对接精度 ±10mm; 空/满/异常三态判定 100% (POC ≥98%) · 单次判定 ≤500ms · 异常态拒送并告警 |
| **🧿 DeepSeek-V4-Flash · 场景理解 (L5 大模型主路)** | - | [L5 大模型主路] DeepSeek-V4-Flash (API · 支持 Vision): 场景判读/工序纠错 → 结构化落 data/scene/scene_state.json, 喂 L3 规划/技能编排与 L4 意图解码; 本地保障 = smolvlm2-500m (HuggingFaceTB/SmolVLM2-500M, 权重在 ~/.cache | `ss/n_web_agent/out`, `ss/ssdata/out`, `ss/ssllm_in/out` | `ss/n_dsvl/out` | 见能力层 §4.1 |
| **📚 工程记忆 · 技能与经验库** | - | 工程记忆 = docs/memory/*.md (跨端同步记忆) + Hermes 记忆 (MEMORY/USER) + 技能库清单; 读真实文件 → 汇总条数/落盘时间 → 同步进 🧠总装记忆中枢 (顶层宏观记忆, macro_memory.uplink) | （源节点） | `ss/n_eng_mem/out` | 采集→训练→部署闭环可无人值守 |
| **🧠 意图丛 · 四槽语法** | - | goal/from/skill/gate — 层间只传意图 Δz=z_g−z_t, 动作只在 L2 生成 (INTACT 同构接口) | `ss/ssllm/out` | `ss/n_intent_bundle/out` | 见能力层 §4.1 |
| **🔮 意图直读 · Direct** | - | Δz → 技能最近邻, 无搜索 (参照 INTACT Direct 2.9–5.5ms) | `ss/ssintact_dec/out` | `ss/n_intent_direct/out` | IntAct 稳态 101ms · 冷启 6.7s (常驻) |
| **🔗 跨层连接 · 记忆图谱** | - | 层间链接 links (L4筹划→L3流程→L2技能) + 意图检索 recall (距离门防负迁移) | `ss/ss_mem_l2/out`, `ss/ss_mem_l3/out`, `ss/ss_mem_l4/out` | `ss/n_mem_links/out` | 见能力层 §4.1 |
| **👁 视觉语言大模型 · 场景理解 (Qwen2.5/3-VL)** | - | 大模型层**视觉通路** (2026-09-19 实测可用): 环境帧/引擎真图/真机帧 → 场景理解 JSON (目标/在不在夹爪/画面质量/光照/背景/标定建议) → 任务规划器·异常推理器·技能编排器·意图解码器·总装记忆。 默认走 **DeepSeek Vision (deepseek-flash / V4.1-Flash, 本机 ~/.hermes | `ss/n_dsvl/out` | `ss/n_vlm_llm/out` | 见能力层 §4.1 |
| **🌐 Web 智能体桥 · 远程提示词** | - | [L5 人机在环] web 上的 agent 用**自然语言提示词**远程调用状态空间的**只读功能**(状态/画布/报告/记忆/技能/仿真自检/网络/AOI 只读判决/真机只读信号/飞书通知), 并把执行结果回执到 web; 动作类提示词一律拒答 (老倪红线: 不动真机)。画布侧: 入=工程记忆能力清单, 出=提示词意图 → L5 场景理解(DeepSee | `ss/n_eng_mem/out` | `ss/n_web_agent/out` | 多机台/多车协同, 场景编排 |
| **📐 2D→3D 解算** | - | [基础·分段小模型] 感知层·B2 空间位姿感知: YOLO 2D框中心 + 相机反投影 → 目标 3D 坐标 → 增强 43D 状态向量 | `ss/n_board_frame/out`, `ss/ss_seg/out`, `ss/ssyolo/out` | `ss/ss2d3d/out` | 型号规格识别 100% (POC ≥98%) · 换型 ≤30min · 新型号配置/学习 ≤3h; 对位残差 ≤0.5mm · 重投影 rmse 合格; 对接精度 ±10mm |
| **🎛 L4 · INTACT LoRA 微调 (r8/α16) · 接入中** | - | [L4 微调] INTACT 本域 LoRA: 注入 112 层线性 (r=8/α=16), 从官方 pusht 权重初始化, 数据 optical_insert v6 真机示教; 产物必须 merge 后才可部署 (包装键→Missing key→trained=False 零动作); 现状: 200 步产物 A/B 未证明提升 → 不切在役指针; 202 | `ss/ss_l5/out`, `ss/ssz700/out` | `ss/ss_lora_l4/out` | 见能力层 §4.1 |
| **🧮 流形引擎 (Manifold Engine · 编码→投影→度量→导航→反馈)** | - | L4 核心内核: 把高维状态自动约束为低维流形, 在流形上做测地线导航/梯度流/有界反馈; 输出意图与动作建议 | `ss/n_calib_mani/out`, `ss/ss_moe/out`, `ss/sscalib/out` | `ss/ss_mani_eng/out` | 见能力层 §4.1 |
| **🧲 总装机记忆 · 势场联络 (L2/L3/L4 势场 → 意图 −∇Φ)** | - | [总装机记忆·势场联络] L2 肌肉记忆: 每条技能冠军轨迹→技能势场 Φ_SK (谷底=真跑末点 · σ=谷宽 · 触发/速度上限取技能库真值) · L3 工艺流程记忆: 按真实段时长(真跑帧数)加权组合→流程势场 Φ_process(x,t), 谷底随时序从 SK01 连续移到 SK07 · L4 物理工作空间记忆: Φ_process + 障碍场(孔壁 | `ss/ss_mem_l2/out`, `ss/ss_mem_l3/out`, `ss/ss_mem_l4/out` | `ss/ss_mem_field/out` | 见能力层 §4.1 |
| **🔧 L2 · 肌肉记忆操作 (小脑 · 标杆回放)** | - | 🔧 L2 · 肌肉记忆操作 (小脑 · 标杆回放) | `ss/n_skill_dict/out`, `ss/ss_mem_share/out` | `ss/ss_mem_l2/out` | 见能力层 §4.1 |
| **🚀 L3 · 长程序列规划 (记忆: 海马体)** | - | 🚀 L3 · 长程序列规划 (记忆: 海马体) | `ss/ss_mem_share/out` | `ss/ss_mem_l3/out` | 单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载具与产品损伤 0; 自动重试 ≤3 次 · 断点续作成功率 ≥95% · 错误继续执行 0 (零容忍); 连续自主 ≥12 盘周转盘 (硬下限 ≥6) · 单日连续运行 ≥20h  |
| **🏆 L4 · 工作安全 + 物理世界导航 (记忆: 前额叶)** | - | 🏆 L4 · 工作安全 + 物理世界导航 (记忆: 前额叶) | `ss/ss_mem_share/out` | `ss/ss_mem_l4/out` | 见能力层 §4.1 |
| **🧠 总装记忆中枢 (前额叶总装 · 三层协同)** | - | 🧠 总装记忆中枢 (前额叶总装 · 三层协同) | `ss/n_board_frame/out`, `ss/n_eng_mem/out`, `ss/n_mem_links/out` | `ss/ss_mem_share/out` | 多机台/多车协同, 场景编排 |
| **🔍 光学质量检测** | - | [基础·分段小模型] 感知层·B5 外观质量检测 (AOI): 金手指划痕/端面脏污/外观缺陷判定 → 上报监控 (良率支撑)。【2026-09-20 接线·v4.2 几何】原始图 → 状态空间区域检测/伺服引导: ①区域检测 GET /region?grab=1 = 原始图坐标系的**金手指区域**(只含焊盘排, 实测~1455x70; 不含下方实心金带与 | `ss/ssyolo/out` | `ss/ssaoi/out` | 外观缺陷检出率按 AOI 口径 |
| **📈 旁路实时可视化 (当前阶段/残差/接触概率)** | - | [可视化层·回路外] 旁路逐帧记录 → 当前阶段(13 段状态机)/残差(m)/接触概率 实时曲线, 500ms 刷新; 同窗显示六层调用数 · 零下行自证(rclpy/socket/写回) · 缺口计数 · 数据源新鲜度 | `ss/ssdata/out` | `ss/ssbypv/out` | 见能力层 §4.1 |
| **🧮 标定层 · 引力-斥力-动作** | - | [L4 标定·地图校准 回路外] 引力(快速动作标定: Kp+阶段限速) — 斥力(状态预测标定: 卡尔曼/接触/否决) — 动作(新: DiT action 输出标定量, 输入见 ssdec 连线); 潜空间域已独立至「🧮 潜空-流形」节点 (L4 流形输入); 源码 calibration_layer.py | `ss/ss2d3d/out` | `ss/sscalib/out` | 写 M 幂等 · 范围校验 · 回读确认 |
| **🧭 能力档位** | - | [数据源层·能力档位] 单击圆钮直选 / 双击循环: L2 基础(插装成功) → L3 +smolvla(插→拔→AOI→放回全链) → L4 +流形预测世界模型(失败自主恢复直到完成) → L5 大模型视觉语言自动标注(L2/L3/L4 监督数据) + 标注完成自动启动训练(L2 YOLO 全量 / L3 SmolVLA LoRA / L4 INTACT  | `ss/ssmode/out` | `ss/sscap/out` | 见能力层 §4.1 |
| **📦 metaworld 数据源** | - | [数据源层] 运行环境数据源: 仿真(metaworld 39D/4D 演示) ⇄ 真机(4060 远程只读订阅 Orin: TCP位姿+姿态/六关节/六维力/夹爪/机器人状态/图像) — 点节点上的「仿真/真机」拨钮或右键菜单切换; 双击=按当前模式运行真实模型 (🚀训练/📷推理) | （源节点） | `ss/ssdata/out` | 见能力层 §4.1 |
| **🎯 Flow-Matching Action Head (DiT)** | - | [高级·端到端模仿学习] Decoder: 状态空间 ActionHead — 潜空间 z → 4D 动作块 (StateSpaceActionHead); 源码 src/lerobot/policies/smolvla_lew/state_space_action_head.py | `ss/ssintact_dec/out`, `ss/sslat/out`, `ss/ssmani_c/out` | `ss/ssdec/out` | 单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载具与产品损伤 0 |
| **🧩 Feature 功能清单** | - | Feature 功能清单: 状态空间系统全部 feature 汇总 (A12/B13/C4/D3/E5/F4/G10/H6; 分级 L2 38/L4 11); 共 57 条自动/半自动断言 · 功能树 113 功能×562 用例 (22 节点); 新增: F-B12 3D视觉引导 / F-B13 触觉反馈闭环 (2026-09-24); 源码 verific | `ss/ss_mem_share/out`, `ss/ssworld/out` | `ss/ssfeat/out` | 见能力层 §4.1 |
| **🎯 INTACT (L4) · 工作安全 + 物理世界导航** | - | [L4 策略] INTACT (zju3dv/INTACT-JEPA, MIT) 意图-动作: 共享 local/goal 动作律 + 四槽语法 [z, m_t, z⊙m_t, A(a_{t-1})] → 一次前向直接出 action chunk (**零候选搜索**, 无 CEM); **数据源直接接入 metaworld** (MT1 peg-inser | `ss/ss_lora_l4/out`, `ss/sscap/out`, `ss/ssdata/out` | `ss/ssintact/out` | 见能力层 §4.1 |
| **🎯 INTACT 意图解码器 (L4 → L3 条件)** | - | [L4 → L3] INTACT 意图解码器 (src/lerobot/policies/intact/decoder.py): **两路输出**: ①→DiT 的 L3 条件 (未标定不注入) ②→流形专家预测器的意图 m_int (z_t 口径用; 活跃 z7 口径下当门控) · 把 INTACT 的意图/潜空间解码成 L3 能吃的条件 —— ① u_f | `ss/n_intent_bundle/out`, `ss/n_vlm_llm/out`, `ss/ss_mani_eng/out` | `ss/ssintact_dec/out` | 见能力层 §4.1 |
| **🧮 潜空-流形** | - | [L4 潜空间/世界模型流形标定] 潜空间=世界模型预测流形 (地图几何标定: 维度/类别/速度场 prior_A) + 轨迹观测 PCA 有效维实测; 输入: L4 流形(接触/性能) + 潜状态/先验预测; 源码 calibration_layer.py LATENT_CALIB | `ss/sscalib/out`, `ss/ssvlm/out` | `ss/sslat/out` | 见能力层 §4.1 |
| **🛡 安全执行边界 (饱和限幅)** | - | [基础·分段小模型] 安全执行边界: 饱和限幅 — 阶段切换与动作融合后输出物理指令 | `ss/sssched/out` | `ss/sslimit/out` | 见能力层 §4.1 |
| **🧠 L3 长程序列规划器 (场景理解驱动)** | - | 任务规划器 TaskPlanner: 指令/场景 → 技能Token序列 (242条原子技能库, 规则校验后) → 下发状态机 | `ss/n_hil/out`, `ss/n_vlm_llm/out`, `ss/ss_mem_share/out` | `ss/ssllm/out` | 短提示 + 小 JSON 输出, timeout ≥300s |
| **📝 任务指令 · MES/自然语言** | - | 大模型层·输入: MES 工单/自然语言指令 + **场景图通道** (in1 仿真 metaworld 渲染帧 / in2 引擎真图 / in3 真机帧与位姿) → 视觉大模型(SceneVLM: 本地 Qwen2.5-VL-3B 或 API) 场景理解 → 🧠任务规划器 (planner.py); 无模型时规则回退并如实标注 | `ss/ssdata/out`, `ss/ssz700/out` | `ss/ssllm_in/out` | 短提示 + 小 JSON 输出, timeout ≥300s |
| **🧮 接触流形 · 导航地图 (e∥进度/e⊥偏离)** | - | [专家·世界模型] 接触流形 ContactManifold: e=T−hand 沿通道轴分解 → 切向 e∥(测地线进度)+法向 e⊥(离流形漂移→弯曲风险), V=½‖e‖², V̇=−e·v; 通道: 垂直(z 对销)/孔轴(x 入孔); 源码 manifold_layer.py | `ss/n_calib_mani/out`, `ss/ss2d3d/out`, `ss/ss_mani_eng/out` | `ss/ssmani_c/out` | 插拔力上限可配 · 超限即退 (MON) |
| **🧠 流形专家预测器 (JEPA: 潜空间→流形→动作)** | - | [专家·世界模型 L4] **入线两条意图通道**: ①活跃口径 z7 = 引擎几何潜空间 R7 + 引擎几何意图 (target−peg_head), 来自 📐 2D→3D 解算; ②z_t 口径 = INTACT 潜空间 192 + 意图增量 m_int=δ(z_goal−z_t), 来自 🎯 INTACT 意图解码器 (该口径 LOSO R² 全负未启 | `ss/n_calib_mani/out`, `ss/ss2d3d/out`, `ss/ss_mani_eng/out` | `ss/ssmani_exp/out` | 见能力层 §4.1 |
| **🧮 性能流形 · 耦合代价 (V_p/η)** | - | [专家·世界模型] 性能流形 PerformanceManifold: δ=销头−孔底 → V_p=½δᵀWδ(横向重权), 估计耦合效率 η=exp(−V_p/σ²) (高斯光束近似), ∇V_p 最优对准方向; 真机接光功率计标定 W/σ; 源码 manifold_layer.py | `ss/ss2d3d/out`, `ss/ss_mani_eng/out`, `ss/ssmani_exp/out` | `ss/ssmani_p/out` | 见能力层 §4.1 |
| **🧭 动作调制器** | - | [基础·分段小模型] 动作调制器 (原状态机, 握有否决权): 6阶段状态机 + 否决权 + 按阶段动作融合 (力控插入) | `ss/n_board_frame/out`, `ss/n_intent_direct/out`, `ss/n_l2_muscle/out` | `ss/sssched/out` | 0~800mm 覆盖多层工位; 双臂干涉检测 + 协同节拍; 宏动定位 + 微调收敛, 末端重复性 ≤0.05mm; 插入成功率 ≥99% · 头到孔底 <4mm |
| **📡 融合定位建图** | - | [基础·分段小模型·建图] 📡 融合定位建图 = 视觉与触觉融合: 视觉(YOLO目标检测→2D→3D 坐标) + 触觉感知(4D 力/接触) + 外观质量 → 统一状态空间 (43D obs, 供 L2/L3/L4/L5 消费); 新增建图能力: 专用实现 src/lerobot/manifold/localization_mapping.py (ORB  | `ss/ss2d3d/out`, `ss/ssaoi/out`, `ss/ssdata/out` | `ss/sssensor/out` | 跨工位流转成功率 ≥97% |
| **② 对位 · SK02** | - | [基础·分段小模型] 原子技能 ② 对位 (SK02): 固定轨迹模板 — 决策层选定本技能时实时赋值 (阶段目标/速度), 复制模板实例化快速执行 → 输出执行指令给执行器 | `ss/sslimit/out`, `ss/ssskill/out` | `ss/sssk2/out` | 对位残差 ≤0.5mm · 重投影 rmse 合格 |
| **③ 下降 · SK03** | - | [基础·分段小模型] 原子技能 ③ 下降 (SK03): 固定轨迹模板 — 决策层选定本技能时实时赋值 (阶段目标/速度), 复制模板实例化快速执行 → 输出执行指令给执行器 | `ss/sslimit/out`, `ss/ssskill/out` | `ss/sssk3/out` | 见能力层 §4.1 |
| **④ 抓取 · SK04** | - | [基础·分段小模型] 原子技能 ④ 抓取 (SK04): 固定轨迹模板 — 决策层选定本技能时实时赋值 (阶段目标/速度), 复制模板实例化快速执行 → 输出执行指令给执行器 | `ss/sslimit/out`, `ss/ssskill/out` | `ss/sssk4/out` | 抓取成功率 ≥97% |
| **⑤ 抬起 · SK05** | - | [基础·分段小模型] 原子技能 ⑤ 抬起 (SK05): 固定轨迹模板 — 决策层选定本技能时实时赋值 (阶段目标/速度), 复制模板实例化快速执行 → 输出执行指令给执行器 | `ss/sslimit/out`, `ss/ssskill/out` | `ss/sssk5/out` | 见能力层 §4.1 |
| **⑥ 转移 · SK06** | - | [基础·分段小模型] 原子技能 ⑥ 转移 (SK06): 固定轨迹模板 — 决策层选定本技能时实时赋值 (阶段目标/速度), 复制模板实例化快速执行 → 输出执行指令给执行器 | `ss/sslimit/out`, `ss/ssskill/out` | `ss/sssk6/out` | 抓取成功率 ≥97% |
| **⑦ 插入 · SK07** | - | [基础·分段小模型] 原子技能 ⑦ 插入 (SK07): 固定轨迹模板 — 决策层选定本技能时实时赋值 (阶段目标/速度), 复制模板实例化快速执行 → 输出执行指令给执行器 | `ss/sslimit/out`, `ss/ssskill/out` | `ss/sssk7/out` | 插入成功率 ≥99% · 头到孔底 <4mm; 插拔力上限可配 · 超限即退 (MON) |
| **⑧ 完成 · SK08** | - | [基础·分段小模型] 原子技能 ⑧ 完成 (SK08): 固定轨迹模板 — 决策层选定本技能时实时赋值 (阶段目标/速度), 复制模板实例化快速执行 → 输出执行指令给执行器 | `ss/sslimit/out`, `ss/ssskill/out` | `ss/sssk8/out` | 抓取成功率 ≥97% |
| **🛠 L3 技能序列编排** | - | 技能编排器 SkillComposer: 五大作业场景定义 (steps→技能序列, performance→参数覆盖默认) / 新型号规格 → 技能序列+力阈值/节拍 | `ss/n_vlm_llm/out`, `ss/ssdata/out`, `ss/ssreason/out` | `ss/ssskill/out` | 见能力层 §4.1 |
| **🖐 触觉感知** | - | [基础·分段小模型] 夹爪开度+接触力 (metaworld 真值) → 4D 触觉 [grasp/contact/dir] | `ss/ssdata/out` | `ss/sstactile/out` | 外观缺陷检出率按 AOI 口径; 插拔力上限可配 · 超限即退 (MON) |
| **🧠 VLM 通用视觉编码器 (SmolVLA)** | - | [高级·端到端模仿学习] 高级·Encoder (SmolVLA): 真实 SmolVLM2 视觉编码 — 图像帧 → 潜空间 z R960 (encode_stage); 源码 src/lerobot/policies/smolvla_lew/vlm_encoder.py | `ss/ss_lora_l3/out`, `ss/ss_seg/out`, `ss/sscap/out` | `ss/ssvlm/out` | 单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载具与产品损伤 0 |
| **🎯 YOLO 目标检测** | - | [基础·分段小模型] 感知层·B1 目标识别定位: YOLO 检测光模块/插座/料盘/缺陷等 22 个目标 (类别/位姿/方向, 指标含 mAP/推理时间); 双击=目标清单, 右下角导出=Excel | `ss/ss_l5/out`, `ss/ssdata/out` | `ss/ssyolo/out` | 型号规格识别 100% (POC ≥98%) · 换型 ≤30min · 新型号配置/学习 ≤3h; 空/满/异常三态判定 100% (POC ≥98%) · 单次判定 ≤500ms · 异常态拒送并告警 |
| **🖥 Z700 真机信号 (全信号观测 · 物理世界输出)** | - | [可视化层·回路外] 输入 = 🌍物理世界输出。显示全部真机信号: TCP 位置+姿态四元数+坐标系 · 六关节位置/速度(含关节名) · 六维力/力矩 · 夹爪开度 · 触觉 4D · 机器人电源/运行/报警/急停/碰撞 · 产线阶段 · 采样率与新鲜度 · 缺通道清单; 附状态空间旁路当前阶段/残差/接触概率 | （源节点） | `ss/ssz700/out` | 见能力层 §4.1 |
| **🧪 光模块插拔 · 环境渲染图像源 (Z-MAX 引擎逐帧真图)** | - | [L4 数据源] Z-MAX 引擎逐帧渲染真图 (224×224 RGB, 来自 RealStateSpaceSim · metaworld peg-insert-side-v3 + MUJOCO_GL=egl 离屏渲染), 由 tools/intact_sw_optical_bridge.py 写 spool/*.jpg + status.json + s | `ss/ssdata/out`, `ss/ssyolo/out`, `ss/swworld/out` | `ss/swds/out` | 见能力层 §4.1 |
| **🎯 INTACT 插拔策略 · 光模块抓取插入 (本域微调 · 零搜索)** | - | [L4 中间策略] INTACT-JEPA 本域微调权重 (u 口径数据集 optical_insert_v4 训练, 从官方 pusht 权重初始化): 渲染图像+目标帧(解析链成功末帧)+动作历史 → 一次前向出动作块 (零候选搜索 candidate_action_steps=0) → 唯一变换=训练归一化逆运算 a_raw=z·std+mean →  | `ss/sscap/out`, `ss/ssintact/out`, `ss/swds/out` | `ss/swintact/out` | 见能力层 §4.1 |
| **🎬 插拔渲染视频 (从 Z-MAX 引擎取出 · 实况窗)** | - | [L4 可视化·回路外观察器] 从 Z-MAX 引擎取出的渲染视频 (480², 10fps): 模型直驱在环录像(打标真模型/真推理次数/模型输出/插入深度) + 同 seed 解析链对照 (插入 / 插→拔→AOI 全链) + 合集, 存 reports/intact_sw/video; 双击开互动查看器看任意帧信号 (不参与自动运行链) | `ss/swworld/out` | `ss/swvideo/out` | 见能力层 §4.1 |
| **🌍 Z-MAX 引擎 · 光模块插拔真物理 (模型动作真下发 env.step)** | - | [L4 硬件层] Z-MAX 六层引擎 RealStateSpaceSim (metaworld peg-insert-side-v3 真接触/夹持/插入动力学): 每步接收 INTACT 模型动作 → env.step 真下发 (引擎既有直驱入口 _direct_act, 不经解析控制器) → 逐帧渲染回数据源; 同 seed 另跑解析链对照(插入 + 插 | `ss/n_realscene/out`, `ss/ssworld/out`, `ss/swintact/out` | `ss/swworld/out` | 见能力层 §4.1 |

## 五、每个功能的 topic 输入/输出 **实际测试报告**

> 实测方式: 逐 topic **真 DDS 往返** (`zmax::SSTest` 载体, 发布/订阅**两个独立参与者**, 挂单播配置 `CYCLONEDDS_URI=dds/cyclonedds_unicast.xml`) + 注册 typed 话题按注册 QoS 只读订阅。
> 判据: 发出/收到 且 收到 ≥ 发出/2 ⇒ 通道 ✅; 收到 0 条 ⇒ 如实写 ❌ (不当「通过」)。

| 汇总 | 数 |
|---|---|
| 功能(画布节点)总数 | 74 |
| 节点输出通道往返 ✅ | **74 / 74** |
| 注册 typed 话题有流量 ✅ | **6 / 16** |

### 5.1 本场景启用功能 (51 个) 逐条实测

| 功能 (节点) | 输出 topic | 发出 | 收到 | 匹配 | 输出通道 | 输入 topic (上游) | 输入通道 |
|---|---|---|---|---|---|---|---|
| **💪 L2 肌肉记忆技能库 (光模块抓放循环)** | `ss/n_l2_muscle/out` | 65 | 65 | 1 | ✅ | `ss/ssskill/out` | ✅ 1/1 |
| **📐 板坐标系定位 (工序坐标系·免手眼)** | `ss/n_board_frame/out` | 65 | 65 | 1 | ✅ | `ss/n_dsvl/out`, `ss/ssyolo/out` | ✅ 3/3 |
| **🧿 DeepSeek-V4-Flash · 场景理解 (L5 大模型主路)** | `ss/n_dsvl/out` | 65 | 65 | 1 | ✅ | `ss/n_web_agent/out`, `ss/ssdata/out` | ✅ 3/3 |
| **📚 工程记忆 · 技能与经验库** | `ss/n_eng_mem/out` | 65 | 65 | 1 | ✅ | （源节点） | —(源) |
| **🧠 意图丛 · 四槽语法** | `ss/n_intent_bundle/out` | 65 | 65 | 1 | ✅ | `ss/ssllm/out` | ✅ 1/1 |
| **🔮 意图直读 · Direct** | `ss/n_intent_direct/out` | 65 | 65 | 1 | ✅ | `ss/ssintact_dec/out` | ✅ 1/1 |
| **🔗 跨层连接 · 记忆图谱** | `ss/n_mem_links/out` | 65 | 65 | 1 | ✅ | `ss/ss_mem_l2/out`, `ss/ss_mem_l3/out` | ✅ 3/3 |
| **👁 视觉语言大模型 · 场景理解 (Qwen2.5/3-VL)** | `ss/n_vlm_llm/out` | 65 | 65 | 1 | ✅ | `ss/n_dsvl/out` | ✅ 1/1 |
| **🌐 Web 智能体桥 · 远程提示词** | `ss/n_web_agent/out` | 65 | 65 | 1 | ✅ | `ss/n_eng_mem/out` | ✅ 1/1 |
| **📐 2D→3D 解算** | `ss/ss2d3d/out` | 65 | 65 | 1 | ✅ | `ss/n_board_frame/out`, `ss/ss_seg/out` | ✅ 3/3 |
| **🎛 L4 · INTACT LoRA 微调 (r8/α16) · 接入中** | `ss/ss_lora_l4/out` | 65 | 65 | 1 | ✅ | `ss/ss_l5/out`, `ss/ssz700/out` | ✅ 2/2 |
| **🧮 流形引擎 (Manifold Engine · 编码→投影→度量→导航→反馈)** | `ss/ss_mani_eng/out` | 65 | 65 | 1 | ✅ | `ss/n_calib_mani/out`, `ss/ss_moe/out` | ✅ 6/6 |
| **🧲 总装机记忆 · 势场联络 (L2/L3/L4 势场 → 意图 −∇Φ)** | `ss/ss_mem_field/out` | 65 | 65 | 1 | ✅ | `ss/ss_mem_l2/out`, `ss/ss_mem_l3/out` | ✅ 3/3 |
| **🔧 L2 · 肌肉记忆操作 (小脑 · 标杆回放)** | `ss/ss_mem_l2/out` | 65 | 65 | 1 | ✅ | `ss/n_skill_dict/out`, `ss/ss_mem_share/out` | ✅ 2/2 |
| **🚀 L3 · 长程序列规划 (记忆: 海马体)** | `ss/ss_mem_l3/out` | 65 | 65 | 1 | ✅ | `ss/ss_mem_share/out` | ✅ 1/1 |
| **🏆 L4 · 工作安全 + 物理世界导航 (记忆: 前额叶)** | `ss/ss_mem_l4/out` | 65 | 65 | 1 | ✅ | `ss/ss_mem_share/out` | ✅ 1/1 |
| **🧠 总装记忆中枢 (前额叶总装 · 三层协同)** | `ss/ss_mem_share/out` | 65 | 65 | 1 | ✅ | `ss/n_board_frame/out`, `ss/n_eng_mem/out` | ✅ 4/4 |
| **🔍 光学质量检测** | `ss/ssaoi/out` | 65 | 65 | 1 | ✅ | `ss/ssyolo/out` | ✅ 1/1 |
| **📈 旁路实时可视化 (当前阶段/残差/接触概率)** | `ss/ssbypv/out` | 65 | 65 | 1 | ✅ | `ss/ssdata/out` | ✅ 1/1 |
| **🧮 标定层 · 引力-斥力-动作** | `ss/sscalib/out` | 65 | 65 | 1 | ✅ | `ss/ss2d3d/out` | ✅ 1/1 |
| **🧭 能力档位** | `ss/sscap/out` | 65 | 65 | 1 | ✅ | `ss/ssmode/out` | ✅ 1/1 |
| **📦 metaworld 数据源** | `ss/ssdata/out` | 65 | 65 | 1 | ✅ | （源节点） | —(源) |
| **🎯 Flow-Matching Action Head (DiT)** | `ss/ssdec/out` | 65 | 65 | 1 | ✅ | `ss/ssintact_dec/out`, `ss/sslat/out` | ✅ 5/5 |
| **🧩 Feature 功能清单** | `ss/ssfeat/out` | 65 | 65 | 1 | ✅ | `ss/ss_mem_share/out`, `ss/ssworld/out` | ✅ 2/2 |
| **🎯 INTACT (L4) · 工作安全 + 物理世界导航** | `ss/ssintact/out` | 65 | 65 | 1 | ✅ | `ss/ss_lora_l4/out`, `ss/sscap/out` | ✅ 5/5 |
| **🎯 INTACT 意图解码器 (L4 → L3 条件)** | `ss/ssintact_dec/out` | 65 | 65 | 1 | ✅ | `ss/n_intent_bundle/out`, `ss/n_vlm_llm/out` | ✅ 5/5 |
| **🧮 潜空-流形** | `ss/sslat/out` | 65 | 65 | 1 | ✅ | `ss/sscalib/out`, `ss/ssvlm/out` | ✅ 2/2 |
| **🛡 安全执行边界 (饱和限幅)** | `ss/sslimit/out` | 65 | 65 | 1 | ✅ | `ss/sssched/out` | ✅ 1/1 |
| **🧠 L3 长程序列规划器 (场景理解驱动)** | `ss/ssllm/out` | 65 | 65 | 1 | ✅ | `ss/n_hil/out`, `ss/n_vlm_llm/out` | ✅ 4/4 |
| **📝 任务指令 · MES/自然语言** | `ss/ssllm_in/out` | 65 | 65 | 1 | ✅ | `ss/ssdata/out`, `ss/ssz700/out` | ✅ 2/2 |
| **🧮 接触流形 · 导航地图 (e∥进度/e⊥偏离)** | `ss/ssmani_c/out` | 65 | 65 | 1 | ✅ | `ss/n_calib_mani/out`, `ss/ss2d3d/out` | ✅ 5/5 |
| **🧠 流形专家预测器 (JEPA: 潜空间→流形→动作)** | `ss/ssmani_exp/out` | 65 | 65 | 1 | ✅ | `ss/n_calib_mani/out`, `ss/ss2d3d/out` | ✅ 6/6 |
| **🧮 性能流形 · 耦合代价 (V_p/η)** | `ss/ssmani_p/out` | 65 | 65 | 1 | ✅ | `ss/ss2d3d/out`, `ss/ss_mani_eng/out` | ✅ 4/4 |
| **🧭 动作调制器** | `ss/sssched/out` | 65 | 65 | 1 | ✅ | `ss/n_board_frame/out`, `ss/n_intent_direct/out` | ✅ 13/13 |
| **📡 融合定位建图** | `ss/sssensor/out` | 65 | 65 | 1 | ✅ | `ss/ss2d3d/out`, `ss/ssaoi/out` | ✅ 4/4 |
| **② 对位 · SK02** | `ss/sssk2/out` | 65 | 65 | 1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 |
| **③ 下降 · SK03** | `ss/sssk3/out` | 65 | 65 | 1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 |
| **④ 抓取 · SK04** | `ss/sssk4/out` | 65 | 65 | 1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 |
| **⑤ 抬起 · SK05** | `ss/sssk5/out` | 65 | 65 | 1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 |
| **⑥ 转移 · SK06** | `ss/sssk6/out` | 65 | 65 | 1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 |
| **⑦ 插入 · SK07** | `ss/sssk7/out` | 65 | 65 | 1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 |
| **⑧ 完成 · SK08** | `ss/sssk8/out` | 65 | 65 | 1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 |
| **🛠 L3 技能序列编排** | `ss/ssskill/out` | 65 | 65 | 1 | ✅ | `ss/n_vlm_llm/out`, `ss/ssdata/out` | ✅ 4/4 |
| **🖐 触觉感知** | `ss/sstactile/out` | 65 | 65 | 1 | ✅ | `ss/ssdata/out` | ✅ 1/1 |
| **🧠 VLM 通用视觉编码器 (SmolVLA)** | `ss/ssvlm/out` | 65 | 65 | 1 | ✅ | `ss/ss_lora_l3/out`, `ss/ss_seg/out` | ✅ 5/5 |
| **🎯 YOLO 目标检测** | `ss/ssyolo/out` | 65 | 65 | 1 | ✅ | `ss/ss_l5/out`, `ss/ssdata/out` | ✅ 2/2 |
| **🖥 Z700 真机信号 (全信号观测 · 物理世界输出)** | `ss/ssz700/out` | 65 | 65 | 1 | ✅ | （源节点） | —(源) |
| **🧪 光模块插拔 · 环境渲染图像源 (Z-MAX 引擎逐帧真图)** | `ss/swds/out` | 65 | 65 | 1 | ✅ | `ss/ssdata/out`, `ss/ssyolo/out` | ✅ 3/3 |
| **🎯 INTACT 插拔策略 · 光模块抓取插入 (本域微调 · 零搜索)** | `ss/swintact/out` | 65 | 65 | 1 | ✅ | `ss/sscap/out`, `ss/ssintact/out` | ✅ 3/3 |
| **🎬 插拔渲染视频 (从 Z-MAX 引擎取出 · 实况窗)** | `ss/swvideo/out` | 65 | 65 | 1 | ✅ | `ss/swworld/out` | ✅ 1/1 |
| **🌍 Z-MAX 引擎 · 光模块插拔真物理 (模型动作真下发 env.step)** | `ss/swworld/out` | 65 | 65 | 1 | ✅ | `ss/n_realscene/out`, `ss/ssworld/out` | ✅ 3/3 |

### 5.2 数据空间注册 typed 话题 (全量) 实测

| 话题 | 本窗口条数 | 实测 Hz | 帧龄 s | 判定 |
|---|---|---|---|---|
| `zmax/heartbeat` | 2 | 0.2 | 1.05 | ✅ 有流量 |
| `zmax/hw_state` | 4 | 0.4 | 1.05 | ✅ 有流量 |
| `zmax/ss_calib` | 66 | 6.6 | 0.15 | ✅ 有流量 |
| `zmax/ss_diag` | 66 | 6.6 | 0.15 | ✅ 有流量 |
| `zmax/ss_torque` | 66 | 6.6 | 0.15 | ✅ 有流量 |
| `zmax/train_prog` | 3 | 0.3 | 1.05 | ✅ 有流量 |
| `zmax/deploy_cmd` | 0 | 0.0 | None | ❌ 无发布端 (本刻未起) |
| `zmax/ss_action` | 0 | 0.0 | None | ❌ 无发布端 (本刻未起) |
| `zmax/ss_canvas` | 0 | 0.0 | None | ❌ 无发布端 (本刻未起) |
| `zmax/ss_energy` | 0 | 0.0 | None | ❌ 无发布端 (本刻未起) |
| `zmax/ss_infer` | 0 | 0.0 | None | ❌ 无发布端 (本刻未起) |
| `zmax/ss_macro` | 0 | 0.0 | None | ❌ 无发布端 (本刻未起) |
| `zmax/ss_nodes` | 0 | 0.0 | None | ❌ 无发布端 (本刻未起) |
| `zmax/ss_plan` | 0 | 0.0 | None | ❌ 无发布端 (本刻未起) |
| `zmax/ss_state` | 0 | 0.0 | None | ❌ 无发布端 (本刻未起) |
| `zmax/ss_test` | 0 | 0.0 | None | ❌ 无发布端 (本刻未起) |

## 六、质量评估结论与达成路径

- **节拍**: 未达标 — 摆盘实测 CT [10.64, 11.55, 11.62] s vs 目标 ≤3.15s / 硬上限 3.5s ⇒ 3.32×
- **成功率**: 证据不足(非指标失败) — 现有 4 次观测 0 失效 ⇒ 95% 置信下限 52.7%; 要判 ≥99% 需 ≥299 次连续 0 失效
- **取放精度**: 达标 — Δxy ≤0.13mm / 姿态 ≤0.04° (判据 ≤1mm/≤1°)
- **插拔(插入到位)**: 达标 — 到位残差 0.45mm ≤ 判据 2mm · 配置行程 ins.depth=35mm · episode 时长 10.43s · success=True
- **真空建立**: 未达标 — 实测 [425.0, 538.0, 525.0] ms vs 配方上限 200.0 ms
- **信号→topic 登记**: 有缺口 — 信号 286 条 · DDS typed 14 · 画布节点输出族 184 · ROS2 通道 0 · **未登记 88**; 信号族构成: AOI检测14·引擎快照184·AR/L588
- **信号实测覆盖**: 部分 — 当前快照里在跑的信号 17/286 条 (其余需先跑场景/起发布端)
- **总线判据**: 见判据段 — 数据总线一致性 ('39', '39') · 节点输出 topic ('14', '14') · 驱动扭矩话题 29 · 场景色标 ('27', '27')

**达成 99% / 3.5s 的路径** (改完必须重跑同口径验收):
1. 真空保持 `pick.hold_s` 5.0s → 0.6~1.0s (节拍大头);
2. 接近段末尾**预抽真空**, 把真空建立时间藏进接近时间 (不放宽判据);
3. 放开速度档位 (`speed_scale` 现被 `est=11.0` 硬编码卡在 1.5×, 达标需 3.38×), 保留加速度限幅;
4. 连续验收 12 盘 × 25 颗 = 300 颗 0 失效, 出具 95% 置信下限 ≥99% 的成功率结论。

## 复核命令

```bash
python3 tools/ss_task_runner.py --task TASK-01-FW --no-video
venvs/dds-venv/bin/python tools/verify_feature_io.py --seconds 10
gui-venv311/bin/python tools/delivery/gen_scene_doc.py --task TASK-01-FW --ver 5.50.C
```
