# -*- coding: utf-8 -*-
"""Signal 列的**英文变量名**: 中文键 → 状态空间里那个真实变量的英文名。

老倪 2026-10-17: 「Signal 列统一显示英文名称, 对应状态空间的实际变量信号」
(同一条: 「trace 窗口删除 name 列」—— Name 列的中文名不再单占一列, 只留在 tooltip 里)

口径:
  · 能查到**生产者代码里真实变量**的, 用那个名字 (u_ff / u_fuse / grasp_prob / phi / grad_norm …);
    证据写在 _EVIDENCE 里, 谁改代码谁顺手改这里。
  · gravity 那 95 个键是 **阶段 × 层 × (力大小|实部)** 的规则化命名, 不逐个抄:
      下降·L2 力大小_mps → descend_l2_force_mps
      总合力 实部        → total_real
  · 已经是 ASCII 的键 (chunk.H / link_value / joint_1 …) 原样返回, 不加前缀不改造。
  · 真没收录的键**原样返回**(不编造英文名); tools/verify_signal_en.py 会把"未映射"列出来。
"""
from __future__ import annotations

import re

# 阶段名: 真源 ActionModulator.STAGES 是中文 (cognition.py:71) ⇒ 这里只做**英文代号**映射,
# 一份表两处用 (插拔链 + 摆盘链共用同一批阶段名)。
STAGE_EN = {
    "接近": "approach", "对位": "align", "下降": "descend", "抓取": "grasp",
    "抬起": "lift", "转移": "transfer", "插入": "insert", "拔出": "extract",
    "AOI转移": "aoi_transfer", "AOI检测": "aoi_inspect", "回程": "return",
    "放下": "place", "完成": "finish", "放入": "place",
}

# 逐键表: 中文键 → 英文变量名 (ss_state / ss_engine)
FIELD_EN = {
    # ── 帧/时钟 ──
    "帧": "frame_idx", "总帧": "frame_total", "时间_s": "t_s", "阶段": "stage",
    "阶段序号": "stage_idx", "八阶段序号": "stage8_idx", "阶段限速_mps": "stage_speed_limit",
    # ── 末端位姿 (生产者: ss_dreamview.publish_trace_live 的 x[0..2] / peg_grasp / peg_h) ──
    "末端_x": "end_x", "末端_y": "end_y", "末端_z": "end_z", "末端_len": "end_norm",
    "光模块_x": "peg_x", "光模块_y": "peg_y", "光模块_z": "peg_z",
    "光模块_len": "peg_norm", "光模块头_len": "peg_tip_norm",
    "光模块头到孔_mm": "peg_hole_dist_mm",
    # ── 估计器 ──
    "估计值_len": "est_norm", "估计误差_mm": "est_err_mm", "估计抖动_mm每步": "est_jitter_mm",
    # ── 接触/夹持 ──
    "夹爪": "gripper", "夹持": "contact_grasp", "环境接触": "contact_env",
    "接触概率": "grasp_prob", "净接触": "net_contact",
    "残差": "residual", "残差系统偏差_mm": "residual_bias_mm",
    "残差系统占比_pct": "residual_bias_pct",
    # ── 前馈加速器 / 动作调制器 / 安全层 (真源: u_ff_vec / u_fuse_vec / u_limit_vec) ──
    "前馈速度_mps": "u_ff_norm", "前馈速度_x_mps": "u_ff_x",
    "前馈速度_y_mps": "u_ff_y", "前馈速度_z_mps": "u_ff_z",
    "前馈速度_夹爪": "u_ff_gripper",
    "动作调制_mps": "u_fuse_norm", "动作调制_x_mps": "u_fuse_x",
    "动作调制_y_mps": "u_fuse_y", "动作调制_z_mps": "u_fuse_z",
    "动作调制_夹爪": "u_fuse_gripper",
    "安全边界_mps": "u_limit_norm", "安全边界_x_mps": "u_limit_x",
    "安全边界_y_mps": "u_limit_y", "安全边界_z_mps": "u_limit_z",
    # ── 流形引擎 (zmax/ss_engine) ──
    "控制周期": "ctrl_period_s", "循环耗时_ms": "loop_ms", "控制环_hz": "loop_hz",
    "势能_phi": "phi", "梯度范数": "grad_norm", "动量M": "momentum_M",
    "置信度": "confidence", "内稳态紧迫度": "homeo_urgency", "内稳态否决": "homeo_veto",
    "元任务数": "meta_task_count",
    # ── 动作块 (chunk) ──
    "chunk.平滑_转角_deg": "chunk.smooth_turn_deg",
    "chunk.步间差": "chunk.step_delta",
    "chunk.二阶差分": "chunk.step_ddot",
    "chunk.首个动作_mps": "chunk.first_action_mps",
    "chunk.块耗时_ms": "chunk.build_ms",
    # ── 技能派发 ──
    "skill.接近.最新_mps": "skill.approach_latest_mps",
    "skill.对位.最新_mps": "skill.align_latest_mps",
    "skill.下降.最新_mps": "skill.descend_latest_mps",
    "skill.抓取.最新_mps": "skill.grasp_latest_mps",
    "skill.抬起.最新_mps": "skill.lift_latest_mps",
    "skill.转移.最新_mps": "skill.transfer_latest_mps",
    "skill.插入.最新_mps": "skill.insert_latest_mps",
    "skill.完成.最新_mps": "skill.finish_latest_mps",
    # ── gravity 表头几项 ──
    "总合力 力大小_mps": "total_force_mps", "总合力 实部": "total_real",
    "参考速度 u_ref_mps": "u_ref_mps", "一致度": "consistency",
    "主力层号": "dominant_layer", "主力项序号": "dominant_term",
}

# 证据: 这些英文名不是翻出来的, 是生产者代码里就有的标识 (改代码时同步这里)
_EVIDENCE = {
    "u_ff_norm": "ss_dreamview.publish_trace_live: 前馈速度_mps = ‖u_ff_vec[:3]‖",
    "u_fuse_norm": "同上: 动作调制_mps = ‖u_fuse_vec[:3]‖",
    "u_limit_norm": "同上: 安全边界_mps = ‖u_limit_vec[:3]‖",
    "grasp_prob": "同上: 接触概率 = cp (状态校正器输出的接触概率)",
    "phi": "ss_engine: 势能 φ (Lyapunov)", "grad_norm": "ss_engine: ∇φ 范数",
}

# ── AR 场景 / 技能派发: 段名与字段名按**词典**翻 (生产者就用中文键, 这里给英文代号) ──
SEG_EN = {
    "引擎": "engine", "相机": "camera", "AOI": "aoi", "叠加": "overlay", "末端": "end",
    "光学质量检测": "optical_qc", "GUI测试点": "gui_test_pt", "准备点": "ready_pt",
    "空间点": "space_pt", "安全点": "safe_pt", "侧面点": "side_pt", "金手指点": "finger_pt",
}
AR_FIELD_EN = {
    "倾角_deg": "tilt_deg", "判决": "verdict", "拍照_epoch": "shot_epoch",
    "推理_ms": "infer_ms", "矩形中心_x": "rect_cx", "矩形中心_y": "rect_cy",
    "矩形宽_px": "rect_w_px", "矩形高_px": "rect_h_px", "缺陷数": "defect_count",
    "划伤数": "scratch_count", "污点数": "stain_count", "取像体检": "image_health",
    "清晰度": "sharpness", "灰度偏差": "gray_bias", "边缘占比": "edge_ratio",
    "健康度_H": "health_H", "健康度_H̃_尺度不变": "health_H_scale_inv", "分级": "grade",
    "各向异性": "anisotropy", "度量分量数": "metric_components", "度量尺度_M": "metric_scale_M",
    "扭矩_τ": "torque_tau", "最大特征值_λmax": "eig_max", "最小特征值_λmin": "eig_min",
    "条件数_κ": "condition_number", "帧龄_s": "frame_age_s", "增益": "gain",
    "帧数": "frame_count", "平面RMS_mm": "plane_rms_mm", "曝光_us": "exposure_us",
    "有效深度比": "valid_depth_ratio", "深度_m": "depth_m", "点位数": "point_count",
    "目标_x_m": "target_x_m", "目标_y_m": "target_y_m", "目标_z_m": "target_z_m",
}
SKILL_FIELD_EN = {
    "偏差_mps": "dev_mps", "可行": "feasible", "拍": "tick", "请求_mps": "request_mps",
    "mps": "mps", "块帧龄_s": "chunk_age_s", "派发帧龄_s": "dispatch_age_s",
    "技能拍": "skill_tick", "段闸拍": "stage_tick", "不可行拍": "infeasible_tick",
    "拍数": "tick_count",
}
GATE_CLIP_EN = {"位移": "disp", "速度": "vel", "加速度": "accel",
                "加加速度": "jerk", "动量/质量率": "momentum_rate"}

_ASCII = re.compile(r"^[ -~]+$")
_GRAV_LAYER = re.compile(r"^(?P<stage>[^·]+)·(?P<layer>L[2-5]) (?:力大小_mps|实部)$")
_GRAV_SUM = re.compile(r"^(?P<stage>[^·]+)·合力 (?:力大小_mps|实部)$")
_GRAV_COL = re.compile(r"^列(?P<layer>L[2-5])·合力 (?:力大小_mps|实部)$")


def en_of(field, topic="", mtype=None):
    """中文键 → 英文变量名; ASCII 原样; 没收录原样返回 (不编)。
    mtype: 报文类型 (zmax::MotionPlan) —— 只有裸端口名 in1/out1 会用到它。"""
    k = str(field or "")
    if not k:
        return ""
    _ps = port_signal(k, mtype)
    if _ps:
        return _ps
    if k in FIELD_EN:
        return FIELD_EN[k]
    if _ASCII.match(k):                      # 已经是 ASCII (chunk.H / λ0 / joint_1 …)
        return k.replace("λ", "lambda_").replace("·", "_")
    # gravity: 阶段 × 层
    m = _GRAV_LAYER.match(k)
    if m:
        st = STAGE_EN.get(m.group("stage"), m.group("stage"))
        kind = "real" if k.endswith("实部") else "force_mps"
        return "%s_%s_%s" % (st, m.group("layer").lower(), kind)
    m = _GRAV_COL.match(k)          # ⚠️ 先匹配「列Lx·合力」再匹配「阶段·合力」——
    if m:                           #   否则 stage 会被当成 "列L2" (实测过, 出来是 列L2_sum_...)
        return "col_%s_sum_%s" % (m.group("layer").lower(),
                                  "real" if k.endswith("实部") else "force_mps")
    m = _GRAV_SUM.match(k)
    if m:
        st = STAGE_EN.get(m.group("stage"), m.group("stage"))
        return "%s_sum_%s" % (st, "real" if k.endswith("实部") else "force_mps")
    # 技能物理约束 (skillphys): "SK01 接近 · F_max 力上限 N" → "SK01.approach.F_max"
    m = re.match(r"^(?P<sk>SK\d+)\s(?P<stage>[^·]+?)·\s*(?P<var>[A-Za-z_][A-Za-z0-9_]*)\s.*$", k)
    if m:
        st = STAGE_EN.get(m.group("stage").strip(), m.group("stage").strip())
        return "%s.%s.%s" % (m.group("sk"), st, m.group("var"))
    # 潜表示_p0..p3 / 块步0..7 / λ0..7
    # ── AR 场景: ar.<段>.<字段> / ar.<点集>N.<轴> ──
    m = re.match(r"^ar\.(?P<seg>[^.]+)\.(?P<fld>.+)$", k)
    if m:
        seg, fld = m.group("seg"), m.group("fld")
        _p = re.match(r"^(空间点|安全点|侧面点|金手指点)(\d+)$", seg)
        if _p:
            seg_en = "%s_%s" % (SEG_EN[_p.group(1)], _p.group(2))
        else:
            seg_en = SEG_EN.get(seg, seg)
        return "ar.%s.%s" % (seg_en, AR_FIELD_EN.get(fld, fld))
    # ── 技能派发: skill.<阶段>_<字段> / skill.闸_削因.<原因> ──
    m = re.match(r"^skill\.闸_削因\.(?P<why>.+)$", k)
    if m:
        return "skill.gate.clip_reason." + GATE_CLIP_EN.get(m.group("why"), m.group("why"))
    m = re.match(r"^skill\.(?P<rest>.+)$", k)
    if m:
        rest = m.group("rest")
        if rest.startswith("过闸_"):
            return "skill.gate." + SKILL_FIELD_EN.get(rest[3:], rest[3:])
        if rest.startswith("闸_"):
            return "skill.gate." + SKILL_FIELD_EN.get(rest[2:], rest[2:])
        for _st_cn, _st_en in sorted(STAGE_EN.items(), key=lambda kv: -len(kv[0])):
            if rest.startswith(_st_cn + "_"):
                tail = rest[len(_st_cn) + 1:]
                return "skill.%s_%s" % (_st_en, SKILL_FIELD_EN.get(tail, tail))
        return "skill." + SKILL_FIELD_EN.get(rest, rest)
    # ── 技能物理约束的中文字段 ──
    m = re.match(r"^(?:skillphys\.)?(SK\d+)\s(?P<stage>[^·]+)·\s*(?P<var>[^\s]+)", k)
    if m:
        _v = {"位姿帧龄": "pose_age_s", "在职": "active"}.get(m.group("var"), m.group("var"))
        st = STAGE_EN.get(m.group("stage").strip(), m.group("stage").strip())
        return "%s.%s.%s" % (m.group(1), st, _v)
    m = re.match(r"^潜表示_p(\d+)$", k)
    if m:
        return "latent_p" + m.group(1)
    m = re.match(r"^chunk\.块步(\d+)_mps$", k)
    if m:
        return "chunk.step" + m.group(1) + "_mps"
    m = re.match(r"^chunk\.λ(\d+)$", k)
    if m:
        return "chunk.lambda" + m.group(1)
    return k


def is_mapped(field):
    """是否给出了英文名 (给判据用): 未映射且非 ASCII ⇒ False。"""
    k = str(field or "")
    return bool(k) and (k in FIELD_EN or bool(_ASCII.match(k))
                        or bool(_GRAV_LAYER.match(k)) or bool(_GRAV_SUM.match(k))
                        or bool(_GRAV_COL.match(k))
                        or bool(re.match(r"^(潜表示_p\d+|chunk\.块步\d+_mps|chunk\.λ\d+)$", k)))


def unmapped(keys):
    """给定一批中文键, 返回没英文名的那些 (判据/巡检用)。"""
    return [k for k in keys if not is_mapped(k)]


# ── 元数据键: 不是"信号", 不该出现在 Signal 列 (老倪 2026-10-17: 「怎么还有 topic ts json 这样的名字」) ──
_META_NAMES = frozenset((
    "ts", "t", "time", "count", "bytes", "n", "seq", "age_s", "frame", "frames", "total",
    "topic", "type", "src", "json", "payload", "digest", "msg", "header", "stamp", "size",
    "reset_n", "样本", "计数",
))


def is_meta(name):
    """True = 文件/元数据字段 (ts、topic、json、src、count…), 不是状态空间信号, 两个窗口都不列。"""
    k = str(name or "").strip().lower()
    if not k:
        return True
    if k in _META_NAMES:
        return True
    if "." in k and k.rsplit(".", 1)[-1] in _META_NAMES:      # space.topics.heartbeat.bytes 这类
        return True
    if k.endswith(".json") or k.endswith(".jsonl") or k.endswith(".py"):
        return True
    return False


def en_of_key(prefix, field, mtype=None):
    """数据源前缀 + 字段名 → 界面 Signal 列的**唯一**名字 (两个窗口都调它)。

    规则: 先按字段名映射; 还留非 ASCII 就退回 "前缀.字段" 的整键映射; 两个都不是纯 ASCII
    ⇒ 用字段名本身 (不带前缀, 保证两边逐字相同)。
    """
    def _ascii(x):
        return bool(x) and all(ord(c) < 128 for c in str(x))

    cands = []
    try:
        cands.append(en_of(field, "", mtype))
    except Exception:                                                     # noqa: BLE001
        pass
    if prefix:
        try:
            cands.append(en_of("%s.%s" % (prefix, field), ""))
        except Exception:                                                 # noqa: BLE001
            pass
    for c in cands:
        if _ascii(c):
            return c
    return cands[0] if cands else str(field)

# ───────────────── 裸端口名 (out1 / in1 / out2 …) → 语义名 (2026-10-18) ─────────────────
# 老倪: 「你看信号 out1 in1，根本看不出来是什么意思。全局搜索，signal 要能表达出这个信号的基本含义，
#        简单明了。全局修改信号的英文字符串」
# 规则: 端口本身没有语义 ⇒ 用**报文类型**命名 (mw_topic.type 是真源), 表里有就用手挑的短名,
#       没有就 CamelCase→snake_case 兜底; 还取不到类型就保留端口名 (不编)。
_PORT_RE = re.compile(r"^(in|out)(\d+)$")

TYPE_SIGNAL_EN = {
    "MotionPlan": "plan",
    "MotionPlanIn": "plan_in",
    "RobotAction": "action",
    "RobotActionIn": "action_in",
    "MotionState": "motion_state",
    "SceneUnderstanding": "scene",
    "EngineeringMemory": "memory",
    "HumanInLoop": "hil_action",
    "MemoryLinks": "mem_links",
    "VlmSceneText": "vlm_text",
    "WebAgentBridge": "web_agent",
    "L5AutoLabel": "auto_label",
    "L5AutoLabel2": "auto_label_2",
    "L5AutoLabel3": "auto_label_3",
    "JointStates": "joints",
    "JointState": "joints",
    "TcpPose": "tcp_pose",
    "GripperState": "gripper",
    "ForceTorque": "force_torque",
    "SafetyGate": "safety_gate",
    "PlanSegments": "plan_segments",
    "ActuationCommand": "act_cmd",
    "ExecResult": "exec_result",
    "SkillRequest": "skill_req",
    "SkillState": "skill_state",
    "MuscleSkillBank": "muscle_bank",
    "SkillDictionary": "skill_dict",
    "L2MuscleRecall": "muscle_recall",
    "Pose3D": "pose3d",
    "OpticalInspection": "aoi",
    "CapabilityLevel": "capability",
    "HardwareState": "hw_state",
    "BoardFrame": "board_frame",
    "BoardFrameIn": "board_frame_in",
    "SceneText": "scene_text",
}


def type_signal_name(mtype):
    """'zmax::MotionPlan' → 'plan' (表里没有则 CamelCase→snake_case)。"""
    t = str(mtype or "").split("::")[-1].strip()
    if not t:
        return ""
    if t in TYPE_SIGNAL_EN:
        return TYPE_SIGNAL_EN[t]
    s2 = re.sub(r"(?<!^)(?=[A-Z])", "_", t).lower()
    return s2


def port_signal(field, mtype=None):
    """裸端口 (out1/in1) → 语义名; 不是裸端口或拿不到类型 → None (保留原样)。"""
    f = str(field or "")
    m = _PORT_RE.match(f)
    if not m:
        return None
    base = type_signal_name(mtype)
    if not base:
        return None
    # 同一个话题类型常有多条入口 (in1/in2 …) ⇒ 只有第 1 个用裸名, 其余带序号区分 (plan_in / plan_in_2)
    idx = str(m.group(2))
    return base if idx == "1" else "%s_%s" % (base, idx)
