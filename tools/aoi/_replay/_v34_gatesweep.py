# -*- coding: utf-8 -*-
"""Sweep (col_level_frac, cf_key_col, min_key_w) -> segment count, using the module's own funcs.
usage: _v34_gatesweep.py <mod.py> <frame> [y0 y1]"""
import sys, os
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader
mod, frame = sys.argv[1], sys.argv[2]
force = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else None
M = _loader.load(mod, "gs_" + os.path.basename(mod).replace(".", "_"))
bgr = cv2.imread(frame, cv2.IMREAD_COLOR)
g = M._v21_luma(np.asarray(bgr)); ga = M._v25_norm_luma(g)
lvl = float(M._V21_BRIGHT_LEVEL)
hits = M._v21_key_windows(ga, lvl)
if force:
    ky0, ky1 = force
else:
    ky0, ky1 = M._v26_pick_band(list(hits), {}, thumb=None)
left, right, *_ = M._v21_strip_cols(ga, ky0, ky1)
if right is None: right = ga.shape[1] - 1
cx0 = int(max(0, left - M._V21_COL_PAD)); cx1 = int(min(ga.shape[1], right + 1 + M._V21_COL_PAD))
rows = np.arange(ky0, ky1 + 1)
print("frame", os.path.basename(frame), "band", ky0, ky1, "cx", cx0, cx1, "lvl", lvl)
print("  frac  cfk  mkw  nsegs nkeys  pitch  widths")
for frac in (0.75, 0.85, 0.95, 1.00, 1.10):
    for cfk in (0.50, 0.60, 0.70, 0.80, 0.90):
        for mkw in (8, 12):
            lc = max(M._V21_BRIGHT_MIN, frac * lvl)
            segs, cf, cl = M._v21_key_cols(ga, rows, cx0, cx1, lc, cf_key_col=cfk, min_key_w=mkw)
            if not segs:
                continue
            ws = [b - a + 1 for a, b in segs]
            cen = [(a + b) / 2.0 for a, b in segs]
            dd = np.diff(cen); mp = float(np.median(dd)) if dd.size else 0.0
            if len(segs) >= 12:
                print("  %.2f %.2f %3d  %3d   %3d  %5.1f  %s" % (frac, cfk, mkw, len(segs), len(segs), mp, ws[:22]))
