#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 Z-MAX 全局数据空间 (Global Data Space) —— **权威映射表 · 单一真源**

老倪 2026-09-29: 「构建全局数据空间的映射关系, 要有数据闭环流程 …… 应用 DDS 技术,
全面数据质量管理, 做到全链路 topic 可视化」

本文件 = 全局数据空间的**映射表本身**(不是文档): 谁发什么/谁消费/频率/QoS/质量判据,
以及数据闭环每一环节的入口·产物·质量门·证据来源。控制台(DreamView 风格)、守护进程、
巡检脚本、网页都从**这一处**读, 不许再各写一份。

三层映射 (老倪的分层口径):
  ① 物理层  话题 ↔ IDL 类型 ↔ QoS ↔ 频率      → TOPICS
  ② 语义层  话题 ↔ 生产者/消费者 ↔ 画布节点   → TOPICS[*]["producer"/"consumers"] + node 字段
  ③ 闭环层  环节 ↔ 输入/产物 ↔ 质量门         → CLOSED_LOOP

规矩:
  · 缺测 = -1.0, **不许用 0 冒充**(0 是合法实测值)  —— 全空间统一
  · 每个字段必须能追到真实来源; 追不到的不许进表(标 unverified 并写明为什么)
  · prod 模式 = 量产零开销(不建 DDS 参与者); diag/calib/test = 各自话题子集
"""

# ─────────────────────── 元信息 ───────────────────────
VERSION = "1.0.0"
UPDATED = "2026-10-10"
DDS_PREFIX = "zmax/"          # 实际话题名 = DDS_PREFIX + key  (见 zmax_dds/zmax_node.py:95)

# 类型定义真源(当前在仓库外, 见 "收口计划")
TYPES_SRC = "/home/ubuntu/zmax/dds/ss_types.py"      # 9 个状态空间类型
TYPES_SRC_HW = "/home/ubuntu/zmax/dds/zmax_types.py"  # 4 个三端类型
TYPES_SRC_LINK = "tools/gui/dds_link_bus.py"          # link_value (画布连线值)

# ─────────────────────── ① 物理层: 话题表 ───────────────────────
# qos: state = RELIABLE·KEEP_LAST(1)·TRANSIENT_LOCAL(latch, 新订阅者立刻拿最新)
#      beat  = BEST_EFFORT·KEEP_LAST(1)          (丢帧无妨, 低延迟)
#      cmd   = RELIABLE·KEEP_ALL                 (一条都不许丢)
QOS_LABEL = {
    "state": "RELIABLE·KEEP_LAST(1)·TRANSIENT_LOCAL",
    "beat": "BEST_EFFORT·KEEP_LAST(1)",
    "cmd": "RELIABLE·KEEP_ALL",
}

TOPICS = {
    # ── 三端(4060/Orin/Mac/ECS) ──────────────────────────────────────────
    "hw_state": {
        "type": "zmax::HardwareState", "src": TYPES_SRC_HW, "rate_hz": 0.33, "qos": "state",
        "producer": "zmax_dds_publisher.py --interval 3 (zmax-dds-pub.service)",
        "consumers": ["zmax_dds_aggregator.py → JSON", "控制台 硬件页/数据空间页", "网页工位总览"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["node", "role", "backend", "util_pct", "mem_used_mb/mem_total_mb",
                       "temp_c", "power_w", "cpu_util_pct", "disk_free_gb", "train_steps_per_s"],
        "quality": ["freshness", "hz_tol", "no_zero_fake", "range", "unit"],
        "provenance": "nvidia-smi / /proc / torch.backends.mps",
    },
    "train_prog": {
        "type": "zmax::TrainProgress", "src": TYPES_SRC_HW, "rate_hz": 0.33, "qos": "state",
        "producer": "训练脚本写进度文件 → zmax_dds_publisher.py",
        "consumers": ["zmax_dds_aggregator.py → JSON", "控制台 训练/数据空间页"],
        "modes": ["diag", "test"],
        "key_fields": ["job", "layer", "step/total/pct", "loss", "best_obs", "best_act",
                       "gain_obs_pct", "gain_act_pct", "running"],
        "quality": ["freshness", "hz_tol", "loss_finite", "gain_reported", "monotonic_step"],
        "provenance": "训练进度文件(真实逐 N 步写出)",
    },
    "deploy_cmd": {
        "type": "zmax::DeployCommand", "src": TYPES_SRC_HW, "rate_hz": 0.0, "qos": "cmd",
        "producer": "ECS / 控制台(人工晋级)",
        "consumers": ["4060 部署执行", "Orin 部署执行"],
        "modes": ["test"],
        "key_fields": ["issuer", "layer", "artifact", "action(promote/rollback/stop_train)", "note"],
        "quality": ["audit_issuer", "artifact_exists"],
        "provenance": "人工/守护发起的晋级指令",
    },
    "heartbeat": {
        "type": "zmax::Heartbeat", "src": TYPES_SRC_HW, "rate_hz": 0.2, "qos": "beat",
        "producer": "各端守护", "consumers": ["zmax_dds_aggregator.py", "控制台节点灯"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["node", "role", "alive", "extra"],
        "quality": ["liveness", "freshness"],
        "provenance": "各端进程自身",
    },
    # ── 状态空间 ────────────────────────────────────────────────────────
    "ss_state": {
        "type": "zmax::SSState", "src": TYPES_SRC, "rate_hz": 10.0, "qos": "beat",
        "producer": "zmax_dds_ss_daemon.py ← 真机只读 tap ~/zmax/zmax_data/ss_live/state_*.jsonl",
        "consumers": ["控制台 数据空间页/状态空间页", "备份端"],
        "modes": ["calib", "test"],
        "key_fields": ["ts", "layer", "stage", "vec/dim", "manifold_theta", "manifold_norm",
                       "pos_x/y/z", "lyap_v/lyap_dv", "source"],
        "quality": ["freshness", "hz_tol", "negative_age_reject", "dim_match", "no_zero_fake"],
        "provenance": "真机 tap(只读) / 引擎 / 仿真 —— source 字段自述",
    },
    "ss_action": {
        "type": "zmax::SSAction", "src": TYPES_SRC, "rate_hz": 10.0, "qos": "beat",
        "producer": "zmax_dds_ss_daemon.py ← tap proposal_*.jsonl (本机推理 8790 输出)",
        "consumers": ["控制台 数据空间页", "审计(动作必须可追闸门)"],
        "modes": ["calib", "test"],
        "key_fields": ["ts", "kind(joint/tcp/gripper/rt)", "joints", "tcp_pose", "gripper",
                       "speed", "gate_pass", "gate_reason", "source"],
        "quality": ["freshness", "hz_tol", "gate_audit", "dim_match", "no_zero_fake", "finite"],
        "provenance": "推理输出 / 真机下发记录",
    },
    "ss_infer": {
        "type": "zmax::SSInfer", "src": TYPES_SRC, "rate_hz": 0.5, "qos": "beat",
        "producer": "zmax_dds_ss_daemon.py ← http://127.0.0.1:8790/health",
        "consumers": ["控制台 推理页/数据空间页"],
        "modes": ["diag", "test"],
        "key_fields": ["ts", "model", "layer", "latency_ms", "device", "out_vec", "conf", "ok"],
        "quality": ["freshness", "hz_tol", "latency_budget", "no_zero_fake"],
        "provenance": "本机推理服务 /health(真实推理计数)",
    },
    "ss_canvas": {
        "type": "zmax::SSCanvasNode", "src": TYPES_SRC, "rate_hz": 0.5, "qos": "state",
        "producer": "画布/引擎节点状态上报",
        "consumers": ["控制台 画布页/数据空间页"],
        "modes": ["test"],
        "key_fields": ["ts", "node_id", "name", "layer", "status", "fps", "last_ms", "counter"],
        "quality": ["freshness", "hz_tol", "name_primary", "status_enum"],
        "provenance": "节点真实执行(每次 run 一行)",
    },
    "ss_macro": {
        "type": "zmax::SSMacro", "src": TYPES_SRC, "rate_hz": 0.2, "qos": "state",
        "producer": "五层记忆/宏观层(SS_MACRO)",
        "consumers": ["控制台 记忆页/数据空间页"],
        "modes": ["test"],
        "key_fields": ["ts", "layer_name", "intent", "plan", "progress", "recalled"],
        "quality": ["freshness", "hz_tol", "layer_enum", "progress_range"],
        "provenance": "总装 Qwen / 记忆层",
    },
    "ss_nodes": {
        "type": "zmax::SSNodes", "src": TYPES_SRC, "rate_hz": 0.2, "qos": "state",
        "producer": "数据空间自描述(谁在发什么)",
        "consumers": ["控制台 数据空间页(节点清单)"],
        "modes": ["test"],
        "key_fields": ["ts", "nodes", "topics", "publish_hz"],
        "quality": ["freshness", "hz_tol", "self_describe_match"],
        "provenance": "发布端自述 —— **必须与实测频率对账**, 否则是假自述",
    },
    "ss_calib": {
        "type": "zmax::SSCalib", "src": TYPES_SRC, "rate_hz": 0.2, "qos": "state",
        "producer": "zmax_dds_ss_daemon.py ← 标定真源文件(calib.json/handeye/align/gate)",
        "consumers": ["控制台 标定页/数据空间页", "现场核对(mm/deg 口径)"],
        "modes": ["calib", "test"],
        "key_fields": ["ts", "kind", "src_frame/dst_frame", "T(16)", "plane_z_mm", "tx/ty/tz",
                       "rx/ry/rz_deg", "rms_mm", "samples", "valid"],
        "quality": ["freshness", "valid_flag", "rms_budget", "no_zero_fake", "unit"],
        "provenance": "标定真源文件(与 zmax_params.py 同源)",
    },
    "ss_diag": {
        "type": "zmax::SSDiag", "src": TYPES_SRC, "rate_hz": 0.5, "qos": "beat",
        "producer": "zmax_dds_ss_daemon.py(延时/帧龄/吞吐/健康度)",
        "consumers": ["控制台 监控页/数据空间页", "运维告警"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["ts", "node", "kind", "latency_ms", "frame_age_s", "hz", "count",
                       "dropped", "queue", "health", "level", "msg"],
        "quality": ["freshness", "hz_tol", "negative_age_reject", "range", "level_enum"],
        "provenance": "实测(非估算)",
    },
    "ss_test": {
        "type": "zmax::SSTest", "src": TYPES_SRC, "rate_hz": 0.0, "qos": "state",
        "producer": "取证/回归脚本(verify_*.py / preflight)",
        "consumers": ["控制台 评估页/数据空间页"],
        "modes": ["test"],
        "key_fields": ["ts", "suite", "case", "passed", "dur_ms", "total", "failed", "detail"],
        "quality": ["counts_consistent(total = passed + failed)"],
        "provenance": "最近一次真跑的取证 JSON",
    },
    "ss_plan": {
        "type": "zmax::SSPlan", "src": TYPES_SRC, "rate_hz": 0.5, "qos": "state",
        "producer": "zmax_dds_ss_daemon.py ← MoveIt plan-only 镜像 tap ~/zmax/zmax_data/runtime/moveit_plan/live_plan.jsonl",
        "consumers": ["控制台 数据空间页/独立数据空间窗口", "叠加层(画规划折线)", "审计(轨迹必须可追同源闸)"],
        "modes": ["calib", "test"],
        "key_fields": ["ts", "source", "plan_code", "n_points", "joints_path(n×6)", "tcp_path(n×3,m)",
                       "start_joints", "goal_xyz", "end_err_mm", "gate_same_source", "gate_reason",
                       "frame_age_s"],
        "quality": ["freshness", "hz_tol", "plan_code_success", "path_dim(n%6==0)", "same_source_gate",
                    "frame_age_positive", "no_zero_fake"],
        "provenance": "MoveIt2 /plan_kinematic_path (plan-only 容器 zmax-moveit, ROS_DOMAIN_ID=42, "
                      "allow_trajectory_execution=False) → FK 逐路点 → JSONL tap → DDS",
    },
    "link_value": {
        "type": "zmax::LinkValue", "src": TYPES_SRC_LINK, "rate_hz": 5.0, "qos": "beat",
        "producer": "画布连线总线(dds_link_bus)",
        "consumers": ["控制台 画布页(节点间传值可视化)"],
        "modes": ["calib", "test"],
        "key_fields": ["link", "value", "src_node", "dst_node"],
        "quality": ["freshness", "hz_tol", "finite"],
        "provenance": "画布上真实连线求值",
    },
    "ss_cfg_names": {
        "type": "zmax::SSConfigNames", "src": TYPES_SRC, "rate_hz": 0.2, "qos": "state",
        "producer": "状态空间数据空间守护 (tools/dds/ss_daemon.py · zmax-dds-ss.service) "
                    "← 画布节点 n_calib_mani(🧮 主参数 M) 的 cfg_entries / cfg_loaded_at 真源",
        "consumers": ["控制台 数据空间页", "独立窗口/网页端", "报告/审计"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["ts", "names", "loaded_at", "source", "note"],
        "quality": ["freshness", "names_only", "no_path_no_hash", "no_fake_when_unloaded"],
        "provenance": ("主参数节点执行 import_config_files() → write_into_node() 时把逐文件清单写进该节点；"
                       "本话题只读这条记录 ⇒ names 就是节点真加载过的**配置名称**(不含路径/哈希/计数)。"
                       "周期 5s (老倪 2026-10-14: 「需要发出加载的配置名称的 topic, 字符串就可以, 周期5秒」)"),
    },
    "ss_meta_task": {
        "type": "zmax::SSMetaTask", "src": TYPES_SRC, "rate_hz": 0.2, "qos": "state",
        "producer": "状态空间数据空间守护 (tools/dds/ss_daemon.py · zmax-dds-ss.service) "
                    "← 派生器 tools/ss_meta_task.py (复用 export_meta_doc.build_meta_tasks 同一条映射链)",
        "consumers": ["控制台 数据空间页", "状态空间工程/画布", "元层(ss_moe)/大屏", "报告/审计"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["ts", "task_id", "n", "n_all", "layers", "prio", "fn_ids", "src"],
        "quality": ["derived_from_true_source", "no_intent_readthrough", "counts_match_enabled_nodes"],
        "provenance": ("元任务 = 功能(FN-SYSx-N) + 全部配置参数 + 依赖 + 验证方法 + 归属层; "
                       "任务(TASK-xx) ──enabled_nodes──> 画布节点 ──module_ref──> 功能 ──fn_id──> 元任务。"
                       "内容真源现算(config_meta.json/ss_task_binding.json/画布), 意图只决定选哪一批; "
                       "周期 5s, 出口=主参数节点 n_calib_mani (与已加载配置名同一节拍)"),
    },
    "ss_action_chunk": {
        "type": "zmax::SSActionChunk", "src": TYPES_SRC, "rate_hz": 0.2, "qos": "state",
        "producer": "状态空间数据空间守护 (tools/dds/ss_daemon.py · zmax-dds-ss.service) "
                    "← 常驻回路 tools/ss_engine_loop.py 经 tools/ss_chunk_pipeline.py 落盘",
        "consumers": ["控制台 信号分析页", "🦾 技能派发循环服务 (zmax-ss-skill-dispatch)", "报告/审计"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["ts", "cycle", "h", "stage", "stage_idx", "chunk", "ff", "u", "lam",
                       "turn_mean_deg", "step_delta", "jerk", "u_norm0", "skill_list",
                       "dispatch_age_s", "chunk_src", "ff_mode", "note"],
        "quality": ["chunk_is_multi_step", "ff_seq_length_equals_h", "weighted_and_modulated",
                    "safety_clamped", "staleness_flagged"],
        "provenance": ("「Flow Matching Action Head 的输出, 是个 chunk action, 预测 [a_t,…,a_{t+H-1}] … "
                       "应该有输出 topic, 在信号分析里显示」(老倪 2026-10-15): 块=流形引擎一次求解的测地线规划 "
                       "→ 逐点解码; ff=前馈加速器(训练左脑 MLP)的 H 步序列; u=加权+逐拍动作调制+逐拍安全后的"
                       "执行序列(待技能选取); 真源 zmax_data/ss_live/chunk_latest.json"),
    },
    "ss_meta_pred": {
        "type": "zmax::SSMetaPred", "src": TYPES_SRC, "rate_hz": 0.2, "qos": "state",
        "producer": "状态空间数据空间守护 (tools/dds/ss_daemon.py · zmax-dds-ss.service) "
                    "← 预测器 tools/ss_meta_predict.py (输入=流形引擎驱动扭矩 zmax/ss_torque)",
        "consumers": ["控制台 信号分析页", "状态空间工程/画布", "报告/审计"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["ts", "ts_pred", "scene", "n_meta", "n_cand", "top_ids", "top_scores",
                       "input_src", "input_ok", "input_age_s", "method", "trained", "frozen", "note"],
        "quality": ["input_is_driving_torque", "no_fake_power", "frozen_flagged", "staleness_flagged"],
        "provenance": ("「将元任务预测的topic，放到信号分析」(老倪 2026-10-14): 输入=流形引擎驱动扭矩 "
                       "(zmax/ss_torque, 10Hz), 输出=各元任务(功能 FN-SYSx-N)的得分 + top-k; "
                       "真源 zmax_data/ss_live/meta_pred.json; trained=0/frozen=1 时**如实标注** "
                       "「未训练头/恒定输入降级」, 不假装有预测力; 帧龄 >180s 写「预测陈旧」"),
    },
    "ss_energy": {
        "type": "zmax::SSEnergy", "src": TYPES_SRC, "rate_hz": 0.5, "qos": "state",
        "producer": "流形引擎能量探针 tools/manifold_energy_probe.py → tap "
                    "zmax_data/ss_live/energy_*.jsonl (真跑一轮 pipeline 迭代的实测)",
        "consumers": ["流形引擎画布节点", "控制台 数据空间页/训练页", "备份端", "报告/审计"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["ts", "node", "state", "e_total_cj", "e_base_cj", "e_boost_cj", "p_in_w", "w_in_j",
                       "eta_total_cjj", "n_levels_active", "shells[].layer/shell_n/e_layer_cj/e_cum_cj/"
                       "e_work_cj/e_standing_cj/tau_cj/omega_hz/eta_cjj/feasible_r/lora_r/lora_boost_cj",
                       "shell_monotonic_ok", "feasible_narrowing_ok", "sum_ok", "criterion"],
        "quality": ["freshness", "hz_tol", "energy_nonneg", "sum_consistent", "shell_monotonic",
                    "feasible_narrowing", "eta_sign", "finite", "no_zero_fake"],
        "provenance": ("nvidia-smi power.draw(真瓦特) + 各层训练日志真实指标(势能序列) + 步时实测 ⇒ "
                       "发动机类比: 输入功率 P_in / 转速 ω / 扭矩 τ=P每循环做功 / 能量 E=τ·N / 效率 η=E/W_in。"
                       "1 CJ ≜ 把归一化势能下降 1.0 的能力 (逐层同口径); 总能量 E_total = Σ(存量+做功)"),
    },
    "ss_engine": {
        "type": "zmax::SSManifoldStep", "src": TYPES_SRC, "rate_hz": 10.0, "qos": "beat",
        "ros_alias": "/manifold_engine/step",
        "producer": "流形引擎常驻周期回路 tools/ss_engine_loop.py (每周期真调 ManifoldEngine.step) "
                    "→ tap /dev/shm/zmax_ss_engine/engine_*.jsonl; 由状态空间工程驱动 "
                    "(工程/活跃任务/主参数 M 每 5s 跟随真源)",
        "consumers": ["控制台 数据空间页", "实时监控", "画布「🧮 流形引擎」对照", "L2 执行层"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["ts", "cycle", "hz", "step_ms", "provider", "traj_at", "traj_idx", "traj_n",
                       "replay", "project", "task_id", "task_name", "scene", "M", "inertia", "calib",
                       "decode_src", "p[16]", "p_norm", "phi", "grad_norm", "action[4]", "action_norm",
                       "confidence", "anomaly", "residual", "momentum", "hom_enabled", "hom_mode",
                       "hom_vitality", "hom_gain", "hom_dominant", "hom_urgency", "hom_veto"],
        "quality": ["freshness", "finite", "no_zero_fake", "step_per_period"],
    },
    "ss_stage": {
        "type": "zmax::SSStage", "src": TYPES_SRC, "rate_hz": 5.0, "qos": "beat",
        "ros_alias": "/ss/stage",
        "producer": "状态空间工程驱动守护 tools/dds/ss_daemon.py (只读转发) ← 3D 面板快照 "
                    "zmax_data/ss_live/trace_live.json 的阶段字段; 阶段真源 = "
                    "src/lerobot/policies/left_right/state_space/cognition.py:31 ActionModulator"
                    " (STAGES 13 段 / 插拔八段 0..7 / STAGE_V_CAP 阶段限速 m/s)",
        "consumers": ["控制台 实时监控·信号分析", "数据空间页", "现场状态机核对"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["ts", "idx", "idx8", "name", "v_cap", "done", "age_s", "source", "note"],
        "quality": ["freshness", "no_zero_fake", "stage_monotonic_within_episode"],
        "provenance": ("老倪 2026-10-15「动作调制器 还有 八阶段状态机, 在哪里?」+「八个状态, 是哪个 topic "
                       "发出来的?」—— 在这之前**没有任何话题**发这八个状态: 阶段只是 trace_live.json 里的"
                       "一个字符串(\"阶段\": \"抓取\"), 信号分析页只收数值 ⇒ 看不到状态机。本话题把它做成"
                       "真实 DDS 通道: idx=13 段序号, idx8=插拔八段序号(0..7), v_cap=本阶段限速(m/s)。"),
    },
    "ss_torque": {
        "type": "zmax::SSDrivingTorque", "src": TYPES_SRC, "rate_hz": 10.0, "qos": "beat",
        "ros_alias": "/manifold_engine/driving_torque",   # 老倪 2026-10-13 规格里的 ROS 话题名
        "producer": "流形引擎驱动扭矩发布器 tools/tdrive_bus.py → tap "
                    "zmax_data/ss_live/torque_*.jsonl (真源主参数 M + 真实势场 −∇Φ 逐帧算)",
        "consumers": ["实时监控 (📈 全局数据空间信号源)", "控制台 数据空间页", "L2 执行层 (限幅后)", "报告/审计"],
        "modes": ["diag", "calib", "test"],
        "key_fields": ["ts", "torque[6]", "torque_norm", "torque_inv[6]", "unit", "metric_tensor[36]",
                       "metric_dim", "potential_gradient[6]", "neg_gradient[6]", "phi", "health",
                       "status", "gain", "x[3]", "gates", "source", "unit_note",
                       # 🏷 标识信息 (老倪 2026-10-14): 一帧载荷自带"在为哪个任务/哪个产品干活"
                       "task_id", "task_name", "product", "product_prime", "m_scale", "identity_json"],
        "quality": ["freshness", "finite", "unit", "no_zero_fake", "metric_definite",
                    "torque_matches_definition", "health_gain_consistent"],
        "provenance": ("T_drive = M·(−∇Φ): M = 主参数度量张量真源 (config/calib/zmax_manifold.json, dim6); "
                       "−∇Φ = 真实势场负梯度 (src/lerobot/memory/potential_field.py 解析梯度: "
                       "L2 肌肉记忆技能场 + L3 流程场 + L4 障碍/世界项, 按逐层开关合成, 全关 ⇒ 零不干预)。"
                       "转动惯量 I ↔ M, 角加速度 α ↔ −∇Φ (老倪 2026-10-13 规格)。"
                       "通道: 规格三通道 1000Hz 电机 / 100Hz 监控 / 10Hz 数据 —— **当前只接 10Hz 数据通道**, "
                       "100Hz/1000Hz 未接 (无实时消费者, 如实标注, 不得当作已实现)。"),
    },
    "ds_dataset": {
        "type": "zmax::SliceJSON", "src": "(JSON 切面, 见 provenance)", "rate_hz": 0.05, "qos": "state",
        "area": "数据集", "status": "已登记 · 待接 DDS 生产者 (当前真源为只读工具 JSON)",
        "producer": "tools/dataset_inventory.py --json",
        "consumers": ['控制台 数据集页/数据空间页', '大屏 dashboard_source.py'],
        "modes": ["diag", "calib", "test"],
        "key_fields": ['real_path', 'category', 'size_bytes', 'file_count', 'latest_mtime'],
        "quality": ["freshness", "no_zero_fake", "source_on_disk"],
        "provenance": "各功能区 = **同一数据源的不同切面**: 由只读工具真扫盘/真采集产出 JSON, 登记为话题后即可走数据总线统一体现; 生产者脚本产出前不得由消费者自行编数",
    },
    "ds_model": {
        "type": "zmax::SliceJSON", "src": "(JSON 切面, 见 provenance)", "rate_hz": 0.05, "qos": "state",
        "area": "模型引擎", "status": "已登记 · 待接 DDS 生产者 (当前真源为只读工具 JSON)",
        "producer": "tools/model_inventory.py --json",
        "consumers": ['控制台 模型引擎页/数据空间页', '大屏 dashboard_source.py'],
        "modes": ["diag", "calib", "test"],
        "key_fields": ['layer', 'name', 'active', 'size_h', 'mtime', 'gpu.util', 'mem_used_mb', 'temp_c'],
        "quality": ["freshness", "no_zero_fake", "source_on_disk"],
        "provenance": "各功能区 = **同一数据源的不同切面**: 由只读工具真扫盘/真采集产出 JSON, 登记为话题后即可走数据总线统一体现; 生产者脚本产出前不得由消费者自行编数",
    },
    "ds_scene": {
        "type": "zmax::SliceJSON", "src": "(JSON 切面, 见 provenance)", "rate_hz": 0.05, "qos": "state",
        "area": "场景", "status": "已登记 · 待接 DDS 生产者 (当前真源为只读工具 JSON)",
        "producer": "tools/scene_edit.py list --json",
        "consumers": ['控制台 Sim&Real 页', '8793 叠加服务', '建图同步 map_marker_sync.py'],
        "modes": ["diag", "calib", "test"],
        "key_fields": ['objects[]', 'markers[]', 'fences[]', 'trajectories[]', 'visibility.deleted/traj_show'],
        "quality": ["freshness", "no_zero_fake", "source_on_disk"],
        "provenance": "各功能区 = **同一数据源的不同切面**: 由只读工具真扫盘/真采集产出 JSON, 登记为话题后即可走数据总线统一体现; 生产者脚本产出前不得由消费者自行编数",
    },
    "ds_endpoint": {
        "type": "zmax::SliceJSON", "src": "(JSON 切面, 见 provenance)", "rate_hz": 0.05, "qos": "state",
        "area": "监控", "status": "已登记 · 待接 DDS 生产者 (当前真源为只读工具 JSON)",
        "producer": "tools/remote_monitor_aggregate.py --json",
        "consumers": ['控制台 监控页/数据空间页', '大屏', '飞书卡片'],
        "modes": ["diag", "calib", "test"],
        "key_fields": ['endpoints[].name/url/ok/status/data_age_s/stale', 'same_source[].fact/consistent/tol'],
        "quality": ["freshness", "no_zero_fake", "source_on_disk"],
        "provenance": "各功能区 = **同一数据源的不同切面**: 由只读工具真扫盘/真采集产出 JSON, 登记为话题后即可走数据总线统一体现; 生产者脚本产出前不得由消费者自行编数",
    },
    "ds_version": {
        "type": "zmax::SliceJSON", "src": "(JSON 切面, 见 provenance)", "rate_hz": 0.05, "qos": "state",
        "area": "版本", "status": "已登记 · 待接 DDS 生产者 (当前真源为只读工具 JSON)",
        "producer": "tools/verify_version_sync.py --json",
        "consumers": ['控制台 版本同步页/数据空间页', '大屏'],
        "modes": ["diag", "calib", "test"],
        "key_fields": ['canonical', 'ok', 'remote_has_tag', 'release_tag', 'deviations[]'],
        "quality": ["freshness", "no_zero_fake", "source_on_disk"],
        "provenance": "各功能区 = **同一数据源的不同切面**: 由只读工具真扫盘/真采集产出 JSON, 登记为话题后即可走数据总线统一体现; 生产者脚本产出前不得由消费者自行编数",
    },
    "ds_aoi": {
        "type": "zmax::SliceJSON", "src": "(JSON 切面, 见 provenance)", "rate_hz": 0.05, "qos": "state",
        "area": "AOI", "status": "已登记 · 待接 DDS 生产者 (当前真源为只读工具 JSON)",
        "producer": "工控机 AOI 10082/10083 (/last_result)",
        "consumers": ['控制台 工控机页', 'remote_monitor_aggregate'],
        "modes": ["diag", "calib", "test"],
        "key_fields": ['verdict', 'count', 'ms', 'n'],
        "quality": ["freshness", "no_zero_fake", "source_on_disk"],
        "provenance": "各功能区 = **同一数据源的不同切面**: 由只读工具真扫盘/真采集产出 JSON, 登记为话题后即可走数据总线统一体现; 生产者脚本产出前不得由消费者自行编数",
    },
    "ds_hil": {
        "type": "zmax::SliceJSON", "src": "(JSON 切面, 见 provenance)", "rate_hz": 0.05, "qos": "state",
        "area": "HIL", "status": "已登记 · 待接 DDS 生产者 (当前真源为只读工具 JSON)",
        "producer": "tools/hil_local_api.py (8795 /hil/state)",
        "consumers": ['控制台 数据空间页', '手机现场页'],
        "modes": ["diag", "calib", "test"],
        "key_fields": ['stage', 'frame_age_s', 'layers', 'events', 'canvas_nodes'],
        "quality": ["freshness", "no_zero_fake", "source_on_disk"],
        "provenance": "各功能区 = **同一数据源的不同切面**: 由只读工具真扫盘/真采集产出 JSON, 登记为话题后即可走数据总线统一体现; 生产者脚本产出前不得由消费者自行编数",
    },
    "ds_arch": {
        "type": "zmax::SliceJSON", "src": "(JSON 切面, 见 provenance)", "rate_hz": 0.05, "qos": "state",
        "area": "架构", "status": "已登记 · 待接 DDS 生产者 (当前真源为只读工具 JSON)",
        "producer": "tools/arch_graph.py --json",
        "consumers": ['控制台 系统架构页/数据空间页', '工程库'],
        "modes": ["diag", "calib", "test"],
        "key_fields": ['nodes', 'links', 'layers[]', 'edges[]'],
        "quality": ["freshness", "no_zero_fake", "source_on_disk"],
        "provenance": "各功能区 = **同一数据源的不同切面**: 由只读工具真扫盘/真采集产出 JSON, 登记为话题后即可走数据总线统一体现; 生产者脚本产出前不得由消费者自行编数",
    },
}

# ─────────────────────── 遥测模式 → 允许话题 (口径与守护一致) ───────────────────────
# ⚠️ 真源当前是 /home/ubuntu/zmax/dds_ss_daemon.py:51 (MODE_TOPICS) 与
#    tools/gui/zmax_telemetry.py::MODE_TOPICS —— 两处手工同步, 收口后本表为准。
MODE_TOPICS = {   # 🧮 ss_cfg_names: 主参数节点已加载配置名称 (5s, 字符串) 见 ss_daemon.tick
    "prod":  [],
    # 🧾 ss_meta_task = 元任务清单 (主参数节点出口 5s) · 🧾 ss_meta_pred = 元任务**预测值**
    #    (输入=流形引擎驱动扭矩; 老倪 2026-10-14「将元任务预测的topic，放到信号分析」)
    "diag":  ["hw_state", "heartbeat", "ss_infer", "train_prog", "ss_diag", "ss_energy", "ss_torque",
              "ss_cfg_names", "ss_engine", "ss_meta_task", "ss_meta_pred", "ss_stage",
              "ss_action_chunk"],
    "calib": ["ss_state", "ss_action", "link_value", "hw_state", "heartbeat", "ss_calib", "ss_diag",
              "ss_plan", "ss_energy", "ss_torque", "ss_cfg_names", "ss_engine",
              "ss_meta_task", "ss_meta_pred", "ss_stage", "ss_action_chunk"],
    "test":  ["hw_state", "heartbeat", "train_prog", "deploy_cmd", "link_value", "ss_state",
              "ss_action", "ss_infer", "ss_canvas", "ss_macro", "ss_nodes", "ss_calib",
              "ss_diag", "ss_test", "ss_plan", "ss_energy", "ss_torque", "ss_cfg_names", "ss_engine",
              "ss_meta_task", "ss_meta_pred", "ss_stage", "ss_action_chunk"],
}
MODE_TOPICS["dev"] = MODE_TOPICS["test"]

# 8 个功能区切面 (ds_*) 的**登记状态**: 话题/生产者/消费者/质量已在 TOPICS 里定好, 但守护会按
# MODE_TOPICS 预建 DDS 类型, 而 `zmax::SliceJSON` 类型还没落地 ⇒ 现在放进 MODE_TOPICS 会让
# diag 档直接起不来。故单列此处, 落地 SliceJSON(IDL) + 通用 JSON 生产者后并入各档。
MODE_TOPICS_PENDING = {m: [k for k in TOPICS if k.startswith("ds_")] for m in ("diag", "calib", "test")}
DS_SLICES_NEED = "dds/ss_types.py 增 zmax::SliceJSON (string key, string json, double ts) + tools/dds_slice_publish.py"
MODE_DESC = {
    "prod":  "量产: 零开销 —— 不建 DDS 参与者、不开口、不 import cyclonedds",
    "diag":  "诊断: 只取性能/硬件类(不碰状态与标定)",
    "calib": "标定: 状态+动作+连线+标定量(现场核对用)",
    "test":  "测试: 全量 22 话题(取证/回归, 含 8 个功能区切面 ds_*)",
    "dev":   "同 test",
}

# ─────────────────────── ② 语义层: 话题 ↔ 生产者/消费者 ───────────────────────
# 画面上的「节点」= 生产者进程 与 消费者进程; 中间是话题。画布节点与话题的绑定在
# TOPICS[*]["producer"] 里点名的脚本 → 脚本注册的画布节点(见 nodes/library.py)。
PRODUCERS = {
    "4060-硬件发布端": {"unit": "zmax-dds-pub.service", "path": "/home/ubuntu/zmax/dds_publisher.py",
                        "publishes": ["hw_state", "train_prog"]},
    "状态空间数据空间守护": {"unit": "zmax-dds-ss.service", "path": "/home/ubuntu/zmax/dds_ss_daemon.py",
                        "publishes": ["ss_state", "ss_action", "ss_infer", "ss_calib", "ss_diag",
                                      "ss_test", "ss_canvas", "ss_macro", "ss_nodes", "ss_plan",
                                      "ss_energy", "ss_cfg_names"]},
    "流形引擎能量探针": {"unit": None, "path": "tools/manifold_energy_probe.py",
                        "publishes": ["ss_energy"],
                        "note": "写 tap zmax_data/ss_live/energy_*.jsonl; 由 ss_daemon 转发上 DDS"},
    "流形引擎驱动扭矩发布器": {"unit": "tools/tdrive_bus.py (前台/常驻, 10Hz)", "path": "/home/ubuntu/zmax/tools/tdrive_bus.py",
                        "publishes": ["ss_torque"], "source": "真源 M (config/calib/zmax_manifold.json) × 真实 −∇Φ (potential_field 解析梯度)"},
    "DDS→relay 汇聚器": {"unit": "zmax-dds-agg.service", "path": "/home/ubuntu/zmax/dds_aggregator.py",
                        "publishes": [], "subscribes": ["hw_state", "train_prog", "heartbeat"]},
    "画布连线总线": {"unit": None, "path": "tools/gui/dds_link_bus.py",
                        "publishes": ["link_value"]},
}

# ─────────────────────── ③ 闭环层: 数据闭环流程 ───────────────────────
# 每个环节: entry(入口命令) · produces(产物) · gate(质量门 + 判据) · evidence(证据来源) · owner
CLOSED_LOOP = [
    {
        "id": "S0", "name": "采数前自检",
        "entry": "现场核对: 标定 ss_calib.valid=1 · TCP 位姿新鲜(rokae_sdk/tcp_out/latest.json) · 相机帧龄≤1s",
        "produces": "—(门)", "owner": "人/静静",
        "gate": "全绿才许开采集: 手眼 rms≤2mm · TCP 非全 0 · 帧龄>0 且 <1s",
        "evidence": "ss_calib 话题 / latest.json / 8793 工位总览横幅",
        "why": "标定不对 ⇒ 采到的 3D 全是错的, 整轮数据作废(比采不到更贵)",
    },
    {
        "id": "S1", "name": "真机采集",
        "entry": "Orin 侧采集脚本(20s MCAP + 打标)", "owner": "现场/Orin",
        "produces": "数据包: observation.state(6) + action(6) + 图 + label + timestamp",
        "gate": "帧数≥20 · 维度一致(6D) · 图像有效帧率>0 · action≠state(恒等=无效)",
        "evidence": "包内 meta.frames / n_joint / n_action",
        "why": "action==state 的包会让训练学出恒等映射(历史上真踩过)",
    },
    {
        "id": "S2", "name": "上传中转",
        "entry": "POST https://datadrive.world/api/relay/upload", "owner": "Orin 侧",
        "produces": "ECS relay 队列(单包≤100M)", "gate": "上传回执 + 包内帧数/维度一致 + 校验和一致",
        "evidence": "GET /api/relay/status · /api/relay/peek",
        "why": "弹栈取走即删 ⇒ 必须留 peek 先验后取",
    },
    {
        "id": "S3", "name": "入库质量门",
        "entry": "本地弹栈 → 质检 → 构建 LeRobot 数据集(build_orin6d_dataset.py)", "owner": "静静",
        "produces": "LeRobot 数据集(parquet + mp4, 全局 frame_index/timestamp)",
        "gate": "帧数=视频帧数 · 时间戳单调(禁回拨) · float32 定长列表 · episodes 索引 int64",
        "evidence": "数据集 meta/info.json + 逐帧对账脚本",
        "why": "时间戳/索引不全局 ⇒ 训练 IndexError + 视频错位",
    },
    {
        "id": "S4", "name": "训练",
        "entry": "ACT 三阶段(S1 冻结→S2 零样本→S3 真机低 lr 微调, ensemble 必开)", "owner": "静静(4060)",
        "produces": "ckpt + 训练进度文件", "gate": "GPU 负载达标 · loss 有限且下降 · 每 N 步落进度",
        "evidence": "train_prog 话题 / 训练日志", "why": "掉载=每步 CPU 开销 > 计算",
    },
    {
        "id": "S5", "name": "评测",
        "entry": "同口径评测(训练同源预处理 + 留出集 + 平凡基线)", "owner": "静静",
        "produces": "评测 JSON(passed/total/成功率)", "gate": "**有提升**才放行(非仅不回退) · 平凡基线对照",
        "evidence": "ss_test 话题 / reports/*.json", "why": "loss 低≠有效; 不回退≠提升",
    },
    {
        "id": "S6", "name": "发布",
        "entry": "推静态 URL + sha256 + 版本号", "owner": "静静",
        "produces": "https://datadrive.world/models/<name>.safetensors (644)", "gate": "sha256 与本地一致 · HTTP 200 · 可匿名拉取",
        "evidence": "curl -sI 静态 URL", "why": "弹栈队列传模型丢过 4 次",
    },
    {
        "id": "S7", "name": "部署",
        "entry": "DeployCommand(issuer/layer/artifact/action) over DDS → Orin", "owner": "静静/人",
        "produces": "Orin 上的在役权重", "gate": "issuer 可追 · artifact 存在且 sha256 匹配 · 留旧版可回滚",
        "evidence": "deploy_cmd 话题 + 部署日志", "why": "部署是唯一不可逆动作 ⇒ 必须带审计与回滚点",
    },
    {
        "id": "S8", "name": "真实推理与回采",
        "entry": "Orin 真机推理(8790 / Orin 侧)", "owner": "现场",
        "produces": "推理计数 + 真实成功率 + 失败样本", "gate": "infer_count>0 · 成功率按任务口径统计 · 失败帧归档回采",
        "evidence": "ss_infer 话题 / /api/relay/orin/status",
        "why": "无回采 = 开环; 失败样本是下一轮数据的主料",
    },
]

# ─────────────────────── 全面数据质量: 判据(规则 id → 定义) ───────────────────────
QUALITY_RULES = {
    "freshness":        "帧龄 = now - ts, 超阈值(默认 5s) → 只报 diag、状态类降级",
    "negative_age_reject": "ts > now+1 ⇒ 拒用(本机 NTP 曾有 8h 回拨)",
    "no_zero_fake":     "未测量必须 -1.0; 统计字段里 0 的占比 ≈100% 判为假 0",
    "dim_match":        "vec 长度 == dim, 且与声明维度(6 关节/39 观测)一致",
    "monotonic_step":   "训练 step 单调不减; 回退 ⇒ 重启/覆盖, 要标记",
    "loss_finite":      "loss 为有限数(NaN/Inf 直接告警)",
    "gain_reported":    "提升必须带平凡基线对照的 %(缺 = 未证明)",
    "range":            "物理量在合理区间(利用率 0~100, 温度 -20~100)",
    "unit":             "单位与命名一致(util_pct / mem_mb / plane_z_mm / *_deg)",
    "latency_budget":   "推理延时 ≤ 预算(MoE 稳态 101ms, 冷启 6.7s 不算违规)",
    "liveness":         "心跳缺失 > 3×周期 ⇒ 节点掉线",
    "valid_flag":       "标定量 valid=1 才算数(缺测 valid=0/-1)",
    "rms_budget":       "手眼残差 ≤2mm(超 = 标定不合格, 不许用)",
    "audit_issuer":     "指令必须有 issuer(谁发的), 匿名指令拒收",
    "artifact_exists":  "指令里的产物路径必须真实存在",
    "self_describe_match": "自述话题/频率 vs 实测订阅/实测 Hz 对账",
    "counts_consistent": "total == passed + failed",
    "status_enum":      "状态取值必须在枚举内(pending/running/success/failed)",
    "layer_enum":       "层名必须在枚举内(L2/L3/L4/L5/meta)",
    "progress_range":   "进度 0..1",
    "gate_audit":       "动作必须带闸门判定(gate_pass≠-1)与原因",
    "finite":           "数值必须有限",
    "name_primary":     "以 name 为主键(id 重生会变)",
    # ── 流形引擎能量层 (2026-10-07) ──
    "energy_nonneg":    "任何一层能量 E ≥ 0 (能量只增不减; 出现负值 = 口径/符号错)",
    "sum_consistent":   "E_total == Σ 各层 (存量+做功), 容差 1e-9 (逐位可核 ⇒ 总量不靠估)",
    "shell_monotonic":  "能级壳层 E_cum 单调不减 (能级越高总能量越大 = 壳层扩展律)",
    "feasible_narrowing": "可行域半径逐层收窄 R_L2 ≥ R_L3 ≥ R_L4 ≥ R_L5 (权限向上收窄律)",
    # ── 驱动扭矩 T_drive=M·(−∇Φ) (2026-10-13) ──
    "metric_definite":  "主参数 M 必须对称正定 (6×6, 特征值>0) 才允许发扭矩",
    "torque_matches_definition": "torque == M·(−∇Φ) 且 torque_inv == M⁻¹·(−∇Φ) (用报文体自带的 M/∇Φ 独立复算, 容差 1e-9)",
    "health_gain_consistent": "gain 必须与 status 一致 (normal=1.0 / warning=0.5 / critical=0.0), 不许自行放宽",
    "eta_sign":         "效率 η = E_total/W_in ≥ 0; W_in ≤ 0 时必须报 -1(未测), 不许用 0 冒充",
}


# ─────────────────────── 小工具 ───────────────────────
def full_name(key: str) -> str:
    """短名 → 真实话题名 (zmax/ss_state 等)"""
    return DDS_PREFIX + key


def topics_for_mode(mode: str):
    """该模式允许的话题 key 列表"""
    return list(MODE_TOPICS.get((mode or "prod").strip().lower(), []))


def summary():
    """给控制台/巡检用的一行摘要"""
    return {
        "version": VERSION, "updated": UPDATED,
        "n_topics": len(TOPICS), "n_rules": len(QUALITY_RULES),
        "n_stages": len(CLOSED_LOOP),
        "modes": {m: len(t) for m, t in MODE_TOPICS.items()},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
    print("话题:", ", ".join(sorted(TOPICS)))
    for t, d in TOPICS.items():
        q = d["quality"] if isinstance(d["quality"], list) else [d["quality"]]
        print("  %-12s %-12s %5.2fHz  %-6s  质量规则 %d 条" % (t, d["type"], d["rate_hz"], d["qos"], len(q)))
