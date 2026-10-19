#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 Z-MAX 状态空间工程 · 全局数据空间（DDS 协议）

老倪 2026-09-25: "状态空间工程全局数据空间用DDS协议，开始改"

把状态空间工程的**全部数据流**统一到 DDS 的全局数据空间（Global Data Space）:

  话题                      内容                              典型频率    QoS
  ─────────────────────────────────────────────────────────────────────────────
  zmax/ss/state            状态空间状态(各层/流形/几何)        10-50Hz   BEST_EFFORT·KEEP_LAST(3)
  zmax/ss/action           动作指令(关节/末端/夹爪)           10-50Hz   BEST_EFFORT·KEEP_LAST(3)
  zmax/ss/infer            推理结果(模型/延迟/置信/输出)       1-10Hz    BEST_EFFORT·KEEP_LAST(3)
  zmax/ss/canvas           画布节点状态(节点名/状态/指标)      0.5Hz     RELIABLE·KEEP_LAST(1)
  zmax/ss/train            训练进度(层/步数/loss/ETA)          0.5Hz     RELIABLE·KEEP_LAST(1)
  zmax/ss/macro            宏观层/记忆层(SS_MACRO)             0.2Hz     RELIABLE·KEEP_LAST(1)
  zmax/hw_state            硬件实际值(已上线)                  0.3Hz     RELIABLE·TRANSIENT_LOCAL
  zmax/deploy_cmd          部署/回滚指令                       事件      RELIABLE·KEEP_ALL
  zmax/heartbeat           节点存活                            0.2Hz     BEST_EFFORT·KEEP_LAST(1)

设计原则:
  · 高频感知/动作 → BEST_EFFORT（丢帧无妨，要低延迟）
  · 状态/画布/训练 → RELIABLE + KEEP_LAST(1)（新订阅者立刻拿到最新，不丢状态）
  · 指令 → RELIABLE + KEEP_ALL（一条都不许丢）
  · 未测到的量 = -1.0（不用 0 冒充，与硬件话题一致）
"""
from dataclasses import dataclass, field

from cyclonedds.idl import IdlStruct
from cyclonedds.idl.types import float64, int32, int64, sequence


# ─────────────────────────── 状态空间 ───────────────────────────
@dataclass
class SSState(IdlStruct, typename="zmax::SSState"):
    """状态空间状态（一层或整链）"""
    ts: float64 = 0.0                 # epoch 秒
    layer: str = ""                   # L5/L4/L3/L2/ALL
    stage: str = ""                   # 接近/对位/下降/抓取/抬起/转移/插入
    # 状态向量（层内观测/潜变量; 未测=-1.0）
    vec: sequence[float64] = field(default_factory=list)
    dim: int32 = -1
    # 流形（SU(2) 结构化流形）
    manifold_theta: float64 = -1.0    # 流形角 θ
    manifold_norm: float64 = -1.0     # 归一化残差
    # 几何（真机/仿真同源）
    pos_x: float64 = -1.0
    pos_y: float64 = -1.0
    pos_z: float64 = -1.0
    # 稳定性（李雅普诺夫）
    lyap_v: float64 = -1.0            # 势函数值
    lyap_dv: float64 = -1.0           # 导数（<0 收敛）
    # 元信息
    source: str = ""                  # engine/sim/real/…
    note: str = ""


@dataclass
class SSAction(IdlStruct, typename="zmax::SSAction"):
    """动作指令（真机/仿真统一口径: 关节角 或 末端位姿 + 夹爪）"""
    ts: float64 = 0.0
    kind: str = ""                    # joint / tcp / gripper / rt
    joints: sequence[float64] = field(default_factory=list)   # 6 关节 rad
    tcp_pose: sequence[float64] = field(default_factory=list)  # x,y,z,rx,ry,rz
    gripper: float64 = -1.0           # 0..1
    speed: float64 = -1.0
    # 闸门/收口（L2 收口闸）
    gate_pass: int32 = -1             # 1=放行 0=否决 -1=未判
    gate_reason: str = ""
    source: str = ""


# ─────────────────────────── 推理 ───────────────────────────
@dataclass
class SSInfer(IdlStruct, typename="zmax::SSInfer"):
    """单次推理的结果与性能（模型名必填, 便于按模型统计）"""
    ts: float64 = 0.0
    model: str = ""                   # 如 l4_mani_predictor_v5
    layer: str = ""                   # L2/L3/L4/L5
    latency_ms: float64 = -1.0
    device: str = ""                  # cuda/mps/cpu
    # 输出（未测=-1.0; 向量用 out_vec）
    out_vec: sequence[float64] = field(default_factory=list)
    conf: float64 = -1.0              # 置信度
    ok: int32 = -1                    # 1=成功 0=失败 -1=未知
    note: str = ""


# ─────────────────────────── 画布 / 节点 ───────────────────────────
@dataclass
class SSCanvasNode(IdlStruct, typename="zmax::SSCanvasNode"):
    """画布节点状态（节点级可观测性: 谁在跑/跑得怎么样）"""
    ts: float64 = 0.0
    node_id: str = ""                 # 节点 id
    name: str = ""                    # 节点名（重生后 id 会变 → 以 name 为准）
    layer: str = ""
    status: str = ""                  # pending/running/success/failed
    fps: float64 = -1.0
    last_ms: float64 = -1.0
    counter: int32 = -1               # 累计调用次数
    note: str = ""


@dataclass
class SSMacro(IdlStruct, typename="zmax::SSMacro"):
    """宏观层/记忆层（SS_MACRO / 五层记忆）"""
    ts: float64 = 0.0
    layer_name: str = ""              # L2肌肉/L3流程/L4工作/宏观
    intent: str = ""                  # 上层意图
    plan: str = ""                    # 规划/分解
    progress: float64 = -1.0
    recalled: int32 = -1              # 召回条数
    note: str = ""


@dataclass
class SSNodes(IdlStruct, typename="zmax::SSNodes"):
    """全局数据空间节点清单（自描述: 谁在发布什么）"""
    ts: float64 = 0.0
    nodes: sequence[str] = field(default_factory=list)
    topics: sequence[str] = field(default_factory=list)
    publish_hz: sequence[float64] = field(default_factory=list)


# ═══════════════════════ 标定 / 诊断 / 测试（老倪 2026-09-25）═══════════════════════
@dataclass
class SSCalib(IdlStruct, typename="zmax::SSCalib"):
    """标定量（手眼/台面/示教点）—— 用于「标定」模式下的实时核对

    维度口径: 全部按 mm / deg 存储（与产线口径一致）, 未标定 = -1.0
    """
    ts: float64 = 0.0
    kind: str = ""                    # handeye / plane / teach_point / extrinsic
    src_frame: str = ""               # 相机/工具/基座
    dst_frame: str = ""
    # 手眼矩阵 T (4x4 拉平 16 个数, 行优先); 未标定 = 空
    T: sequence[float64] = field(default_factory=list)
    # 关键标量
    plane_z_mm: float64 = -1.0        # 台面高度
    tx: float64 = -1.0                # 平移 x (mm)
    ty: float64 = -1.0
    tz: float64 = -1.0
    rx_deg: float64 = -1.0            # 旋转 (deg)
    ry_deg: float64 = -1.0
    rz_deg: float64 = -1.0
    rms_mm: float64 = -1.0            # 标定残差
    samples: int32 = -1               # 标定样本数
    valid: int32 = -1                 # 1=有效 0=无效 -1=未知
    note: str = ""


@dataclass
class SSDiag(IdlStruct, typename="zmax::SSDiag"):
    """诊断量（延时/帧龄/吞吐/健康度）—— 用于「诊断」模式"""
    ts: float64 = 0.0
    node: str = ""
    kind: str = ""                    # latency / frame_age / throughput / health / error
    # 通用量（未测 = -1.0）
    latency_ms: float64 = -1.0
    frame_age_s: float64 = -1.0
    hz: float64 = -1.0
    count: int32 = -1                 # 累计计数
    dropped: int32 = -1               # 丢弃/丢帧
    queue: int32 = -1                 # 队列深度
    health: float64 = -1.0            # 0..1 健康度
    level: str = ""                   # ok / warn / error
    msg: str = ""



# ─────────────────────────── 规划 (MoveIt plan-only → DDS 镜像) ───────────────────────────
@dataclass
class SSPlan(IdlStruct, typename="zmax::SSPlan"):
    """MoveIt2 plan-only 的产出一份 DDS 镜像 (只规划不执行)

    老倪 2026-09-29: 「起 plan-only 的 move_group 容器, 把 /plan_kinematic_path 返回的关节轨迹
    也镜像成 DDS 一条 (ss_plan), 能在独立窗口里逐帧对」

    口径(必须与 moveit_plan_only.py 一致):
      · joints_path  拉平 n×6 (rad), 顺序 = joint_names
      · tcp_path     拉平 n×3 (m, base 系) —— 由每个路点 FK 得到, 供叠加层画线
      · gate_same_source: 1=FK(真关节)≈真 /robot/tcp_pose(过同源闸, 可贴真机画面)
                          0=不同源(只可当"设计态轨迹"看, 不许冒充真机) -1=未判
      · 未测 = -1.0, 不用 0 冒充 (与全空间口径一致)
    """
    ts: float64 = 0.0                       # 规划时刻 (epoch 秒)
    source: str = ""                        # moveit_plan_only / ...
    group: str = ""                         # 规划组
    base_frame: str = ""                    # 基座坐标系
    plan_code: int32 = -1                   # MoveIt ErrorCode (1=SUCCESS)
    n_points: int32 = -1                    # 关节路点数
    plan_time_s: float64 = -1.0             # 轨迹时长 (time_from_start 末尾)
    joints_path: sequence[float64] = field(default_factory=list)     # 拉平 n×6
    tcp_path: sequence[float64] = field(default_factory=list)        # 拉平 n×3 (m)
    start_joints: sequence[float64] = field(default_factory=list)    # 6 (真机关节角=起状态)
    goal_xyz: sequence[float64] = field(default_factory=list)        # 3 (目标请求, m)
    end_err_mm: float64 = -1.0              # 末端位置误差 mm
    fk_start_pos_err_mm: float64 = -1.0     # FK(起状态) 与请求起点的位置差 mm
    gate_same_source: int32 = -1            # 同源闸: 1/0/-1
    gate_reason: str = ""                   # 判据文字 (差多少 mm/deg)
    frame_age_s: float64 = -1.0             # 规划所用真机状态距今多久 (s)
    note: str = ""

@dataclass
class SSTest(IdlStruct, typename="zmax::SSTest"):
    """测试用例结果 —— 用于「测试」模式（回归/自检的可观测化）"""
    ts: float64 = 0.0
    suite: str = ""                   # 用例集名
    case: str = ""                    # 用例名
    passed: int32 = -1                # 1=过 0=失败 -1=未跑
    dur_ms: float64 = -1.0
    total: int32 = -1
    failed: int32 = -1
    detail: str = ""


# ─────────────────── 流形引擎 · 能量层 (2026-10-07 老倪) ───────────────────
@dataclass
class SSEnergyLayer(IdlStruct, typename="zmax::SSEnergyLayer"):
    """单层能量读数（能级壳层里的一格）"""
    layer: str = ""                   # L2/L3/L4/L5
    shell_n: int32 = 0                # 壳层序号 (L2=1 … L5=4)
    e_layer_cj: float64 = 0.0         # 层能量 = 存量 + 做功 (CJ)
    e_cum_cj: float64 = 0.0           # 累积能量 (到本壳层为止, 单调不减)
    e_work_cj: float64 = 0.0          # 本轮做功 (增量)
    e_standing_cj: float64 = 0.0      # 存量能力 (能力水平×循环; 基座在场就有)
    level_c: float64 = -1.0           # 能力水平 c∈[0,1] (-1=未测)
    tau_cj: float64 = 0.0             # 扭矩 (CJ/循环)
    omega_hz: float64 = -1.0          # 转速 (Hz)
    p_out_cjs: float64 = -1.0         # 输出功率 = τ·ω
    eta_cjj: float64 = -1.0           # 效率 (CJ/J)
    feasible_r: float64 = -1.0        # 可行域半径 (向上收窄)
    lora_r: int32 = -1                # LoRA rank (-1=未挂)
    lora_boost_cj: float64 = 0.0      # 增压附加能量
    share: float64 = -1.0             # 本轮占比
    note: str = ""                    # 口径/缺项说明（必须能自证）


@dataclass
class SSEnergy(IdlStruct, typename="zmax::SSEnergy"):
    """流形引擎能量层 —— 发动机类比的物理量（输入功率/转速/扭矩/能量/效率/能级壳层）"""
    ts: float64 = 0.0
    node: str = ""                    # 流形引擎节点名
    state: str = ""                   # train / run / idle
    e_total_cj: float64 = 0.0         # ★ 总能量 = Σ 各层能力总量 (CJ)
    e_base_cj: float64 = 0.0          # 基础 L2 能量
    e_boost_cj: float64 = 0.0         # LoRA 增压合计
    e_worksum_cj: float64 = 0.0       # 做功合计 (增量)
    e_standsum_cj: float64 = 0.0      # 存量能力合计
    p_in_w: float64 = -1.0            # 输入功率 = GPU 电功率 (W)
    w_in_j: float64 = -1.0            # 电功 (J)
    eta_total_cjj: float64 = -1.0     # 整机效率 (CJ/J)
    n_levels_active: int32 = -1       # 活跃能级数
    shells: sequence[SSEnergyLayer] = field(default_factory=list)   # 能级壳层
    shell_monotonic_ok: int32 = -1    # 壳层单调 (能量向上扩张)
    feasible_narrowing_ok: int32 = -1 # 可行域收窄 (权限向上收窄)
    sum_ok: int32 = -1                # 总量自检 Σ分层==总量
    criterion: str = ""               # 能量口径 (CJ 定义)
    source: str = ""                  # 数据来源 (日志/话题/tap)
    note: str = ""


@dataclass
class SSDrivingTorque(IdlStruct, typename="zmax::SSDrivingTorque"):
    """驱动扭矩 T_drive = M·(−∇Φ) —— 流形引擎在度量张量 M 下沿势场负方向产生的驱动力

    口径 (老倪 2026-10-13 命名): 转动惯量 I ↔ 度量张量 M; 角加速度 α ↔ 负梯度 −∇Φ; T = M·(−∇Φ)。
      · torque     6D = M·(−∇Φ)  (M 作用在 6D 梯度上, 后 3 维平移为真实势场分量)
      · torque_inv 6D = M⁻¹·(−∇Φ) (分量定义式 T^i = M^{ij}·(−∂_j Φ), 与 torque 成对给出)
      · unit       N·m (按真源标定口径; 未做扭矩计量学标定 —— 见 unit_note)
      · metric_tensor 36 = 6×6 主参数 M (真源 config/calib/zmax_manifold.json)
      · potential_gradient 6D ∇Φ (前 3 维旋转恒 0: 当前势场只定义在平移子空间, 如实标注)
      · health/status/gain: 健康度 >0.5 正常; 0.1~0.5 良好; 0.01~0.1 警告(×0.5); <0.01 危险(×0.0)
    """
    ts: float64 = 0.0
    node: str = ""
    scene: str = ""
    stage: str = ""
    skill: str = ""
    torque: sequence[float64] = field(default_factory=list)
    torque_norm: float64 = 0.0
    torque_inv: sequence[float64] = field(default_factory=list)
    unit: str = "N·m"
    metric_tensor: sequence[float64] = field(default_factory=list)
    metric_dim: int32 = 0
    potential_gradient: sequence[float64] = field(default_factory=list)
    neg_gradient: sequence[float64] = field(default_factory=list)
    phi: float64 = 0.0
    health: float64 = -1.0
    status: str = ""
    gain: float64 = 1.0
    x: sequence[float64] = field(default_factory=list)
    gates: str = ""
    source: str = ""
    unit_note: str = ""
    note: str = ""
    # ── 🏷 标识信息 (老倪 2026-10-14: 「输出 topic 看到正在执行的任务/产品质数/主参数等标识信息」) ──
    #    标量给数据空间视图直接显示; identity_json 是完整块 (能力质数签名是大整数 ⇒ 只能走字符串, int64 装不下)
    task_id: str = ""                    # TASK-01-FW (活跃配置真源 config/ss_task_binding.json)
    task_name: str = ""                  # FW Loading + EEPROM 写/读校验
    product: str = ""                    # 550A 原创版 (版本段 5.50.A)
    product_prime: int64 = 0             # 1009 (产品质数真源 config/platform/zmax_product.json)
    m_scale: float64 = -1.0              # 主参数 M (度量尺度, config/calib/zmax_manifold.json)
    identity_json: str = ""              # 完整标识块 JSON (任务/场景/站点/产品/质数/主参数/来源)


# ─────────────────────── 🧮 配置导入 (主参数节点) ───────────────────────
@dataclass
class SSConfigNames(IdlStruct, typename="zmax::SSConfigNames"):
    """主参数节点**已加载的配置名称** (老倪 2026-10-14:
    「那主参数节点, 需要发出 加载的配置名称的 topic, 字符串就可以, 周期可以是5秒」)

    口径: **只发名称** (不含路径/哈希/计数) —— 跟「打开工程弹窗只列配置名称」同一口径。
    真源: 画布节点 n_calib_mani (🧮 标定诊断测量 · 主参数 M) 的 params.cfg_entries / cfg_loaded_at,
          该节点每次执行 (import_config_files → write_into_node) 才会刷新 ⇒ loaded_at 即它的加载时刻。
    """
    ts: float64 = 0.0                 # epoch 秒 (本次发布时间)
    names: str = ""                   # 已加载配置名称, 以 " · " 连接的一整串 (主载荷)
    loaded_at: str = ""               # 主参数节点上次真加载的时刻 (真源 cfg_loaded_at, 供判帧龄)
    source: str = ""                  # 名称的真源位置
    note: str = ""


# ──────────────── 🧾 元任务 · 任务 → 功能+参数+依赖+验证 (老倪 2026-10-14) ──
@dataclass
class SSMetaTask(IdlStruct, typename="zmax::SSMetaTask"):
    """**根据任务输出的元任务清单** (老倪 2026-10-14: 「流形引擎, 需要根据任务, 输出元任务」)

    口径 (技能 zmax-meta-task-planning): 元任务 = 一个功能(FN-SYSx-N) + 该功能全部配置参数 + 依赖
    + 验证方法 + 归属层。它是**登记表派生件**, 不是意图、不是技能:

        任务(TASK-xx) ──enabled_nodes──> 画布节点 ──name──> 功能(module_ref) ──fn_id──> 元任务

    ⇒ 内容只能真源现算 (config_meta.json + ss_task_binding.json + 画布); 意图只决定**选哪一批**
      (🔮 意图直读/ss_intent_direct 是 Δz→技能 kNN, 输出技能ID, 不能当元任务读)。
    出口: 主参数节点 n_calib_mani (与「已加载配置名」同一个 5s 节拍, 派生器 tools/ss_meta_task.py)。
    """
    ts: float64 = 0.0                  # epoch 秒 (发布时刻)
    task_id: str = ""                  # 任务ID (真源 ss_task_binding.json 的 active_task 或指定)
    task_name: str = ""
    n: int32 = 0                       # 本任务元任务数
    n_all: int32 = 0                   # 全量元任务数 (工程 74)
    layers: str = ""                   # 层分布 "L2=9 · L3=1 · L4/L5=14 · PLAT=7"
    prio: str = ""                     # 优先级分布 "P0=31"
    fn_ids: str = ""                   # 功能ID串 (前 N 个, "FN-SYS0-36, FN-SYS0-49, …")
    src: str = ""                      # 真源 sha 摘要 (可复核)
    note: str = ""


@dataclass
class SSMetaPred(IdlStruct, typename="zmax::SSMetaPred"):
    """🧾 **元任务预测值** (老倪 2026-10-14: 「将元任务预测的topic，放到信号分析」)

    口径: 输入 = **流形引擎的驱动扭矩** (zmax/ss_torque, 10Hz), 输出 = 各元任务(功能)的预测得分 + top-k。
    真源: tools/ss_meta_predict.py (结构先验原型 + 真算特征; trained=false 时**如实标 frozen**, 不假装有预测力)。
    发布: 守护 tools/dds/ss_daemon.py 读 zmax_data/ss_live/meta_pred.json (帧龄阈值内才发; 过期写明)。
    """
    ts: float64 = 0.0                  # 发布时刻 (epoch 秒)
    ts_pred: float64 = 0.0             # 预测生成时刻 (真源文件 ts —— 判帧龄用这个)
    scene: str = ""                    # 场景 (SCN-xx)
    task_id: str = ""
    n_meta: int32 = 0                  # 参与打分的元任务数
    n_cand: int32 = 0                  # 候选总数
    top_ids: str = ""                  # top-k 功能ID ("FN-SYS2-29, FN-SYS3-04, …")
    top_scores: str = ""               # top-k 得分 (与 ids 一一对应, 保留 4 位)
    input_src: str = ""                # 输入真源 (驱动扭矩 tap 路径 / 场景)
    input_ok: int32 = 0                # 1 = 输入帧新鲜可用
    input_age_s: float64 = -1.0        # 输入帧龄
    method: str = ""                   # 预测方法 ("结构先验原型 + 真算特征")
    trained: int32 = 0                 # 1 = 已训练头, 0 = 未训练 (如实)
    frozen: int32 = 0                  # 1 = 降级/恒定输入 ⇒ 无区分度 (如实)
    src: str = ""                      # 真源摘要 (可复核)
    note: str = ""


# ─────────────────────── 🧩 动作块 (老倪 2026-10-15) ───────────────────────
@dataclass
class SSActionChunk(IdlStruct, typename="zmax::SSActionChunk"):
    """🧩 **动作块 (chunk action)** —— 老倪 2026-10-15: 「Flow Matching Action Head 的输出是个 chunk action,
    预测 [a_t,…,a_{t+H-1}], 一次推理管多步 … 应该有输出 topic, 在信号分析里显示」

    链路口径 (每一环都在载荷里, 不是图上的箭头):
      chunk[H,4]  引擎**一次求解**的测地线规划 → 逐点解码的动作块 (a_t … a_{t+H-1})
      ff[H,4]     前馈加速器 (训练左脑 MLP 真权重) 的 H 步序列 (逐拍 或 hold, ff_mode 写明)
      u[H,4]      加权后的序列 (u = (1-λ)·ff + λ·chunk) → 逐拍过动作调制器 → 逐拍过安全执行边界
      lam[H]      块权重 (近步小、远步大, 单调; 可查)
    真源: tools/ss_chunk_pipeline.py 落的 zmax_data/ss_live/chunk_latest.json (常驻回路每周期写);
          守护读它发布 (过期/缺块只发告警, 不拿旧块当现在)。
    H 上限 16 (载荷按 16 预留, 实际块长看 h 字段)。
    """
    ts: float64 = 0.0                  # 发布时刻 (epoch 秒)
    cycle: int64 = 0                   # 产出块的回路周期号 (单调, 可判"是不是真在跑")
    h: int32 = 0                       # 块长 H (实际)
    stage: str = ""                    # 当前八阶段 (接近/对位/下降/…)
    stage_idx: int32 = -1
    chunk_src: str = ""                # 块来源 (测地线规划 … / ridge 解码 …)
    ff_mode: str = ""                  # 前馈序列来源 (rollout / hold)
    chunk: sequence[float64] = field(default_factory=list)   # H*4 平铺 (a_t … a_{t+H-1})
    ff: sequence[float64] = field(default_factory=list)      # H*4 平铺 (前馈序列)
    u: sequence[float64] = field(default_factory=list)       # H*4 平铺 (调制+安全后, 待技能选取)
    lam: sequence[float64] = field(default_factory=list)     # H (块权重)
    turn_max_deg: float64 = -1.0       # 块内最大折角 (度)
    turn_mean_deg: float64 = -1.0      # 块内平均折角 (度)
    step_delta: float64 = -1.0         # 块内平均步间差 ‖Δa‖
    jerk: float64 = -1.0               # 块内平均二阶差分 ‖Δ²a‖
    u_norm0: float64 = -1.0            # 第一拍 (当前阶段要执行的那一拍) 速度模长
    skill_list: str = ""               # 派发到各技能 ("下降:步0, 抓取:步1, …")
    dispatch_age_s: float64 = -1.0     # 技能派发帧龄 (由技能循环服务刷新的 skill_dispatch.json)
    ms: float64 = -1.0                 # 本块耗时
    src: str = ""
    note: str = ""


# ──────────────── 🧮 流形引擎 · 常驻周期循环 (老倪 2026-10-14) ────────────────
@dataclass
class SSManifoldStep(IdlStruct, typename="zmax::SSManifoldStep"):
    """ManifoldEngine.step() 的**每周期**输出 (流形引擎常驻回路 → 全局数据空间)

    老倪 2026-10-14: 「常驻循环在周期性调，由状态空间工程调用，流形引擎是全系统的核心，
    怎么只是调用一次呢？改」

    改前: step() 只在①画布节点执行 ②引擎自检 ③hom 演示 ④bench 时被调 ⇒ 引擎核心没有常驻回路
          (10Hz 的 zmax-torque-bus 每周期算的是 T=M·(−∇Φ), 不经过 step)。
    改后: tools/ss_engine_loop.py 常驻按周期(默认10Hz)真调 step, 每周期落 tap,
          守护 tools/dds/ss_daemon.py 读 tap → 本话题。帧龄过期只发告警, 不把旧帧当现在。
    """
    ts: float64 = 0.0                  # epoch 秒 (发布时刻)
    cycle: int64 = 0                   # 常驻回路累计周期数 (单调, 可判"是不是真在跑")
    hz: float64 = 0.0                  # 目标频率
    step_ms: float64 = 0.0             # 本周期 step() 实测耗时
    provider: str = ""                 # 状态源: traj(工程轨迹真源) / state_file(外部实时源)
    source: str = ""                   # 状态源说明 (文件/真源标签)
    traj_at: str = ""                  # 状态空间工程该轮运行的落盘时刻
    traj_idx: int32 = -1               # 当前吃的是轨迹第几帧
    traj_n: int32 = 0                  # 轨迹总帧数
    replay: int32 = 0                  # 1 = 已回放到尾部(重放), 0 = 第一遍
    project: str = ""                  # 状态空间工程名 (真源 zmax_space.proj)
    task_id: str = ""                  # 活跃任务 (真源 config/ss_task_binding.json)
    task_name: str = ""
    scene: str = ""
    M: float64 = -1.0                  # 主参数 M (真源 config/calib/zmax_manifold.json)
    inertia: int32 = 0                 # 1 = 二阶(有惯性)演化, 0 = 一阶过阻尼
    calib: str = ""                    # 标定来源 (标定文件 / 现场拟合 / 未标定占位)
    decode_src: str = ""               # 动作解码来源 (ridge 拟合 / 占位前 N 维)
    p: sequence[float64] = field(default_factory=list)     # 潜坐标 (流形上的点)
    p_norm: float64 = 0.0
    phi: float64 = 0.0                 # 势能 Φ
    grad_norm: float64 = 0.0           # ‖∇Φ‖
    action: sequence[float64] = field(default_factory=list)  # 解出的动作
    action_norm: float64 = 0.0
    confidence: float64 = 0.0
    anomaly: float64 = 0.0
    residual: float64 = 0.0
    momentum: float64 = -1.0           # 二阶动量模长 (无惯性时 -1)
    hom_enabled: int32 = 0
    hom_mode: str = ""                 # ⚖ 内稳态模式 / 生命体征 / 增益 / 否决
    hom_vitality: float64 = 0.0
    hom_gain: float64 = 1.0
    hom_dominant: str = ""
    hom_urgency: float64 = 0.0
    hom_veto: int32 = 0
    t_encode_ms: float64 = -1.0
    t_project_ms: float64 = -1.0
    t_grad_ms: float64 = -1.0
    node: str = "manifold_engine"
    note: str = ""

# ─────────────────── 🎛 八阶段状态机 (动作调制器) ───────────────────
@dataclass
class SSStage(IdlStruct, typename="zmax::SSStage"):
    """🎛 动作调制器的八阶段状态机 —— 老倪 2026-10-15: 「八个状态, 是哪个 topic 发出来的?」

    真源 = src/lerobot/policies/left_right/state_space/cognition.py:31 `class ActionModulator`
      · STAGES 13 段: 接近/对位/下降/抓取/抬起/转移/插入/拔出/AOI转移/AOI检测/回程/放下/完成
      · 插拔链「八阶段」= 接近→对位→下降→抓取→抬起→转移→插入→完成 (摆盘链把「插入」换「放入」)
      · STAGE_V_CAP = 每阶段限速 m/s —— 动作调制器就是按当前阶段这张表给动作限幅

    补齐的理由(诚实记录): 在这之前**没有任何话题**发这八个状态 —— 阶段只以**字符串**形式躺在
    3D 面板快照 zmax_data/ss_live/trace_live.json 的 "阶段" 字段里(还有画布内部 stage_idx),
    所以信号分析页(只收数值)看不到状态机。本话题把它做成真实 DDS 通道。
    未测 = -1 / 空串(不用 0 冒充)。
    """
    ts: float64 = 0.0                  # epoch 秒 (发布时刻)
    idx: int32 = -1                    # STAGES 13 段序号 (接近=0 … 完成=12; -1=取不到)
    idx8: int32 = -1                   # 插拔链八阶段序号 0..7 (接近=0 … 完成=7; -1=取不到)
    name: str = ""                     # 阶段名 (接近/对位/…/完成)
    v_cap: float64 = -1.0              # 本阶段限速 m/s (调制器限幅表; -1=取不到)
    done: int32 = 0                    # 1 = 已到「完成」段
    age_s: float64 = -1.0              # 源快照帧龄 (s; -1=无源)
    source: str = ""                   # 真源文件 / 采集口
    note: str = ""


# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class SSSkillPhys(IdlStruct, typename="zmax::SSSkillPhys"):
    """⚖ 原子技能的**物理量**. 每个技能一条话题 (zmax/skill_sk01 … zmax/skill_sk08)

    老倪 2026-10-15: 「所有的原子技能, 例如接近、对位, 都要有 topic 输出, 且在实时监控信号分析窗口都有
    对应的信号; 我要在信号分析窗口看到实际的物理模型, x y z v a 等距离、速度、角度等物理值; 要实际发出来。」

    真源 (全部可追):
      · 数值 v/a/s/偏差/上限 ← 技能派发循环服务每拍过物理闸的结果
          zmax_data/ss_live/skill_phys.json  (生产: tools/ss_skill_dispatch.py)
          ← src/lerobot/policies/left_right/state_space/physics_constraints.py (InertiaLimiter)
      · 标定上下限 ← config/calib/zmax_skill_physics.json (tools/skill_physics_calib.py)
      · x/y/z/angle ← 真机 tap 状态帧 zmax_data/ss_live/state_*.jsonl (tcp 位姿; 该技能在职才有意义)
      · 未测 = -1.0 (不用 0 冒充) · 不在职 = 在职 0 + 数值 -1 + note 说明

    信号 (信号分析窗口里逐条可画):
      x/y/z 位置 mm · v 速度 mm/s · a 加速度 mm/s² · s 段累计行程 mm · angle 姿态角 deg
      v_cap 限速 / a_max 加速度上限 / jerk_max / s_step 单拍位移上限 / s_max 段行程上限 / m / F_max  ← 物理模型包络
    """
    ts: float64 = 0.0                  # epoch 秒 (发布时刻)
    skill: str = ""                    # 技能号 SK01.. (真源 atomic_skills.py 的 code)
    stage: str = ""                    # 阶段名 (接近/对位/…)
    in_service: int32 = 0              # 1 = 该技能当前在职 (有块认领); 0 = 不在职 (数值 -1)
    step: int32 = -1                   # 块内第几拍 (-1=无)
    # ── 实测物理量 (缺测 -1) ──
    x: float64 = -1.0                  # 末端 x mm
    y: float64 = -1.0                  # 末端 y mm
    z: float64 = -1.0                  # 末端 z mm
    v: float64 = -1.0                  # 速度 mm/s  (= ‖实际下发的 3 维动作‖)
    a: float64 = -1.0                  # 加速度 mm/s² (= ‖Δv‖/dt, 物理闸逐拍算的那个)
    s: float64 = -1.0                  # 本段累计行程 mm (InertiaLimiter.travel)
    angle: float64 = -1.0              # 末端姿态角 deg (由旋转矩阵反解, 真机 tap)
    err: float64 = -1.0                # 物理闸削出的偏差 mm/s (‖u_req − u‖)
    big: int32 = 0                     # 1 = 大偏差 (⇒ 融合定位 → 流形引擎顶层补偿)
    # ── 本段物理模型包络 (标定真源; 静态可查) ──
    v_cap: float64 = -1.0              # 限速 m/s
    a_max: float64 = -1.0              # 加速度上限 m/s² (= F/m 或标定 a)
    jerk_max: float64 = -1.0           # 加加速度上限 m/s³
    s_step: float64 = -1.0             # 单拍位移上限 m
    s_max: float64 = -1.0              # 段行程上限 m
    m_kg: float64 = -1.0               # 运动质量 kg
    f_max: float64 = -1.0              # 力上限 N
    frame_age_s: float64 = -1.0        # 源帧龄 s
    source: str = ""                   # 真源文件 / 采集口
    why: str = ""                      # 本拍被哪几条约束削 (速度/加速度/…)
    note: str = ""


# ─────────────── 分层力 L2~L5 (老倪 2026-10-19「L2~L5 力的输出, 在力场上显示的力, 都做到 trace 的 topic」) ───────────────
@dataclass
class SSForceLayer(IdlStruct, typename="zmax::SSForceLayer"):
    """单层的力输出 —— 与万有引力表/太阳系/S³ 面板**同一份**加权矢量 (真源 tools/layer_forces.py)。

    一条话题只承载一层力 ⇒ 信号分析里按话题就能分辨是哪一层, trace 里 tx 字段直接写"谁发的力":
      · ss_force_l2  tx = 前馈加速器      (chunk_latest.ff[0][:3], MLP u_ff)
      · ss_force_l3  tx = DiT 动作头      (chunk_latest.chunk[0][:3])
      · ss_force_l4  tx = 流形引擎        (度量张量 M̂ = M/m_ref 作用于前馈)
      · ss_force_l5  tx = DeepSeek VL 场景理解 (l5_scene_vec / l5_understand_latest)
    取不到的层不发 (vacuous 胜过 0 充数); 帧龄超 max_age_s 只标 fresh=0, 数值照给。
    """
    ts: float64 = 0.0                  # epoch 秒 (发布时刻)
    layer: str = ""                    # L2 / L3 / L4 / L5
    tx: str = ""                       # 力的产生端 (前馈加速器 / DiT 动作头 / 流形引擎 / DeepSeek VL)
    seq: int32 = 0                     # 该话题累计条数
    stage: str = ""                    # 当前阶段 (真源 chunk_latest.stage / trace_live.阶段)
    task: str = ""                     # 任务/配置标识
    x: float64 = 0.0                   # 加权后力矢量 (m/s 当量)
    y: float64 = 0.0
    z: float64 = 0.0
    mag: float64 = -1.0                # ‖加权后矢量‖
    raw_mag: float64 = -1.0            # 加权前原始幅值 (对账用)
    w: float64 = -1.0                  # 该层权重 (config/calib/layer_forces.json)
    k: float64 = -1.0                  # 该层单位换算系数
    fresh: int32 = 0                   # 1 = 真源帧龄 ≤ max_age_s
    age_s: float64 = -1.0              # 真源帧龄 s
    src: str = ""                      # 真源文件.字段 (逐项可对账)
    note: str = ""
