#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_l4_inject.py — 实测 L4 几何注入是否真生效（节点级端到端 + 受控近孔场景）

场景 1（真实帧）: 跑 ssmani_p/ssmani_c/ssdec，看在当前真实帧下注入的判定。
  远离孔时 δ 大 ⇒ η=exp(−V_p/σ²)→0 ⇒ 门控**拒绝**纠偏。这是正确行为，不是失效。
场景 2（受控近孔）: 把 δ 设成 0.5mm（对孔完成状态），走同一条 correct() 路径，
  证明在正常装配条件下注入真的产生非零修正，且方向朝 −∇V。
"""
import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax/src")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

ROOT = "/home/ubuntu/zmax"
from lerobot.middleware.nodes.impl import shared_runtime as SR  # noqa: E402
from lerobot.middleware.nodes.impl import ss_mani_c as MC  # noqa: E402
from lerobot.middleware.nodes.impl import flow_matching_impl as FM  # noqa: E402
from lerobot.policies.manifold.geodesic_inject import correct  # noqa: E402


def _arr(v):
    return np.asarray(v, dtype=float).reshape(-1)


class _Mod:
    _ss_tr = None
    _ss_round = 0


def _ctx(params=None, name=""):
    return {"module": _Mod(), "log": lambda m: print("   LOG", m),
            "root": ROOT, "params": params or {}, "name": name}


print("=" * 70)
print("场景 1 · 真实帧（性能流形 → 动作头）")
r1 = MC.node_ss_mani(_ctx(name="📈 性能流形"))
p = SR._SS_STATE.get("perf_mani") or {}
grad = p.get("grad")
Vp = float(p.get("V_p") or 0.0)
eta = float(p.get("eta") or 0.0)
print("   V_p=%.6g (m²)  eta=%.6g  grad=%s" % (
    Vp, eta, np.round(_arr(grad), 5) if grad is not None else None))
print("   stage=%s" % p.get("stage"))

MC.node_ss_mani(_ctx(name="🧮 接触流形"))
c = SR._SS_STATE.get("contact_mani") or {}
ax = c.get("axis")
print("   contact axis=%s  progress=%.6g  risk=%.6g  Vdot=%.4g" % (
    np.round(_arr(ax), 4) if ax is not None else None,
    float(c.get("progress") or 0), float(c.get("risk") or 0), float(c.get("Vdot") or 0)))

out = FM.run(_ctx())
o = (out or {}).get("out1") or {}
inj1 = o.get("l4_inject") or {}
print("   → l4_cond_injected = %s" % o.get("l4_cond_injected"))
print("   → injected=%s  reason=%s" % (inj1.get("injected"), inj1.get("reason")))
if inj1.get("injected"):
    print("   → Δξ=%s mm 径向 %.5f 轴向 %.5f α=%.4f" % (
        np.round(_arr(inj1.get("delta")), 5), inj1.get("radial", 0),
        inj1.get("axial", 0), inj1.get("alpha", 0)))
print("   → nominal_L3=%s" % np.round(_arr(o.get("nominal_L3")) if o.get("nominal_L3") else None, 5))

print("\n" + "=" * 70)
print("场景 2 · 受控近孔（δ=0.5mm，对孔完成状态；同一 correct() 路径）")
d = np.array([0.0, 0.35, 0.35])              # 径向 0.495mm 偏差（mm 单位）
W = np.diag([0.4, 1.0, 1.0])
g = W @ d
vp_mm = 0.5 * float(d @ W @ d)
eta_mm = float(np.exp(-vp_mm / 16.0))        # σ=4mm ⇒ σ²=16mm²
xi = np.array([0.5, 0.0, 0.0])               # 名义动作：沿轴推进 0.5mm
u_star, inj2 = correct(list(xi) + [0.0], g, [1.0, 0.0, 0.0], eta=eta_mm, V_p=vp_mm)
print("   输入: δ=%s mm (|δ⊥|=%.4f)  V_p=%.6f mm²  η=%.4f  ξ=%s" % (
    np.round(d, 4), np.linalg.norm(d), vp_mm, eta_mm, np.round(xi, 3)))
print("   输出: injected=%s  Δξ=%s mm" % (inj2.get("injected"), np.round(_arr(inj2.get("delta")), 5)))
print("        径向 %.5f mm  轴向 %.5f mm  α=%.4f  gate=%.4f" % (
    inj2.get("radial", 0), inj2.get("axial", 0), inj2.get("alpha", 0), inj2.get("gate", 0)))
dn = _arr(inj2.get("delta"))
if np.linalg.norm(dn) > 1e-12:
    cos = float(np.dot(-g / np.linalg.norm(g), dn / np.linalg.norm(dn)))
    print("        与 −∇V 余弦 = %.6f  (1.0 = 严格沿下降方向)" % cos)
    print("        Lyapunov ∇VᵀΔξ = %.6g  (≤0 合格)" % float(np.dot(g, dn)))
print("=" * 70)

res = {
    "scenario1_real_frame": {
        "V_p": Vp, "eta": eta, "grad": (list(_arr(grad)) if grad is not None else None),
        "axis": (list(_arr(ax)) if ax is not None else None),
        "l4_cond_injected": o.get("l4_cond_injected"),
        "injected": inj1.get("injected"), "reason": inj1.get("reason"),
        "nominal_L3": o.get("nominal_L3"),
    },
    "scenario2_near_hole": {
        "delta_mm": list(d), "V_p_mm2": vp_mm, "eta": eta_mm,
        "injected": inj2.get("injected"), "delta_xi_mm": list(_arr(inj2.get("delta"))),
        "radial": inj2.get("radial"), "axial": inj2.get("axial"),
        "alpha": inj2.get("alpha"), "gate": inj2.get("gate"),
        "metric": inj2.get("metric"),
    },
}
pth = os.path.join(ROOT, "zmax_data", "ss_live", "l4_inject_probe.json")
json.dump(res, open(pth, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
print("存:", os.path.relpath(pth, ROOT))
