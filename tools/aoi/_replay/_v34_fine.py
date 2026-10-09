# -*- coding: utf-8 -*-
"""Fine sweep of col level -> seg count for one frame + band, to find the 19-split point."""
import sys, os
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader
mod, frame = sys.argv[1], sys.argv[2]
y0, y1 = int(sys.argv[3]), int(sys.argv[4])
M = _loader.load(mod, "fs_" + os.path.basename(mod).replace(".", "_"))
bgr = cv2.imread(frame, cv2.IMREAD_COLOR)
g = M._v21_luma(np.asarray(bgr)); ga = M._v25_norm_luma(g)
lvl = float(M._V21_BRIGHT_LEVEL)
rows = np.arange(y0, y1 + 1)
cx0, cx1 = 0, ga.shape[1]
print("frame %s band %d..%d lvl %.0f" % (os.path.basename(frame), y0, y1, lvl))
for cfk in (0.45, 0.55, 0.65, 0.75):
    for frac in (1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30):
        lc = max(M._V21_BRIGHT_MIN, frac * lvl)
        segs, cf, cl = M._v21_key_cols(ga, rows, cx0, cx1, lc, cf_key_col=cfk, min_key_w=8)
        if not segs:
            continue
        ws = [b - a + 1 for a, b in segs]
        cen = [(a + b) / 2.0 for a, b in segs]
        dd = np.diff(cen); mp = float(np.median(dd)) if dd.size else 0.0
        mark = " <== 19" if len(segs) == 19 else ""
        print("  cfk %.2f frac %.2f lvl %.0f n=%2d pitch=%.1f w=%s%s" % (cfk, frac, lc, len(segs), mp, ws[:24], mark))
