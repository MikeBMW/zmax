# -*- coding: utf-8 -*-
"""quat_truth.py — 统一状态空间里的「四元数真值 → 感知补偿 → 群/势函数」策略层

老倪 2026-11-03 的策略 (本模块逐条落地, 每条都可测):
  ① 理论真值来自**记忆**: 技能库 (data/memory/l2_store/skills.json, 106 条原子技能) 每条技能声明轴向
     (`axis`: z_pos/x_pos…)。真值四元数 = 工具 z 轴对齐该轴向; 绕轴 yaw 取离线 IK 验证过的可行值
     (2026-11-03 实测: 同一轴向下 24 个 yaw 中一部分 0.0mm 可达, 另一部分差 30~150mm ⇒ yaw 不能乱选)。
  ② 感知补偿: 有新鲜测量就在 S³ 上做互补滤波 q_fused = slerp(q_truth, q_meas, w·α),
     w = 新鲜度权重 (0..1), α = 补偿增益 (默认 0.5); 过期/无测量 ⇒ w=0, q_fused = q_truth (**不假装测到**)。
  ③ 输出给下游: 群元素 (pose_caliper 精确映射, 无 tanh) + 误差角 + 势函数 V + 「万有引力」方向
     (V = ½k·θ², 引力 = 沿 S³ 测地线指向真值的方向)。整份契约落 JSON, 供流形引擎/工艺编排/action/原子技能消费。
  ④ 可观察/可修正/可测量/可改进: 每次调用都留 (err_deg, V, w, innovation), 流水落盘 ⇒ 轨迹可复盘。

口径 (不许含糊)
  · 这里的「真值」= **记忆里的理论基准**, 不是物理测量真值; 物理真值只能来自标定/编码器。
  · θ 是物理旋转角 (deg), S³ 夹角是它的一半 (双覆盖已商)。
  · 补偿是**加权融合**, 不是"用测量覆盖记忆"; 记忆始终是基准, 测量只按新鲜度打折修正。
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:            # 被 _ss_import(spec 加载) 调入时没有本目录 ⇒ 手动补
    sys.path.insert(0, _HERE)
import pose_caliper as pc             # noqa: E402

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), *([".."] * 5)))
SKILLS = os.path.join(REPO, "data", "memory", "l2_store", "skills.json")
LIVE_DIR = os.path.join(os.environ.get("ZMAX_DATA", os.path.join(REPO, "zmax_data")), "ss_live")
TRUTH_JSON = os.path.join(LIVE_DIR, "quat_truth.json")
CALLS_LOG = os.path.join(LIVE_DIR, "quat_truth_calls.jsonl")

# 技能轴向 → 单位向量 (工具 z 轴要指向哪)
AXIS_VEC = {
    "z_pos": (0, 0, 1), "z_neg": (0, 0, -1),
    "x_pos": (1, 0, 0), "x_neg": (-1, 0, 0),
    "y_pos": (0, 1, 0), "y_neg": (0, -1, 0),
}
# 离线 IK 验证过的可行 yaw (2026-11-03, 现场 URDF): 120°~300° 在料盘/孔口都 0.0mm; 取 180° 作基准
YAW_PREF_DEG = float(os.environ.get("SS_TRUTH_YAW_DEG", "180"))
GAIN_ALPHA = float(os.environ.get("SS_TRUTH_ALPHA", "0.5"))     # 感知补偿增益
K_POT = float(os.environ.get("SS_TRUTH_K", "1.0"))              # 势函数刚度 (V = ½kθ²)


def _R_for_axis(axis, yaw_deg=YAW_PREF_DEG):
    """工具 z 轴对齐 axis, 再绕该轴转 yaw —— 得到唯一姿态 (yaw 是自由度, 由策略定)。"""
    a = np.asarray(axis, dtype=float)
    a = a / np.linalg.norm(a)
    R0 = pc.R_from_q(pc.q_from_rotvec(_rotvec_from_z_to(a)))
    return _rot_about(R0, a, np.radians(yaw_deg))


def q_for_axis(axis, yaw_deg=None):
    """给定轴向 → 真值四元数 (yaw 取策略基准值)。axis 可为名字(x_pos…)或 3 维向量。"""
    if isinstance(axis, str):
        v = np.asarray(AXIS_VEC.get(axis, (0, 0, 1)), float)
    else:
        v = np.asarray(axis, float)
    return pc.q_from_R(_R_for_axis(v, YAW_PREF_DEG if yaw_deg is None else yaw_deg))


def _rotvec_from_z_to(a):
    z = np.array([0.0, 0, 1.0])
    v = np.cross(z, a)
    c = float(np.dot(z, a))
    s = float(np.linalg.norm(v))
    if s < 1e-12:
        return np.zeros(3) if c > 0 else np.array([np.pi, 0, 0])
    return v / s * float(np.arctan2(s, c))


def _qmul(a, b):
    """四元数乘法 (Hamilton, w,x,y,z) —— 不能用逐元素相乘冒充。"""
    aw, ax, ay, az = [float(x) for x in a]
    bw, bx, by, bz = [float(x) for x in b]
    return np.array([aw * bw - ax * bx - ay * by - az * bz,
                     aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw])


def rel_q(q_from, q_to):
    """q_to 相对 q_from 的误差四元数 (q_from⁻¹ ⊗ q_to), 已商双覆盖。"""
    a = pc.canonical(q_from)
    return pc.canonical(_qmul(np.array([a[0], -a[1], -a[2], -a[3]]), pc.canonical(q_to)))


def _rot_about(R, axis, ang):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return (np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * (K @ K)) @ np.asarray(R, float)


# ── ① 真值: 记忆技能 → 四元数 ───────────────────────────────────────────────
def build_truth(force=False) -> dict:
    """106 条技能 → {skill_id: {q, R, axis, yaw_deg, name}}; 落盘缓存 (可复盘)。"""
    if os.path.isfile(TRUTH_JSON) and not force:
        try:
            with open(TRUTH_JSON, encoding="utf-8") as f:
                return json.load(f)
        except Exception:                                                  # noqa: BLE001
            pass
    inv = {v: k for k, v in AXIS_VEC.items()}
    try:
        with open(SKILLS, encoding="utf-8") as f:
            sk = json.load(f).get("skills") or {}
    except Exception as e:                                                 # noqa: BLE001
        raise RuntimeError("技能库读取失败: %s" % e)
    out = {}
    for sid, s in sk.items():
        ax_name = str(s.get("axis") or "")
        ax = np.asarray(AXIS_VEC.get(ax_name, (0, 0, 1)), float)
        R = _R_for_axis(ax)
        out[sid] = {"name": s.get("name"), "axis": ax_name, "yaw_deg": YAW_PREF_DEG,
                    "q": [round(float(x), 12) for x in pc.q_from_R(R)],
                    "R": [[round(float(x), 12) for x in row] for row in R],
                    "src": "memory:l2_store/skills.json(axis) + geom + IK验证yaw(离线)"}
    os.makedirs(LIVE_DIR, exist_ok=True)
    with open(TRUTH_JSON, "w", encoding="utf-8") as f:
        json.dump({"built_at": time.time(), "n": len(out), "yaw_deg": YAW_PREF_DEG,
                   "note": "理论基准(记忆)≠物理测量真值; 物理真值需标定/编码器", "skills": out},
                  f, ensure_ascii=False)
    return {"built_at": time.time(), "n": len(out), "yaw_deg": YAW_PREF_DEG, "skills": out}


def truth_q(skill_id, axis=None):
    """取某技能的理论真值四元数; 技能不在库里但有 axis 就按 axis 现算 (标注来源)。"""
    d = build_truth()
    s = (d.get("skills") or {}).get(str(skill_id))
    if s:
        return np.asarray(s["q"], float), "memory:%s" % skill_id
    if axis:
        return pc.q_from_R(_R_for_axis(np.asarray(AXIS_VEC.get(str(axis), (0, 0, 1)), float))), \
            "geom:axis=%s" % axis
    raise KeyError("技能 %s 不在记忆库, 且未给 axis" % skill_id)


# ── ② 感知补偿 + ③ 势函数/万有引力 ─────────────────────────────────────────
def observe(skill_id=None, *, axis=None, meas_q=None, meas_age_s=None, ttl_s=2.0,
            alpha=GAIN_ALPHA, k=K_POT, log=True) -> dict:
    """一次观测: (记忆真值) ⊕ (感知测量) → 融合姿态 + 偏差 + 势 + 引力方向。

    meas_q:     测到的姿态 (四元数; 真机=标定/编码器/视觉框姿态推出来的都行)
    meas_age_s: 该测量的帧龄 (秒). None/超 ttl ⇒ 视为不新鲜, w=0 (不拿旧测量当新证据)
    """
    q_t, src = truth_q(skill_id, axis)
    w = 0.0
    innov_deg = None
    q_f = q_t.copy()
    if meas_q is not None:
        q_m = pc.canonical(meas_q)
        age = 1e9 if meas_age_s is None else float(meas_age_s)
        if age <= float(ttl_s):
            w = float(np.clip(1.0 - age / max(ttl_s, 1e-9), 0.0, 1.0))
            innov_deg = float(np.degrees(np.linalg.norm(pc.rotvec_from_q(rel_q(q_t, q_m)))))  # 物理角
            q_f = pc.slerp(q_t, q_m, w * float(np.clip(alpha, 0.0, 1.0)))
    err = np.asarray(pc.rotvec_from_q(rel_q(q_t, q_f)), float)
    err_deg = float(np.degrees(np.linalg.norm(err)))
    V = 0.5 * float(k) * float(np.radians(err_deg)) ** 2                   # ½kθ² (θ 用弧度)
    grav = np.zeros(3)
    if err_deg > 1e-9:
        grav = -err / max(np.linalg.norm(err), 1e-12) * float(np.linalg.norm(err))
    out = {
        "skill": skill_id, "axis": axis, "src_truth": src,
        "q_truth": [float(x) for x in q_t], "q_fused": [float(x) for x in q_f],
        "w_meas": round(w, 4), "alpha": alpha,
        "innovation_deg": None if innov_deg is None else round(innov_deg, 4),
        "err_deg": round(err_deg, 4), "V": round(V, 8),
        "gravity": [round(float(x), 6) for x in grav],      # 指向真值 (S³ 测地线切向), 幅值=θ
        "theta_so3_deg_truth": round(float(np.degrees(pc.theta_so3(q_t))), 4),
        "ts": time.time(),
        "note": "真值=记忆基准; 测量按新鲜度加权, 过期不参与",
    }
    if log:
        try:
            os.makedirs(LIVE_DIR, exist_ok=True)
            with open(CALLS_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
        except Exception:                                                  # noqa: BLE001
            pass
    return out


def to_group(res: dict):
    """融合姿态 → SU(2) 群元素 (精确映射, 不做 tanh 压缩)。"""
    try:
        from su2 import SU2Element
        return SU2Element(*[float(x) for x in res["q_fused"]])
    except Exception:                                                      # noqa: BLE001
        return None


def contract(res: dict) -> dict:
    """给下游 (流形引擎/工艺编排/action/原子技能) 的唯一契约 (落盘即可被消费)。"""
    return {
        "node": "🧩 四元数真值 (记忆基准 + 感知补偿)",
        "skill": res.get("skill"), "q_truth": res.get("q_truth"),
        "q_fused": res.get("q_fused"), "err_deg": res.get("err_deg"),
        "V": res.get("V"), "gravity": res.get("gravity"),
        "w_meas": res.get("w_meas"), "ts": res.get("ts"),
        "consumers": ["流形引擎(测地线/势)", "工艺编排(阶段切换)",
                      "action(前馈/规划)", "原子技能(姿态基准)", "AR(可观察)"],
    }


def write_contract(res: dict) -> str:
    p = os.path.join(LIVE_DIR, "quat_truth_latest.json")
    os.makedirs(LIVE_DIR, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(contract(res), f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


# ── 自检 (真数据: 记忆库 106 条技能) ────────────────────────────────────────
def selftest(verbose=True) -> dict:
    d = build_truth(force=True)
    sk = d["skills"]
    # ① 轴向对齐: R 的第 3 列 == 技能 axis
    worst_axis = 0.0
    for sid, s in sk.items():
        ax = np.asarray(AXIS_VEC.get(s.get("axis"), (0, 0, 1)), float)
        ax = ax / np.linalg.norm(ax)
        worst_axis = max(worst_axis, float(np.linalg.norm(np.asarray(s["R"], float)[:, 2] - ax)))
    # ② 补偿: 3° 测量误差, 全新鲜 (w=1, α=0.5) ⇒ 融合后 ≈1.5°, 且必须 < 测量误差
    sid = "L2.lift" if "L2.lift" in sk else next(iter(sk))
    q_t = np.asarray(sk[sid]["q"], float)
    q_m = pc.q_from_R(_rot_about(pc.R_from_q(q_t), np.array([1.0, 0, 0]), np.radians(3.0)))
    r_fresh = observe(sid, meas_q=q_m, meas_age_s=0.0, log=False)
    r_stale = observe(sid, meas_q=q_m, meas_age_s=9.0, log=False)
    r_none = observe(sid, meas_q=None, log=False)
    # ③ 势: V(真值)=0, V 随误差单调增; 引力方向指向真值
    errs, Vs, dirs, pairs = [], [], [], []
    for deg in (0.0, 1.0, 3.0, 10.0, 30.0):
        qx = pc.q_from_R(_rot_about(pc.R_from_q(q_t), np.array([0, 1.0, 0]), np.radians(deg)))
        r = observe(sid, meas_q=qx, meas_age_s=0.0, alpha=1.0, log=False)   # α=1 ⇒ 完全取测量
        errs.append(r["err_deg"]); Vs.append(r["V"]); dirs.append(r["gravity"]); pairs.append(qx)
    mono = all(Vs[i] <= Vs[i + 1] + 1e-12 for i in range(len(Vs) - 1))
    # 引力方向与「真值−测量」方向一致 (cos≈1)
    cos = []
    for deg, g, qm in zip(errs, dirs, pairs):
        if deg < 1e-6:
            continue
        ref = np.asarray(pc.rotvec_from_q(rel_q(qm, q_t)), float)   # 测量→真值 的方向
        if np.linalg.norm(ref) > 1e-12 and np.linalg.norm(g) > 1e-12:
            cos.append(float(np.dot(g / np.linalg.norm(g), ref / np.linalg.norm(ref))))
    out = {
        "n_skills": d["n"], "axis_align_max_err": worst_axis,
        "fresh": {"err_deg": r_fresh["err_deg"], "w": r_fresh["w_meas"],
                  "innovation_deg": r_fresh["innovation_deg"]},
        "stale": {"err_deg": r_stale["err_deg"], "w": r_stale["w_meas"]},
        "no_meas": {"err_deg": r_none["err_deg"], "w": r_none["w_meas"]},
        "V_curve": [round(v, 8) for v in Vs], "V_monotone": mono,
        "gravity_cos_min": (round(min(cos), 6) if cos else None),
        "ok": bool(worst_axis < 1e-9 and r_fresh["err_deg"] < 3.0 and r_stale["w_meas"] == 0.0
                   and r_none["err_deg"] == 0.0 and mono and cos and min(cos) > 0.999),
    }
    if verbose:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return out


if __name__ == "__main__":
    selftest()
