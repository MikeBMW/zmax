#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔗 hjepa_mr_layers.py — H-JEPA-MR 几何量的 L2/L3/L4/L5 协同接线 (老倪 2026-10-23)

架构原则 (仓库一贯口径, 不许反过来):
    上层只给意图/条件 → 可行域逐层收窄 → 执行永远由 L2 收口 → 稳定性由 L2 势函数兜底

所以几何量**不是新的"力"**: 「力」在 `tools/layer_forces.py` 里是 3 维速度矢量
(L2=ff[0], L3=chunk[0], L4=M̂·u_ff, L5=场景矢量)。几何量的角色是**约束与条件**:

    L2 执行层  d_normal 法向偏离 / d_se3 测地线距离 → 横向限幅 + veto  (收口)
    L3 调度层  d_se3 < 阈值 且 d_normal < 阈值      → 允许阶段推进     (条件)
    L4 认知层  ξ twist + log_sigma 不确定性         → 度量各向异性权重 (调制)
    L5 规划层  动力学 rollout 未来位姿序列          → 规划条件/校验   (意图)

每层都只返回"是否放行 / 限幅多少 / 权重多少", **不产生动作**。

自检: python3 -m lerobot.manifold.hjepa_mr_layers --selftest
"""
from __future__ import annotations

import os
import sys

import numpy as np

try:
    from .hjepa_manifold import (rollout_poses, se3_distance,
                                 tangent_gaussian_nll)
except Exception:                                                      # noqa: BLE001
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from hjepa_manifold import (rollout_poses, se3_distance,           # type: ignore
                                tangent_gaussian_nll)

# ── 阈值 (工程默认; 现场按标定覆盖, 不要写死进代码逻辑) ──
D_SE3_STAGE_M = 0.002       # 2mm: 阶段推进的 SE(3) 测地线阈值
D_NORMAL_STAGE_RAD = 0.026  # 1.5°: 法线对齐阈值
D_NORMAL_VETO_RAD = 0.087   # 5°: 法线偏离超此值 ⇒ L2 veto (接触面明显不平行)
D_SE3_VETO_M = 0.020        # 20mm: 位姿偏离超此值 ⇒ L2 veto
SIGMA_HIGH = 0.20           # 切空间 σ 超过此值 ⇒ 几何预测不可信 (L3 不许推进)


def l2_gate(mr, lateral_max=1.0):
    """L2 执行层收口闸: 法向偏离/位姿偏离 → 横向限幅系数 + veto。

    为什么由 L2 收口而不是上层: 上层只能表达"我想往哪走", 能不能走要看接触几何。
    法线偏了还猛推 = 插斜 = 弯针; 这一步必须在执行层拦下。

    返回 dict(gain, veto, why, d_normal, d_se3)
      gain ∈ [0,1]: 横向动作限幅系数 (纵向插深不缩, 因为法线偏斜时纵向推进本身是错的方向)
    """
    if not mr or not mr.get("ok"):
        return {"gain": 1.0, "veto": False, "why": "几何通道未就绪 (不拦)", "d_normal": None, "d_se3": None}
    dn = float(mr.get("d_normal") or 0.0)
    ds = float(mr.get("d_se3") or 0.0)

    if dn >= D_NORMAL_VETO_RAD:
        return {"gain": 0.0, "veto": True, "d_normal": dn, "d_se3": ds,
                "why": "法线偏离 %.3f rad (%.1f°) ≥ %.1f° ⇒ 接触面不平行, 禁止推进"
                       % (dn, np.degrees(dn), np.degrees(D_NORMAL_VETO_RAD))}
    if ds >= D_SE3_VETO_M:
        return {"gain": 0.0, "veto": True, "d_normal": dn, "d_se3": ds,
                "why": "SE(3) 偏离 %.4f m ≥ %.3f m ⇒ 离流形, 禁止推进" % (ds, D_SE3_VETO_M)}

    # 限幅: 法线偏离越大, 横向动作越受限 (线性衰减到接近阈值时为 0)
    ratio = dn / D_NORMAL_VETO_RAD
    gain = float(max(0.0, min(1.0, (1.0 - ratio) * lateral_max)))
    why = ("横向限幅 %.2f (法线偏离 %.1f°)" % (gain, np.degrees(dn))
           if gain < 0.99 else "在流形, 不限幅")
    return {"gain": gain, "veto": False, "why": why, "d_normal": dn, "d_se3": ds}


def l3_stage_gate(mr, sigma_high=SIGMA_HIGH):
    """L3 调度层: 是否允许推进到下一阶段 (只给条件, 不做动作)。

    三个条件同时满足才放行:
      ① d_se3 ≤ 2mm     —— 位姿已对准
      ② d_normal ≤ 1.5° —— 接触面已平行
      ③ 切空间 σ ≤ 0.20 —— 几何预测本身可信 (不确定性太大时不许推进, 宁可等)
    """
    if not mr or not mr.get("ok"):
        return {"allow": False, "why": "几何通道未就绪 ⇒ 不推进", "conds": {}}
    dn = float(mr.get("d_normal") or 0.0)
    ds = float(mr.get("d_se3") or 0.0)
    ls = mr.get("log_sigma")
    sigma_max = None
    if ls is not None:
        arr = np.asarray(ls, float).ravel()
        if arr.size:
            sigma_max = float(np.exp(arr).max())

    c_se3 = ds <= D_SE3_STAGE_M
    c_nrm = dn <= D_NORMAL_STAGE_RAD
    c_unc = (sigma_max is None) or (sigma_max <= sigma_high)
    allow = bool(c_se3 and c_nrm and c_unc)
    why = []
    if not c_se3:
        why.append("d_SE3=%.4fm > %.4fm" % (ds, D_SE3_STAGE_M))
    if not c_nrm:
        why.append("d_normal=%.1f° > %.1f°" % (np.degrees(dn), np.degrees(D_NORMAL_STAGE_RAD)))
    if not c_unc:
        why.append("σ_max=%.3f > %.2f (几何不可信)" % (sigma_max, sigma_high))
    return {"allow": allow,
            "why": "可推进" if allow else ("; ".join(why)),
            "conds": {"se3": c_se3, "normal": c_nrm, "uncertainty": c_unc,
                      "d_se3": ds, "d_normal_rad": dn, "sigma_max": sigma_max}}


def l4_metric(mr, base_M=1.0, anisotropy=2.0):
    """L4 认知层: 把 twist 方向 + 不确定性变成度量各向异性权重。

    思想: 度量张量 M 本来就是「哪个方向更"贵"」的编码。几何分支给了两件真信息:
      · ξ 的方向 = 当前误差的主要方向 (这个方向要更贵, 梯度流才会沿它收敛)
      · log_sigma = 对该方向的把握 (把握大 ⇒ 权重更果断; 把握小 ⇒ 接近各向同性)

    返回 dict(M_scalar, direction, weight) —— 只给 L4 调 M, 不改动作。
    """
    if not mr or not mr.get("ok"):
        return {"M_scalar": float(base_M), "direction": None, "weight": 1.0,
                "why": "几何通道未就绪 ⇒ 保持基础度量"}
    xi = np.asarray(mr.get("xi") or np.zeros(6), float).ravel()[:6]
    n = float(np.linalg.norm(xi))
    if n < 1e-9:
        return {"M_scalar": float(base_M), "direction": None, "weight": 1.0,
                "why": "ξ≈0 (已对准) ⇒ 各向同性"}
    direction = (xi / n).tolist()
    # 不确定性: σ 越小越可信 → 各向异性越强
    ls = mr.get("log_sigma")
    conf = 1.0
    if ls is not None:
        arr = np.asarray(ls, float).ravel()[:6]
        if arr.size:
            sig = float(np.exp(arr).mean())
            conf = float(1.0 / (1.0 + sig / 0.1))       # σ=0.1 ⇒ conf=0.5
    M_scalar = float(base_M * (1.0 + (anisotropy - 1.0) * conf))
    return {"M_scalar": M_scalar, "direction": direction, "weight": conf,
            "why": "沿 ξ 方向各向异性 ×%.2f (置信 %.2f)" % (M_scalar / max(base_M, 1e-9), conf)}


def l5_condition(mr, dyn_fn=None, n_steps=3, horizon_s=None):
    """L5 规划层: 动力学 rollout 出的未来位姿序列, 当规划条件/校验用。

    不产生动作 —— 给上层看"如果照当前几何趋势走, 未来 n 步的位姿会到哪",
    上层据此决定要不要改意图 (比如提前减速、换插入角度)。
    """
    if not mr or not mr.get("ok"):
        return {"ok": False, "why": "几何通道未就绪", "poses": []}
    T0 = np.asarray(mr.get("T_pred") or np.eye(4).tolist(), float).reshape(4, 4)
    if dyn_fn is None:
        # 无动力学模型 ⇒ 退化成"匀速外推": 用当前 ξ 当每步增量 (并在 why 里写明)
        xi = np.asarray(mr.get("xi") or np.zeros(6), float).ravel()[:6]
        twists = [xi] * int(n_steps)
        poses = rollout_poses(T0, twists)
        return {"ok": True, "poses": [p.tolist() for p in poses],
                "d_se3_each": [round(float(se3_distance(T0, p)), 6) for p in poses],
                "why": "无动力学模型 ⇒ 用当前 ξ 匀速外推 %d 步 (仅趋势参考, 非预测)" % n_steps}
    try:
        twists = [np.asarray(dyn_fn(k), float).ravel()[:6] for k in range(int(n_steps))]
        poses = rollout_poses(T0, twists)
        return {"ok": True, "poses": [p.tolist() for p in poses],
                "d_se3_each": [round(float(se3_distance(T0, p)), 6) for p in poses],
                "why": "动力学模型 f_dyn rollout %d 步" % n_steps}
    except Exception as e:                                             # noqa: BLE001
        return {"ok": False, "why": "rollout 失败: %s" % str(e)[:120], "poses": []}


def layer_report(mr, base_M=1.0):
    """四层协同的总报告 (画布/日志/大屏一次取全)。"""
    g2 = l2_gate(mr)
    g3 = l3_stage_gate(mr)
    g4 = l4_metric(mr, base_M=base_M)
    g5 = l5_condition(mr)
    return {
        "L2": {"role": "执行收口", **g2},
        "L3": {"role": "阶段条件", **g3},
        "L4": {"role": "度量调制", **g4},
        "L5": {"role": "规划条件", "ok": g5["ok"], "n_steps": len(g5.get("poses") or []),
               "d_se3_each": g5.get("d_se3_each"), "why": g5.get("why")},
        "ok": bool(mr and mr.get("ok")),
    }


# ═══════════════════════ 自检 ═══════════════════════
def _selftest() -> int:
    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    def mk(dn=0.0, ds=0.0, sigma=None, xi=None):
        d = {"ok": True, "d_normal": dn, "d_se3": ds, "xi": xi or [0.0] * 6}
        if sigma is not None:
            d["log_sigma"] = [np.log(sigma)] * 9
        return d

    print("① L2 收口闸")
    g = l2_gate(mk(dn=0.0, ds=0.0))
    chk("完全对准 ⇒ 不限幅", g["gain"] > 0.99 and not g["veto"], "gain=%.3f" % g["gain"])
    g = l2_gate(mk(dn=np.radians(2.5), ds=0.0))
    chk("法线偏 2.5° ⇒ 部分限幅", 0 < g["gain"] < 0.99 and not g["veto"],
        "gain=%.3f (%s)" % (g["gain"], g["why"]))
    g = l2_gate(mk(dn=np.radians(6.0), ds=0.0))
    chk("法线偏 6° ⇒ veto", g["veto"] is True and g["gain"] == 0.0, g["why"])
    g = l2_gate(mk(dn=0.0, ds=0.025))
    chk("位姿偏 25mm ⇒ veto", g["veto"] is True, g["why"])
    g = l2_gate(None)
    chk("几何未就绪 ⇒ 不拦 (gain=1)", g["gain"] == 1.0 and not g["veto"], g["why"])
    # 限幅单调性
    gains = [l2_gate(mk(dn=np.radians(d)))["gain"] for d in (0, 1, 2, 3, 4)]
    chk("限幅随法线偏离单调降",
        all(gains[i] >= gains[i + 1] - 1e-12 for i in range(len(gains) - 1)),
        " → ".join("%.3f" % v for v in gains))

    print("② L3 阶段条件")
    r = l3_stage_gate(mk(dn=0.0, ds=0.0, sigma=0.05))
    chk("三条件全满足 ⇒ 放行", r["allow"] is True, r["why"])
    r = l3_stage_gate(mk(dn=np.radians(3.0), ds=0.0, sigma=0.05))
    chk("法线超 1.5° ⇒ 拒", r["allow"] is False and "d_normal" in r["why"], r["why"])
    r = l3_stage_gate(mk(dn=0.0, ds=0.005, sigma=0.05))
    chk("d_se3 超 2mm ⇒ 拒", r["allow"] is False and "d_SE3" in r["why"], r["why"])
    r = l3_stage_gate(mk(dn=0.0, ds=0.0, sigma=0.5))
    chk("σ 太大 ⇒ 拒 (几何不可信)", r["allow"] is False and "σ" in r["why"], r["why"])
    r = l3_stage_gate(None)
    chk("几何未就绪 ⇒ 不推进", r["allow"] is False, r["why"])

    print("③ L4 度量调制")
    r = l4_metric(mk(xi=[0.0] * 6))
    chk("ξ=0 ⇒ 各向同性 (M=base)", abs(r["M_scalar"] - 1.0) < 1e-12, "%.4f" % r["M_scalar"])
    r = l4_metric(mk(xi=[0.1, 0, 0, 0, 0, 0], sigma=0.01))
    chk("ξ 非零 + 高置信 ⇒ M 放大", r["M_scalar"] > 1.5, "%.4f (conf %.3f)" % (r["M_scalar"], r["weight"]))
    chk("方向是单位向量", abs(np.linalg.norm(r["direction"]) - 1.0) < 1e-9,
        str(r["direction"])[:40])
    r_lo = l4_metric(mk(xi=[0.1, 0, 0, 0, 0, 0], sigma=0.5))
    r_hi = l4_metric(mk(xi=[0.1, 0, 0, 0, 0, 0], sigma=0.01))
    chk("σ 越小 ⇒ 各向异性越强", r_hi["M_scalar"] > r_lo["M_scalar"],
        "σ=0.5→%.3f, σ=0.01→%.3f" % (r_lo["M_scalar"], r_hi["M_scalar"]))

    print("④ L5 规划条件")
    r = l5_condition(mk(xi=[0.01, 0, 0, 0, 0, 0]), n_steps=3)
    chk("rollout 出 3 步", r["ok"] and len(r["poses"]) == 3, r["why"])
    chk("每步距离单调增", all(r["d_se3_each"][i] <= r["d_se3_each"][i + 1] + 1e-12
                          for i in range(len(r["d_se3_each"]) - 1)),
        " → ".join("%.5f" % v for v in r["d_se3_each"]))
    chk("无动力学时如实标注匀速外推", "匀速外推" in r["why"], r["why"])
    r = l5_condition(mk(xi=[0.0] * 6), n_steps=2)
    chk("ξ=0 ⇒ rollout 不动", all(v < 1e-12 for v in r["d_se3_each"]),
        str(r["d_se3_each"]))

    print("⑤ 四层总报告")
    rep = layer_report(mk(dn=np.radians(1.0), ds=0.001, sigma=0.05, xi=[0.01, 0, 0, 0, 0, 0]))
    chk("四层齐全", all(k in rep for k in ("L2", "L3", "L4", "L5", "ok")))
    chk("L2 角色是收口", rep["L2"]["role"] == "执行收口")
    chk("L3 角色是条件", rep["L3"]["role"] == "阶段条件")
    chk("L4 角色是调制", rep["L4"]["role"] == "度量调制")
    chk("L5 角色是规划条件", rep["L5"]["role"] == "规划条件")
    print("    L2 gain=%.3f veto=%s | L3 allow=%s | L4 M=%.3f | L5 %d步"
          % (rep["L2"]["gain"], rep["L2"]["veto"], rep["L3"]["allow"],
             rep["L4"]["M_scalar"], rep["L5"]["n_steps"]))

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 全部通过 (L2/L3/L4/L5 几何协同接线)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv or len(sys.argv) == 1:
        sys.exit(_selftest())
    print("用法: python3 -m lerobot.manifold.hjepa_mr_layers --selftest")
