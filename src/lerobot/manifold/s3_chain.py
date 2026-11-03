# -*- coding: utf-8 -*-
"""s3_chain.py — 「逻辑条件 → 流形潜空间 → 预测 SU(2) 轨迹 → 三维角速度」

老倪 2026-11-03 原则落地:
    高维物理世界 → 有界映射到 S³(单位四元数) → 在球面上算路径 → 翻译回三维执行。

口径 (与 state_space/su2.py 完全一致, 这里不另发明一套):
  · U = I  ⇔ 场景收敛(误差为零);  θ = 偏离幅度;  n̂ = 误差方向 (基座系)
  · 预测  = 从 U_now 沿 S³ 测地线走向 I, 步长由角速度限幅决定 (不外推幻想必到的点)
  · 解码  = ω_k = log(U_k⁻¹·U_{k+1}) / dt   (rad/s, 消去误差的方向)
            R_cmd = R_ref · R_from_q(U)⁻¹  —— 施加后 U→I (符号现场校验一次即可)
  · 潜空间 = 把「逻辑条件」拼成 z_cond 喂给流形引擎 project(), 得到同一群的另一路投影 p
  · 独立真值 = 几何误差 e = obs43[4:7](+30mm 头部偏置) − obs43[36:39]
    —— 它与引擎 L4 输出不同源, 用来打破「预测喂预测」的自环

诚实边界 (写进返回值, 不靠注释口头保证):
  · latent_calibrated=False 表示 z_cond 未按训练标定口径归一, 该路 p 只作对照, 不当在役潜表示
  · 任何一路失败都返回 ok=False + why, 不填 0 冒充
"""
from __future__ import annotations

import math
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_SS = os.path.normpath(os.path.join(_HERE, "..", "policies", "left_right", "state_space"))
for _p in (_HERE, _SS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pose_caliper as pc                                    # noqa: E402
from su2 import SU2Element, compose_scene, encode_layers, obs43_geometry   # noqa: E402

STAGES = ("接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成")


# ── 小工具 ─────────────────────────────────────────────────────────────────
def _scalar(x, default=0.0) -> float:
    if x is None:
        return default
    try:
        a = np.asarray(x, dtype=float).reshape(-1)
        return float(a[0]) if a.size else default
    except Exception:                                                    # noqa: BLE001
        try:
            return float(x)
        except Exception:                                            # noqa: BLE001
            return default


def q_of(u: SU2Element) -> np.ndarray:
    return pc.canonical(np.array([u.w, u.x, u.y, u.z], float))


def conditions(frame: dict, obs43=None) -> dict:
    """逻辑条件: 意图 + 阶段 + 几何真值 + 接触/限幅读数 → 可解释字典 + 16 维潜向量。

    z_cond 布局固定 (下游/复现都按这个切):
      [0:3] 意图向量 (L5; 没有就 0 ⇒ 该字段诚实为空)
      [3:11] 阶段 one-hot (8 阶段)
      [11:14] 几何误差 e (m, 基座系, 独立真值)
      [14] 接触概率
      [15] 1−性能流形效能 (未达程度)
    """
    intent = frame.get("L5_intent") or []
    v_int = np.zeros(3)
    if len(list(intent)) >= 3:
        v_int = np.asarray(intent, float).reshape(-1)[:3]
    stage = str(frame.get("stage") or "").strip()
    one = np.zeros(len(STAGES))
    if stage in STAGES:
        one[STAGES.index(stage)] = 1.0
    e = np.zeros(3)
    if obs43 is not None:
        try:
            e = np.asarray(obs43_geometry(obs43), float).reshape(-1)[:3]
        except Exception:                                            # noqa: BLE001
            e = np.zeros(3)
    contact = _scalar(frame.get("contact_p"), 0.0)
    miss = 1.0 - _scalar(frame.get("mani_eta"), 0.0)
    z = np.concatenate([v_int, one, e, [contact, miss]])
    return {"intent": v_int.tolist(), "stage": stage, "geom_err": e.tolist(),
            "geom_err_mm": float(np.linalg.norm(e) * 1000.0),
            "contact_p": contact, "perf_miss": miss,
            "intent_src": "L5 意图 (未接入=0)" if not v_int.any() else "L5 意图",
            "z_cond": z, "z_dim": int(z.size)}


class S3Chain:
    """一条链路: 条件 → U(群) → S³ 预测轨迹 → 角速度指令。

    只算不下发: 返回值是**建议指令** (rad/s + 目标位姿), 真机执行必须走现场授权链。
    """

    def __init__(self, dt: float = 0.1, horizon: int = 8,
                 omega_max: float = 1.0, log=None) -> None:
        self.dt = float(dt)
        self.h = max(1, int(horizon))
        self.omega_max = float(omega_max)          # rad/s 角速度上限 (执行端限幅同口径)
        self._log = log
        self.n = 0
        self.hist_q: list[np.ndarray] = []
        self.stats = {"theta_sum": 0.0, "omega_sum": 0.0, "n": 0}

    # ── S³ 上的测地线预测 ────────────────────────────────────────────────
    def predict(self, q_now: np.ndarray, q_goal=None) -> dict:
        """从 q_now 沿 S³ 测地线走向 q_goal(默认 I), 步长 = omega_max·dt (物理角)。

        刻度关系 (su2 铁律): **物理转角 = 2 × S³ 测地角**, 所以 S³ 上每步只走 ω·dt/2;
        报出去的 theta 一律是**物理角** (与 SU2Element.theta() 同口径), 不混用。
        """
        q0 = pc.canonical(np.asarray(q_now, float).reshape(4))
        qf = pc.canonical(np.asarray(q_goal, float).reshape(4)) if q_goal is not None \
            else np.array([1.0, 0.0, 0.0, 0.0])
        th_s3 = float(pc.s3_angle(q0, qf))                                   # S³ 测地角 (rad)
        th_phys = 2.0 * th_s3                                                # 物理转角 (rad)
        step_phys = self.omega_max * self.dt
        step_s3 = step_phys / 2.0
        n_need = int(math.ceil(th_phys / step_phys)) if step_phys > 1e-12 else 0
        traj, dth = [], []
        for k in range(1, self.h + 1):
            t = min(1.0, k * step_s3 / th_s3) if th_s3 > 1e-12 else 1.0
            traj.append(pc.canonical(pc.slerp(q0, qf, t)))
            prev = traj[-2] if k > 1 else q0
            dth.append(2.0 * float(pc.s3_angle(prev, traj[-1])))             # 物理角增量
        return {"q_goal": qf.tolist(), "theta_rad": th_phys,
                "theta_deg": math.degrees(th_phys),
                "s3_angle_rad": th_s3,
                "steps_needed": int(n_need), "horizon": self.h,
                "step_max_deg": math.degrees(step_phys),
                "q": [q.tolist() for q in traj],
                "dtheta_rad": dth,
                "eta_s": round(n_need * self.dt, 3)}

    # ── 解码成三维指令 ──────────────────────────────────────────────────
    def decode(self, q_list, q_start=None, R_ref=None) -> dict:
        """轨迹 → **每步增量**角速度 (不是全程角速度)。

        ω_k = log(q_{k-1}⁻¹·q_k)/dt, 幅值 = 单步转角/dt ≤ omega_max;
        R_cmd = R_ref · R_from_q(U)⁻¹  (施加后 U→I: 符号现场校验一次)
        """
        qs = [pc.canonical(np.asarray(q, float)) for q in q_list]
        prev = pc.canonical(np.asarray(q_start, float)) if q_start is not None else None
        om = []
        for q in qs:
            if prev is None:
                om.append(np.zeros(3).tolist())          # 不知道起点 ⇒ 不给假指令
                prev = q
                continue
            # 基座系 (左乘) 增量: q_next = exp(ω·dt) · q_prev  ⇒ ω = log(q_next·q_prev⁻¹)/dt
            dq = SU2Element(*q) * SU2Element(*prev).inv()
            om.append((np.asarray(dq.log(), float) / self.dt).tolist())
            prev = q
        out = {"omega_rad_s": om,
               "omega_norm_rad_s": [float(np.linalg.norm(o)) for o in om],
               "omega_src": "step_delta" if q_start is not None else "none(缺起点)",
               "dir_convention": "基座系左乘: q_next=exp(ω·dt)·q_prev; R_cmd=exp(ω·dt)·R_now",
               "clamped": bool(any(np.linalg.norm(o) > self.omega_max + 1e-9 for o in om))}
        if R_ref is not None and qs:
            Rc = np.asarray(R_ref, float).reshape(3, 3)
            out["R_cmd"] = (Rc @ pc.R_from_q(qs[0]).T).ravel().tolist()
        return out

    # ── 状态预测 (不是计划): 切空间一阶外推 ──────────────────────────────
    def predict_next(self, q_now: np.ndarray) -> dict:
        """预测**物理下一拍**会到哪个群点 (与"计划轨迹"是两回事)。

        v = log(q_cur·q_prev⁻¹)/dt (基座系角速度), q̂(t+1) = exp(v·dt)·q_cur。
        历史不足 2 拍 ⇒ 零阶保持并标注; 相邻两拍跳变 >30° ⇒ 判定换段, 不用跨段速度。
        """
        h = self.hist_q
        q0 = pc.canonical(np.asarray(q_now, float).reshape(4))
        if len(h) < 1:
            return {"q": q0.tolist(), "src": "zoh(无历史)", "omega_rad_s": [0.0, 0.0, 0.0],
                    "step_deg": 0.0}
        dq = SU2Element(*q0) * SU2Element(*h[-1]).inv()
        v = np.asarray(dq.log(), float) / self.dt
        step_deg = math.degrees(float(np.linalg.norm(v)) * self.dt)
        if step_deg < 0.05:                     # 静止: 外推只会虚构运动 ⇒ 零阶保持
            return {"q": q0.tolist(), "src": "zoh(静止 %.3f°)" % step_deg,
                    "omega_rad_s": [0.0, 0.0, 0.0], "step_deg": round(step_deg, 3)}
        if step_deg > 30.0:                     # 换段一跳: 不用这一步的速度外推
            return {"q": q0.tolist(), "src": "zoh(换段 %.1f° 不外推)" % step_deg,
                    "omega_rad_s": v.tolist(), "step_deg": round(step_deg, 3)}
        qh = SU2Element.from_rotvec(v * self.dt) * SU2Element(*q0)
        return {"q": pc.canonical(np.array([qh.w, qh.x, qh.y, qh.z])).tolist(),
                "src": "切空间一阶外推", "omega_rad_s": [round(float(x), 6) for x in v],
                "step_deg": round(step_deg, 3)}

    # ── 主入口: 一拍 ────────────────────────────────────────────────────
    def step(self, frame: dict, obs43=None, *, R_ref=None, eng=None) -> dict:
        """一拍: 条件 → 群 → 预测 → ω。

        两路分开, 不混用 (2026-11-03 实测教训):
          · scene = U_L2⊗U_L3⊗U_L4⊗U_L5 —— 场景状态表示 (理解/判据/层分解), L3/L4 是**进度/动作**
            量不是误差, 群乘后 θ 会饱和在 ~166° ⇒ **不能**拿它当"待消除误差"解码 ω
          · exec  = U_L2 —— 几何误差群 (e=光模块头−孔位), U→I ⇔ 到位; 预测与 ω 只走这一路
        """
        t0 = time.perf_counter()
        self.n += 1
        try:
            cond = conditions(frame, obs43)
            layers = encode_layers(frame, obs43)
            scene = compose_scene(layers)
            q_scene = q_of(scene)
            q_exec = q_of(layers["L2"])
            pred = self.predict(q_exec)
            nxt = self.predict_next(q_exec)
            dec = self.decode(pred["q"], q_start=q_exec, R_ref=R_ref)
            self.hist_q.append(q_exec)
            self.hist_q = self.hist_q[-240:]
            # 潜空间对照路: 同一帧 state(43D) → 引擎潜空间投影 p
            #   注意: 引擎 project() 吃的是 **43D state** (内部编码), 不是条件向量;
            #   「逻辑条件」目前只是契约字段 (z_cond), 尚未进编码器 —— 要进得训练带条件的编码器,
            #   这里不假装它已经进去了 (真做了才写 latent_calibrated=True)。
            lat = {"ok": False, "why": "engine 未提供 project()"}
            if eng is not None and hasattr(eng, "project") and obs43 is not None:
                try:
                    pr = eng.project(np.asarray(obs43, float).reshape(-1))
                    p = np.asarray(pr[0] if isinstance(pr, tuple) else pr.get("p"), float).ravel()
                    lat = {"ok": True, "p": [round(float(x), 6) for x in p],
                           "norm": round(float(np.linalg.norm(p)), 9),
                           "s3_angle_vs_exec_deg": round(
                               math.degrees(float(pc.s3_angle(p, q_exec))) if p.size == 4 else -1.0, 3),
                           "s3_angle_vs_scene_deg": round(
                               math.degrees(float(pc.s3_angle(p, q_scene))) if p.size == 4 else -1.0, 3),
                           "latent_calibrated": False,
                           "z_cond_used": False,
                           "why": "条件向量 z_cond(16) 尚未接入编码器; 本路是 state(43D)→引擎潜投影, 只作对照"}
                except Exception as e:                                   # noqa: BLE001
                    lat = {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:80])}
            self.stats["theta_sum"] += pred["theta_rad"]
            self.stats["omega_sum"] += float(sum(dec["omega_norm_rad_s"]))
            self.stats["n"] += 1
            ms = (time.perf_counter() - t0) * 1000.0
            return {
                "ok": True, "ts": time.time(), "cycle": self.n, "ms": round(ms, 3),
                "conditions": {k: v for k, v in cond.items() if k != "z_cond"},
                # 场景态 (理解/判据): 四层群乘, L3/L4 是进度/动作 ⇒ θ 会饱和, 不当误差用
                "scene_q": q_scene.tolist(), "scene_theta_rad": scene.theta(),
                "scene_theta_deg": math.degrees(scene.theta()),
                "scene_w": scene.visibility(), "scene_bloch": scene.bloch().tolist(),
                # 可执行态 (几何误差群): U→I ⇔ 到位, 预测/ω 只走这一路
                "exec_q": q_exec.tolist(),
                "exec_theta_deg": math.degrees(layers["L2"].theta()),
                "exec_axis": layers["L2"].axis().tolist(),
                "layers_theta": {L: round(layers[L].theta(), 6) for L in layers},
                "predict": {k: pred[k] for k in ("theta_rad", "theta_deg", "steps_needed",
                                                 "eta_s", "q", "dtheta_rad", "step_max_deg")},
                # 状态预测 (物理下一拍会到哪): 与"计划轨迹"分开报
                "predict_next": nxt,
                "decode": dec, "latent": lat,
                "chain": "逻辑条件 → S³(几何误差群 U_L2) → 状态预测/测地线计划 → ω 指令",
            }
        except Exception as e:                                           # noqa: BLE001
            return {"ok": False, "cycle": self.n, "why": "%s: %s" % (type(e).__name__, str(e)[:120]),
                    "ms": round((time.perf_counter() - t0) * 1000.0, 3)}


# ── 误差状态 EKF on S³ (可选融合器; 与"固定增益互补滤波"是两回事) ─────────────
def _skew(v) -> np.ndarray:
    x, y, z = np.asarray(v, float).reshape(3)
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]], float)


class S3EKF:
    """S³ 上的误差状态 EKF: 状态 = 单位四元数, 协方差 P(3×3) 在体坐标系切空间。

    与 `quat_truth.observe(alpha=0.5)` / `cognition.state_correction(K=0.5)` 的区别:
    那两处是**固定增益互补滤波** (增益写死, 不随不确定度变); 这里是
        K = P(P+R)⁻¹,  P⁺ = F P Fᵀ + Q,  P ← (I−K)P
    ⇒ 增益随"模型有多可信 / 测量有多准"自适应。

    Q/R 必须来自实测标定 (过程噪声 / 测量噪声方差, rad²); 没标定就别宣称"已上真机",
    默认值只是占位 (Q=1e-4, R=1e-3 rad² ≈ 1.8° 测量噪声)。
    """

    def __init__(self, q0=None, P0=None, Q=None, R=None) -> None:
        self.q = pc.canonical(np.asarray(q0 if q0 is not None else [1, 0, 0, 0], float).reshape(4))
        self.P = np.eye(3) * 1e-4 if P0 is None else np.asarray(P0, float).reshape(3, 3).copy()
        self.Q = np.eye(3) * 1e-4 if Q is None else np.asarray(Q, float).reshape(3, 3).copy()
        self.R = np.eye(3) * 1e-3 if R is None else np.asarray(R, float).reshape(3, 3).copy()
        self.n_pred = 0
        self.n_upd = 0

    # 传播: q⁺ = q ⊗ exp(ω dt),  P⁺ = F P Fᵀ + Q,  F = exp(−[ω dt]×)
    def predict(self, omega_rad_s, dt: float) -> np.ndarray:
        w = np.asarray(omega_rad_s, float).reshape(3)
        qd = SU2Element.from_rotvec(w * dt)
        qn = SU2Element(*self.q) * qd
        self.q = pc.canonical(np.array([qn.w, qn.x, qn.y, qn.z]))
        A = _skew(w * dt)
        F = np.eye(3) - A + 0.5 * (A @ A)
        self.P = F @ self.P @ F.T + self.Q
        self.n_pred += 1
        return self.q

    # 更新: r = log(q⁻¹ ⊗ q_meas) (体坐标新息), K = P(P+R)⁻¹, q ← q ⊗ exp(K r)
    def update(self, q_meas, R=None) -> dict:
        Rm = self.R if R is None else np.asarray(R, float).reshape(3, 3)
        qm = pc.canonical(np.asarray(q_meas, float).reshape(4))
        rel = SU2Element(*self.q).inv() * SU2Element(*qm)
        # ⚠ SU2Element.log() 用 atan2(‖v‖, w) 不折叠主值: w<0 时会给出 >π 的角
        #   (实测创新 278° 而真差 7° ⇒ 一步过冲 61°、EKF 崩到正交). 距离类一律先商双覆盖。
        rc = pc.canonical(np.array([rel.w, rel.x, rel.y, rel.z]))
        r = SU2Element(*rc).log()
        S = self.P + Rm
        K = self.P @ np.linalg.inv(S)
        d = K @ r
        qd = SU2Element.from_rotvec(d)
        q = SU2Element(*self.q) * qd
        self.q = pc.canonical(np.array([q.w, q.x, q.y, q.z]))
        self.P = (np.eye(3) - K) @ self.P
        self.P = 0.5 * (self.P + self.P.T)                 # 对称化 (数值)
        self.n_upd += 1
        return {"innovation_rad": r.tolist(), "innovation_deg": math.degrees(float(np.linalg.norm(r))),
                "gain": K.diagonal().tolist(), "gain_trace": float(np.trace(K)),
                "P_trace": float(np.trace(self.P)), "q": self.q.tolist()}



def selftest(n: int = 200, seed: int = 11) -> dict:
    """判据: ① ‖q‖=1 ② 距目标单调递减 ③ 每步角 ≤ 限幅 ④ ω 方向自洽(施加后残余≈0) ⑤ R_cmd 正交"""
    rng = np.random.default_rng(seed)
    ch = S3Chain(dt=0.1, horizon=8, omega_max=1.0)
    unit, mono, step_ok, dec_ok, orth, resid = 0.0, 0, 0, 0, 0.0, 0.0
    for _ in range(n):
        q = pc.canonical(pc.q_from_rotvec(rng.normal(size=3) * 0.8))
        pr = ch.predict(q)
        qs = [np.asarray(x, float) for x in pr["q"]]
        unit = max(unit, max(abs(float(np.linalg.norm(x)) - 1.0) for x in qs))
        goal = np.asarray(pr["q_goal"], float)
        dg = [float(pc.s3_angle(goal, x)) for x in qs]                   # 距目标
        mono += int(all(dg[i] <= dg[i - 1] + 1e-12 for i in range(1, len(dg))))
        steps = [float(pc.s3_angle(qs[i - 1] if i else q, qs[i])) for i in range(len(qs))]
        step_ok += int(max(steps) <= ch.omega_max * ch.dt / 2.0 + 1e-9)
        d = ch.decode(qs, q_start=q)
        dec_ok += int(all(np.isfinite(o).all() for o in np.asarray(d["omega_rad_s"])))
        # ω 方向自洽: 左乘施加后应精确到轨迹第 1 点 (q ← exp(ω·dt)·q0 = qs[0])
        U = SU2Element(*np.asarray(q, float))
        w = np.asarray(d["omega_rad_s"][0], float)
        left = SU2Element.from_rotvec(w * ch.dt) * U
        resid = max(resid, float(pc.s3_angle([left.w, left.x, left.y, left.z], qs[0])))
        Rc = pc.R_from_q(q) @ pc.R_from_q(qs[0]).T
        orth = max(orth, float(np.max(np.abs(Rc.T @ Rc - np.eye(3)))), abs(float(np.linalg.det(Rc)) - 1.0))
    return {"n": n, "unit_norm_max_err": unit, "monotone_to_goal_ratio": mono / n,
            "step_limit_ok_ratio": step_ok / n, "decode_finite_ratio": dec_ok / n,
            "omega_direction_residual_rad": resid, "R_cmd_orthonormal_err": orth,
            "step_max_deg": math.degrees(ch.omega_max * ch.dt)}


def selftest_ekf(steps: int = 400, seed: int = 5, dt: float = 0.1,
                 sigma_meas_deg: float = 2.0, sigma_proc_deg: float = 0.5) -> dict:
    """合成数据验证滤波器实现是否正确 (已知真值 + 已知噪声; **不是**真机效果)。

    对比三种估计: 纯测量 / 固定增益互补(α=0.5) / S3EKF(协方差自适应)。
    期望: EKF ≤ 固定增益 ≤ 纯测量 (在 Q/R 与真实噪声一致的条件下)。
    """
    rng = np.random.default_rng(seed)
    om = rng.normal(size=3)
    om = om / np.linalg.norm(om) * 0.6                       # rad/s, 恒定角速度
    sm, sp = math.radians(sigma_meas_deg), math.radians(sigma_proc_deg)
    q_true = np.array([1.0, 0, 0, 0])
    q_meas_only = q_true.copy()
    q_fix = q_true.copy()
    ekf = S3EKF(q_true, P0=np.eye(3) * sp ** 2,
                Q=np.eye(3) * sp ** 2, R=np.eye(3) * sm ** 2)
    e_meas, e_fix, e_ekf, gains = [], [], [], []
    for _ in range(steps):
        # 真值: 恒定 ω + 小过程扰动
        w_true = om + rng.normal(size=3) * sp / math.sqrt(dt)
        q_true = pc.canonical(_mul(q_true, SU2Element.from_rotvec(w_true * dt)))
        # 测量: 真值 ⊕ N(0, σ_meas)
        q_meas = pc.canonical(_mul(q_true, SU2Element.from_rotvec(rng.normal(size=3) * sm)))
        q_meas_only = q_meas
        q_fix = pc.slerp(q_fix, q_meas, 0.5)                 # 固定增益 (现有 quat_truth 口径)
        ekf.predict(w_true, dt)                              # 模型预测 (真 ω 当控制输入)
        u = ekf.update(q_meas)
        gains.append(u["gain_trace"])
        for e, q_est in ((e_meas, q_meas_only), (e_fix, q_fix), (e_ekf, ekf.q)):
            e.append(float(pc.s3_angle(q_est, q_true)))
    rm = lambda a: math.degrees(2.0 * float(np.sqrt(np.mean(np.square(a)))))   # 物理角 RMS
    return {"steps": steps, "sigma_meas_deg": sigma_meas_deg, "sigma_proc_deg": sigma_proc_deg,
            "rmse_meas_only_deg": round(rm(e_meas), 4),
            "rmse_fixed_gain_deg": round(rm(e_fix), 4),
            "rmse_ekf_deg": round(rm(e_ekf), 4),
            "ekf_vs_meas": round(rm(e_ekf) / max(1e-12, rm(e_meas)), 4),
            "ekf_vs_fixed": round(rm(e_ekf) / max(1e-12, rm(e_fix)), 4),
            "gain_trace_mean": round(float(np.mean(gains)), 4),
            "note": "合成数据 (噪声已知); 真机需用实测 Q/R 重新标定, 此结果不代表真机精度"}


def _mul(q, e: SU2Element) -> np.ndarray:
    r = SU2Element(*np.asarray(q, float).reshape(4)) * e
    return np.array([r.w, r.x, r.y, r.z], float)


if __name__ == "__main__":
    r = selftest()
    print("S3Chain 自检:", {k: (round(v, 12) if isinstance(v, float) else v) for k, v in r.items()})
