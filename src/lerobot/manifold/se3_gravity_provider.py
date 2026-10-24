#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌍 se3_gravity_provider.py — 用 SE(3) 几何阻抗实现状态空间的「万有引力」

老倪 2026-10-25: 「将状态空间的万有引力, 按照这个算法实现」

## 原来的万有引力
`manifold_engine._metric_phi_smooth`:  Φ(q) = ½(1 − ⟨q̂, ĝ⟩)
- 球面口径, 只有方向没有轴向/侧向之分
- 旋转用参数化差, 大姿态下 Lyapunov 失效

## 现在的万有引力
V(g) = ½·ξ_eᵀ·K·ξ_e ,  ξ_e = log(g⁻¹·g_d)      ← 黎曼测地线代价
u    = +K·ξ_e − B·ξ + F_d                      ← 体坐标力扭 (被动, 等变)

**刚性主轴固定在工具本体**: 插销时侧向软 (k_lat=80)、轴向硬 (k_ax=400),
末端怎么转, 这个主轴都跟着工具走 —— 欧氏阻抗做不到。

## 为什么不是"多加一个通道"而是"替换引力"
老倪要的是把万有引力按这个算法实现, 所以:
  · 提供 `phi(g)` —— 标量势, 可直接喂给 engine.gradient_flow(potential_fn=...)
  · 提供 `force(g, xi)` —— 体坐标力扭 u, 给 L2 收口/执行层用
  · 提供 `prov()` —— 采样 provider, 引擎 rec["se3_gravity"] 通道
旧 `_metric_phi_smooth` **保留不动** (零回归), 新通道默认关闭 (SE3_GRAVITY_W=0)。

自检: python3 -m lerobot.manifold.se3_gravity_provider --selftest
"""
from __future__ import annotations

import os
import sys

import numpy as np

try:
    from .se3_impedance import (Se3ImpedanceController, pose_error, potential,
                                potential_rate, _xi_std_to_lie)
except Exception:                                                      # noqa: BLE001
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from se3_impedance import (Se3ImpedanceController, pose_error,        # type: ignore
                               potential, potential_rate, _xi_std_to_lie)


def _rpy_to_T(s7):
    """state7 (xyz + rpy + gripper) → 4×4 SE(3)。rpy 用 ZYX (yaw-pitch-roll) 约定。"""
    s7 = np.asarray(s7, float).ravel()
    x, y, z = float(s7[0]), float(s7[1]), float(s7[2])
    r, p, w = (float(s7[3]), float(s7[4]), float(s7[5])) if len(s7) >= 6 else (0.0, 0.0, 0.0)
    cr, sr = np.cos(r), np.sin(r)
    cp, sp = np.cos(p), np.sin(p)
    cw, sw = np.cos(w), np.sin(w)
    R = np.array([
        [cw * cp, cw * sp * sr - sw * cr, cw * sp * cr + sw * sr],
        [sw * cp, sw * sp * sr + cw * cr, sw * sp * cr - cw * sr],
        [-sp,     cp * sr,                cp * cr],
    ], float)
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = [x, y, z]
    return T


class Se3GravityProvider:
    """状态空间「万有引力」的 SE(3) 几何阻抗实现。

    与引擎的两种接法:
      ① 标量势: engine.gradient_flow(potential_fn=p.phi_fn())
         —— 走引擎原有的度规梯度流, 只是势换成测地线代价
      ② 体坐标力扭: rec["se3_gravity"] = p()
         —— 给 L2 收口/执行层直接下发 (需要真机的 J_b 才能转成 τ)
    """

    def __init__(self, state_fn=None, goal=None, k_lat=None, k_ax=None,
                 alpha=None, F_d=None, name="SE(3) 几何阻抗 (万有引力)"):
        self.name = name
        self.state_fn = state_fn or (lambda: np.zeros(7))
        self.ctrl = Se3ImpedanceController(k_lat=k_lat, k_ax=k_ax, alpha=alpha,
                                           filter_alpha=1.0)
        self.goal = None if goal is None else np.asarray(goal, float).ravel()[:7]
        self.F_d = None if F_d is None else np.asarray(F_d, float).ravel()
        self._steps = 0
        self._last = None
        # 势函数 (给 engine.gradient_flow 用): 输入 state7 → 标量
        self.phi = self._phi_impl

    # ── 目标设定 ──
    def set_goal(self, goal):
        self.goal = np.asarray(goal, float).ravel()[:7]
        return self.goal

    def _goal_T(self):
        g = self.goal if self.goal is not None else np.zeros(7)
        return _rpy_to_T(g)

    # ── ① 标量势 ──
    def _phi_impl(self, q):
        """Φ(q) = ½·ξ_eᵀ·K·ξ_e —— 可直接作为 gradient_flow 的 potential_fn。"""
        T = _rpy_to_T(q)
        return potential(T, self._goal_T(), self.ctrl.K)

    def phi_fn(self):
        return self._phi_impl

    # ── ② 体坐标力扭 ──
    def force(self, xi=None):
        """当前状态下的体坐标力扭 u (6维, 标准序 [力(3); 力矩(3)])。"""
        T = _rpy_to_T(self.state_fn())
        rec = self.ctrl.step(T, self._goal_T(),
                             xi=np.zeros(6) if xi is None else xi,
                             F_d=self.F_d)
        return rec

    # ── provider 接口 (引擎每帧调) ──
    def start(self):
        self._steps = 0
        self.ctrl.reset()
        T = _rpy_to_T(self.state_fn())
        _, xi_e = pose_error(T, self._goal_T())
        return True, ("就绪 · |ξ_e|=%.5f · V=%.6f"
                      % (float(np.linalg.norm(xi_e)),
                         potential(T, self._goal_T(), self.ctrl.K)))

    def __call__(self):
        try:
            T = _rpy_to_T(self.state_fn())
            g_d = self._goal_T()
            g_t, xi_e = pose_error(T, g_d)
            rec = self.ctrl.step(T, g_d, xi=np.zeros(6), F_d=self.F_d)
            self._steps += 1
            out = {
                "ok": True, "steps": self._steps,
                "xi_e": [round(float(v), 8) for v in xi_e],
                "|xi_e|": round(float(np.linalg.norm(xi_e)), 8),
                "rho": [round(float(v), 8) for v in xi_e[0:3]],
                "omega": [round(float(v), 8) for v in xi_e[3:6]],
                "u": [round(float(v), 6) for v in rec["u"]],
                "V": round(float(rec["V"]), 8),
                "Vdot": round(float(rec["Vdot"]), 8),
                "saturated": bool(rec["saturated"]),
                "K_diag": [float(self.ctrl.K[i, i]) for i in range(6)],
                "B_diag": [round(float(self.ctrl.B[i, i]), 6) for i in range(6)],
                "goal": None if self.goal is None else [round(float(v), 6) for v in self.goal],
                "note": "SE(3) 几何阻抗: 侧向软/轴向硬, 主轴固定本体",
            }
            self._last = out
            return out
        except Exception as e:                                         # noqa: BLE001
            return {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:160])}


# ═══════════════ 自检 ═══════════════
def _selftest() -> int:
    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("① 势函数给 gradient_flow 用")
    goal = np.zeros(7); goal[2] = 0.02
    p = Se3GravityProvider(goal=goal)
    chk("目标处 Φ=0", abs(p.phi_fn()(np.array([0, 0, 0.02, 0, 0, 0, 0.]))) < 1e-15,
        "Φ=%.2e" % p.phi_fn()(np.array([0, 0, 0.02, 0, 0, 0, 0.])))
    phi0 = p.phi_fn()(np.zeros(7))
    chk("原点 Φ=½·k_ax·0.02²=0.08", abs(phi0 - 0.08) < 1e-12, "Φ=%.6f" % phi0)
    # 单调: 越接近目标, Φ 越小
    phis = [p.phi_fn()(np.array([0, 0, z, 0, 0, 0, 0.])) for z in (0.0, 0.005, 0.01, 0.015, 0.02)]
    chk("Φ 随接近目标单调降",
        all(phis[i] >= phis[i + 1] - 1e-15 for i in range(len(phis) - 1)),
        " → ".join("%.4f" % v for v in phis))

    print("② provider 输出结构")
    state = {"s": np.zeros(7)}
    prov = Se3GravityProvider(state_fn=lambda: state["s"], goal=goal)
    ok, why = prov.start()
    chk("start 返回", ok is True, why)
    out = prov()
    chk("ok", out.get("ok") is True, str(out.get("why") or "")[:80])
    chk("ξ_e 6 维", len(out.get("xi_e") or []) == 6, str(out.get("xi_e")))
    chk("u 6 维", len(out.get("u") or []) == 6, str(out.get("u")))
    chk("V/V̇ 齐备", "V" in out and "Vdot" in out,
        "V=%.6f V̇=%.6f" % (out.get("V", 0), out.get("Vdot", 0)))
    chk("V̇ ≤ 0", float(out.get("Vdot", 1)) <= 1e-15, "%.3e" % out.get("Vdot", 1))
    print("     ξ_e=%s" % np.round(out["xi_e"], 5))
    print("     u   =%s" % np.round(out["u"], 4))

    print("③ 轴向 vs 侧向: 万有引力有方向偏好")
    state["s"] = np.array([0, 0, 0, 0, 0, 0, 0.])       # 原点, 目标 z=+0.02
    out_z = prov()
    goal_x = np.zeros(7); goal_x[0] = 0.02
    prov_x = Se3GravityProvider(state_fn=lambda: state["s"], goal=goal_x)
    prov_x.start()
    out_x = prov_x()
    fz = abs(out_z["u"][2]); fx = abs(out_x["u"][0])
    chk("同为 2cm 误差, 轴向力 > 侧向力", fz > fx * 2,
        "|u_z|=%.2f N vs |u_x|=%.2f N (比 %.1f×)" % (fz, fx, fz / max(fx, 1e-9)))
    chk("K 对角 = [80,80,400, 2,2,10]", np.allclose(out_z["K_diag"], [80, 80, 400, 2, 2, 10]),
        str(out_z["K_diag"]))

    print("④ 闭环: 状态逐步靠近目标 ⇒ Φ 单调降")
    prov2 = Se3GravityProvider(state_fn=lambda: state["s"], goal=goal)
    prov2.start()
    phis, Vs = [], []
    for z in np.linspace(0.0, 0.02, 41):
        state["s"] = np.array([0, 0, z, 0, 0, 0, 0.])
        o = prov2()
        phis.append(prov2.phi_fn()(state["s"]))
        Vs.append(o["V"])
    chk("Φ 单调降", all(phis[i] >= phis[i + 1] - 1e-15 for i in range(len(phis) - 1)),
        "%.4f → %.4e" % (phis[0], phis[-1]))
    chk("V 与 Φ 一致 (同源)", abs(Vs[0] - phis[0]) < 1e-12,
        "V=%.6f Φ=%.6f" % (Vs[0], phis[0]))
    chk("末端 Φ≈0", phis[-1] < 1e-20, "%.3e" % phis[-1])

    print("⑤ 力前馈")
    prov3 = Se3GravityProvider(state_fn=lambda: state["s"], goal=goal,
                               F_d=np.array([0, 0, -10.0, 0, 0, 0]))
    state["s"] = np.array([0, 0, 0.02, 0, 0, 0, 0.])   # 已到位
    prov3.start()
    o = prov3()
    chk("到位 + F_d ⇒ u = F_d", np.allclose(o["u"], [0, 0, -10, 0, 0, 0], atol=1e-6),
        str(np.round(o["u"], 3)))

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 全部通过 (万有引力 = SE(3) 几何阻抗, 可直接喂 gradient_flow)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv or len(sys.argv) == 1:
        sys.exit(_selftest())
    print("用法: python3 -m lerobot.manifold.se3_gravity_provider --selftest")
