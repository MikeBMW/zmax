#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态空间的哈密顿能量层 —— H = K + U，力场 = −∇U，全部层受同一力场约束。

老倪 2026-10-25: 「我要基于万有引力，计算状态空间的动能和势能；画布右侧栏的主参数下面的
合力计算，你觉得合理么？有没有真正的对应关系？要不改成哈密顿力学？H=K+U，你来设计公式和 UI」

## 一、为什么把"合力"换成 H = K + U（旧口径的三个硬伤）

旧口径 (tools/layer_forces.py + tools/gui/gravity_table.py) 的"合力"是：
    F_合 = Σ_l w_l·k_l·v_l ,  v_l 是各层模型输出的**速度当量 (m/s)**
三个问题：
  ① **量纲不对**：它是 m/s 的加权矢量和，被当成"力"画在表上；真力是 N。两者之间没有质量、
     没有惯量、没有时间积分 ⇒ 不存在任何换算关系（不是比例系数没调好，是**没有对应关系**）。
  ② **不可积**：不存在一个标量 Φ 使 v_l 的加权和 = −∇Φ ⇒ "力场"这个词不成立
     （保守场才谈势；力场若不可积，闭环能量无法定义，被动性也无从判定）。
  ③ **没有能量**：没有 K（动能）、没有 U（势能）⇒ 无法回答"这次动作把多少能量注进了系统"。

## 二、本模块的公式（全部可数值核验，见 tools/verify_hamiltonian_energy.py）

位形与速度（体坐标，标准序 ρ=[x,y,z] · ω=[rx,ry,rz]）：
    g ∈ SE(3) 末端位姿 · ξ ∈ se(3) 体速度 [v; ω] · ξ_e = log(g⁻¹·g_d) 指向目标

势能 U（全部是 ξ_e 的二次型 ⇒ 天然保守、可积）：
    U_task  = ½ ξ_eᵀ K_c ξ_e                    任务势（阻抗势）
    U_layer = Σ_l ½ s_l ξ_eᵀ K_c ξ_e = ½ ξ_eᵀ(Σ s_l)K_c ξ_e
              其中 s_l 是每层刚度份额, **Σ_l s_l = 1** ⇒ U_layer ≡ U_task 的分解（恒等式）
    U_grav  = −G Σ_{i<j} M_i M_j / r_ij         层间引力（r_ij=‖F_i−F_j‖; 无 G 配置则记 0，不造数）
    U       = U_task + U_grav

动能 K（体坐标惯量 Λ = diag(m,m,m,Ix,Iy,Iz)）：
    K = ½ ξᵀ Λ ξ

哈密顿量：
    H = K + U

力（力场 = 势的梯度，逐层可分解）：
    F_l = s_l · K_c ξ_e          （偏导 ∂U_layer/∂ξ_e 的逐层份额）
    F   = K_c ξ_e + ∂U_grav/∂x   （Σ_l F_l = K_c ξ_e，恒等式，残差应 = 0）

闭环动力学（阻抗 + 阻尼注入，端口哈密顿形式）：
    ξ̇ = Λ⁻¹ ( F − B ξ ) ,   B = α·K_c  （α = 阻尼比）
    Ḣ = ξᵀΛξ̇ + ξ_eᵀK_c ξ̇_e
      = ξᵀ(F − Bξ) + ξ_eᵀK_c(−ξ)
      = −ξᵀBξ  ≤ 0        ← 交叉项精确抵消，**被动性由结构保证**，不是靠调参

## 三、符号约定（踩过的坑，别改）

· ξ_e 指向目标，所以驱动量取 **+K_c ξ_e**（不是 −）。按原文 −K 会往反方向推：
  实测闭环 V 从 0.08 炸到 1.8e7、残余 299 m。
· 分量序是 **[ρ; ω] = [力; 力矩]**，不是 [ω; v]。搞反 ⇒ 侧向/轴向刚度互换，
  「插销柔顺」变「插销僵硬」（Pinocchio 的 Adjoint 也是 [ω;v] 分块，自写时别照抄）。
· 单位：ξ 平移 m/s、旋转 rad/s；K 平移 N/m、旋转 N·m/rad；U/K/H 焦耳(J)；F 的平移 N、旋转 N·m。
"""
from __future__ import annotations

import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from se3_impedance import K_INSERT, pose_error  # noqa: E402
from se3_gravity_provider import _rpy_to_T  # noqa: E402
try:                                        # 与 se3_impedance 同一份真件 (lie_intent)
    from .lie_intent import se3_exp, se3_log   # type: ignore  # noqa: F401
except Exception:                                                  # noqa: BLE001
    from lie_intent import se3_exp, se3_log     # type: ignore  # noqa: F401

# 每层刚度份额（归一化后 Σ=1）—— 与 config/calib/layer_forces.json 的 w 同源，
# 但这里必须归一，否则 U_layer 不是 U_task 的分解（旧口径"权重不参与归一"就是这个病）。
LAYER_SHARE = {"L2": 0.30, "L3": 0.25, "L4": 0.30, "L5": 0.15}

# 体坐标惯量默认值（3.643 kg = layer_forces.json 的 m_ref；惯量按 0.05kg·m² 量级给，
# 真机标定后从 config/calib/hamiltonian.json 覆盖 —— 缺配置就用这里，并且**如实标注来源**）。
DEFAULT_MASS_KG = 3.643
DEFAULT_INERTIA = (0.020, 0.020, 0.012)   # Ix, Iy, Iz (kg·m²)


def layer_shares(weights: dict | None = None) -> dict:
    """把任意非负权重归一成份额（Σ=1）。缺项/全 0 ⇒ 用 LAYER_SHARE。"""
    w = dict(weights or LAYER_SHARE)
    tot = sum(max(0.0, float(v)) for v in w.values())
    if tot <= 0:
        return dict(LAYER_SHARE)
    return {k: max(0.0, float(v)) / tot for k, v in w.items()}


class StateSpaceHamiltonian:
    """状态空间能量层：给 (g, g_d, ξ) 算出 U / K / H / F 与逐层力。"""

    def __init__(self, k_lat=None, k_ax=None, k_rot_lat=None, k_rot_ax=None,
                 alpha=None, mass=None, inertia=None, shares=None, G=None,
                 grav_masses=None, source=""):
        c = K_INSERT
        self.k_lat = c["k_lat"] if k_lat is None else float(k_lat)
        self.k_ax = c["k_ax"] if k_ax is None else float(k_ax)
        self.k_rot_lat = c["k_rot_lat"] if k_rot_lat is None else float(k_rot_lat)
        self.k_rot_ax = c["k_rot_ax"] if k_rot_ax is None else float(k_rot_ax)
        self.alpha = c["alpha"] if alpha is None else float(alpha)
        # K 顺序 [ρ(3); ω(3)]
        self.K = np.diag([self.k_lat, self.k_lat, self.k_ax,
                          self.k_rot_lat, self.k_rot_lat, self.k_rot_ax])
        self.B = self.alpha * self.K
        self.share = layer_shares(shares)
        self.mass = float(DEFAULT_MASS_KG if mass is None else mass)
        inertia = DEFAULT_INERTIA if inertia is None else inertia
        self.Lam = np.diag([self.mass, self.mass, self.mass,
                            float(inertia[0]), float(inertia[1]), float(inertia[2])])
        # 层间引力（可选）：没给 G 就明确记 0，不当成"算出来了 0"
        self.G = None if G is None else float(G)
        self.grav_masses = dict(grav_masses or {})
        self.source = source or ("config/calib/hamiltonian.json" if G is not None else
                                 "默认值(m_ref=%.3f kg, 无引力项)" % self.mass)

    # ── 势能 ──
    def potential(self, g, g_d):
        """U = U_task + U_grav（J）。返回 (U, 明细 dict)。"""
        _, xi_e = pose_error(g, g_d)
        u_task = 0.5 * float(xi_e @ self.K @ xi_e)
        u_layer = {k: s * u_task for k, s in self.share.items()}
        u_grav, r_ij = self._grav_potential(g, g_d, xi_e)
        return u_task + u_grav, {
            "U_task": u_task, "U_layer": u_layer, "U_grav": u_grav,
            "U": u_task + u_grav, "xi_e": xi_e, "r_ij": r_ij,
        }

    def _layer_forces(self, xi_e):
        """逐层力 F_l = s_l·K ξ_e（N / N·m）。Σ_l F_l = K ξ_e 是恒等式。"""
        return {k: s * (self.K @ xi_e) for k, s in self.share.items()}

    def _grav_potential(self, g, g_d, xi_e):
        if self.G is None or len(self.grav_masses) < 2:
            return 0.0, {}
        fl = self._layer_forces(xi_e)
        keys = [k for k in self.share if k in self.grav_masses]
        u, rmap = 0.0, {}
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                r = float(np.linalg.norm(fl[a] - fl[b]))
                if r < 1e-9:
                    continue
                rmap["%s-%s" % (a, b)] = r
                u -= self.G * float(self.grav_masses[a]) * float(self.grav_masses[b]) / r
        return u, rmap

    # ── 动能 ──
    def kinetic(self, xi):
        xi = np.asarray(xi, float).ravel()
        return 0.5 * float(xi @ self.Lam @ xi)

    # ── 总能量 ──
    def energy(self, g, g_d, xi):
        xi = np.zeros(6) if xi is None else np.asarray(xi, float).ravel()
        u, det = self.potential(g, g_d)
        k = self.kinetic(xi)
        fl = self._layer_forces(det["xi_e"])
        F = self.K @ det["xi_e"]
        return {
            "U": u, "K": k, "H": k + u,
            "U_task": det["U_task"], "U_layer": det["U_layer"], "U_grav": det["U_grav"],
            "xi_e": det["xi_e"], "F": F, "F_layers": fl,
            "F_task_only": F.copy(),
            "layer_residual": float(np.linalg.norm(sum(fl.values()) - F)),
            "mass_kg": self.mass, "inertia": list(np.diag(self.Lam)[3:]),
            "K_diag": list(np.diag(self.K)), "alpha": self.alpha,
            "share": dict(self.share), "source": self.source,
            "r_ij": det["r_ij"],
        }

    # ── 动力学 + 被动性 ──
    def accel(self, xi_e, xi):
        """ξ̇ = Λ⁻¹(F − Bξ)：F 取 +K·ξ_e（指向上式符号约定）。"""
        return np.linalg.solve(self.Lam, self.K @ np.asarray(xi_e, float) - self.B @ np.asarray(xi, float))

    def hdot_analytic(self, xi):
        """Ḣ = −ξᵀBξ（交叉项精确抵消）—— 结构保证，不是拟合。"""
        xi = np.asarray(xi, float).ravel()
        return -float(xi @ self.B @ xi)

    def rollout(self, g0, g_d, xi0=None, n=250, dt=1e-3):
        """闭环积分（SE(3) exp 回拉），返回每步的 U/K/H 序列。"""
        g = np.asarray(g0, float).reshape(4, 4).copy()
        xi = np.zeros(6) if xi0 is None else np.asarray(xi0, float).ravel().copy()
        rows = []
        for _ in range(n):
            _, xi_e = pose_error(g, g_d)
            a = self.accel(xi_e, xi)
            xi = xi + a * dt
            g = g @ se3_exp(self._std_to_lie(xi) * dt)
            e = self.energy(g, g_d, xi)
            rows.append({"U": e["U"], "K": e["K"], "H": e["H"], "xi": xi.copy(),
                         "rho_mm": 1000.0 * float(np.linalg.norm(e["xi_e"][:3]))})
        return rows

    @staticmethod
    def _std_to_lie(xi_std):
        """标准序 [ρ;ω] → 李代数序 [ω;ρ]（se3_exp 吃的是 [ω;ρ]）。"""
        xi_std = np.asarray(xi_std, float).ravel()
        return np.concatenate([xi_std[3:], xi_std[:3]])

    # ── 层受控判据：层动作在力场里的分量 ──
    def layer_projection(self, layer_axis, xi_e=None, tol_deg=60.0):
        """某层输出方向与合力方向的夹角 ⇒ 是否允许（沿力场的分量放行，横向否决）。

        layer_axis: 该层输出的平移方向（3 维, 任意尺度）
        返回 {'cos': 余弦, 'deg': 夹角, 'allow': bool}
        判据与 L2 收口闸同口径: 夹角 > tol_deg ⇒ veto（不许横着走）。
        """
        if xi_e is None:
            raise ValueError("need xi_e")
        F = (self.K @ np.asarray(xi_e, float))[:3]
        a = np.asarray(layer_axis, float).ravel()[:3]
        nf, na = np.linalg.norm(F), np.linalg.norm(a)
        if nf < 1e-12 or na < 1e-12:
            return {"cos": 0.0, "deg": 90.0, "allow": False}
        c = float(np.clip(F @ a / (nf * na), -1.0, 1.0))
        deg = float(np.degrees(np.arccos(c)))
        return {"cos": c, "deg": deg, "allow": deg <= float(tol_deg)}




# ═══════════════ 实时取数 (引擎回路与画布节点共用同一份, 不各算一套) ═══════════════
def live_energy(root: str, cache: dict | None = None, ham=None) -> dict:
    """从**在跑的**实况算 U/K/H/F/Ḣ (引擎 emit 每周期调一次; 画布节点也调这里)。

    数据源 (缺就报缺, 绝不拿 0 冒充):
        zmax_data/ss_live/trace_live.json   末端_x/y/z · 光模块_x/y · 阶段 · src
        zmax_data/ss_live/chunk_latest.json 参考速度 u (首帧兜底)
    cache: 传入一个 dict 复用 (存上一帧 pos/ts 以算实测速度)。
    """
    import json as _json
    import os as _os
    import time as _t

    cache = cache if cache is not None else {}
    live = _os.path.join(root, "zmax_data", "ss_live")
    tr = _json.load(open(_os.path.join(live, "trace_live.json"), encoding="utf-8"))
    try:
        ck = _json.load(open(_os.path.join(live, "chunk_latest.json"), encoding="utf-8"))
    except Exception:                                                    # noqa: BLE001
        ck = {}
    pos = np.array([float(tr.get(k, 0.0)) for k in ("末端_x", "末端_y", "末端_z")])
    # 🔴 2026-10-29: 原来 z 恒取 pos[2] ⇒ ξ_e[2]≡0, 势场只在 xy 平面,
    #   插入/下降阶段的 z 误差被整段忽略 (实测光模块_z 0.1458 vs 末端_z 0.1735 差 27.7mm 却算成 0),
    #   四层力与势场力夹角落到 88°/126° 全被否决。改成 z 也参与, 缺值才回落。
    _mz = tr.get("光模块_z")
    tgt = np.array([float(tr.get("光模块_x", pos[0])), float(tr.get("光模块_y", pos[1])),
                    float(_mz) if _mz is not None else pos[2]])
    _axis = "xyz" if _mz is not None else "xy(z 缺光模块_z ⇒ 不参与)"
    xi_e = np.zeros(6)
    xi_e[0:3] = tgt[0:3] - pos[0:3]
    ts = float(tr.get("ts") or _t.time())
    prev = cache.get("prev")
    src_vel = "差分(实测末端)"
    if prev and ts > prev[0] and (ts - prev[0]) < 2.0:
        xi = np.zeros(6)
        xi[0:3] = (pos - prev[1]) / (ts - prev[0])
    else:
        xi = np.zeros(6)
        for k, v in enumerate((ck.get("u") or [])[:3]):
            xi[k] = float(v) if isinstance(v, (int, float)) else 0.0
        src_vel = "chunk 参考速度 u (首帧兜底)"
    cache["prev"] = (ts, pos.copy())
    h = ham or StateSpaceHamiltonian()
    K = h.kinetic(xi)
    U = 0.5 * float(xi_e @ h.K @ xi_e)
    F = h.K @ xi_e
    return {"ok": True, "ts": ts, "src": tr.get("src", ""), "stage": str(tr.get("阶段") or ""),
            "U": U, "K": K, "H": K + U, "hdot": h.hdot_analytic(xi), "passive": bool(h.hdot_analytic(xi) <= 0),
            "F": [float(x) for x in F], "F_norm": float(np.linalg.norm(F)),
            "xi_e": [float(x) for x in xi_e], "rho_mm": 1000.0 * float(np.linalg.norm(xi_e[:3])),
            "xi_e_axes": _axis,
            "xi": [float(x) for x in xi], "xi_src": src_vel,
            "K_diag": [float(x) for x in np.diag(h.K)], "alpha": h.alpha, "mass_kg": h.mass,
            "share": dict(h.share),
            "F_layers": {k: [float(x) for x in v] for k, v in h._layer_forces(xi_e).items()},
            "formula": "H=K+U · U=½ξeᵀKξe · K=½ξᵀΛξ · F=Kξe · Ḣ=−ξᵀBξ",
            "param_source": h.source}


# ═══════════════ 自测（最小可核） ═══════════════
def _selftest() -> int:
    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    h = StateSpaceHamiltonian()
    g0 = np.eye(4)
    g_d = _rpy_to_T([0.0, 0.0, 0.02, 0.0, 0.0, 0.0])       # 轴向 2cm 偏差
    e = h.energy(g0, g_d, np.zeros(6))
    chk("2cm 轴向 ⇒ U = ½·400·0.02² = 0.08 J", abs(e["U_task"] - 0.08) < 1e-12, "U_task=%.6f" % e["U_task"])
    xi = np.array([0.1, 0, 0, 0, 0, 0])
    chk("ξ=0.1m/s ⇒ K = ½·m·v²", abs(h.kinetic(xi) - 0.5 * h.mass * 0.01) < 1e-12,
        "K=%.6f J (m=%.3f)" % (h.kinetic(xi), h.mass))
    e2 = h.energy(g0, g_d, xi)
    chk("H = K + U", abs(e2["H"] - (e2["K"] + e2["U"])) < 1e-15, "H=%.6f" % e2["H"])
    chk("Σ_l F_l = K·ξ_e (层分解恒等式)", e2["layer_residual"] < 1e-12,
        "残差=%.3e N" % e2["layer_residual"])
    chk("Σ_l s_l = 1", abs(sum(h.share.values()) - 1.0) < 1e-15, str(h.share))
    chk("F_z = +k_ax·0.02 (符号: 指向目标)", abs(e2["F"][2] - 400 * 0.02) < 1e-12, "F_z=%.4f N" % e2["F"][2])
    roll = h.rollout(g0, g_d, np.zeros(6), n=1200, dt=1e-3)
    Hs = np.array([r["H"] for r in roll])
    chk("H 单调不增 (1200 步)", bool(np.all(np.diff(Hs) <= 1e-15)), "H: %.3e → %.3e" % (Hs[0], Hs[-1]))
    # Ḣ 解析式 vs 数值差分（同源检查, 不是"小于 0 就算过"）
    #   数值侧用**一步极小 dt 的瞬时差分**（dt=1e-6）: 避免 Euler 累计离散误差冒充公式错误。
    g_t = np.eye(4)
    xi_t = np.array([0.02, 0.0, 0.01, 0.0, 0.0, 0.0])
    _, xe_t = pose_error(g_t, g_d)
    a_t = h.accel(xe_t, xi_t)
    h0_t = h.energy(g_t, g_d, xi_t)["H"]
    dt_t = 1e-6
    g1_t = g_t @ se3_exp(h._std_to_lie(xi_t) * dt_t)
    h1_t = h.energy(g1_t, g_d, xi_t + a_t * dt_t)["H"]
    hd_num = (h1_t - h0_t) / dt_t
    hd_ana = h.hdot_analytic(xi_t)
    rel = abs(hd_num - hd_ana) / max(abs(hd_ana), 1e-12)
    chk("Ḣ 解析 −ξᵀBξ == 数值 dH/dt", rel < 0.02, "解析 %.6e vs 数值 %.6e (相对差 %.3f%%)"
        % (hd_ana, hd_num, 100 * rel))
    chk("末端残余 < 0.2mm", roll[-1]["rho_mm"] < 0.2, "ρ=%.4f mm (t=%.1fs)" % (roll[-1]["rho_mm"], 1200 * 1e-3))
    chk("无 G 配置 ⇒ U_grav 记 0 且来源可查(不造数)", e2["U_grav"] == 0.0 and "无引力项" in h.source, h.source)
    pr = h.layer_projection([1.0, 0, 0], xi_e=e2["xi_e"])
    chk("横向层动作被力场否决 (>60°)", pr["allow"] is False, "夹角 %.1f°" % pr["deg"])
    pr2 = h.layer_projection([0, 0, 1.0], xi_e=e2["xi_e"])
    chk("沿力场方向放行", pr2["allow"] is True, "夹角 %.1f°" % pr2["deg"])
    print("\n%s 全部通过" % "✅" if not fails else "\n❌ 失败: %s" % fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(_selftest())
