#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚙️ se3_impedance.py — SE(3) 几何阻抗 (状态空间的「万有引力」后端, 老倪 2026-10-25)

老倪原话: 「将状态空间的万有引力, 按照这个算法实现」

## 万有引力原来是什么
画布「🪐 球心引力架构」背后的势函数是 `manifold_engine._metric_phi_smooth`:
    Φ(q) = ½(1 − ⟨q̂, ĝ⟩)          # 球面上的"离开目标多远", 欧氏/球面口径
它有两个毛病: ① 只有**方向**, 没有轴向/侧向的区别, 插销时侧向和轴向一样硬
              ② 旋转用参数化差, 大姿态下 Lyapunov 失效

## 现在换成什么 (本模块)
SE(3) 几何阻抗的势能就是黎曼测地线代价:
    V(g) = ½‖log(g⁻¹·g_d)‖²_K = ½·ξ_eᵀ·K·ξ_e        ξ_e = log(g⁻¹g_d) ∈ se(3)
反馈:
    u = −K·ξ_e − B·(ξ − Ad_{g̃⁻¹}·ξ_d) + F_d
被动性 (要证的):
    V̇ = −ξ_eᵀ·B·ξ_e ≤ 0        (K,B 正定 ⇒ 半负定 ⇒ LaSalle ⇒ g→g_d)

## 刚性主轴固定在**工具本体**, 所以插销能"侧向软、轴向硬"
    K = diag[k_lat, k_lat, k_ax, k_rot_lat, k_rot_lat, k_rot_ax]   (顺序 [ρ; ω])
这是欧氏阻抗做不到的: 末端一转, 欧氏刚度主轴就跟着世界系错位了。

## 🔴 分量顺序 (踩过就会侧向/轴向互换)
本模块对外一律用老倪方案的 **[ρ(3); ω(3)]  平移在前**。
`lie_intent.se3_log` 返回的却是 **[ω(3); v(3)]  旋转在前**,
所以每次进出都走 `_xi_lie_to_std` / `_xi_std_to_lie` 显式转换 —— 不要图省事直接传。

自检: python3 -m lerobot.manifold.se3_impedance --selftest
"""
from __future__ import annotations

import os
import sys

import numpy as np

try:
    from .lie_intent import R_from_quat, se3_exp, se3_log
except Exception:                                                      # noqa: BLE001
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lie_intent import R_from_quat, se3_exp, se3_log                # type: ignore


# ═══════════════ 分量顺序转换 ═══════════════
def _xi_lie_to_std(xi_lie):
    """lie_intent 的 [ω; v] → 老倪方案的标准序 [ρ; ω] (平移在前)。"""
    x = np.asarray(xi_lie, float).ravel()
    return np.concatenate([x[3:6], x[0:3]])


def _xi_std_to_lie(xi_std):
    """标准序 [ρ; ω] → lie_intent 的 [ω; v]。"""
    x = np.asarray(xi_std, float).ravel()
    return np.concatenate([x[3:6], x[0:3]])


# ═══════════════ SE(3) 伴随 ═══════════════
def skew(p):
    """3 维向量 → 反对称矩阵。"""
    x, y, z = float(p[0]), float(p[1]), float(p[2])
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]], float)


def adjoint(g):
    """SE(3) 伴随 Ad_g (6×6), 按标准序 [ρ; ω] 分块。

        Ad_g = [[ R,      hat(p)·R ],
                [ 0,      R       ]]
    Pinocchio 的 `pin.SE3.adjoint` 走的是 [ω; v] 分块, 这里按老倪的 [ρ; ω] 排,
    所以两个角块的位置和它相反 —— 用错会让伴随校正整体错位。
    """
    g = np.asarray(g, float).reshape(4, 4)
    R = g[:3, :3]
    p = g[:3, 3]
    Ad = np.zeros((6, 6), float)
    Ad[0:3, 0:3] = R
    Ad[0:3, 3:6] = skew(p) @ R
    Ad[3:6, 3:6] = R
    return Ad


def adjoint_inv(g):
    """Ad_{g⁻¹} —— 直接用 4×4 求逆, 避免手推符号错。"""
    g = np.asarray(g, float).reshape(4, 4)
    return adjoint(np.linalg.inv(g))


# ═══════════════ 势能 / 误差 ═══════════════
def pose_error(g, g_d):
    """体坐标系相对误差位姿 g̃ = g⁻¹·g_d 与切空间误差 ξ_e = log(g̃)。"""
    g = np.asarray(g, float).reshape(4, 4)
    g_d = np.asarray(g_d, float).reshape(4, 4)
    g_t = np.linalg.inv(g) @ g_d
    xi_e = _xi_lie_to_std(se3_log(g_t))
    return g_t, xi_e


def potential(g, g_d, K):
    """V(g) = ½ ξ_eᵀ K ξ_e —— 这就是黎曼测地线代价 (Lyapunov 候选)。"""
    _, xi_e = pose_error(g, g_d)
    return 0.5 * float(xi_e @ np.asarray(K, float) @ xi_e)


def potential_rate(xi_e, B):
    """V̇ = −ξ_eᵀ B ξ_e —— 闭环设计目标。K,B 正定 ⇒ ≤ 0。"""
    return -float(np.asarray(xi_e, float) @ np.asarray(B, float) @ np.asarray(xi_e, float))


# ═══════════════ 阻抗控制器 ═══════════════
# 销钉插入默认刚度 (老倪方案 §二 的数值: 侧向软、轴向硬)
K_INSERT = dict(k_lat=80.0, k_ax=400.0, k_rot_lat=2.0, k_rot_ax=10.0, alpha=0.15)


class Se3ImpedanceController:
    """SE(3) 几何阻抗 — 体坐标系, 被动, 等变。

    两种输出模式:
      mode="torque"  给力控臂: τ = Jᵀ·u           (需要体雅可比 J_b)
      mode="twist"   给速度环: 直接下发期望体 twist (低成本协作臂)

    本类**不碰关节**, 只产出体坐标系力扭 u (6维, 标准序 [力; 力矩]?? 注意:
    标准序 [ρ; ω] 对应 [力; 力矩] —— ρ 是平移误差, 共轭量是力; ω 是旋转误差,
    共轭量是力矩)。τ 由调用方用 J_bᵀ 映射。
    """

    def __init__(self, k_lat=None, k_ax=None, k_rot_lat=None, k_rot_ax=None,
                 alpha=None, u_max=None, Kf=None, filter_alpha=0.3):
        c = K_INSERT
        k_lat = c["k_lat"] if k_lat is None else float(k_lat)
        k_ax = c["k_ax"] if k_ax is None else float(k_ax)
        k_rot_lat = c["k_rot_lat"] if k_rot_lat is None else float(k_rot_lat)
        k_rot_ax = c["k_rot_ax"] if k_rot_ax is None else float(k_rot_ax)
        alpha = c["alpha"] if alpha is None else float(alpha)

        # K 顺序 [ρ(3); ω(3)] = [x, y, z, rx, ry, rz]
        #   销钉插入: z 是插入轴 ⇒ k_ax 在第 3 位
        self.K = np.diag([k_lat, k_lat, k_ax, k_rot_lat, k_rot_lat, k_rot_ax])
        self.B = alpha * self.K
        # 笛卡尔力扭限幅 [N, N, N, Nm, Nm, Nm]
        self.u_max = np.array([20.0, 20.0, 50.0, 5.0, 5.0, 3.0]) if u_max is None else np.asarray(u_max, float)
        # 力反馈增益 (纯位姿阻抗时全 0)
        self.Kf = np.zeros((6, 6)) if Kf is None else np.asarray(Kf, float)
        self.filter_alpha = float(filter_alpha)
        self._u_prev = None
        self.trace = []

    # ── 饱和 ──
    def saturate(self, u):
        return np.clip(np.asarray(u, float), -self.u_max, self.u_max)

    # ── 一阶低通 ──
    def _filter(self, u):
        if self._u_prev is None or self.filter_alpha >= 1.0:
            self._u_prev = u.copy()
            return u
        a = self.filter_alpha
        out = a * u + (1.0 - a) * self._u_prev
        self._u_prev = out.copy()
        return out

    def reset(self):
        self._u_prev = None
        self.trace.clear()

    def step(self, g, g_d, xi, xi_d=None, F_m=None, F_d=None):
        """一个控制周期。

        g, g_d   : 4×4 SE(3), 体坐标系/装配局部系 (不要世界系 —— H-JEPA 输出的是 g_rel)
        xi       : 当前体 twist, 标准序 [v(3); ω(3)]
        xi_d     : 目标体 twist (静态装配置 None)
        F_m      : 测量体力扭 (无传感器置 None)
        F_d      : 期望接触力扭 (插入压紧力, 如 [0,0,-10,0,0,0])
        → dict(u, u_imp, u_force, xi_e, V, Vdot, sat, why)
        """
        xi = np.asarray(xi, float).ravel() if xi is not None else np.zeros(6)
        g_t, xi_e = pose_error(g, g_d)

        # 目标 twist 的伴随校正 (空间 → 体)
        if xi_d is None:
            xi_d_body = np.zeros(6)
        else:
            xi_d_body = adjoint_inv(g_t) @ np.asarray(xi_d, float).ravel()

        # 阻抗项
        # 🔴 符号: 方案原文写 u = −K·ξ_e − B·ξ, 但 ξ_e = log(g⁻¹g_d) 是**从当前指向目标**
        #    的体位移 (目标在 +z 时 ξ_e.ρ_z = +0.02)。要让 g 追上 g_d, 体速度必须沿 +ξ_e,
        #    而 −K·ξ_e 恰好往反方向推 ⇒ 闭环发散 (实测 V 从 0.08 炸到 1.8e7, 残余 299m)。
        #    正确律: u = +K·ξ_e − B·ξ。它同样满足 V̇ = −ξ_eᵀBξ_e:
        #    闭环稳态 ξ → K⁻¹Bξ_e ⇒ V̇ = ξ_eᵀK(−ξ) = −ξ_eᵀBξ_e ≤ 0。
        u_imp = self.K @ xi_e - self.B @ (xi - xi_d_body)

        # 力项: F_err = F_m − F_d, u_force = F_d − Kf·F_err
        if F_d is None:
            F_d = np.zeros(6)
        else:
            F_d = np.asarray(F_d, float).ravel()
        if F_m is None:
            u_force = F_d.copy()
        else:
            F_err = np.asarray(F_m, float).ravel() - F_d
            u_force = F_d - self.Kf @ F_err

        u_cart = u_imp + u_force
        u_sat = self.saturate(u_cart)
        sat = bool(np.any(np.abs(u_cart) > self.u_max + 1e-12))
        u = self._filter(u_sat)

        V = 0.5 * float(xi_e @ self.K @ xi_e)
        Vdot = potential_rate(xi_e, self.B)
        rec = {"u": u, "u_imp": u_imp, "u_force": u_force, "xi_e": xi_e,
               "g_tilde": g_t, "V": V, "Vdot": Vdot, "saturated": sat,
               "xi_d_body": xi_d_body}
        self.trace.append({"V": V, "Vdot": Vdot, "|xi_e|": float(np.linalg.norm(xi_e))})
        return rec

    # ── 关节点映射 ──
    @staticmethod
    def to_joint_torque(u, Jb):
        """τ = J_bᵀ · u —— **必须用体雅可比**, 空间雅可比 J_s 会直接让稳定性不成立。"""
        Jb = np.asarray(Jb, float)
        return Jb.T @ np.asarray(u, float)


# ═══════════════ 自检 ═══════════════
def _selftest() -> int:
    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("① 分量顺序转换")
    x_lie = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])       # [ω; v]
    x_std = _xi_lie_to_std(x_lie)
    chk("lie[ω;v]→std[ρ;ω] 正确", np.allclose(x_std, [0.4, 0.5, 0.6, 0.1, 0.2, 0.3]),
        str(np.round(x_std, 3)))
    chk("往返一致", np.allclose(_xi_std_to_lie(x_std), x_lie))

    print("② 伴随映射")
    # 纯平移 p=(1,0,0), R=I ⇒ Ad = [[I, skew(p)],[0,I]]
    g = np.eye(4); g[0, 3] = 1.0
    Ad = adjoint(g)
    expect = np.eye(6); expect[0:3, 3:6] = skew([1, 0, 0])
    chk("纯平移 Ad_g 正确", np.allclose(Ad, expect))
    # 恒等位姿 ⇒ Ad=I
    chk("g=I ⇒ Ad=I", np.allclose(adjoint(np.eye(4)), np.eye(6)))
    # Ad_{g}·Ad_{g⁻¹} = I
    th = np.radians(35)
    g2 = np.eye(4); g2[:3, :3] = [[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]]
    g2[:3, 3] = [0.3, -0.2, 0.1]
    chk("Ad_g·Ad_{g⁻¹}=I", np.allclose(adjoint(g2) @ adjoint_inv(g2), np.eye(6), atol=1e-12),
        "max|Δ|=%.2e" % np.abs(adjoint(g2) @ adjoint_inv(g2) - np.eye(6)).max())

    print("③ 势能与误差")
    ctrl = Se3ImpedanceController()
    g_id = np.eye(4)
    chk("g=g_d ⇒ ξ_e=0", np.allclose(pose_error(g_id, g_id)[1], 0.0, atol=1e-15))
    chk("g=g_d ⇒ V=0", abs(potential(g_id, g_id, ctrl.K)) < 1e-15)
    # 纯轴向(z)偏 1cm
    gd = np.eye(4); gd[2, 3] = 0.01
    _, xi_e = pose_error(g_id, gd)
    chk("纯 z 偏 1cm ⇒ ρ_z=0.01 且 ω=0",
        abs(xi_e[2] - 0.01) < 1e-12 and np.allclose(xi_e[3:], 0, atol=1e-12),
        "ξ_e=%s" % np.round(xi_e, 6))
    V = potential(g_id, gd, ctrl.K)
    chk("V = ½·k_ax·(0.01)² = 0.02 J", abs(V - 0.5 * 400.0 * 1e-4) < 1e-12, "V=%.6f" % V)

    print("④ 被动性 V̇ = −ξ_eᵀBξ_e ≤ 0")
    rng = np.random.default_rng(0)
    worst = -1e9
    for _ in range(500):
        xi_e = rng.normal(0, 0.05, 6)
        vd = potential_rate(xi_e, ctrl.B)
        worst = max(worst, vd)
    chk("500 个随机 ξ_e 全部 V̇ ≤ 0", worst <= 1e-15, "max V̇ = %.3e" % worst)
    # 非正定 B 应该被抓出来 (示例: 负刚度)
    bad = np.diag([-1.0, 1, 1, 1, 1, 1])
    chk("负刚度 ⇒ V̇ 可为正 (说明检查有效)", potential_rate([1, 0, 0, 0, 0, 0], bad) > 0,
        "V̇=%.3f" % potential_rate([1, 0, 0, 0, 0, 0], bad))

    print("⑤ 闭环收敛 (质量-弹簧-阻尼, m=1kg)")
    # 🔴 u 的量纲是**力**不是速度。第一版直接拿 u 当速度积分:
    #    K=400N/m × 0.02m = 8N 被当成 8m/s ⇒ V 从 0.08 炸到 4.5e6, 残余 150m。
    #    正确做法: m·v̇ = u ⇒ v += (u/m)·dt, 位姿按 v 积分。
    ctrl2 = Se3ImpedanceController(filter_alpha=1.0)
    g_cur = np.eye(4)
    g_goal = np.eye(4); g_goal[2, 3] = 0.02      # 向下插 2cm
    m = 1.0
    v = np.zeros(6)
    Vs, Vdots = [], []
    dt = 2e-4
    for _ in range(20000):
        rec = ctrl2.step(g_cur, g_goal, xi=v)
        Vs.append(rec["V"]); Vdots.append(rec["Vdot"])
        a = rec["u"] / m                          # 力 → 加速度
        v = v + a * dt
        g_cur = g_cur @ se3_exp(_xi_std_to_lie(v * dt))
    chk("V 单调不增", all(Vs[i + 1] <= Vs[i] + 1e-10 for i in range(len(Vs) - 1)),
        "V: %.4e → %.4e" % (Vs[0], Vs[-1]))
    chk("V 收敛到近 0", Vs[-1] < 1e-7, "V_end=%.3e" % Vs[-1])
    resid = float(np.linalg.norm(g_cur[:3, 3] - g_goal[:3, 3]))
    chk("末态残余距离 <0.5mm", resid < 5e-4, "残余 %.6f m" % resid)
    chk("V̇ 全程 ≤0", max(Vdots) <= 1e-12, "max V̇ = %.3e" % max(Vdots))

    print("⑥ 各向异性: 侧向软 / 轴向硬")
    # 同样 1cm 误差, 轴向需要的力应远大于侧向
    gx = np.eye(4); gx[0, 3] = 0.01
    gz = np.eye(4); gz[2, 3] = 0.01
    u_x = ctrl2.step(np.eye(4), gx, xi=np.zeros(6))["u_imp"]
    u_z = ctrl2.step(np.eye(4), gz, xi=np.zeros(6))["u_imp"]
    chk("轴向力 > 侧向力", abs(u_z[2]) > abs(u_x[0]) * 2,
        "|F_z|=%.2f N vs |F_x|=%.2f N (比 %.1f×)" % (abs(u_z[2]), abs(u_x[0]),
                                                     abs(u_z[2]) / max(abs(u_x[0]), 1e-9)))
    chk("力方向朝目标 (符号正确)", u_z[2] > 0 and u_x[0] > 0,
        "目标在 +z ⇒ u_z=%.2f>0 ✓; 目标在 +x ⇒ u_x=%.2f>0 ✓" % (u_z[2], u_x[0]))
    chk("刚度比 = k_ax/k_lat = 5", abs((ctrl.K[2, 2] / ctrl.K[0, 0]) - 5.0) < 1e-12,
        "%.1f" % (ctrl.K[2, 2] / ctrl.K[0, 0]))

    print("⑦ 饱和与低通")
    ctrl3 = Se3ImpedanceController(filter_alpha=1.0)
    gfar = np.eye(4); gfar[2, 3] = 0.5           # 50cm 偏离 ⇒ 远超限幅
    r = ctrl3.step(np.eye(4), gfar, xi=np.zeros(6))
    chk("超限被标记 saturated", r["saturated"] is True, str(r["saturated"]))
    chk("输出在限幅内", np.all(np.abs(r["u"]) <= ctrl3.u_max + 1e-9),
        "max|u|=%.2f" % np.abs(r["u"]).max())
    ctrl4 = Se3ImpedanceController(filter_alpha=0.3)
    r1 = ctrl4.step(np.eye(4), gz, xi=np.zeros(6))["u"]
    r2 = ctrl4.step(np.eye(4), gz, xi=np.zeros(6))["u"]
    chk("低通首步=原值, 次步趋稳", np.allclose(r1, r2, atol=1e-9),
        "一致 (稳态输入下不变)")

    print("⑧ 力前馈 + 力反馈")
    ctrl5 = Se3ImpedanceController(filter_alpha=1.0)
    Fd = np.array([0, 0, -10.0, 0, 0, 0])       # 轴向 -10N 压紧
    r = ctrl5.step(np.eye(4), np.eye(4), xi=np.zeros(6), F_d=Fd, F_m=Fd)
    chk("Kf=0 且力已达标 ⇒ 输出 = F_d", np.allclose(r["u"], Fd, atol=1e-9),
        "u=%s" % np.round(r["u"], 3))
    # 打开轴向力反馈增益 kf_z=0.5 N/N: 力不足 6N ⇒ 补 0.5×6 = 3N
    Kf = np.zeros((6, 6)); Kf[2, 2] = 0.5
    ctrl6 = Se3ImpedanceController(filter_alpha=1.0, Kf=Kf)
    r = ctrl6.step(np.eye(4), np.eye(4), xi=np.zeros(6), F_d=Fd,
                   F_m=np.array([0, 0, -4.0, 0, 0, 0]))
    chk("力不足 6N + kf=0.5 ⇒ 输出 = F_d − 0.5×6 = −13N",
        abs(r["u"][2] - (-13.0)) < 1e-9, "u_z=%.2f (期望 -13.00)" % r["u"][2])
    chk("Kf=0 时轴向不随 F_err 变 (前面那条判据写错的原因)",
        abs(ctrl5.step(np.eye(4), np.eye(4), xi=np.zeros(6), F_d=Fd,
                       F_m=np.array([0, 0, -4.0, 0, 0, 0]))["u"][2] - Fd[2]) < 1e-9)

    print("⑨ 体雅可比映射")
    Jb = np.ones((6, 7)) * 0.1
    u = np.array([1.0, 2, 3, 0.1, 0.2, 0.3])
    tau = Se3ImpedanceController.to_joint_torque(u, Jb)
    chk("τ 维数 = 关节数", tau.shape == (7,), str(tau.shape))
    chk("τ = Jᵀu 逐位", np.allclose(tau, Jb.T @ u))

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 全部通过 (SE(3) 几何阻抗: 被动性/收敛/各向异性/力前馈)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv or len(sys.argv) == 1:
        sys.exit(_selftest())
    print("用法: python3 -m lerobot.manifold.se3_impedance --selftest")
