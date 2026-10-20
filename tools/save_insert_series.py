#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""save_insert_series.py — 把 watch_insert 打出来的采样表存成 jsonl + 给出时序结论

输入: 采样表文本 (每行: 时刻 x y z 轴向/侧向 检出框 画面差)
输出: zmax_data/evidence/insertion_series_<tag>.jsonl  + 终端摘要 (只算, 不编)
"""
from __future__ import annotations

import json
import os
import re
import sys

REPO = "/home/ubuntu/zmax"
OUT = os.path.join(REPO, "zmax_data", "evidence")

# 13:48:18   815.6   228.7   277.7   -6.4 /   2.4   检出 c=( 274,  44)  34x 88     41.0%
LINE = re.compile(
    r"^(?P<time>\d\d:\d\d:\d\d)\s+"
    r"(?P<x>-?[\d.]+)\s+(?P<y>-?[\d.]+)\s+(?P<z>-?[\d.]+)\s+"
    r"(?P<ax>-?[\d.]+)\s*/\s*(?P<lat>-?[\d.]+)\s+"
    r"(?P<det>检出|未检出)"
    r"(?:\s+c=\(\s*(?P<cx>-?[\d.]+),\s*(?P<cy>-?[\d.]+)\)\s+(?P<bw>[\d.]+)x\s*(?P<bh>[\d.]+))?")


def main(path, tag):
    rows = []
    for ln in open(path, encoding="utf-8"):
        m = LINE.match(ln.strip())
        if not m:
            continue
        d = m.groupdict()
        r = {"t": d["time"],
             "x_mm": float(d["x"]), "y_mm": float(d["y"]), "z_mm": float(d["z"]),
             "axial_N": float(d["ax"]), "lateral_N": float(d["lat"]),
             "det": d["det"] == "检出"}
        if d["cx"] is not None:
            r.update({"cx": float(d["cx"]), "cy": float(d["cy"]),
                      "bw": float(d["bw"]), "bh": float(d["bh"])})
        rows.append(r)
    if not rows:
        print("没解析到任何行 —— 采样表格式变了?"); return 1
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "insertion_series_%s.jsonl" % tag)
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 摘要 (全部从这份序列算)
    xs = [r["x_mm"] for r in rows]
    zs = [r["z_mm"] for r in rows]
    ax = [r["axial_N"] for r in rows]
    lat = [r["lateral_N"] for r in rows]
    i_peak = max(range(len(rows)), key=lambda i: abs(ax[i]))
    i_lat = max(range(len(rows)), key=lambda i: lat[i])
    # 静止段: 相邻三点 x/y/z 变化 <0.5mm 视作保持
    holds, cur = [], None
    for i, r in enumerate(rows):
        if cur and abs(r["x_mm"] - cur["x_mm"]) < 0.05 and abs(r["z_mm"] - cur["z_mm"]) < 0.05:
            cur["n"] += 1; cur["t1"] = r["t"]
        else:
            if cur and cur["n"] >= 5:
                holds.append(cur)
            cur = {"t0": r["t"], "t1": r["t"], "n": 1, "x_mm": r["x_mm"], "z_mm": r["z_mm"],
                   "ax_mean": r["axial_N"], "n_ax": 1}
    if cur and cur["n"] >= 5:
        holds.append(cur)
    print("样本 %d 条 · %s → %s" % (len(rows), rows[0]["t"], rows[-1]["t"]))
    print("X 行程 %.1f → %.1f mm (跨度 %.1f) · Z %.1f~%.1f mm (跨度 %.1f)"
          % (xs[0], xs[-1], max(xs) - min(xs), min(zs), max(zs), max(zs) - min(zs)))
    print("轴向力 %+.1f ~ %+.1f N (峰值在 %s) · 侧向力 %.1f ~ %.1f N (峰值在 %s)"
          % (min(ax), max(ax), rows[i_peak]["t"], min(lat), max(lat), rows[i_lat]["t"]))
    print("保持段(≥5 样本几乎不动):")
    for h in holds:
        print("   %s→%s  %d 样本  x=%.1f z=%.1f mm" % (h["t0"], h["t1"], h["n"], h["x_mm"], h["z_mm"]))
    print("落盘:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "20261020_1348"))
