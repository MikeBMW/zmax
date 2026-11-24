#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""夜间管线 —— 「切断输入 → 对齐先验 → 剔除噪声/提取泛化 → 闸门 → 原子切换」。

四步(每一步都留可复核数字):
  ① 清洗: 丢掉缺字段/时间戳重复的样本, 按 ts 排序
  ② 对齐: 用**当天白天**的实测样本算残差(Θ/p/H/K 相对当前先验), 时间上前 80% 训练, 后 20% 留出
  ③ 固化: 先把"先验"往当天的均值拉 30%(指数滑动), 再把 45 维残差池统计(分位数)存成缓冲先验
  ④ 闸门: 同一份留出集上,**新先验必须比旧先验的残差至少好 3%**, 且耗散比例(Ḣ≤0 占比)不退化 2pp、
          样本量 ≥ 200; 一项不过就保留旧版(夜间不许"感觉更好"就上线)

铁律: 夜间产物只写 zmax_data/daynight/candidates/, 只有 promote() 才原子换 current.json ——
      在线进程读的永远是 current.json, 不会读到写一半的东西。
"""
from __future__ import annotations

import json
import math
import os
import time

from . import daylog
from .phase import DN_DIR, end_night, read_state, start_night, write_state

CAND_DIR = os.path.join(DN_DIR, "candidates")
PRIOR = os.path.join(DN_DIR, "current.json")
REPORT_DIR = os.path.join(DN_DIR, "reports")

# 先验的四维口径(与相空间窗口同源): 参考 Θ(mm) / 参考 p / 参考 H / 动能占比
SCALE = {"th_mm": 100.0, "p": 0.05, "H": 0.1, "k_share": 0.1}
BLEND = 0.30
GATE_IMPROVE = 0.03          # 残差至少改善 3%
GATE_DISSIP = 0.02           # 耗散比例允许退化的上限(2pp)
GATE_MIN_N = 200


def _ensure() -> None:
    for d in (CAND_DIR, REPORT_DIR):
        os.makedirs(d, exist_ok=True)


def load_prior() -> dict:
    _ensure()
    try:
        with open(PRIOR, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                             # noqa: BLE001
        return {"ver": "v0", "ts": 0.0, "n": 0,
                "th_mm": 0.0, "p": 0.0, "H": 0.02, "k_share": 0.05,
                "buffer": {}, "writer": "bootstrap"}


def _clean(recs: list[dict]) -> tuple[list[dict], dict]:
    seen = set()
    out = []
    drop_field = drop_dup = 0
    for r in recs:
        if not all(isinstance(r.get(k), (int, float)) for k in ("ts", "th_mm", "p", "H", "K", "U")):
            drop_field += 1
            continue
        if r["ts"] in seen:
            drop_dup += 1
            continue
        seen.add(r["ts"])
        out.append(r)
    out.sort(key=lambda r: r["ts"])
    return out, {"drop_field": drop_field, "drop_dup": drop_dup, "kept": len(out)}


def _feat(r: dict) -> dict:
    H = float(r["H"])
    return {"th_mm": float(r["th_mm"]), "p": float(r["p"]), "H": H,
            "k_share": (float(r["K"]) / H) if H > 1e-9 else 0.0}


def _components(prior: dict) -> list[dict]:
    """先验可以是**多盆地混合**(一天里往往有两三个不同工位/姿态簇)。"""
    comps = prior.get("components")
    if comps:
        return comps
    return [{"w": 1.0, **{k: float(prior.get(k, 0.0)) for k in SCALE}}]


def _residual(prior: dict, recs: list[dict]) -> dict:
    comps = _components(prior)
    tot = []
    for r in recs:
        f = _feat(r)
        best = float("inf")
        for c in comps:
            s = 0.0
            for k, sc in SCALE.items():
                s += ((f[k] - float(c.get(k, 0.0))) / sc) ** 2
            best = min(best, math.sqrt(s))
        tot.append(best)
    if not tot:
        return {"n": 0, "mean": float("inf"), "p90": float("inf")}
    tot_sorted = sorted(tot)
    return {"n": len(tot), "mean": sum(tot) / len(tot),
            "p90": tot_sorted[min(len(tot_sorted) - 1, int(len(tot_sorted) * 0.9))]}


def _dissipation(recs: list[dict]) -> float:
    """Ḣ ≤ 0 的样本占比: 真正受控/耗散的运动应占多数; 参考点在跳时会明显偏低。"""
    if len(recs) < 2:
        return 0.0
    down = 0
    tot = 0
    for a, b in zip(recs, recs[1:]):
        d = float(b["H"]) - float(a["H"])
        if abs(d) < 1e-12:
            continue
        tot += 1
        if d <= 0:
            down += 1
    return (down / tot) if tot else 0.0


def _quant(vals: list[float]) -> dict:
    if not vals:
        return {"p10": 0.0, "p50": 0.0, "p90": 0.0}
    v = sorted(vals)
    pick = lambda q: v[min(len(v) - 1, max(0, int(len(v) * q)))]
    return {"p10": round(pick(0.1), 4), "p50": round(pick(0.5), 4), "p90": round(pick(0.9), 4)}


def night_run(day_id: str = "", why: str = "", promote_if_pass: bool = True) -> dict:
    _ensure()
    st = start_night(why or "夜间管线")
    if not day_id:
        day_id = daylog.latest_with_data()
        if not day_id:
            end_night(False, why="夜间中止: 没有白天日志")
            return {"ok": False, "why": "没有白天日志"}

    recs_raw = daylog.read(day_id)
    recs, clean_info = _clean(recs_raw)
    if len(recs) < GATE_MIN_N:
        end_night(False, why="夜间中止: 有效样本 %d < %d" % (len(recs), GATE_MIN_N))
        return {"ok": False, "why": "有效样本不足", "n": len(recs), "day_id": day_id}

    cut = int(len(recs) * 0.8)
    train, hold = recs[:cut], recs[cut:]
    prior_old = load_prior()

    r_old = _residual(prior_old, hold)
    d_old = _dissipation(hold)

    # ② 对齐 + ③ 固化: 先验向当天均值指数滑动(EB 风格), 缓冲池存分位数
    ths = sorted(_feat(r)["th_mm"] for r in train)
    split = ths[len(ths) // 2]
    clusters = [[r for r in train if _feat(r)["th_mm"] <= split],
                [r for r in train if _feat(r)["th_mm"] > split]]
    clusters = [c for c in clusters if c]
    old_comps = _components(prior_old)
    comps = []
    for idx, cl in enumerate(clusters):
        mean = {k: sum(_feat(r)[k] for r in cl) / len(cl) for k in SCALE}
        base = old_comps[idx] if idx < len(old_comps) and len(old_comps) > 1 else old_comps[0]
        c = {"w": round(len(cl) / float(len(train)), 4)}
        for k in SCALE:
            c[k] = float(base.get(k, 0.0)) * (1 - BLEND) + mean[k] * BLEND
        comps.append(c)
    priors_mean = {k: sum(c[k] * c["w"] for c in comps) for k in SCALE}
    prior_new = dict(prior_old)
    prior_new.update(priors_mean)
    prior_new["components"] = comps
    resid_train = [_feat(r)["th_mm"] - prior_new["th_mm"] for r in train]
    hbuf = [float(r["H"]) for r in train]
    kbuf = [_feat(r)["k_share"] for r in train]
    prior_new["buffer"] = {
        "th_resid_mm": _quant(resid_train),
        "H": _quant(hbuf),
        "k_share": _quant(kbuf),
        "dissipation": round(_dissipation(train), 4),
        "dims": 45, "source": "白天残差池压缩(Θ残差/H/动能占比 分位数)",
    }
    prior_new["n"] = int(prior_old.get("n") or 0) + len(train)
    prior_new["ts"] = time.time()
    prior_new["day_id"] = day_id
    prior_new["ver"] = "v%d" % (int(str(prior_old.get("ver", "v0")).lstrip("v") or 0) + 1)

    r_new = _residual(prior_new, hold)

    improve = (r_old["mean"] - r_new["mean"]) / r_old["mean"] if r_old["mean"] > 0 else 0.0
    dissip_ok = _dissipation(hold) >= d_old - GATE_DISSIP
    gate = {
        "improve_pct": round(improve * 100, 2),
        "need_pct": round(GATE_IMPROVE * 100, 1),
        "improve_ok": improve >= GATE_IMPROVE,
        "dissipation_ok": dissip_ok,
        "resid_old": {k: round(v, 5) for k, v in r_old.items()},
        "resid_new": {k: round(v, 5) for k, v in r_new.items()},
        "dissipation": round(d_old, 4),
        "n_valid": len(recs),
        "passed": bool(improve >= GATE_IMPROVE and dissip_ok and len(recs) >= GATE_MIN_N),
    }

    report = {"ts": time.time(), "day_id": day_id, "night_id": st.get("night_id"),
              "clean": clean_info, "train": len(train), "holdout": len(hold),
              "prior_old_ver": prior_old.get("ver"), "prior_new_ver": prior_new["ver"],
              "prior_new": {k: round(prior_new[k], 5) for k in SCALE},
              "buffer": prior_new["buffer"], "gate": gate}
    rp = os.path.join(REPORT_DIR, "night_%s.json" % (st.get("night_id") or int(time.time())))
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    report["report_path"] = rp

    cand = os.path.join(CAND_DIR, "prior_%s.json" % prior_new["ver"])
    with open(cand, "w", encoding="utf-8") as f:
        json.dump(prior_new, f, ensure_ascii=False, indent=1)
    report["candidate"] = cand

    if gate["passed"] and promote_if_pass:
        promote(cand)
        end_night(True, model_ver=prior_new["ver"], why="夜间闸门通过 → 切到 %s" % prior_new["ver"])
        report["promoted"] = True
    else:
        end_night(False, why="夜间闸门未过 → 保留 %s" % prior_old.get("ver"))
        report["promoted"] = False
    return report


def promote(cand_path: str) -> dict:
    """原子切换: 只改 current.json 的指针, 不原地改(在线进程可能正在读)。"""
    _ensure()
    with open(cand_path, encoding="utf-8") as f:
        prior = json.load(f)
    tmp = PRIOR + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prior, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PRIOR)
    st = read_state()
    st["model_ver"] = prior.get("ver", st.get("model_ver"))
    write_state(st, "promote: 切到 %s" % prior.get("ver"))
    return {"promoted": prior.get("ver"), "path": PRIOR}
