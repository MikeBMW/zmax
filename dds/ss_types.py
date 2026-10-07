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
from cyclonedds.idl.types import float64, int32, sequence


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
