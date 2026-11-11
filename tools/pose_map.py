#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用录下来的位姿出图/建图 —— 俯视轨迹图 + 高度剖面 + 3D 视图 + 覆盖统计。

    ./gui-venv311/bin/python tools/pose_map.py --rec latest
    ./gui-venv311/bin/python tools/pose_map.py --rec latest --with-scene   # 叠加 AR 围栏/料盘 footprint

产出 (落 zmax_data/pose_records/<rec>/):
  map_top.png    俯视 X-Y 轨迹 (按段着色) + 100mm 栅格 + 起点/终点 + 场景 footprint
  map_side.png   X-Z 高度剖面 (看抬升/下降)
  map_3d.png     等轴测 3D 轨迹
  coverage.json  包围盒 / 覆盖栅格(20mm) / 路程 / 段 / 速度统计

口径: 点全部来自 poses.jsonl 的真值(米), 不做平滑不插值; 场景 footprint 只在 --with-scene 时叠加,
并且只画 enabled 的 box, 仅为"看出路径在工位里的位置", 不参与任何判定。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "zmax_data/pose_records")
AR = "http://127.0.0.1:8797"


def load(rec):
    if rec in ("latest", "", None):
        ds = sorted(os.path.basename(p) for p in glob.glob(os.path.join(BASE, "rec_*")) if os.path.isdir(p))
        if not ds:
            raise SystemExit("没有录制")
        rec = ds[-1]
    f = os.path.join(BASE, rec, "poses.jsonl")
    rows = [json.loads(l) for l in open(f) if '"x"' in l]
    if len(rows) < 2:
        raise SystemExit("样本太少")
    return rec, rows


def segments(rows):
    out, cur = [], None
    for i, r in enumerate(rows):
        if r.get("moving"):
            cur = (cur[0], i) if cur else (i, i)
        else:
            if cur and cur[1] > cur[0]:
                out.append(cur)
            cur = None
    if cur and cur[1] > cur[0]:
        out.append(cur)
    return out


def fetch_fences():
    try:
        with urllib.request.urlopen(AR + "/api/fence", timeout=10) as r:
            return (json.loads(r.read().decode()) or {}).get("items") or []
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rec", default="latest")
    ap.add_argument("--with-scene", action="store_true")
    ap.add_argument("--cell", type=float, default=20.0, help="覆盖栅格 mm")
    a = ap.parse_args()

    rec, rows = load(a.rec)
    d = os.path.join(BASE, rec)
    P = [[r["x"] * 1000, r["y"] * 1000, r["z"] * 1000] for r in rows]
    segs = segments(rows)
    xs = [p[0] for p in P]
    ys = [p[1] for p in P]
    zs = [p[2] for p in P]
    L = sum(((P[i + 1][0] - P[i][0]) ** 2 + (P[i + 1][1] - P[i][1]) ** 2 +
             (P[i + 1][2] - P[i][2]) ** 2) ** 0.5 for i in range(len(P) - 1))

    pal = ["#22d3ee", "#f59e0b", "#a78bfa", "#34d399", "#f472b6", "#facc15",
           "#38bdf8", "#fb7185", "#a3e635", "#e879f9"]
    items = fetch_fences() if a.with_scene else []

    # ---------- 俯视 ----------
    fig, ax = plt.subplots(figsize=(9, 8), dpi=140)
    ax.set_facecolor("#0d1117")
    fig.patch.set_facecolor("#0d1117")
    for it in items:
        if it.get("type") != "box" or not it.get("enabled", True):
            continue
        p1, p2 = it.get("p1"), it.get("p2")
        if not (p1 and p2):
            continue
        x0, x1 = sorted([p1[0] * 1000, p2[0] * 1000])
        y0, y1 = sorted([p1[1] * 1000, p2[1] * 1000])
        ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                                   ec="#2f3b4a", lw=0.6, zorder=1))
    for it in items:
        if it.get("type") != "points":
            continue
        pts = it.get("pts") or []
        if len(pts) < 2:
            continue
        ax.plot([p[0] * 1000 for p in pts], [p[1] * 1000 for p in pts],
                color="#31465c", lw=0.7, zorder=1)
    ax.plot(xs, ys, color="#25303d", lw=1.0, zorder=2)
    for n, (i0, i1) in enumerate(segs):
        ax.plot(xs[i0:i1 + 1], ys[i0:i1 + 1], color=pal[n % len(pal)], lw=2.4, zorder=3,
                solid_capstyle="round")
        ax.plot(xs[i0], ys[i0], "o", ms=5, color=pal[n % len(pal)], zorder=4)
        ax.annotate("S%d" % (n + 1), (xs[i0], ys[i0]), textcoords="offset points",
                    xytext=(4, 3), color=pal[n % len(pal)], fontsize=7, zorder=5)
    ax.plot(xs[0], ys[0], "o", ms=11, mfc="none", mec="#22c55e", mew=2, zorder=6)
    ax.plot(xs[-1], ys[-1], "X", ms=11, color="#ef4444", zorder=6)
    ax.annotate("START", (xs[0], ys[0]), textcoords="offset points", xytext=(8, -12),
                color="#22c55e", fontsize=8)
    ax.annotate("END", (xs[-1], ys[-1]), textcoords="offset points", xytext=(8, -12),
                color="#ef4444", fontsize=8)
    ax.set_xlabel("X (mm)", color="#9fb0c0")
    ax.set_ylabel("Y (mm)", color="#9fb0c0")
    ax.grid(True, color="#1c2733", lw=0.6)
    ax.tick_params(colors="#8b9bab")
    for s in ax.spines.values():
        s.set_color("#2a3644")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title("TCP path  %s · %d samples · %.0fmm · %d segs"
                 % (rec, len(rows), L, len(segs)), color="#dbe7f3", fontsize=10)
    fig.tight_layout()
    p_top = os.path.join(d, "map_top.png")
    fig.savefig(p_top, facecolor=fig.get_facecolor())
    plt.close(fig)

    # ---------- 高度剖面 ----------
    fig, ax = plt.subplots(figsize=(9, 3.4), dpi=140)
    ax.set_facecolor("#0d1117")
    fig.patch.set_facecolor("#0d1117")
    tt = [r["ts"] - rows[0]["ts"] for r in rows]
    ax.plot(tt, zs, color="#22d3ee", lw=1.6)
    for n, (i0, i1) in enumerate(segs):
        ax.axvspan(tt[i0], tt[i1], color=pal[n % len(pal)], alpha=0.10)
    ax.set_xlabel("t (s)", color="#9fb0c0")
    ax.set_ylabel("Z (mm)", color="#9fb0c0")
    ax.grid(True, color="#1c2733", lw=0.6)
    ax.tick_params(colors="#8b9bab")
    for s in ax.spines.values():
        s.set_color("#2a3644")
    ax.set_title("Z profile · %.0f..%.0f mm" % (min(zs), max(zs)), color="#dbe7f3", fontsize=10)
    fig.tight_layout()
    p_side = os.path.join(d, "map_side.png")
    fig.savefig(p_side, facecolor=fig.get_facecolor())
    plt.close(fig)

    # ---------- 3D ----------
    fig = plt.figure(figsize=(8.6, 7), dpi=140)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("#0d1117")
    fig.patch.set_facecolor("#0d1117")
    ax.plot(xs, ys, zs, color="#3b4a5c", lw=0.8)
    for n, (i0, i1) in enumerate(segs):
        ax.plot(xs[i0:i1 + 1], ys[i0:i1 + 1], zs[i0:i1 + 1], color=pal[n % len(pal)], lw=2.0)
    ax.scatter([xs[0]], [ys[0]], [zs[0]], color="#22c55e", s=60, marker="o")
    ax.scatter([xs[-1]], [ys[-1]], [zs[-1]], color="#ef4444", s=70, marker="X")
    ax.set_xlabel("X", color="#9fb0c0")
    ax.set_ylabel("Y", color="#9fb0c0")
    ax.set_zlabel("Z", color="#9fb0c0")
    ax.tick_params(colors="#8b9bab", labelsize=7)
    ax.set_title("TCP path 3D (mm)", color="#dbe7f3", fontsize=10)
    try:
        ax.xaxis.pane.set_facecolor((0.05, 0.07, 0.09, 1))
        ax.yaxis.pane.set_facecolor((0.05, 0.07, 0.09, 1))
        ax.zaxis.pane.set_facecolor((0.05, 0.07, 0.09, 1))
    except Exception:
        pass
    ax.view_init(elev=24, azim=-58)
    fig.tight_layout()
    p_3d = os.path.join(d, "map_3d.png")
    fig.savefig(p_3d, facecolor=fig.get_facecolor())
    plt.close(fig)

    # ---------- 统计 ----------
    cell = a.cell
    cells = {(int((p[0] - min(xs)) // cell), int((p[1] - min(ys)) // cell)) for p in P}
    cov = {
        "rec": rec, "n_samples": len(rows), "dur_s": round(rows[-1]["ts"] - rows[0]["ts"], 1),
        "path_mm": round(L, 1), "n_segments": len(segs),
        "bbox_mm": {"x": [round(min(xs), 1), round(max(xs), 1)],
                    "y": [round(min(ys), 1), round(max(ys), 1)],
                    "z": [round(min(zs), 1), round(max(zs), 1)]},
        "span_mm": {"x": round(max(xs) - min(xs), 1), "y": round(max(ys) - min(ys), 1),
                    "z": round(max(zs) - min(zs), 1)},
        "cover_cell_mm": cell, "n_cells": len(cells),
        "cover_area_mm2": round(len(cells) * cell * cell, 0),
        "vmax_mm_s": round(max(r["speed_mm_s"] for r in rows), 1),
        "segments": [{"i": n + 1, "t0": rows[i0]["t"], "t1": rows[i1]["t"],
                      "dur_s": round(rows[i1]["ts"] - rows[i0]["ts"], 2),
                      "from_mm": [round(v, 1) for v in P[i0]], "to_mm": [round(v, 1) for v in P[i1]],
                      "len_mm": round(sum(((P[k + 1][0] - P[k][0]) ** 2 + (P[k + 1][1] - P[k][1]) ** 2 +
                                           (P[k + 1][2] - P[k][2]) ** 2) ** 0.5
                                          for k in range(i0, i1)), 1)}
                     for n, (i0, i1) in enumerate(segs)],
        "files": {"top": p_top, "side": p_side, "3d": p_3d},
        "with_scene": a.with_scene, "n_scene_items": len(items),
    }
    p_cov = os.path.join(d, "coverage.json")
    with open(p_cov, "w") as f:
        json.dump(cov, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: cov[k] for k in ("rec", "n_samples", "dur_s", "path_mm", "n_segments",
                                          "bbox_mm", "span_mm", "n_cells", "cover_area_mm2")},
                     ensure_ascii=False))
    print(p_top)
    print(p_3d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
