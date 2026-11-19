#!/usr/bin/env python3
"""ft_contact_dataset.py — 力控插入的数据管道 + 接触/入孔判别训练 (只用真实数据, 不造样本)。

输入 (全部是现场落盘的真值):
  zmax_data/rokae_sdk/ft_out/ft_direct_YYYYMMDD.jsonl   六维力 10Hz (world 系, 含工具自重+零点偏置)
  zmax_data/se3_follow/session.json (+ attempt_*.json)  跟随真机录的位姿 20Hz

做法:
  1) 时间对齐 (力 10Hz → 位姿 20Hz 线性插值), 逐帧算: F 三轴 / |F| / dF/dt / 速度 / 相对插入轴(x)深度
  2) 力的**差分口径**: F_ref = 本段位姿静止(|v|<1mm/s)且无位移时段的 F 中位 ⇒ 接触力 = F − F_ref
     (控制器力矩零点/工具负载没标定过, 绝对量不能用; 差分量才能用 —— 这是实测结论)
  3) 标签 (入孔/推进) = 未来 0.5s 内沿 +x 的位移 >0.5mm 且当时 |F_contact| 有非零分量
  4) 训练: 逻辑回归 (numpy IRLS, 不引重依赖) + 时间块 5 折; 与两条平凡基线比:
       基线A 永远猜"没推进"   基线B |F_contact|>阈值就猜"推进"
     只有优于两条基线才允许进默认档 (老倪口径: 有提升才上线)

用法:
  python3 tools/ft_contact_dataset.py --build          # 只建数据集, 报表
  python3 tools/ft_contact_dataset.py --train          # 建 + 训练 + 5 折报表
"""
import argparse
import glob
import json
import math
import os
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FT_DIR = os.path.join(ROOT, "zmax_data", "rokae_sdk", "ft_out")
FOLLOW = os.path.join(ROOT, "zmax_data", "se3_follow")
OUT = os.path.join(ROOT, "zmax_data", "ft_contact")


def _ts(r):
    t = r.get("t")
    if isinstance(t, str):
        import datetime as dt
        return dt.datetime.strptime(t[:19], "%Y-%m-%d %H:%M:%S").timestamp()
    return float(t or 0)


def load_ft(day=None):
    pat = os.path.join(FT_DIR, "ft_direct_%s.jsonl" % (day or "*"))
    rows = []
    for f in sorted(glob.glob(pat)):
        for ln in open(f, encoding="utf-8"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                                # noqa: BLE001
                continue
            # 采样器自己写了 epoch 秒的 ts 就直接用 (t 字符串是控制器时区, 差 8h)
            r["ts"] = float(r["ts"]) if isinstance(r.get("ts"), (int, float)) else _ts(r)
            if r["ts"] > 0:
                rows.append(r)
    rows.sort(key=lambda r: r["ts"])
    return rows


def load_paths():
    out = []
    cand = [os.path.join(FOLLOW, "session.json")] + sorted(glob.glob(os.path.join(FOLLOW, "attempt_*.json")))
    for f in cand:
        if not os.path.exists(f):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:                                                    # noqa: BLE001
            continue
        p = d.get("path") or []
        if len(p) >= 2:
            out.append((os.path.basename(f), p))
    return out


def interp_pose(path, t):
    """位姿点按时间线性插值 (path 里 t 是本地 epoch 秒)"""
    if t <= path[0]["t"]:
        return path[0]["A_mm"]
    if t >= path[-1]["t"]:
        return path[-1]["A_mm"]
    lo, hi = 0, len(path) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if path[mid]["t"] <= t:
            lo = mid
        else:
            hi = mid
    a, b = path[lo], path[hi]
    dt_ = (b["t"] - a["t"]) or 1e-6
    w = (t - a["t"]) / dt_
    return [a["A_mm"][k] + (b["A_mm"][k] - a["A_mm"][k]) * w for k in range(3)]


def _align_hours(ft, paths):
    """现场两套时间口径有 8h 差 (控制器/NTP 回拨: ft 的 t 字段比本地 epoch 慢 8h)。
    用'哪个整小时平移让力数据落进位姿时间窗'来定, 不写死 8。"""
    if not ft or not paths:
        return 0.0
    lohi = [(p[0]["t"], p[-1]["t"]) for _, p in paths]
    f0, f1 = ft[0]["ts"], ft[-1]["ts"]
    best, best_pen = 0.0, None
    for k in range(-12, 13):
        sh = k * 3600.0
        pen = 0.0
        for a, b in lohi:
            if f1 + sh < a or f0 + sh > b:
                pen += min(abs(f0 + sh - b), abs(a - (f1 + sh)))
            else:
                pen -= (min(b, f1 + sh) - max(a, f0 + sh))
        if best_pen is None or pen < best_pen:
            best_pen, best = pen, sh
    return best


def build(day=None):
    ft = load_ft(day)
    paths = load_paths()
    if not ft:
        return {"ok": False, "err": "没有 ft 数据"}
    if not paths:
        return {"ok": False, "err": "没有跟随位姿"}
    shift = _align_hours(ft, paths)
    if shift:
        for r in ft:
            r["ts"] += shift
        ft.sort(key=lambda r: r["ts"])
    # 每帧对齐到位姿
    rows = []
    for r in ft:
        best = None
        for name, p in paths:
            if p[0]["t"] - 60 <= r["ts"] <= p[-1]["t"] + 60:
                best = p
                break
        if best is None:
            continue
        a = interp_pose(best, r["ts"])
        rows.append({"ts": r["ts"], "fx": r.get("fx"), "fy": r.get("fy"), "fz": r.get("fz"),
                     "A": a, "op": r.get("op"), "power": r.get("power")})
    if len(rows) < 20:
        return {"ok": False, "err": "对齐后样本 %d 条, 太少" % len(rows)}
    # 速度 / 深度
    for i, r in enumerate(rows):
        j = max(0, i - 5)          # 0.5s 前
        dt_ = max(1e-3, r["ts"] - rows[j]["ts"])
        r["v"] = math.dist(r["A"], rows[j]["A"]) / dt_
        r["dx5"] = r["A"][0] - rows[j]["A"][0]
    # 差分力基线: 静止窗口 (v<1mm/s 且 |dx5|<0.2) 的 F 中位
    still = [r for r in rows if r["v"] < 1.0 and abs(r["dx5"]) < 0.2]
    ref = [st.median([r[k] for r in still]) for k in ("fx", "fy", "fz")] if len(still) >= 10 else [0.0, 0.0, 0.0]
    for r in rows:
        c = [r["fx"] - ref[0], r["fy"] - ref[1], r["fz"] - ref[2]]
        r["Fc"] = c
        r["Fc_n"] = math.sqrt(sum(v * v for v in c))
        r["Fc_ax"] = c[0]          # 插入轴 = base +x
    # 标签: 未来 0.5s 沿 +x 前移 >0.5mm
    for i, r in enumerate(rows):
        k = min(len(rows) - 1, i + 5)
        r["y"] = 1 if (rows[k]["A"][0] - r["A"][0]) > 0.5 else 0
    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "dataset_%s.jsonl" % (day or "all"))
    with open(fp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({k: (round(v, 4) if isinstance(v, float) else v)
                                for k, v in r.items()}, ensure_ascii=False) + "\n")
    pos = sum(r["y"] for r in rows)
    rep = {"ok": True, "n": len(rows), "pos": pos, "neg": len(rows) - pos,
           "F_ref(静止中位)": [round(v, 2) for v in ref],
           "still_frames": len(still), "file": fp,
           "Fc_n 中位": round(st.median([r["Fc_n"] for r in rows]), 2),
           "Fc_ax 中位": round(st.median([r["Fc_ax"] for r in rows]), 2),
           "op": sorted({str(r["op"]) for r in rows})}
    json.dump(rep, open(os.path.join(OUT, "dataset_report.json"), "w"), ensure_ascii=False, indent=1)
    return rep


def _fit_logreg(X, y, iters=300, l2=1e-3):
    import numpy as np
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, d = X.shape
    w = np.zeros(d + 1)
    Xb = np.hstack([np.ones((n, 1)), X])
    for _ in range(iters):
        z = Xb @ w
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        g = Xb.T @ (p - y) / n
        g[1:] += l2 * w[1:]
        W = np.clip(p * (1 - p), 1e-6, None)
        H = (Xb * W[:, None]).T @ Xb / n
        H[1:, 1:] += l2 * np.eye(d)
        w -= np.linalg.solve(H + 1e-8 * np.eye(d + 1), g)
    return w


def _pred(w, X):
    import numpy as np
    Xb = np.hstack([np.ones((len(X), 1)), np.asarray(X, dtype=float)])
    return 1.0 / (1.0 + np.exp(-np.clip(Xb @ w, -30, 30)))


def train(day=None, folds=5):
    rep = build(day)
    if not rep.get("ok"):
        return rep
    rows = [json.loads(l) for l in open(rep["file"], encoding="utf-8")]
    X = [[r["Fc_ax"], r["Fc_n"], r["fy"], r["fz"], r["v"]] for r in rows]
    y = [r["y"] for r in rows]
    if len(set(y)) < 2:
        return {"ok": True, "trained": False,
                "why": "标签只有一类 (y=%s), 现在没有'推进/入孔'样本 ⇒ 训练无意义。"
                       "等李萨如力控搜索跑起来、有接触→入孔的正样本后再训。" % y[0],
                "n": len(rows), "pos": sum(y), "F_ref": rep["F_ref(静止中位)"]}
    n = len(rows)
    idx = [int(i * n / folds) for i in range(folds + 1)]
    accs, aucs, base_a, base_b = [], [], [], []
    for k in range(folds):
        te = list(range(idx[k], idx[k + 1]))
        tr = [i for i in range(n) if i not in te]
        w = _fit_logreg([X[i] for i in tr], [y[i] for i in tr])
        p = _pred(w, [X[i] for i in te])
        yt = [y[i] for i in te]
        pred = [1 if q >= 0.5 else 0 for q in p]
        tp = sum(1 for a, t in zip(pred, yt) if a == 1 and t == 1)
        tn = sum(1 for a, t in zip(pred, yt) if a == 0 and t == 0)
        fp = sum(1 for a, t in zip(pred, yt) if a == 1 and t == 0)
        fn = sum(1 for a, t in zip(pred, yt) if a == 0 and t == 1)
        # 正样本 <1% 时 "accuracy" 全是假象(全猜0也 0.99) ⇒ 用 balanced accuracy + AUC
        bal = 0.5 * ((tp / (tp + fn)) if (tp + fn) else 0.0) + 0.5 * ((tn / (tn + fp)) if (tn + fp) else 0.0)
        pairs = [(pp, tt) for pp, tt in zip(p, yt)]
        pos = [pp for pp, tt in pairs if tt == 1]
        neg = [pp for pp, tt in pairs if tt == 0]
        auc = 0.5
        if pos and neg:
            wins = sum((1.0 if a > b else 0.5 if a == b else 0.0) for a in pos for b in neg)
            auc = wins / (len(pos) * len(neg))
        accs.append(bal)
        aucs.append(auc)
        # 基线也按 balanced accuracy 算, 否则 99% 负样本下"永远猜0"看着像满分
        ba_tn = sum(1 for t in yt if t == 0)
        ba_tp = sum(1 for t in yt if t == 1)
        base_a.append(0.5 * ((ba_tn / len(te)) if ba_tn else 0.0) + 0.0)
        thr = 3.0
        pb = [1 if X[i][1] > thr else 0 for i in te]
        tpb = sum(1 for a, t in zip(pb, yt) if a == 1 and t == 1)
        tnb = sum(1 for a, t in zip(pb, yt) if a == 0 and t == 0)
        base_b.append(0.5 * ((tpb / (tpb + fn)) if (tpb + fn) else 0.0)
                      + 0.5 * ((tnb / (tnb + fp)) if (tnb + fp) else 0.0))
    res = {"ok": True, "trained": True, "n": n, "pos": sum(y), "pos_rate": round(sum(y) / n, 4),
           "folds": folds,
           "metric": "balanced_accuracy (正样本 %d/%d, 纯 accuracy 无意义)" % (sum(y), n),
           "model_bal_acc_median": round(st.median(accs), 4),
           "model_auc_median": round(st.median(aucs), 4) if aucs else None,
           "baseline_always0_bal_acc": round(st.median(base_a), 4),
           "baseline_forceThr_bal_acc": round(st.median(base_b), 4),
           "verdict": "", "coef": None}
    best_base = max(res["baseline_always0_bal_acc"], res["baseline_forceThr_bal_acc"])
    res["verdict"] = ("模型优于基线 ⇒ 可进影子档" if res["model_bal_acc_median"] > best_base + 0.02
                      else "模型不优于基线 ⇒ 只留影子, 不进执行链")
    json.dump(res, open(os.path.join(OUT, "train_report.json"), "w"), ensure_ascii=False, indent=1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--day", default=None)
    a = ap.parse_args()
    if a.train:
        r = train(a.day)
    else:
        r = build(a.day)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
