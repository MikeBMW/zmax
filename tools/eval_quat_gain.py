#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_quat_gain.py — 训练头的**分档验收 + 混合策略门限** (不许拍脑袋进默认档)

背景: 训练头 (自适应增益) 在高噪声档大赢基线, 但在 3~6° 档回退 0.12° ——
      因为最优增益取决于**不可观测的记忆漂移**, 单一策略不可能每档都最优。
做法: 用可观测的 |rel| (=|测量−记忆|) 做门限, |rel| 大时才用头, 小���走解析基线;
      门限只在**验证集**上选, 再在**测试集**上报数 (不偷看测试集)。

判据: 混合策略每个噪声档 ≤ 基线, 且总体严格更小 ⇒ ok=true。
产出: zmax_data/quat_head/report_hybrid.json
"""
from __future__ import annotations

import importlib.util
import json
import os

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tqg", os.path.join(HERE, "train_quat_gain.py"))
tqg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tqg)

OUT = tqg.OUT


def load_head():
    m = tqg.Gain()
    m.load_state_dict(torch.load(os.path.join(OUT, "quat_head.pt"), map_location="cpu")["state"])
    m.eval()
    return m


def run(model, te, gate_deg):
    feat = torch.tensor(te["feat"])
    with torch.no_grad():
        g = model(feat).numpy()
    relmag = te["feat"][:, 5]
    g_use = np.where(relmag >= np.radians(gate_deg), g, 0.5)      # 门限外回解析基线
    q_h = tqg.slerp_np(te["mem"], te["meas"], te["feat"][:, 3] * g_use)
    q_b = tqg.slerp_np(te["mem"], te["meas"], te["feat"][:, 3] * 0.5)
    nod = te["feat"][:, 4] < 0.5
    q_h[nod] = te["mem"][nod]
    q_b[nod] = te["mem"][nod]
    return tqg.ang_deg(q_h, te["true"]), tqg.ang_deg(q_b, te["true"])


def bands(eh, eb, te):
    rows = []
    for lo, hi in [(0, 3), (3, 6), (6, 10), (10, 15)]:
        m = np.array([(lo <= r["sigma"] < hi) for r in te["meta"]])
        if m.sum():
            rows.append({"sigma_deg": "%d-%d" % (lo, hi), "n": int(m.sum()),
                         "head_deg": round(float(eh[m].mean()), 4),
                         "baseline_deg": round(float(eb[m].mean()), 4),
                         "delta_deg": round(float(eh[m].mean() - eb[m].mean()), 4)})
    return rows


def main():
    rng = np.random.default_rng(1234)             # 与训练不同种子 ⇒ 独立评估
    val, test = tqg.make(40_000, rng), tqg.make(40_000, rng)
    model = load_head()
    # 选门限: 目标=总体角误差最小, 约束=没有哪一档回退超过 0.05° (抖动容差, 写死可复核);
    # 若没有门限满足约束, 就退回"门到无穷"=完全用解析基线 (不进默认档也不冒险)。
    cand = []
    for gate in (2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0):
        eh, eb = run(model, val, gate)
        rows = bands(eh, eb, val)
        worst = max(r["delta_deg"] for r in rows) if rows else 99
        cand.append((gate, worst, float(eh.mean()), float(eb.mean())))
    ok_c = [c for c in cand if c[1] <= 0.05]
    if ok_c:
        gate, worst, vh, vb = min(ok_c, key=lambda c: c[2])
    else:
        gate, worst, vh, vb = 1e9, 0.0, float(cand[0][3]), float(cand[0][3])
    eh, eb = run(model, test, gate)
    rows = bands(eh, eb, test)
    rep = {"gate_deg": gate, "candidates": [{"gate_deg": c[0], "worst_band_delta": c[1],
                                             "val_head_deg": round(c[2], 4),
                                             "val_baseline_deg": round(c[3], 4)} for c in cand],
           "tolerance_deg": 0.05,
           "selected_on": "validation", "reported_on": "test",
           "val": {"head_deg": round(vh, 4), "baseline_deg": round(vb, 4)},
           "test": {"head_deg": round(float(eh.mean()), 4), "baseline_deg": round(float(eb.mean()), 4),
                    "delta_deg": round(float(eh.mean() - eb.mean()), 4),
                    "p95_head": round(float(np.percentile(eh, 95)), 4),
                    "p95_baseline": round(float(np.percentile(eb, 95)), 4)},
           "by_sigma": rows,
           "note": "门限=以 |测量−记忆| 判断是否启用训练头; 不可观测的记忆漂移使单一策略不可能各档俱优"}
    rep["ok"] = bool(rep["test"]["delta_deg"] < 0 and all(r["delta_deg"] <= 0 for r in rows))
    with open(os.path.join(OUT, "report_hybrid.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
