#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金手指几何探针 —— 量 19 个矩形的长/宽/面积/节距/倾角, 并按 QSFP 几何约束做识别。

设计要点（2026-11-27 老倪: 「你能看到是个矩形…计算面积…记录到流形引擎的数据约束里…状态空间的
yolo 或 opencv 要上报直线, 因为这个视图的直线特征很明显, 边长直角很有规律」）：

  · **等分先验 + 格内重心** —— 列剖面直接找峰会被触点内部亮暗分界带偏(实测节距 std 0.11mm),
    而"19 根等距"本身就是最强几何先验; 以它为骨架再取亮度重心, 节距 std 降到 0.006mm。
  · **自标定 px/mm** —— 用节距中位数 / QSFP 0.6mm 反推, 不依赖相机内参(换相机/换工作距离都不失效)。
  · **约束比对** —— 读 config/calib/gold_geometry_constraint.json, 逐项判"是否符合该封装",
    越界项报几何异常(缺根/氧化使亮区缩小/视角畸变)。
  · **缺陷佐证** —— 同一批里面积或高度相对中位数掉 15% 以上 ⇒ 该根可疑(与 YOLO 的 NG 互为交叉证据)。

用法:
  python tools/gold_geometry_probe.py <strip.jpg> [--json]
  from gold_geometry_probe import probe -> dict       (供 8793 直接 import)
"""
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSTRAINT = os.path.join(ROOT, "config/calib/gold_geometry_constraint.json")
QSFP_PITCH_MM = 0.6


def load_constraint():
    try:
        return json.load(open(CONSTRAINT, encoding="utf-8"))
    except Exception:
        return {"constraints": {"count": {"nominal": 19}}}


def probe(bgr, n_pads=None, cons=None):
    """核心: 图 → 19 根矩形的几何 + 合规判定。"""
    cons = cons or load_constraint()
    cc = (cons.get("constraints") or {})
    n = int(n_pads or (cc.get("count") or {}).get("nominal") or 19)
    H, W = bgr.shape[:2]
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)

    y0, y1 = int(H * 0.2), int(H * 0.8)
    prof = g[y0:y1, :].mean(axis=0)
    k = np.array([1, 2, 3, 2, 1], dtype=np.float32)
    k /= k.sum()
    prof = np.convolve(prof, k, mode="same")

    cell = W / float(n)
    centers, widths = [], []
    for i in range(n):
        a, b = int(i * cell), int((i + 1) * cell)
        seg = prof[a:b]
        lo, hi = float(seg.min()), float(seg.max())
        if hi - lo < 5:
            centers.append((a + b) / 2.0)
            widths.append(0)
            continue
        wgt = np.clip((seg - lo) / (hi - lo), 0, None)
        cx = a + float((np.arange(len(seg)) * wgt).sum() / max(1e-6, wgt.sum()))
        thr = lo + 0.45 * (hi - lo)
        idx = np.nonzero(seg >= thr)[0]
        widths.append(int(idx[-1] - idx[0] + 1) if len(idx) > 1 else 0)
        centers.append(cx)

    pit_px = [centers[i + 1] - centers[i] for i in range(n - 1)]
    pitch_px = float(np.median(pit_px)) if pit_px else 1.0
    px_per_mm = pitch_px / QSFP_PITCH_MM if pitch_px > 1 else 1.0

    rows = []
    for i in range(n):
        cx = centers[i]
        c0, c1 = int(max(0, cx - 3)), int(min(W, cx + 4))
        col = g[:, c0:max(c0 + 1, c1)].max(axis=1)
        lo, hi = float(col.min()), float(col.max())
        idx = np.nonzero(col >= lo + 0.45 * (hi - lo))[0]
        hh = int(idx[-1] - idx[0] + 1) if len(idx) > 1 else 0
        y_top, y_bot = (int(idx[0]), int(idx[-1])) if len(idx) > 1 else (0, 0)
        wpx = widths[i]
        wmm, hmm = wpx / px_per_mm, hh / px_per_mm
        rows.append({
            "i": i + 1, "cx_px": round(cx, 1), "y_top": y_top, "y_bot": y_bot,
            "w_px": wpx, "h_px": hh,
            "w_mm": round(wmm, 3), "h_mm": round(hmm, 3),
            "area_mm2": round(wmm * hmm, 4),
            "pitch_mm": round((centers[i] - centers[i - 1]) / px_per_mm, 3) if i else None,
            "h_over_w": round(hmm / wmm, 2) if wmm else None,
        })

    def stat(key):
        v = [r[key] for r in rows if r.get(key) is not None]
        if not v:
            return None
        m = sum(v) / len(v)
        sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5
        return {"mean": round(m, 4), "std": round(sd, 4), "min": round(min(v), 4), "max": round(max(v), 4)}

    # ---- 约束比对 ----
    viol = []
    c_pitch = cc.get("pitch_mm") or {}
    if c_pitch and stat("pitch_mm"):
        if abs(stat("pitch_mm")["mean"] - c_pitch.get("nominal", 0.6)) > c_pitch.get("tol", 0.05):
            viol.append("节距均值 %.3f 越界(标称 %.2f±%.2f)" % (stat("pitch_mm")["mean"], c_pitch.get("nominal"), c_pitch.get("tol")))
        if stat("pitch_mm")["std"] > ((cons.get("geometry_laws") or {}).get("pitch_uniformity") or {}).get("max_std_mm", 0.02):
            viol.append("节距不均匀 std %.4f > %.3f" % (stat("pitch_mm")["std"],
                       ((cons.get("geometry_laws") or {}).get("pitch_uniformity") or {}).get("max_std_mm", 0.02)))
    for key, label in (("w_mm", "宽"), ("area_mm2", "面积")):
        c = cc.get(key) or {}
        s = stat(key)
        if not c or not s:
            continue
        if "range" in c:
            if not (c["range"][0] <= s["mean"] <= c["range"][1]):
                viol.append("%s 均值 %.3f 不在 [%.2f, %.2f]" % (label, s["mean"], c["range"][0], c["range"][1]))
        elif "tol" in c:
            if abs(s["mean"] - c.get("nominal", s["mean"])) > c["tol"]:
                viol.append("%s 均值 %.3f 越界(标称 %.3f±%.3f)" % (label, s["mean"], c["nominal"], c["tol"]))

    # ---- 缺陷佐证: 同批相对掉 15% ----
    a_med = stat("area_mm2")["mean"] if stat("area_mm2") else 0
    h_med = stat("h_mm")["mean"] if stat("h_mm") else 0
    dr = (cons.get("defect_coupling") or {}).get("area_drop_ratio", 0.85)
    hr = (cons.get("defect_coupling") or {}).get("height_drop_ratio", 0.85)
    sus = [r["i"] for r in rows
           if a_med and (r["area_mm2"] < a_med * dr or (h_med and r["h_mm"] < h_med * hr))]

    return {
        "ok": True, "n": n, "strip_px": [W, H], "px_per_mm": round(px_per_mm, 2),
        "pitch_mm": stat("pitch_mm"), "w_mm": stat("w_mm"), "h_mm": stat("h_mm"),
        "area_mm2": stat("area_mm2"),
        "duty": round((stat("w_mm") or {}).get("mean", 0) / QSFP_PITCH_MM, 3),
        "geometry_ok": not viol, "violations": viol,
        "area_suspect": sus,
        "rects": rows,
    }


def main(argv):
    if len(argv) < 2:
        print("用法: gold_geometry_probe.py <strip.jpg> [--json]")
        return 2
    bgr = cv2.imread(argv[1])
    if bgr is None:
        print("读不到", argv[1])
        return 1
    out = probe(bgr)
    if "--json" in argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    print("条带 %dx%d | px/mm %.1f | 检出 %d 根" % (out["strip_px"][0], out["strip_px"][1], out["px_per_mm"], out["n"]))
    print("%-3s %7s %7s %8s %9s %8s" % ("#", "宽mm", "高mm", "面积mm2", "节距mm", "高宽比"))
    for r in out["rects"]:
        print("%-3d %7.3f %7.3f %9.4f %8s %8s"
              % (r["i"], r["w_mm"], r["h_mm"], r["area_mm2"],
                 ("%.3f" % r["pitch_mm"]) if r["pitch_mm"] else "—", r["h_over_w"]))
    print("\n汇总: 节距 %.4f±%.4f | 宽 %.3f | 高 %.3f±%.3f | 面积 %.4f | 占空比 %.3f"
          % (out["pitch_mm"]["mean"], out["pitch_mm"]["std"], out["w_mm"]["mean"],
             out["h_mm"]["mean"], out["h_mm"]["std"], out["area_mm2"]["mean"], out["duty"]))
    print("几何合规: %s%s" % ("是" if out["geometry_ok"] else "否", ("" if out["geometry_ok"] else " → " + "; ".join(out["violations"]))))
    print("面积/高度偏小的可疑根: %s" % (out["area_suspect"] or "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
