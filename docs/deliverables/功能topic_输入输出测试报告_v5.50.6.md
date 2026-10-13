# 功能 topic 输入/输出 实测报告 · v5.50.6

> 真源: 画布 `data/database/zmax/sources/canvas/state_space_obs.json` (89 节点/184 连线) · 注册表 `zmax_data/dataspace/busdb.json` · 工程库 `data/database/zmax/zmax_engineering.db`
> 口径: 功能=画布节点; **输出 topic** = `ss/<节点id>/out`; **输入 topic** = 上游节点输出 topic 集合 + 连线总线 `zmax/link_value`
> 实测方式: 逐 topic **真 DDS 往返** (`zmax::SSTest` 载体, writer+reader 同进程) + 注册 typed 话题按注册 QoS 只读订阅
> 生成时间: 2026-10-13 15:00:23 (窗口 10s)

## 汇总

| 项 | 数 |
|---|---|
| 功能(画布节点) | 74 |
| 输出通道往返 ✅ | **74 / 74** |
| 注册 typed 话题实测有流量 ✅ | **6 / 16** |
| 场景调用 | TASK-06-TRAY(SCN-06-TRAY)=51 节点 · TASK-01-FW(SCN-01-FW)=51 节点 |

## 一、注册 typed 话题 (数据空间 25 个) 实测

| 话题 | 本窗口条数 | 实测 Hz | 帧龄 s | 判定 |
|---|---|---|---|---|
| `zmax/heartbeat` | 2 | 0.2 | 1.2 | ✅有流量 |
| `zmax/hw_state` | 4 | 0.4 | 1.2 | ✅有流量 |
| `zmax/ss_calib` | 66 | 6.6 | 0.15 | ✅有流量 |
| `zmax/ss_diag` | 66 | 6.6 | 0.15 | ✅有流量 |
| `zmax/ss_torque` | 66 | 6.6 | 0.15 | ✅有流量 |
| `zmax/train_prog` | 3 | 0.3 | 1.2 | ✅有流量 |
| `zmax/deploy_cmd` | 0 | 0.0 | None | ❌无发布端 |
| `zmax/ss_action` | 0 | 0.0 | None | ❌无发布端 |
| `zmax/ss_canvas` | 0 | 0.0 | None | ❌无发布端 |
| `zmax/ss_energy` | 0 | 0.0 | None | ❌无发布端 |
| `zmax/ss_infer` | 0 | 0.0 | None | ❌无发布端 |
| `zmax/ss_macro` | 0 | 0.0 | None | ❌无发布端 |
| `zmax/ss_nodes` | 0 | 0.0 | None | ❌无发布端 |
| `zmax/ss_plan` | 0 | 0.0 | None | ❌无发布端 |
| `zmax/ss_state` | 0 | 0.0 | None | ❌无发布端 |
| `zmax/ss_test` | 0 | 0.0 | None | ❌无发布端 |

## 二、逐功能 topic 输入/输出 实测

| 功能 (节点) | 层 | 输出 topic | 发出/收到/匹配 | 输出通道 | 输入 topic (上游) | 输入通道 | 本场景调用 | 性能指标 |
|---|---|---|---|---|---|---|---|---|
| **💪 L2 肌肉记忆技能库 (光模块抓放循环)** | L2 | `ss/n_l2_muscle/out` | 65/65/1 | ✅ | `ss/ssskill/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载 |
| **🧩 开放词汇分割 (SAM3 分割anything)** | L2 | `ss/ss_seg/out` | 65/65/1 | ✅ | `ss/ss_l5/out`, `ss/ssdata/out`, `ss/ssyolo/out` | ✅ 3/3 | — | 型号规格识别 100% (POC ≥98%) · 换型 ≤30min · 新型号配置/学习 ≤3h; 按 Manifes |
| **🧭 MoveIt 运动规划 · SDK 直驱桥(Orin)** | L2/L3 执行面 | `ss/n_moveit/out` | 65/65/1 | ✅ | `ss/ssdec/out`, `ss/sssk1/out`, `ss/sssk2/out` +6 | ✅ 9/9 | — | 见能力清单 |
| **📐 板坐标系定位 (工序坐标系·免手眼)** | - | `ss/n_board_frame/out` | 65/65/1 | ✅ | `ss/n_dsvl/out`, `ss/ssyolo/out`, `ss/ssz700/out` | ✅ 3/3 | TASK-01-FW,TASK-06-TRAY | 对位残差 ≤0.5mm · 重投影 rmse 合格; 对接精度 ±10mm; 空/满/异常三态判定 100% (POC  |
| **🧮 标定诊断测量 · 主参数 M (状态空间结构参数 · 等效惯量)** | - | `ss/n_calib_mani/out` | 65/65/1 | ✅ | `ss/sscalib/out`, `ss/sslat/out` | ✅ 2/2 | — | 见能力清单 |
| **🧿 DeepSeek-V4-Flash · 场景理解 (L5 大模型主路)** | - | `ss/n_dsvl/out` | 65/65/1 | ✅ | `ss/n_web_agent/out`, `ss/ssdata/out`, `ss/ssllm_in/out` | ✅ 3/3 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **📚 工程记忆 · 技能与经验库** | - | `ss/n_eng_mem/out` | 65/65/1 | ✅ | （源节点/无上游） | —(源) | TASK-01-FW,TASK-06-TRAY | 采集→训练→部署闭环可无人值守 |
| **🙋 HIL 人机在环 · 状态↔指示** | - | `ss/n_hil/out` | 65/65/1 | ✅ | `ss/n_dsvl/out` | ✅ 1/1 | — | 见能力清单 |
| **🧠 意图丛 · 四槽语法** | - | `ss/n_intent_bundle/out` | 65/65/1 | ✅ | `ss/ssllm/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🔮 意图直读 · Direct** | - | `ss/n_intent_direct/out` | 65/65/1 | ✅ | `ss/ssintact_dec/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | IntAct 稳态 101ms · 冷启 6.7s (常驻) |
| **🔗 跨层连接 · 记忆图谱** | - | `ss/n_mem_links/out` | 65/65/1 | ✅ | `ss/ss_mem_l2/out`, `ss/ss_mem_l3/out`, `ss/ss_mem_l4/out` | ✅ 3/3 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🎥 真实场景叠加 · 双眼 (sim2real)** | - | `ss/n_realscene/out` | 65/65/1 | ✅ | `ss/ssdata/out` | ✅ 1/1 | — | 见能力清单 |
| **🧬 技能词典 · L2 动作基** | - | `ss/n_skill_dict/out` | 65/65/1 | ✅ | `ss/ssskill/out` | ✅ 1/1 | — | 见能力清单 |
| **👁 视觉语言大模型 · 场景理解 (Qwen2.5/3-VL)** | - | `ss/n_vlm_llm/out` | 65/65/1 | ✅ | `ss/n_dsvl/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🌐 Web 智能体桥 · 远程提示词** | - | `ss/n_web_agent/out` | 65/65/1 | ✅ | `ss/n_eng_mem/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 多机台/多车协同, 场景编排 |
| **📐 2D→3D 解算** | - | `ss/ss2d3d/out` | 65/65/1 | ✅ | `ss/n_board_frame/out`, `ss/ss_seg/out`, `ss/ssyolo/out` | ✅ 3/3 | TASK-01-FW,TASK-06-TRAY | 型号规格识别 100% (POC ≥98%) · 换型 ≤30min · 新型号配置/学习 ≤3h; 对位残差 ≤0.5 |
| **🧭 3D 视图** | - | `ss/ss3d_view/out` | 65/65/1 | ✅ | `ss/ss2d3d/out`, `ss/ssworld/out` | ✅ 2/2 | — | 跨工位流转成功率 ≥97% |
| **🧿 L5 · 视觉语言自动标注 → L2/L3/L4 监督 → 自动训练** | - | `ss/ss_l5/out` | 65/65/1 | ✅ | `ss/ssdata/out` | ✅ 1/1 | — | 见能力清单 |
| **🎛 L3 · SmolVLA LoRA 微调 · 接入中** | - | `ss/ss_lora_l3/out` | 65/65/1 | ✅ | `ss/ss_l5/out`, `ss/ssz700/out` | ✅ 2/2 | — | 见能力清单 |
| **🎛 L4 · INTACT LoRA 微调 (r8/α16) · 接入中** | - | `ss/ss_lora_l4/out` | 65/65/1 | ✅ | `ss/ss_l5/out`, `ss/ssz700/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🧮 流形引擎 (Manifold Engine · 编码→投影→度量→导航→反馈)** | - | `ss/ss_mani_eng/out` | 65/65/1 | ✅ | `ss/n_calib_mani/out`, `ss/ss_moe/out`, `ss/sscalib/out` +3 | ✅ 6/6 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🧲 总装机记忆 · 势场联络 (L2/L3/L4 势场 → 意图 −∇Φ)** | - | `ss/ss_mem_field/out` | 65/65/1 | ✅ | `ss/ss_mem_l2/out`, `ss/ss_mem_l3/out`, `ss/ss_mem_l4/out` | ✅ 3/3 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🔧 L2 · 肌肉记忆操作 (小脑 · 标杆回放)** | - | `ss/ss_mem_l2/out` | 65/65/1 | ✅ | `ss/n_skill_dict/out`, `ss/ss_mem_share/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🚀 L3 · 长程序列规划 (记忆: 海马体)** | - | `ss/ss_mem_l3/out` | 65/65/1 | ✅ | `ss/ss_mem_share/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载 |
| **🏆 L4 · 工作安全 + 物理世界导航 (记忆: 前额叶)** | - | `ss/ss_mem_l4/out` | 65/65/1 | ✅ | `ss/ss_mem_share/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🧠 总装记忆中枢 (前额叶总装 · 三层协同)** | - | `ss/ss_mem_share/out` | 65/65/1 | ✅ | `ss/n_board_frame/out`, `ss/n_eng_mem/out`, `ss/n_mem_links/out` +1 | ✅ 4/4 | TASK-01-FW,TASK-06-TRAY | 多机台/多车协同, 场景编排 |
| **🧬 元数据MOE门控路由** | - | `ss/ss_moe/out` | 65/65/1 | ✅ | `ss/ssobs/out`, `ss/ssvlm/out` | ✅ 2/2 | — | 见能力清单 |
| **🤖 机器人执行器** | - | `ss/ssact/out` | 65/65/1 | ✅ | `ss/n_moveit/out`, `ss/ssbypv/out` | ✅ 2/2 | — | 0~800mm 覆盖多层工位; 抬升闸放开仍须慢速+警报在先 · 听「要碰撞」立即全停; 插入成功率 ≥99% · 头到 |
| **🔍 光学质量检测** | - | `ss/ssaoi/out` | 65/65/1 | ✅ | `ss/ssyolo/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 外观缺陷检出率按 AOI 口径 |
| **📈 旁路实时可视化 (当前阶段/残差/接触概率)** | - | `ss/ssbypv/out` | 65/65/1 | ✅ | `ss/ssdata/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🧮 标定层 · 引力-斥力-动作** | - | `ss/sscalib/out` | 65/65/1 | ✅ | `ss/ss2d3d/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 写 M 幂等 · 范围校验 · 回读确认 |
| **🧭 能力档位** | - | `ss/sscap/out` | 65/65/1 | ✅ | `ss/ssmode/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **📦 metaworld 数据源** | - | `ss/ssdata/out` | 65/65/1 | ✅ | （源节点/无上游） | —(源) | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🎯 Flow-Matching Action Head (DiT)** | - | `ss/ssdec/out` | 65/65/1 | ✅ | `ss/ssintact_dec/out`, `ss/sslat/out`, `ss/ssmani_c/out` +2 | ✅ 5/5 | TASK-01-FW,TASK-06-TRAY | 单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载 |
| **🔮 自适应状态估计器** | - | `ss/ssest/out` | 65/65/1 | ✅ | `ss/ssobs/out` | ✅ 1/1 | — | 见能力清单 |
| **🧩 Feature 功能清单** | - | `ss/ssfeat/out` | 65/65/1 | ✅ | `ss/ss_mem_share/out`, `ss/ssworld/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **⚡ 前馈加速器** | - | `ss/ssff/out` | 65/65/1 | ✅ | `ss/ss_mem_l2/out`, `ss/sscap/out`, `ss/ssdec/out` +1 | ✅ 4/4 | — | 插入成功率 ≥99% · 头到孔底 <4mm |
| **🧠 前馈激活直方图** | - | `ss/ssff_hist/out` | 65/65/1 | ✅ | `ss/ssff/out` | ✅ 1/1 | — | 见能力清单 |
| **🧪 状态校正器** | - | `ss/ssinnov/out` | 65/65/1 | ✅ | `ss/ssest/out`, `ss/sspred/out`, `ss/ssworld/out` | ✅ 3/3 | — | 见能力清单 |
| **🎯 INTACT (L4) · 工作安全 + 物理世界导航** | - | `ss/ssintact/out` | 65/65/1 | ✅ | `ss/ss_lora_l4/out`, `ss/sscap/out`, `ss/ssdata/out` +2 | ✅ 5/5 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🎯 INTACT 意图解码器 (L4 → L3 条件)** | - | `ss/ssintact_dec/out` | 65/65/1 | ✅ | `ss/n_intent_bundle/out`, `ss/n_vlm_llm/out`, `ss/ss_mani_eng/out` +2 | ✅ 5/5 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🧮 潜空-流形** | - | `ss/sslat/out` | 65/65/1 | ✅ | `ss/sscalib/out`, `ss/ssvlm/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🛡 安全执行边界 (饱和限幅)** | - | `ss/sslimit/out` | 65/65/1 | ✅ | `ss/sssched/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🧠 L3 长程序列规划器 (场景理解驱动)** | - | `ss/ssllm/out` | 65/65/1 | ✅ | `ss/n_hil/out`, `ss/n_vlm_llm/out`, `ss/ss_mem_share/out` +1 | ✅ 4/4 | TASK-01-FW,TASK-06-TRAY | 短提示 + 小 JSON 输出, timeout ≥300s |
| **📝 任务指令 · MES/自然语言** | - | `ss/ssllm_in/out` | 65/65/1 | ✅ | `ss/ssdata/out`, `ss/ssz700/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 短提示 + 小 JSON 输出, timeout ≥300s |
| **🧮 接触流形 · 导航地图 (e∥进度/e⊥偏离)** | - | `ss/ssmani_c/out` | 65/65/1 | ✅ | `ss/n_calib_mani/out`, `ss/ss2d3d/out`, `ss/ss_mani_eng/out` +2 | ✅ 5/5 | TASK-01-FW,TASK-06-TRAY | 插拔力上限可配 · 超限即退 (MON) |
| **🧠 流形专家预测器 (JEPA: 潜空间→流形→动作)** | - | `ss/ssmani_exp/out` | 65/65/1 | ✅ | `ss/n_calib_mani/out`, `ss/ss2d3d/out`, `ss/ss_mani_eng/out` +3 | ✅ 6/6 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🧮 性能流形 · 耦合代价 (V_p/η)** | - | `ss/ssmani_p/out` | 65/65/1 | ✅ | `ss/ss2d3d/out`, `ss/ss_mani_eng/out`, `ss/ssmani_exp/out` +1 | ✅ 4/4 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🔀 训练/推理** | - | `ss/ssmode/out` | 65/65/1 | ✅ | `ss/ssdata/out` | ✅ 1/1 | — | 见能力清单 |
| **🧩 SU(2) 统一状态空间 (二阶特殊酉群)** | - | `ss/ssobs/out` | 65/65/1 | ✅ | `ss/sssensor/out` | ✅ 1/1 | — | 按 Manifest + 适配器接入, 能力契约不变 |
| **📈 先验动力学预测器** | - | `ss/sspred/out` | 65/65/1 | ✅ | `ss/ssest/out` | ✅ 1/1 | — | 见能力清单 |
| **🔍 异常推理器 (LLM)** | - | `ss/ssreason/out` | 65/65/1 | ✅ | `ss/n_vlm_llm/out`, `ss/ss_mem_share/out`, `ss/ssobs/out` | ✅ 3/3 | — | 见能力清单 |
| **🧭 动作调制器** | - | `ss/sssched/out` | 65/65/1 | ✅ | `ss/n_board_frame/out`, `ss/n_intent_direct/out`, `ss/n_l2_muscle/out` +10 | ✅ 13/13 | TASK-01-FW,TASK-06-TRAY | 0~800mm 覆盖多层工位; 双臂干涉检测 + 协同节拍; 宏动定位 + 微调收敛, 末端重复性 ≤0.05mm; 插 |
| **📡 融合定位建图** | - | `ss/sssensor/out` | 65/65/1 | ✅ | `ss/ss2d3d/out`, `ss/ssaoi/out`, `ss/ssdata/out` +1 | ✅ 4/4 | TASK-01-FW,TASK-06-TRAY | 跨工位流转成功率 ≥97% |
| **① 接近 · SK01** | - | `ss/sssk1/out` | 65/65/1 | ✅ | `ss/sslimit/out` | ✅ 1/1 | — | 见能力清单 |
| **② 对位 · SK02** | - | `ss/sssk2/out` | 65/65/1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 对位残差 ≤0.5mm · 重投影 rmse 合格 |
| **③ 下降 · SK03** | - | `ss/sssk3/out` | 65/65/1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **④ 抓取 · SK04** | - | `ss/sssk4/out` | 65/65/1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 抓取成功率 ≥97% |
| **⑤ 抬起 · SK05** | - | `ss/sssk5/out` | 65/65/1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **⑥ 转移 · SK06** | - | `ss/sssk6/out` | 65/65/1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 抓取成功率 ≥97% |
| **⑦ 插入 · SK07** | - | `ss/sssk7/out` | 65/65/1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 插入成功率 ≥99% · 头到孔底 <4mm; 插拔力上限可配 · 超限即退 (MON) |
| **⑧ 完成 · SK08** | - | `ss/sssk8/out` | 65/65/1 | ✅ | `ss/sslimit/out`, `ss/ssskill/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 抓取成功率 ≥97% |
| **🛠 L3 技能序列编排** | - | `ss/ssskill/out` | 65/65/1 | ✅ | `ss/n_vlm_llm/out`, `ss/ssdata/out`, `ss/ssreason/out` +1 | ✅ 4/4 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🖐 触觉感知** | - | `ss/sstactile/out` | 65/65/1 | ✅ | `ss/ssdata/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 外观缺陷检出率按 AOI 口径; 插拔力上限可配 · 超限即退 (MON) |
| **📊 仿真波形** | - | `ss/ssvideo/out` | 65/65/1 | ✅ | `ss/ssmani_c/out`, `ss/ssmani_p/out`, `ss/ssobs/out` +1 | ✅ 4/4 | — | 见能力清单 |
| **🎥 操作视频** | - | `ss/ssvideo2/out` | 65/65/1 | ✅ | `ss/ssworld/out`, `ss/swvideo/out` | ✅ 2/2 | — | 见能力清单 |
| **🧠 VLM 通用视觉编码器 (SmolVLA)** | - | `ss/ssvlm/out` | 65/65/1 | ✅ | `ss/ss_lora_l3/out`, `ss/ss_seg/out`, `ss/sscap/out` +2 | ✅ 5/5 | TASK-01-FW,TASK-06-TRAY | 单颗 CT ≤3.15s (PVT) · 取放精度 单边 ≤1mm/角 ≤1° · 成功率 ≥99% (PVT) · 载 |
| **🌍 物理世界** | - | `ss/ssworld/out` | 65/65/1 | ✅ | `ss/ssact/out` | ✅ 1/1 | — | 切换 <30s; 抬升闸放开仍须慢速+警报在先 · 听「要碰撞」立即全停 |
| **🎯 YOLO 目标检测** | - | `ss/ssyolo/out` | 65/65/1 | ✅ | `ss/ss_l5/out`, `ss/ssdata/out` | ✅ 2/2 | TASK-01-FW,TASK-06-TRAY | 型号规格识别 100% (POC ≥98%) · 换型 ≤30min · 新型号配置/学习 ≤3h; 空/满/异常三态判 |
| **🖥 Z700 真机信号 (全信号观测 · 物理世界输出)** | - | `ss/ssz700/out` | 65/65/1 | ✅ | （源节点/无上游） | —(源) | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🧪 光模块插拔 · 环境渲染图像源 (Z-MAX 引擎逐帧真图)** | - | `ss/swds/out` | 65/65/1 | ✅ | `ss/ssdata/out`, `ss/ssyolo/out`, `ss/swworld/out` | ✅ 3/3 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🎯 INTACT 插拔策略 · 光模块抓取插入 (本域微调 · 零搜索)** | - | `ss/swintact/out` | 65/65/1 | ✅ | `ss/sscap/out`, `ss/ssintact/out`, `ss/swds/out` | ✅ 3/3 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🎬 插拔渲染视频 (从 Z-MAX 引擎取出 · 实况窗)** | - | `ss/swvideo/out` | 65/65/1 | ✅ | `ss/swworld/out` | ✅ 1/1 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |
| **🌍 Z-MAX 引擎 · 光模块插拔真物理 (模型动作真下发 env.step)** | - | `ss/swworld/out` | 65/65/1 | ✅ | `ss/n_realscene/out`, `ss/ssworld/out`, `ss/swintact/out` | ✅ 3/3 | TASK-01-FW,TASK-06-TRAY | 见能力清单 |

## 复核

```bash
venvs/dds-venv/bin/python tools/verify_feature_io.py --seconds 6
```
