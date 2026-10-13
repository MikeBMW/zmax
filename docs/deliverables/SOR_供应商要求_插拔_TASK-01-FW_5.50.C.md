# 供应商要求 SOR (Statement of Requirements) · 插拔作业

版本: 5.50.C　文件编号: SOR-SCN-01-FW-550C　生成: 2026-10-13

**明确目标 (硬指标)**: 连续动作成功率 **≥99%** · 单件节拍 **≤3.5s** (任务目标 ≤3.15s, 3.5s 为硬上限)。未达即不予验收。

## 1. 项目与场景

| 项 | 要求 |
|---|---|
| 任务 | FW Loading + EEPROM 写/读校验 (TASK-01-FW) |
| 配方 | 插拔+固件校验 |
| 场景/场景号 | 插拔场景 / SCN-01-FW (色 #2e8b57) |
| 站点 | SITE-A.ST11 |
| 触发/循环 | 来料盒就位 / 上游工位放行信号；单件循环; 连续 2 次抓取失败停机 |
| 适用工序段 | 0 料源与来料状态 / 1 取件 / 2 姿态准备 / 3 识别与工位对接 / 4 放置/插入 / 5 拔出/取回 / 6 分拣与回位 / 7 节拍与循环 |
| 不适用段 | — |
| 工单规则 | 1 批 = 1 工单; 1 件 = 1 条记录 |

## 2. 采购范围与交付分工

| 交付项 | 范围 | 责任方 | 接口/凭据 |
|---|---|---|---|
| 机器人本体 + 控制器 | 六轴 + 力控 + 末端快换 | 供应商 | SDK (珞石 xCore) · 关节/末端状态真值 |
| 末端执行器 | 真空吸盘 (摆盘) / 夹爪 (插拔) | 供应商 | 真空建立/断真空 · 夹持状态反馈 |
| 视觉系统 | 全局定位 + 腕部相机 + 标定 | 供应商 (标定由甲方提供靶标) | 相机内参 K · 手眼/板坐标系 |
| 数据平台 (Z-MAX) | 状态空间引擎 + 数据空间 DDS + 记忆层 | 平台方 | 见 6. 数据平台与接口 |
| 场景解决方案 | 工艺技能编排 / 参数配方 / 集成调试 | 平台方 + 供应商 | 配置单 · 点位台账 · 判据脚本 |
| 安全链 | 急停/力阈值/关节限位/光幕 (站点级, 任务不可覆盖) | 供应商 | 安全回路证书 |

## 3. 性能指标要求 (可测量, 每项含判据与验证方法)

| 指标 | 要求值 | 验证方法 |
|---|---|---|
| 合格率 | ≥99% | 按判据脚本实测, 见 §7 |
| 硬指标 成功率 | ≥99% (连续 300 颗 0 失效, 95% 置信下限 ≥99%) | 12 盘 × 25 颗连续验收 |
| 硬指标 节拍 | ≤3.5s (目标 ≤3.15s) | 逐颗 CT 计时 (进带→锁/放置完成) |
| 取放/插入精度 | 单边 ≤1mm · 角度 ≤1° (插拔: 头到孔底 <4mm) | 激光/视觉量测 + 日志 |
| 过程能力 | 真空建立 ≤200ms · 真空保持按配方 | 真空压力曲线 (进带→锁) |

## 4. 场景作业要求 (工艺技能序列)

| t(s) | 时长(s) | 工艺技能 | 作业要求 |
|---|---|---|---|
| 0.0 | 0.6 | 取料 | 左臂从归位移动到吸塑盒上方(X=2.5,Y=-0.4,Z=1.3), 夹爪闭合(力控1~5N)抓取光模块 |
| 0.6 | 1.0 | 扫码 | 右臂携带模块移至扫码枪前(X=2.1,Y=0.4,Z=1.35), 红色十字激光扫描SN二维码 |
| 1.6 | 0.8 | 翻转 | 腕部旋转180°(150°/s), 模块标签面朝下, 金手指面朝上 |
| 2.4 | 0.5 | 对位 | 视觉定位QSFP插座导向槽, 末端移动到(X=2.5,Y=0,Z=1.26), 偏差<0.1mm |
| 2.9 | 0.7 | 插入 | 沿导向槽直推35mm, 力控≤2N, 弹簧卡扣锁紧 |
| 3.6 | 50.0 | 异步测试 | PC自动下载固件→校验EEPROM→显示PASS/FAIL; R MPV可转向机台B |
| 53.6 | 0.8 | 拔出 | 夹爪夹持模块, 力控拉出≤2N, 脱离QSFP插座 |
| 54.4 | 3.0 | AOI飞拍 | 金手指正反2面飞拍(0.5s×2)+4侧面飞拍(0.5s×4)=3.0s, 速度0.6m/s |
| 57.4 | 0.8 | 分拣 | PASS→绿色料盘(Y=0.35), FAIL→红色料盘(Y=-0.35), 行程0.4m·速度1.0m/s |

## 5. 功能清单与接口要求 (每个功能: 输入 topic / 输出 topic / 性能指标)

功能=能力库条目。每个功能有明确输入与输出 topic, 性能指标为该功能的属性 (可测量, 可多功能共用)。

| 功能 (能力) | 方向 | 功能要求 | 输入 topic | 输出 topic | 性能指标 (可测量) | 本场景 |
|---|---|---|---|---|---|---|
| A1 自主导航流转 | IN/OUT | 跨工位自主移动, 移动即工位 | `ss/ss2d3d/out`, `ss/ssaoi/out` | `ss/sssensor/out` | 跨工位流转成功率 ≥97% | 调用 |
| A2 工位精准对接 | OUT | 到位定位, 对接精度 ±10mm 级 | `ss/n_board_frame/out`, `ss/ss_seg/out` | `ss/ss2d3d/out`, `ss/n_board_frame/out` | 对接精度 ±10mm | 调用 |
| A3 举升高度调节 | OUT/CFG | 垂直举升 0~800mm, 覆盖多层工位 | `ss/n_board_frame/out`, `ss/n_intent_direct/out` | `ss/sssched/out` | 0~800mm 覆盖多层工位 | 调用 |
| A4 双形态作业 | CFG | 固定式/移动式按需切换 | — | —(本场景未调用) | 切换 <30s | 未调用 |
| B1 目标识别定位 | IN | 识别工件/孔位/托盘/料盒并给出位置 | `ss/ss_l5/out`, `ss/ssdata/out` | `ss/ssyolo/out`, `ss/ss2d3d/out` | 型号规格识别 100% (POC ≥98%) · 换型 ≤30min · 新型号配置/学习 ≤3h | 调用 |
| B2 空间位姿感知 | IN | 感知目标三维位置与朝向 | — | —(本场景未调用) | 型号规格识别 100% (POC ≥98%) · 换型 ≤30min · 新型号配置/学习 ≤3h；空/满/异常三态判定 100% (POC ≥98%) · 单次判定 ≤500ms | 未调用 |
| B3 触感感知 | IN | 感知接触状态与力度大小 | — | —(本场景未调用) | 见功能实现节点指标 | 未调用 |
| B4 自身状态感知 | IN/CFG | 感知关节/末端/基座状态 | — | —(本场景未调用) | 见功能实现节点指标 | 未调用 |
| B5 光学质量检测 | IN/MON | 检测金手指划痕/端面脏污/外观缺陷 | `ss/ss_l5/out`, `ss/ssdata/out` | `ss/ssyolo/out`, `ss/sstactile/out` | 外观缺陷检出率按 AOI 口径；空/满/异常三态判定 100% (POC ≥98%) · 单次判定 ≤500ms · 异常态拒送并告警 | 调用 |
| C1 完整作业执行 | OUT | 从看到做, 独立完成连贯作业 | `ss/n_board_frame/out`, `ss/n_intent_direct/out` | `ss/sssched/out`, `ss/sssk4/out` | 插入成功率 ≥99% · 头到孔底 <4mm；抓取成功率 ≥97%；单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) | 调用 |
| C2 精细对位 | CFG/OUT | 亚毫米级对准, 末端 ±0.02mm 级 | `ss/n_board_frame/out`, `ss/ss_seg/out` | `ss/ss2d3d/out`, `ss/sssk2/out` | 对位残差 ≤0.5mm · 重投影 rmse 合格 | 调用 |
| C3 力控插拔保护 | OUT/MON | 插拔过程防损伤, 力控 ≤2N 级 | `ss/ssdata/out` | `ss/sstactile/out`, `ss/ssmani_c/out` | 插拔力上限可配 · 超限即退 (MON) | 调用 |
| C4 灵活翻转取放 | OUT | 翻转 180° 级姿态调整与取放 | — | —(本场景未调用) | 抓取成功率 ≥97%；单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载具与产品损伤 0 | 未调用 |
| C5 双臂协同作业 | OUT | 同步/协同/接力三种协同模式 | `ss/n_board_frame/out`, `ss/n_intent_direct/out` | `ss/sssched/out` | 双臂干涉检测 + 协同节拍 | 调用 |
| C6 宏微复合作业 | OUT | 大行程快动 + 微调精细分工 | `ss/n_board_frame/out`, `ss/n_intent_direct/out` | `ss/sssched/out` | 宏动定位 + 微调收敛, 末端重复性 ≤0.05mm | 调用 |
| D1 过程预判 | GUIDE | 预判后续过程走向, 提前引导 | `ss/ssintact_dec/out` | `ss/n_intent_direct/out` | IntAct 稳态 101ms · 冷启 6.7s (常驻) | 调用 |
| D2 运动规律建模 | OUT | 建立运动规律模型, 支撑分析预测 | — | —(本场景未调用) | IntAct 稳态 101ms · 冷启 6.7s (常驻) | 未调用 |
| D3 决策说明 | MON | 说明当前决策依据, 过程可查 | — | —(本场景未调用) | 见功能实现节点指标 | 未调用 |
| E1 车载数据采集 | TRAIN | 作业过程自动采集三类数据 (数据飞轮) | — | —(本场景未调用) | 见功能实现节点指标 | 未调用 |
| E2 边学边练 | TRAIN | 现场作业中持续学习提升 | — | `ss/n_eng_mem/out`, `ss/n_l2_muscle/out` | 采集→训练→部署闭环可无人值守；连续自主 ≥12 盘周转盘 (硬下限 ≥6) · 单日连续运行 ≥20h · 月 ≥28 天 · 寿命 ≥3 年 | 调用 |
| E3 上岗考核 | EVAL | 正式作业前先经仿真考核 | — | —(本场景未调用) | 采集→训练→部署闭环可无人值守 | 未调用 |
| F1 本地实时作业 | DEPLOY | 机端本地实时完成作业 (70ms 级) | `ss/ss_mem_share/out` | `ss/ss_mem_l3/out`, `ss/n_l2_muscle/out` | 自动重试 ≤3 次 · 断点续作成功率 ≥95% · 错误继续执行 0 (零容忍)；连续自主 ≥12 盘周转盘 (硬下限 ≥6) · 单日连续运行 ≥20h · 月 ≥28 天 · | 调用 |
| F2 远程升级 | DEPLOY | 作业中可远程更新模型能力 | — | —(本场景未调用) | 见功能实现节点指标 | 未调用 |
| F3 多车协同调度 | SCHED | 多机台多车任务分配与协同 | `ss/n_board_frame/out`, `ss/n_eng_mem/out` | `ss/ss_mem_share/out`, `ss/n_web_agent/out` | 多机台/多车协同, 场景编排 | 调用 |
| G1 标准模型接入 | IN/OUT | 按统一接口接入任意模型 | — | —(本场景未调用) | 按 Manifest + 适配器接入, 能力契约不变 | 未调用 |
| G2 运行状态上报 | MON | 作业状态与结果实时上报 | — | —(本场景未调用) | 抬升闸放开仍须慢速+警报在先 · 听「要碰撞」立即全停 | 未调用 |
| G3 事件自动通知 | MON | 关键事件自动通知相关人员 | — | —(本场景未调用) | 按 Manifest + 适配器接入, 能力契约不变 | 未调用 |
| G4 产线系统对接 | MON/CFG | 对接 PLC/MES/联锁信号 | `ss/ssdata/out`, `ss/ssz700/out` | `ss/ssllm_in/out`, `ss/ssllm/out` | 短提示 + 小 JSON 输出, timeout ≥300s | 调用 |
| H1 现场参数可调 | CFG | 作业参数现场直接调整 | `ss/ss2d3d/out` | `ss/sscalib/out` | 写 M 幂等 · 范围校验 · 回读确认 | 调用 |
| H2 方案文档交付 | - | 一键生成方案与能力文档 | — | —(本场景未调用) | 见功能实现节点指标 | 未调用 |
| H3 远程查看 | MON | 手机/网页随时查看运行情况 | — | —(本场景未调用) | 见功能实现节点指标 | 未调用 |

## 6. 数据平台与接口 (DDS 数据空间)

注册话题 25 个 (注册表 v1.0.0); 模式: prod=量产: 零开销 —— 不建  / diag=诊断: 只取性能/硬件类(不 / calib=标定: 状态+动作+连线+标 / test=测试: 全量 22 话题(取 / dev=同 test。每个画布功能节点另有独立输出 topic `ss/<节点id>/out` (89 个)。

| 话题 | 类型 | 设计 Hz | QoS | 生产端 | 实测 |
|---|---|---|---|---|---|
| deploy_cmd | DeployCommand | 0.0 | cmd | ECS / 控制台(人工晋级) | ❌ 本刻无发布端 |
| ds_aoi | SliceJSON | 0.05 | state | 工控机 AOI 10082/10083 (/last_result) | ❌ 本刻无发布端 |
| ds_arch | SliceJSON | 0.05 | state | tools/arch_graph.py --json | ❌ 本刻无发布端 |
| ds_dataset | SliceJSON | 0.05 | state | tools/dataset_inventory.py --json | ❌ 本刻无发布端 |
| ds_endpoint | SliceJSON | 0.05 | state | tools/remote_monitor_aggregate.py --json | ❌ 本刻无发布端 |
| ds_hil | SliceJSON | 0.05 | state | tools/hil_local_api.py (8795 /hil/state) | ❌ 本刻无发布端 |
| ds_model | SliceJSON | 0.05 | state | tools/model_inventory.py --json | ❌ 本刻无发布端 |
| ds_scene | SliceJSON | 0.05 | state | tools/scene_edit.py list --json | ❌ 本刻无发布端 |
| ds_version | SliceJSON | 0.05 | state | tools/verify_version_sync.py --json | ❌ 本刻无发布端 |
| heartbeat | Heartbeat | 0.2 | beat | 各端守护 | ✅ 2 条 / 0.2 Hz |
| hw_state | HardwareState | 0.33 | state | zmax_dds_publisher.py --interval 3 (zmax-dds-pub.ser | ✅ 4 条 / 0.4 Hz |
| link_value | LinkValue | 5.0 | beat | 画布连线总线(dds_link_bus) | ❌ 本刻无发布端 |
| ss_action | SSAction | 10.0 | beat | zmax_dds_ss_daemon.py ← tap proposal_*.jsonl (本机推理 8 | ❌ 本刻无发布端 |
| ss_calib | SSCalib | 0.2 | state | zmax_dds_ss_daemon.py ← 标定真源文件(calib.json/handeye/al | ✅ 66 条 / 6.6 Hz |
| ss_canvas | SSCanvasNode | 0.5 | state | 画布/引擎节点状态上报 | ❌ 本刻无发布端 |
| ss_diag | SSDiag | 0.5 | beat | zmax_dds_ss_daemon.py(延时/帧龄/吞吐/健康度) | ✅ 66 条 / 6.6 Hz |
| ss_energy | SSEnergy | 0.5 | state | 流形引擎能量探针 tools/manifold_energy_probe.py → tap zmax_d | ❌ 本刻无发布端 |
| ss_infer | SSInfer | 0.5 | beat | zmax_dds_ss_daemon.py ← http://127.0.0.1:8790/health | ❌ 本刻无发布端 |
| ss_macro | SSMacro | 0.2 | state | 五层记忆/宏观层(SS_MACRO) | ❌ 本刻无发布端 |
| ss_nodes | SSNodes | 0.2 | state | 数据空间自描述(谁在发什么) | ❌ 本刻无发布端 |
| ss_plan | SSPlan | 0.5 | state | zmax_dds_ss_daemon.py ← MoveIt plan-only 镜像 tap ~/zm | ❌ 本刻无发布端 |
| ss_state | SSState | 10.0 | beat | zmax_dds_ss_daemon.py ← 真机只读 tap ~/zmax/zmax_data/ss | ❌ 本刻无发布端 |
| ss_test | SSTest | 0.0 | state | 取证/回归脚本(verify_*.py / preflight) | ❌ 本刻无发布端 |
| ss_torque | SSDrivingTorque | 10.0 | beat | 流形引擎驱动扭矩发布器 tools/tdrive_bus.py → tap zmax_data/ss_l | ✅ 66 条 / 6.6 Hz |
| train_prog | TrainProgress | 0.33 | state | 训练脚本写进度文件 → zmax_dds_publisher.py | ✅ 3 条 / 0.3 Hz |

接口纪律: ① 全系统只用一张 DDS 配置 (单播, `AllowMulticast=false` + 显式 Peers), 禁止默认多播; ② 节点输入 topic 来源必须可追溯到上游功能节点; ③ 话题缺失/无流量必须在验收报告里如实标注, 不得以「已登记」代替「实测通过」。

## 7. 验收要求 (99% / 3.5s 的判定口径)

| 验收项 | 判据 | 样本量 | 通过条件 |
|---|---|---|---|
| 成功率 | 连续 0 失效; 95% 置信下限 ≥99% | ≥300 件 (12 盘 × 25 颗) | 全部通过 |
| 节拍 | 逐件 CT ≤3.5s | 全部件次 | P95 ≤3.5s |
| 精度 | 单边 ≤1mm / ≤1° (插拔: 头到孔底 <4mm) | 每件 | 全部通过 |
| 功能 topic 输入输出 | 逐功能真收发 (收到 ≥ 发出/2) | 全部功能节点 | 74/74 通过 |
| 安全 | 急停/力阈值/限位/光幕有效; 授权链路只从授权源 | 每次作业 | 100% |

本次实测 (供应商须知): 节拍 10.43 s; 取放精度 Δxy ≤0.13 mm / 姿态 ≤0.04°; 插入到位残差 0.4532 mm; 真空建立 [425.0, 538.0, 525.0] ms; 现状缺口已列在验收报告 §9。

## 8. 交付物与文档

| 交付物 | 形式 | 说明 |
|---|---|---|
| 本 SOR | docx + md | 供应商要求, 含功能清单/接口/验收 |
| 交付文档 (场景) | docx/md | 工程配置 · 任务配置 · 功能清单 · topic 实测报告 |
| 配置单 | md + json | 全套参数 (画布/标定/点位/参数注册表) |
| 验收报告 | md + json | 目标 vs 实测 vs 判定 + 判据原文 |
| 功能 topic 输入输出测试报告 | md + json | 逐功能真 DDS 往返实测 |
| 合作协议 | docx + md | 平台提供/销售 + 解决方案采购 |

## 9. 待商务/待现场项 (如实列出, 不得默认已达标)

站位几何未标定: T_base_cam, plane_z, cell_geometry.points ⇒ 坐标类参数不可信, 本 SOR 中坐标类指标以「待实测」计。

测试报告与质量评估结论以《验收报告》为准; 现场硬件 (相机/位姿真值/建图) 到位后须复测。

