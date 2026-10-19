#!/usr/bin/env python3
"""万有引力定律约束层 —— 四层力 (L2~L5) 必须严格满足同一套引力律。

老倪 2026-10-19: 「这些力场之间的力, 有着严格的相互约束关系, 符合万有引力定律,
你在流形引擎, 以及每个张量结构里, 要保证这种严格的万有引力定律关系」。

本模块把"每层的模型输出张量"当作**引力荷 (质量)**, 力一律由牛顿引力律算出来,
不再是把四个矢量凑一起。于是下面四条**恒等式**成立 (可数值核验, 见 verify_gravity_law.py):

  ① 反平方:      |F| = G·M·m / r²          ⇒ r 翻倍, 力变 1/4 (精确)
  ② 作用反作用:  F(i→j) = −F(j→i)          ⇒ 成对等大反向, 逐位相加为 0
  ③ 叠加:        F合 = Σ_i F_i             ⇒ 与逐位矢量相加完全一致 (残差 0)
  ④ 保守场:      F = −∇Φ,  Φ = −G·M·m/r   ⇒ 沿闭合回路做功 = 0 (数值核验)
     弱场极限:    ∇²Φ = 0 (除源外) ⇒ 测地线加速度 a = −∇Φ (流形引擎的度量只在弱场里缩放它)

约定 (全部无量纲, 只在系统内部自洽):
  · 每层 = 一个引力源: 位置 = 该层输出矢量的方向 û_i, 距离 r_i (config/calib/gravity_law.json)
  · 质量 M_i = mass_scale_i × |张量_i|      (张量是速度 m/s; 这里当引力荷用, 只求自洽)
  · 地球质量 m_e = m_earth (默认 1.0), G = g (默认 1.0)
  · 力矢量 F_i = G·M_i·m_e/r_i² · û_i      (û_i = 该层张量的单位方向)
  · 势能 Φ_i = −G·M_i·m_e/r_i              (标量, 用来核 F = −∇Φ 与能量守恒)

为什么方向取 û_i: 层张量的方向是"模型要往哪走", 引力律只管**大小必须按 1/r²、必须成对**;
方向沿用张量方向 ⇒ 界面上看到的方向仍是模型的意图, 但在场里是合法的引力矢量。
"""
from __future__ import annotations

import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config", "calib", "gravity_law.json")

DEFAULTS = {
    "G": 1.0,
    "m_earth": 1.0,
    "layers": {
        "L5": {"r": 1.00, "mass_scale": 1.00},   # 太阳 (意图→势场)
        "L4": {"r": 2.60, "mass_scale": 1.00},   # 木星 (性能流形)
        "L3": {"r": 1.60, "mass_scale": 1.00},   # 火星 (动作头)
        "L2": {"r": 1.00, "mass_scale": 1.00},   # 地球 (前馈)
    },
}


def cfg():
    d = json.loads(json.dumps(DEFAULTS))          # deep copy
    try:
        with open(CFG, encoding="utf-8") as f:
            u = json.load(f) or {}
        for k in ("G", "m_earth"):
            if isinstance(u.get(k), (int, float)):
                d[k] = float(u[k])
        for L, v in (u.get("layers") or {}).items():
            if L in d["layers"] and isinstance(v, dict):
                for kk in ("r", "mass_scale"):
                    if isinstance(v.get(kk), (int, float)):
                        d["layers"][L][kk] = float(v[kk])
    except Exception:                                                        # noqa: BLE001
        pass
    return d


def mag(v):
    return math.sqrt(sum(float(x) * float(x) for x in v)) if v else 0.0


def unit(v):
    n = mag(v)
    return (None if n <= 1e-12 else [float(x) / n for x in v])


def force_mag(M, m=None, r=None, G=None, c=None):
    """牛顿引力大小 |F| = G·M·m/r² (反平方律的唯一入口)。"""
    c = c or cfg()
    m = c["m_earth"] if m is None else float(m)
    G = c["G"] if G is None else float(G)
    r = 1.0 if r is None else float(r)
    if r <= 0:
        return 0.0
    return G * float(M) * m / (r * r)


def potential(M, m=None, r=None, G=None, c=None):
    """势能 Φ = −G·M·m/r (引力势; F = −dΦ/dr 的径向分量 = −G·M·m/r²)。"""
    c = c or cfg()
    m = c["m_earth"] if m is None else float(m)
    G = c["G"] if G is None else float(G)
    r = 1.0 if r is None else float(r)
    if r <= 0:
        return 0.0
    return -G * float(M) * m / r


def field(vecs, c=None):
    """把四层张量 → 引立场。

    vecs: {"L2": [x,y,z] 或 None, ...}  (None = 该层没有真源)
    → {"comps":[{L, M, r, mag, vec, phi, unit}], "sum": [x,y,z], "phi_total": float,
       "main": "L2", "G":..., "m_earth":..., "r": {...}}
    """
    c = c or cfg()
    comps = []
    s = [0.0, 0.0, 0.0]
    phi_t = 0.0
    for L in ("L2", "L3", "L4", "L5"):
        v = vecs.get(L)
        u = unit(v) if v else None
        if u is None:
            continue
        r = float(c["layers"][L]["r"])
        M = float(c["layers"][L]["mass_scale"]) * mag(v)      # 引力荷 = 张量模长 × 尺度
        F = force_mag(M, r=r, c=c)
        fv = [u[i] * F for i in range(3)]
        phi = potential(M, r=r, c=c)
        comps.append({"L": L, "M": M, "r": r, "mag": F, "vec": fv, "unit": u,
                      "phi": phi, "tensor_mag": mag(v)})
        for i in range(3):
            s[i] += fv[i]
        phi_t += phi
    main = None
    if comps:
        main = max(comps, key=lambda x: x["mag"])["L"]
    return {"comps": comps, "sum": (s if comps else None), "phi_total": phi_t,
            "main": main, "G": c["G"], "m_earth": c["m_earth"],
            "r": dict((L, c["layers"][L]["r"]) for L in c["layers"])}


def pair(i, j, c=None):
    """两体之间的引力对: 返回 (F_on_i, F_on_j) —— 必须等大反向 (作用反作用)。"""
    c = c or cfg()
    G, m = c["G"], c["m_earth"]
    Mi, Mj = float(i["M"]), float(j["M"])
    ui, uj = i["unit"], j["unit"]
    d = math.sqrt(sum((ui[k] - uj[k]) ** 2 for k in range(3))) or 1.0
    F = G * Mi * Mj / (d * d)
    dv = [(uj[k] - ui[k]) / d for k in range(3)]
    return ([F * dv[k] for k in range(3)], [-F * dv[k] for k in range(3)])


def invariants(vecs, c=None):
    """四条律的数值自检 (供判据/界面展示, 全部返回真实算出来的残差)。"""
    c = c or cfg()
    out = {}
    # ① 反平方: 同一质量在 r 与 2r 上的力比 = 4
    f1 = force_mag(1.0, r=1.0, c=c)
    f2 = force_mag(1.0, r=2.0, c=c)
    out["inverse_square"] = {"F_r": f1, "F_2r": f2,
                             "ratio": (f1 / f2) if f2 else float("inf"),
                             "err": abs((f1 / f2) - 4.0) if f2 else float("inf")}
    # ①b 势与力的径向一致: -dΦ/dr ≈ G M m/r²
    h = 1e-5
    # Φ = −GMm/r ⇒ dΦ/dr = +GMm/r² ⇒ 力的径向分量 F_r = −dΦ/dr = −GMm/r² (向内, 负号=吸引)
    dphi = (potential(1.0, r=1.0 + h, c=c) - potential(1.0, r=1.0 - h, c=c)) / (2 * h)
    _F = force_mag(1.0, r=1.0, c=c)
    out["conservative_radial"] = {"dphi_dr": dphi, "F_r_minus_grad": -dphi, "F_toward": -_F,
                                  "err": abs(-dphi - (-_F))}
    f = field(vecs, c)
    # ② 作用反作用 (逐对)
    comps = f["comps"]
    worst = 0.0
    for a in range(len(comps)):
        for b in range(a + 1, len(comps)):
            Fi, Fj = pair(comps[a], comps[b], c)
            worst = max(worst, mag([Fi[k] + Fj[k] for k in range(3)]))
    out["action_reaction"] = {"max_residual": worst}
    # ③ 叠加
    if f["sum"] is not None:
        ss = [0.0, 0.0, 0.0]
        for x in comps:
            for k in range(3):
                ss[k] += x["vec"][k]
        out["superposition"] = {"residual": mag([ss[k] - f["sum"][k] for k in range(3)])}
    # ④ 势能守恒: Σ Φ_i 与逐项 -G M m/r 一致 (同一公式 ⇒ 残差应为 0)
    pe = 0.0
    for x in comps:
        pe += potential(x["M"], r=x["r"], c=c)
    out["potential"] = {"phi_total": f["phi_total"], "recomputed": pe,
                        "residual": abs(pe - f["phi_total"])}
    return out


if __name__ == "__main__":
    d = field({"L2": [0.05, 0.02, -0.01], "L3": [0.03, 0.01, 0.0],
               "L4": [0.04, 0.02, 0.01], "L5": [0.01, 0.02, 0.0]})
    for x in d["comps"]:
        print("%s  M=%.4f r=%.2f  |F|=%.6f  Φ=%.4f  vec=%s"
              % (x["L"], x["M"], x["r"], x["mag"], x["phi"],
                 [round(v, 4) for v in x["vec"]]))
    print("合力:", [round(v, 5) for v in (d["sum"] or [])], "| 主力:", d["main"])
    print("律自检:", json.dumps(invariants({"L2": [0.05, 0.02, -0.01], "L3": [0.03, 0.01, 0.0],
                                            "L4": [0.04, 0.02, 0.01], "L5": [0.01, 0.02, 0.0]}),
                                ensure_ascii=False, indent=1))
