# -*- coding: utf-8 -*-
"""Column-profile diagnostic: for a frame, find band via module, then count key segments
vs the column level. usage: _v34_colprof.py <mod.py> <frame> [force_y0 force_y1]"""
import sys, os
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader
mod, frame = sys.argv[1], sys.argv[2]
M = _loader.load(mod, "cp_" + os.path.basename(mod).replace(".", "_"))
bgr = cv2.imread(frame, cv2.IMREAD_COLOR)
g = M._v21_luma(np.asarray(bgr))
ga = M._v25_norm_luma(g)
lvl = float(M._V21_BRIGHT_LEVEL)
hits = M._v21_key_windows(ga, lvl)
if not hits:
    mrows = ga.mean(axis=1); bg = float(np.percentile(mrows, 20))
    edge = min(bg + 25.0, 1.35 * bg)
    cand = [y for y in range(0, ga.shape[0] - M._V21_WIN_H + 1, M._V21_WIN_STEP)
            if float(mrows[y:y + M._V21_WIN_H].mean()) >= edge]
    if cand:
        lvl = float(np.median([M._v21_adaptive_bright(ga[y:y + M._V21_WIN_H, :]) for y in cand]))
        hits = M._v21_key_windows(ga, lvl)
print("frame", os.path.basename(frame), "mean%.1f" % g.mean(), "p50", int(np.median(g)), "lvl_used", lvl)
try:
    thr = cv2.resize(ga, (48, 36), interpolation=cv2.INTER_AREA)
except Exception:
    thr = None
ky0, ky1 = M._v26_pick_band(list(hits), {}, thumb=thr)
print("band", ky0, ky1, "h", ky1-ky0+1)
left, right, rsrc, lsrc, b = M._v21_strip_cols(ga, ky0, ky1)
print("strip", left, right, "minor_rsrc", rsrc[:60])
cx0 = int(max(0, left - M._V21_COL_PAD)); cx1 = int(min(ga.shape[1], (right if right else ga.shape[1]-1) + 1 + M._V21_COL_PAD))
print("cx", cx0, cx1)
rows = np.arange(ky0, ky1 + 1)
for frac in (0.60, 0.70, 0.85, 0.95, 1.05, 1.20, 1.35, 1.50):
    lc = max(M._V21_BRIGHT_MIN, frac * lvl)
    segs, cf, cl = M._v21_key_cols(ga, rows, cx0, cx1, lc)
    ws = [b2 - a2 + 1 for a2, b2 in segs]
    cen = [(a2+b2)/2.0 for a2, b2 in segs]
    dd = np.diff(cen); mp = float(np.median(dd)) if dd.size else 0
    print("  frac %.2f lvl %.0f -> segs=%d  pitch=%.1f  widths=%s" % (frac, lc, len(segs), mp, ws[:24]))
# print the raw cf profile coarsely at the default level
lc = max(M._V21_BRIGHT_MIN, float(M._V21_COL_LEVEL_FRAC) * lvl)
segs, cf, cl = M._v21_key_cols(ga, rows, cx0, cx1, lc)
print("default lvl %.0f -> segs %d" % (lc, len(segs)))
print("cf[::8]=", np.round(np.asarray(cf)[::8], 2).tolist())
