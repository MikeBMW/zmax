#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""白天在线学习 (Day-mode online learning) —— 有界、可回放、绝不动先验。

和"白天只记日志"的区别: 这里白天就**边学边用**——每来一帧, 用递推最小二乘(RLS, 带遗忘因子)
更新一个 3 维线性预测头 (Θ,p,H) → 下一拍 H。这条头只活在缓冲段, 有三个硬边界:

  ① 参数范数钳制 ‖w‖ ≤ W_MAX      ⇒ 单帧噪声不可能把模型拽走
  ② 学习率由 RLS 的 P 矩阵自然衰减 ⇒ 越学越稳(不是固定步长乱跳)
  ③ 只写 zmax_data/daynight/online/, 绝不写 current.json(先验)
     ⇒ 白天学的东西要经过夜间训练 + 闸门才能进在线权重

影子评估(shadow): 每 N 帧用"当前在线权重 vs 冻结基线"在最近窗口上比 RMSE,
只记录不切换 —— 给夜间闸门提供"白天到底学到了什么"的证据。
"""
from __future__ import annotations

import json
import math
import os
import time

from . import daylog
from .phase import DN_DIR

ON_DIR = os.path.join(DN_DIR, "online")
HEAD = os.path.join(ON_DIR, "head.json")
LOG = os.path.join(ON_DIR, "online_log.jsonl")

DIM = 4                      # [1, Θ_n, p_n, H_n]
# 🔴 λ 必须 = 1.0: 遗忘因子 + 常数列/近共线特征(Θ、H 长时间几乎不变)会让协方差按 λ^-n 爆炸,
# 实测 λ=0.995 跑 11k 帧后 ‖w‖ 顶到钳制上限、影子 RMSE 比持续性基线差 6.9 倍。
# 白天的定位是"稳定增量估计", 忘性交给夜间训练(它才有跨步/非线性)。
LAMBDA = 1.0
W_MAX = 2.0                  # 权重范数上限
RIDGE = 1e-3
P0 = 50.0                    # 初始协方差 → 初始等效步长较大, 但随样本数收敛

SCALE = {"th_mm": 100.0, "p": 0.05, "H": 0.1}


def _ensure() -> None:
    os.makedirs(ON_DIR, exist_ok=True)


def _x(r: dict) -> list[float]:
    return [1.0, float(r["th_mm"]) / SCALE["th_mm"], float(r["p"]) / SCALE["p"],
            float(r["H"]) / SCALE["H"]]


def load_head() -> dict:
    _ensure()
    try:
        with open(HEAD, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                             # noqa: BLE001
        return {"w": [0.0] * DIM, "P": [[P0 if i == j else 0.0 for j in range(DIM)] for i in range(DIM)],
                "n": 0, "ts": 0.0, "rmse_ema": 0.0, "writer": "bootstrap"}


def save_head(h: dict) -> None:
    _ensure()
    h["ts"] = time.time()
    tmp = HEAD + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, HEAD)


def _rls_update(h: dict, x: list[float], y: float) -> tuple[float, float]:
    """一步 RLS; 返回 (预测值, 残差)。数值上用 DIM×DIM 稠密矩阵(DIM=4, 可忽略开销)。"""
    w = h["w"]
    P = h["P"]
    pred = sum(w[i] * x[i] for i in range(DIM))
    err = y - pred
    # k = P x / (λ + xᵀ P x)
    Px = [sum(P[i][j] * x[j] for j in range(DIM)) for i in range(DIM)]
    den = LAMBDA + sum(x[i] * Px[i] for i in range(DIM))
    if den <= 0:
        return pred, err
    k = [Px[i] / den for i in range(DIM)]
    for i in range(DIM):
        w[i] = w[i] + k[i] * err
    for i in range(DIM):
        for j in range(DIM):
            P[i][j] = (P[i][j] - k[i] * Px[j]) / LAMBDA
    # ① 范数钳制
    nrm = math.sqrt(sum(w[i] * w[i] for i in range(DIM)))
    if nrm > W_MAX:
        s = W_MAX / nrm
        for i in range(DIM):
            w[i] *= s
    # 数值卫生: 协方差对角加 ridge, 防止长期运行退化
    for i in range(DIM):
        P[i][i] += RIDGE * 1e-6
    return pred, err


def learn_day(day_id: str = "", steps: int = 0, log: bool = True) -> dict:
    """白天在线学习: 顺序喂当天日志(时间顺序! 不许打乱), 每帧一步 RLS。"""
    _ensure()
    if not day_id:
        day_id = daylog.latest_with_data()
        if not day_id:
            return {"ok": False, "why": "没有白天日志"}
    recs = [r for r in daylog.read(day_id)
            if all(isinstance(r.get(k), (int, float)) for k in ("ts", "th_mm", "p", "H"))]
    recs.sort(key=lambda r: r["ts"])
    if len(recs) < 10:
        return {"ok": False, "why": "样本不足", "n": len(recs)}
    if steps and steps > 0:
        recs = recs[-steps:]

    h = load_head()
    n0 = h["n"]
    cursor = float((h.get("cursor") or {}).get(day_id, -1e18))
    if cursor > -1e17:                     # 只吃新增样本; 重放用 replay_day()
        recs = [r for r in recs if float(r["ts"]) > cursor]
        if not recs:
            return {"ok": True, "day_id": day_id, "samples": 0, "steps_added": 0,
                    "why": "没有新样本(游标已到 %s)" % round(cursor, 1)}
    errs = []
    fh = open(LOG, "a", encoding="utf-8") if log else None
    try:
        for a, b in zip(recs, recs[1:]):
            # 残差学习: 学 ΔH, 绝对预测 = H_t + Δ̂ ⇒ 与"持续性"同台比(否则 98Hz 下必输)
            pred_d, _err = _rls_update(h, _x(a), float(b["H"]) - float(a["H"]))
            pred = float(a["H"]) + pred_d
            err = float(b["H"]) - pred
            h["n"] += 1
            errs.append(abs(err))
            if fh is not None and h["n"] % 20 == 0:
                fh.write(json.dumps({"ts": round(a["ts"], 3), "n": h["n"],
                                     "pred": round(pred, 5), "obs": round(float(b["H"]), 5),
                                     "err": round(err, 5)}, ensure_ascii=False) + "\n")
        if fh is not None:
            fh.flush()
    finally:
        if fh is not None:
            fh.close()

    rmse = math.sqrt(sum(e * e for e in errs) / max(1, len(errs)))
    h["rmse_ema"] = round(0.9 * float(h.get("rmse_ema") or 0.0) + 0.1 * rmse, 6)
    h["day_id"] = day_id
    h["cursor"] = dict(h.get("cursor") or {})
    h["cursor"][day_id] = float(max(r["ts"] for r in recs))
    save_head(h)
    return {"ok": True, "day_id": day_id, "samples": len(recs) - 1,
            "steps_total": h["n"], "steps_added": h["n"] - n0,
            "rmse_batch": round(rmse, 6), "rmse_ema": h["rmse_ema"],
            "w": [round(v, 4) for v in h["w"]], "w_norm": round(math.sqrt(sum(v * v for v in h["w"])), 3)}


def shadow_eval(day_id: str = "", window: int = 500) -> dict:
    """影子评估: 在线权重 vs 冻结基线(全 0 权重 = 预测 H 恒为 0, 即"没有模型的先验")在同一窗口比 RMSE。"""
    if not day_id:
        day_id = daylog.latest_with_data()
        if not day_id:
            return {"ok": False, "why": "没有白天日志"}
    recs = [r for r in daylog.read(day_id)
            if all(isinstance(r.get(k), (int, float)) for k in ("ts", "th_mm", "p", "H"))]
    recs.sort(key=lambda r: r["ts"])
    recs = recs[-window:]
    if len(recs) < 20:
        return {"ok": False, "why": "窗口样本不足", "n": len(recs)}
    w = load_head()["w"]
    e_on = e_base = 0.0
    n = 0
    for a, b in zip(recs, recs[1:]):
        x = _x(a)
        pred = float(a["H"]) + sum(w[i] * x[i] for i in range(DIM))
        e_on += (float(b["H"]) - pred) ** 2
        e_base += (float(b["H"]) - float(a["H"])) ** 2      # 持续性基线: 下一拍 H = 当前 H
        n += 1
    r_on = math.sqrt(e_on / n)
    r_base = math.sqrt(e_base / n)
    return {"ok": True, "day_id": day_id, "n": n,
            "rmse_online": round(r_on, 6), "rmse_persistence": round(r_base, 6),
            "improve_pct": round(100.0 * (r_base - r_on) / r_base, 2) if r_base > 0 else 0.0}
