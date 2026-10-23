#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orbit_evolve_advisor.py — 用对称性给自主进化判方向 (老倪 2026-10-23)

一维退化版：进化只有一个标量目标 mAP50，序列 = 每一代的成绩。
  时间平移对称 ⇒ **同样的变异策略应当带来同样的改进量** ⇒ 下一代成绩可用
  「等改进量推演」预测 (一维欧氏轨道 = 恒定斜率)。
  推演一旦破缺（改进量跳变 / 平台标准差把斜率淹掉）⇒ 说明这条路已被走完,
  该换方向或加算力 —— 不是继续小步微调。

输出 verdict:
  insufficient  样本 <4 代，不猜
  keep          等改进量推演成立且预测值 ≥ best+margin ⇒ 允许小步继续
  escalate      推演破缺 或 预测值 < best−margin ⇒ 平台期确认, 强制大变异+加算力

用法: python3 tools/orbit_evolve_advisor.py [--json]
"""
from __future__ import annotations

import json
import os
import sys

LEDGER = os.path.join(os.environ.get("EVO_WORK", "/home/intel/evolve"), "ledger.json")
SRC = os.environ.get("EVO_SRC", "/home/intel/zmax_map/src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lerobot.manifold.orbit_predict import OrbitPredictor      # noqa: E402


def series(ledger_path: str = LEDGER) -> list[float]:
    """台账里每一代的 mAP50（None 的跳过，绝不补 0）。"""
    try:
        d = json.load(open(ledger_path))
    except Exception:
        return []
    entries = d.get("entries") if isinstance(d, dict) else d
    out = []
    for x in entries or []:
        v = x.get("map50")
        if v is None:
            v = (x.get("val") or {}).get("map50")
        if v is None:
            v = x.get("train_map50")
        if v is not None:
            out.append(float(v))
    return out


def advise(window: int = 6, margin: float = 0.005, ledger_path: str = LEDGER) -> dict:
    s = series(ledger_path)
    if len(s) < 4:
        return {"verdict": "insufficient", "n": len(s), "why": "样本<%d代, 不猜" % 4}
    pr = OrbitPredictor(window=window, horizons=(1, 3), drift_tol=1.0,
                        accel_tol=0.6, bend_tol=0.5, manifold="euclidean")
    o = {}
    for v in s:
        o = pr.observe([v])
    pred = None
    try:
        pred = float((o.get("pred") or {})["1"][0])
    except Exception:
        pred = None
    best = max(s)
    if not o.get("valid", False):
        verdict, why = "escalate", "推演破缺(%s)" % (o.get("break_reason") or "-")
    elif pred is not None and pred >= best + margin:
        verdict, why = "keep", "预测 %.4f ≥ best %.4f+%.3f" % (pred, best, margin)
    elif pred is not None:
        verdict, why = "escalate", "预测 %.4f < best %.4f−%.3f ⇒ 平台期确认" % (pred, best, margin)
    else:
        verdict, why = "insufficient", "无预测值"
    return {"verdict": verdict, "why": why, "pred_next": pred, "best": best, "n": len(s),
            "tail": [round(x, 5) for x in s[-5:]],
            "valid": bool(o.get("valid")), "break": o.get("break_reason") or "",
            "drift": o.get("drift"), "accel": o.get("accel"), "step_mean": o.get("step_mean")}


if __name__ == "__main__":
    a = advise()
    print(json.dumps(a, ensure_ascii=False, indent=1))
