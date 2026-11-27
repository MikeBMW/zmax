# -*- coding: utf-8 -*-
"""wm_verify.py — 世界模型在环的候选动作验证（L4 → L3 的第二类跨层连接）

013 的缺口
----------
013 用 Δξ = −α·M⁻¹∇V **只看当前状态的梯度**，是开环最速下降：
方向对，但"走完这一步之后径向偏差会不会真的变小"没有被验证过。
在盲插/临界干涉区，几何梯度可能指向一个"当下看似下山、走一步反而更卡"的方向。

本模块补的就是这一层：**让世界模型对候选动作做前向，预测未来流形坐标，再决定采不采纳。**

三层连接（本模块负责第 ③ 段）
------------------------------
    L2 ──δ_vis(2D→3D 真值) + 健康度 h──> L3        视觉代价可信度
    L3 ──ξ_d(名义动作)──────────────────> L4        世界模型的**动作条件** a_t
    L4 ──(z_t, a_cand) → z' → dperp' ──> L3        预测式验证 ← 本模块
    闭环: 采纳的 Δξ 进入下一拍动作历史，参与 z 的演化

设计约束
--------
1. **纯函数**：不加载权重、不读文件。预测器由调用方以 `predict_fn(z, a) -> dperp` 注入，
   这样同一个验证逻辑既能接真世界模型，也能接受控解析模型（用于自证）。
2. **未训练即零回退**：调用方若拿不到可信预测器，只传 `predict_fn=None`，
   本模块返回 `verified=False`，**不改变** 013 的原有结果。
3. **只在"预测明确变好"时采纳**：预测变差或无法判断 ⇒ 保留原候选/拒绝，
   绝不因为"预测说差不多"就放大修正量。
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "gain_min": 0.02,      # 预测改善低于该比例(相对)视为无意义, 不采纳
    "shrink_on_worse": 0.35,  # 预测变差时把修正量按该系数缩小(而非直接归零)
    "reject_ratio": -0.15,    # 预测恶化超过 15% ⇒ 直接拒绝该候选
    "cand_scales": (1.0, 0.6, 0.3),  # 候选清一色的缩放档: 先试全额, 再试保守
}


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def candidate_gain(dperp_pred, dperp_cur, *, eps: float = 1e-9) -> float | None:
    """候选动作的预测收益。

    返回 (|dperp_cur| − |dperp_pred|) / max(|dperp_cur|, eps)：
      > 0  预测径向偏差变小  ⇒ 该候选有利
      = 0  无变化
      < 0  预测变大          ⇒ 该候选有害

    用**相对**收益而非绝对差：偏差量级从 0.05mm 到 5mm 都出现过，
    绝对差在不同量级下没有可比性。
    """
    a, b = _f(dperp_pred), _f(dperp_cur)
    if a is None or b is None:
        return None
    return (abs(b) - abs(a)) / max(abs(b), eps)


def verify(cand_delta, predict_dperp: Callable[[Any], float] | None,
           dperp_cur, *, cfg: dict | None = None) -> tuple[np.ndarray | None, dict]:
    """对候选修正量做世界模型前向验证。

    参数
    ----
    cand_delta    : (3,) 解析度规给出的修正量（mm）
    predict_dperp : 可调用，输入"缩放后的候选修正量"，返回预测的未来 d_perp（mm）。
                    None ⇒ 无法验证，原样放行（verified=False）
    dperp_cur     : 当前径向偏差（mm），可为标量或 3 维向量范数
    cfg           : 覆盖 DEFAULTS

    返回
    ----
    (delta_out, info)
      delta_out : 验证后的修正量（可能被采纳 / 缩小 / 拒绝为 0）
      info      : {verified, gain, chosen_scale, reason, tried:[...]}
    """
    c = dict(DEFAULTS)
    if cfg:
        c.update({k: v for k, v in (cfg or {}).items() if v is not None})

    d = np.asarray(cand_delta if cand_delta is not None else [], dtype=float).reshape(-1)
    info: dict[str, Any] = {"verified": False, "gain": None, "chosen_scale": 1.0,
                            "reason": None, "tried": []}
    if not c["enabled"]:
        info["reason"] = "开关关闭"
        return (d[:3] if d.size >= 3 else None), info
    if d.size < 3 or not np.all(np.isfinite(d[:3])):
        info["reason"] = "无候选修正量"
        return None, info
    d = d[:3]
    if predict_dperp is None:
        info["reason"] = "无可信世界模型 ⇒ 不做验证(原样放行, 零回退)"
        return d, info
    cur = _f(dperp_cur if np.isscalar(dperp_cur) else np.linalg.norm(np.asarray(dperp_cur).reshape(-1)))
    if cur is None:
        info["reason"] = "无当前 d_perp 真值 ⇒ 无法比较"
        return d, info

    best = None
    for sc in c["cand_scales"]:
        try:
            dp = predict_dperp(d * float(sc))
        except Exception as e:                                          # noqa: BLE001
            info["tried"].append({"scale": sc, "err": "%s: %s" % (type(e).__name__, e)})
            continue
        g = candidate_gain(dp, cur)
        info["tried"].append({"scale": sc, "dperp_pred": _f(dp), "gain": g})
        if g is None:
            continue
        if best is None or g > best[1]:
            best = (float(sc), g)
        # 只有「全额档且改善显著」才提前收敛; 否则试完所有档选最优
        #   —— 曾因「达标就 break」漏掉更优的保守档(实测: 过冲场景应选 0.6 却停在 1.0)
        if sc == c["cand_scales"][0] and g >= 0.8:
            break

    if best is None:
        info["reason"] = "所有候选都预测失败 ⇒ 放行原候选(不因验证失败惩罚)"
        return d, info

    sc, g = best
    if g >= c["gain_min"]:
        info.update({"verified": True, "gain": round(g, 6), "chosen_scale": sc,
                     "reason": "预测径向偏差下降 %.1f%% ⇒ 采纳(scale=%.2f)" % (100 * g, sc)})
        return d * sc, info
    if g <= c["reject_ratio"]:
        info.update({"verified": True, "gain": round(g, 6), "chosen_scale": 0.0,
                     "reason": "预测径向偏差恶化 %.1f%% ⇒ 拒绝该候选" % (100 * abs(g))})
        return np.zeros(3), info
    # 改善不明显或轻微变差 ⇒ 缩小, 交给下一拍重估
    info.update({"verified": True, "gain": round(g, 6), "chosen_scale": float(c["shrink_on_worse"]),
                 "reason": "预测改善不足/轻微变差(%.1f%%) ⇒ 缩权至 %.2f"
                           % (100 * g, c["shrink_on_worse"])})
    return d * float(c["shrink_on_worse"]), info


def couple_with_geometry(grad_geo, grad_pred, lam: float = 1.0) -> np.ndarray | None:
    """把几何梯度与世界模型预测梯度耦合：∇V = ∇V_geo + λ·∇V_pred。

    两者都必须是**同一坐标系下的 mm 量纲**。若 λ=0 或预测项缺失，
    逐位等于纯几何梯度（零回退）。
    """
    g = np.asarray(grad_geo if grad_geo is not None else [], dtype=float).reshape(-1)
    if g.size < 3 or not np.all(np.isfinite(g[:3])):
        return None
    g = g[:3]
    if not lam or grad_pred is None:
        return g
    p = np.asarray(grad_pred, dtype=float).reshape(-1)
    if p.size < 3 or not np.all(np.isfinite(p[:3])):
        return g
    out = g + float(lam) * p[:3]
    return out if np.all(np.isfinite(out)) else g


__all__ = ["DEFAULTS", "candidate_gain", "verify", "couple_with_geometry"]
