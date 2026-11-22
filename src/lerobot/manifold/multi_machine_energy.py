#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multi_machine_energy.py — 多机能量 + 从机辅助分力 (老倪 2026-11-22 口径)

口径 (原话):
  「主要计算主机的能量和从机的能量，主机的工作量是有数的，从机的工作量，要辅助主机」

于是三件事分开算, 不许混:
  ① 每台机各算一份能量   H_i = K_i + U_i        (位姿 g_i / 目标 g_d,i / 速度 ξ_i)
     —— 直接用 ss_grav_h 的同一个哈密顿量 (StateSpaceHamiltonian), 不另立口径。
  ② 主机工作量 W_m* **是有数的**  (计划给的: 件数 × 单件参考能量, 或 P* × 时间窗)
     ⇒ 主机的"够不够"是拿实测去比这个数, 不是猜。
  ③ 从机工作量 = **补缺口**: 从机承担主机"干不完且不许过载"的那部分
     α_s = clamp(缺口 / (缺口 + 主机实际), α_min, α_max),  Σ_i α_i = 1
     从机自己也有能量上限 H_s ≤ H_s_cap、功率上限 P_s ≤ P_s_cap —— 夹住就记 saturated + shortfall,
     干不完照实报, 不许把缺口悄悄摊平。

力仍是份额×刚度×误差: F_i = α_i·K·ξᵉ, 双层(机×层) F_(i,l) = α_i·s_l·K·ξᵉ,
恒等式 Σ_i Σ_l F_(i,l) = K·ξᵉ (沿用 layer_shares 的验法, 残差应 <1e-12)。

只算不下发。运行: ./gui-venv311/bin/python -m lerobot.manifold.multi_machine_energy --selftest
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "src"))

from lerobot.manifold.state_space_energy import StateSpaceHamiltonian, layer_shares   # noqa: E402
from lerobot.manifold.se3_impedance import pose_error                                  # noqa: E402


def machine_energy(g, g_d, xi, ham=None):
    """单台机的能量明细 (J)。g/g_d = 4×4 位姿, xi = 6 维 [ρ;ω] 速度。"""
    ham = ham or StateSpaceHamiltonian()
    e = ham.energy(g, g_d, xi)
    xi_e = e.get("xi_e")
    F = (ham.K @ xi_e) if xi_e is not None else np.zeros(6)
    return {"U": float(e.get("U", 0.0)), "K": float(e.get("K", 0.0)), "H": float(e.get("H", 0.0)),
            "xi_e_norm": float(np.linalg.norm(xi_e)) if xi_e is not None else 0.0,
            "F": [round(float(v), 6) for v in F],
            "P": float(np.dot(F, xi)) if xi is not None else 0.0,       # 瞬时功率 F·ξ̇
            "src": "StateSpaceHamiltonian (与 ss_grav_h 同源)"}


def assist_share(p_master_actual, master_target, slave_cap_work, master_cap_work=None,
                 alpha_min=0.15, alpha_max=0.85):
    """从机辅助份额 α_s：主机工作量是有数的(target)，缺口交给从机，从机能力封顶。

    参数 (全部同一时间窗口径, 例: W 或 J):
      p_master_actual  主机这段时间**实际**干掉的功 (实测 F·ξ̇ 积分 / 或件数×单件能量)
      master_target    主机**计划**工作量 W_m* (有数的那个数)
      slave_cap_work   从机这段时间**能力上限** (能量上限或产能上限)
      master_cap_work  主机自己的上限 (可选; 给了就在缺口里先把主机余量挖掉, 不硬摊给从机)
    返回 α_s / α_m / 缺口 / 是否饱和 / 谁没干完。
    """
    p_master_actual = max(0.0, float(p_master_actual))
    master_target = max(0.0, float(master_target))
    slave_cap_work = max(0.0, float(slave_cap_work))
    gap = max(0.0, master_target - p_master_actual)                       # 主机缺口
    if master_cap_work is not None:                                       # 主机自己还能再干一点
        gap = max(0.0, gap - max(0.0, float(master_cap_work) - p_master_actual))
    take = min(gap, slave_cap_work)                                       # 从机能接的
    tot = p_master_actual + take
    raw = (take / tot) if tot > 0 else 0.0
    saturated = bool(gap > slave_cap_work + 1e-9)
    # 能力吃不满时**不要**把份额抬到保底值(那会把缺口说小); 保底只用于"有缺口且没饱和"
    al_s = min(max(raw, 0.0 if saturated else alpha_min), alpha_max)
    al_m = 1.0 - al_s
    return {"ok": True, "alpha_slave": round(al_s, 6), "alpha_master": round(al_m, 6),
            "sum_alpha": round(al_s + al_m, 6),
            "master_target": master_target, "master_actual": p_master_actual,
            "gap": round(gap, 6), "slave_take": round(take, 6),
            "saturated": saturated,
            "shortfall": round(max(0.0, gap - take), 6),
            "why": ("从机补 %0.3f (缺口 %0.3f, 能力 %0.3f)" % (take, gap, slave_cap_work))
                   if gap > 0 else "主机自己够 ⇒ 从机不接活 (α_s 仅保底)",
            "note": "α 是**工作量份额**, 不是平均分; 夹住就记 saturated/shortfall, 不静默摊平"}


def dual_layer_forces(ham, alpha, xi_e):
    """F_(i,l) = α_i·s_l·K·ξᵉ；返回残差 (Σ_i Σ_l F − K·ξᵉ) 供判据。"""
    sh = layer_shares(getattr(ham, "share", None) if isinstance(getattr(ham, "share", None), dict) else None)
    Kx = ham.K @ xi_e
    F = {}
    ssum = np.zeros(6)
    for mid, a in alpha.items():
        for lname, s in sh.items():
            v = float(a) * float(s) * Kx
            F["%s.%s" % (mid, lname)] = [round(float(x), 9) for x in v]
            ssum += v
    resid = float(np.max(np.abs(ssum - Kx)))
    return {"F_il": F, "resid_sumF": resid, "sum_alpha": round(float(sum(alpha.values())), 9),
            "sum_layer": round(float(sum(sh.values())), 9), "layers": sh}


class Ledger:
    """工作量台账: 每件料 谁干了多少, 谁等/没干完。"""

    def __init__(self):
        self.rows = []

    def add(self, part_id, machine, work, ok=True, note=""):
        self.rows.append({"part_id": str(part_id), "machine": str(machine),
                          "work": float(work), "ok": bool(ok), "note": note})

    def report(self):
        tot = {}
        for r in self.rows:
            tot[r["machine"]] = tot.get(r["machine"], 0.0) + r["work"]
        s = sum(tot.values()) or 1.0
        return {"parts": len({r["part_id"] for r in self.rows}), "rows": len(self.rows),
                "by_machine": {k: round(v, 6) for k, v in tot.items()},
                "share": {k: round(v / s, 6) for k, v in tot.items()},
                "failed": [r for r in self.rows if not r["ok"]]}


def _selftest() -> int:
    from lerobot.manifold.se3_gravity_provider import _rpy_to_T
    chk, fails = [], []

    def ok(name, cond, detail=""):
        chk.append(name)
        if not cond:
            fails.append("%s  %s" % (name, detail))

    ham = StateSpaceHamiltonian()
    g0 = _rpy_to_T([0.649, 0.404, 0.114, 2.961, -1.490, 0.205, 0.0])      # state7: xyz(m)+rpy+夹爪
    # ① 静止 = 零能量 (真机现在就是停着的) —— 不是"算不出来", 是 U=K=0
    st = machine_energy(g0, g0, np.zeros(6), ham)
    ok("静止 H=0", abs(st["H"]) < 1e-12, str(st["H"]))
    # ② 2cm 轴向误差复现 0.080 J (与 ss_grav_h 12/12 同口径)
    # 位移必须沿**工具轴**才算轴向: pose_error 的 ρ 在工具系里, 世界 +Z 落在大角度姿态下会摊到横向
    g2 = g0.copy()
    g2[:3, 3] = g0[:3, 3] + g0[:3, 2] * 0.02                                # 沿工具 Z 抬 20mm
    e2 = machine_energy(g2, g0, np.zeros(6), ham)
    ok("U(2cm)=0.080000J", abs(e2["U"] - 0.08) < 1e-9, str(e2["U"]))
    # ③ 0.1 m/s ⇒ K=0.018215 J
    e3 = machine_energy(g0, g0, np.array([0.1, 0, 0, 0, 0, 0]), ham)
    ok("K(0.1m/s)=0.018215J", abs(e3["K"] - 0.018215) < 1e-6, str(e3["K"]))
    # ④ 从机补缺口: 主机计划 100, 实测 60, 从机能力 200 ⇒ α_s = 40/100 = 0.40
    a = assist_share(60, 100, 200)
    ok("α_s=0.40", abs(a["alpha_slave"] - 0.40) < 1e-9, str(a["alpha_slave"]))
    ok("Σα=1", abs(a["sum_alpha"] - 1.0) < 1e-9, str(a["sum_alpha"]))
    ok("不饱和", a["saturated"] is False)
    # ⑤ 单调: 主机干得越少 ⇒ 从机份额越高
    seq = [assist_share(p, 100, 200)["alpha_slave"] for p in (90, 70, 50, 30)]
    ok("单调 α_s↑(主机↓)", all(seq[i] < seq[i + 1] for i in range(len(seq) - 1)), str(seq))
    # ⑥ 从机能力封顶 ⇒ saturated + shortfall 照实报
    b = assist_share(0, 500, 200)
    ok("饱和记账", b["saturated"] and abs(b["shortfall"] - 300) < 1e-9, json.dumps(b, ensure_ascii=False)[:80])
    ok("α 上界 0.85", abs(b["alpha_slave"] - 0.85) < 1e-9, str(b["alpha_slave"]))
    # ⑦ 双层(机×层)力恒等: Σ_i Σ_l F = K·ξᵉ
    g5 = _rpy_to_T([0.649, 0.404, 0.134, 2.961, -1.490, 0.205, 0.0])
    _, xi_e = pose_error(g5, g0)
    dl = dual_layer_forces(ham, {"M": a["alpha_master"], "S": a["alpha_slave"]}, xi_e)
    ok("Σ_iΣ_l F − Kξ 残差<1e-12", dl["resid_sumF"] < 1e-12, str(dl["resid_sumF"]))
    ok("层份额 Σ=1", abs(dl["sum_layer"] - 1.0) < 1e-9, str(dl["sum_layer"]))
    # ⑧ 台账
    L = Ledger()
    L.add("P1", "M", 0.4); L.add("P1", "S", 0.6); L.add("P2", "M", 0.5); L.add("P2", "S", 0.5, ok=False, note="从机超时")
    rep = L.report()
    ok("台账 2 件 4 行", rep["parts"] == 2 and rep["rows"] == 4, json.dumps(rep["by_machine"]))
    ok("台账份额 Σ=1", abs(sum(rep["share"].values()) - 1.0) < 1e-9, str(rep["share"]))
    ok("失败记账", len(rep["failed"]) == 1)

    print(json.dumps({"ok": not fails, "checks": len(chk), "pass": len(chk) - len(fails),
                      "fails": fails,
                      "sample": {"static_H": st["H"], "U_2cm": e2["U"], "K_01": e3["K"],
                                 "alpha": a, "forces_resid": dl["resid_sumF"],
                                 "ledger": rep}},
                     ensure_ascii=False, indent=1))
    return 0 if not fails else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv or len(sys.argv) == 1:
        raise SystemExit(_selftest())
    print("用法: python -m lerobot.manifold.multi_machine_energy --selftest")
