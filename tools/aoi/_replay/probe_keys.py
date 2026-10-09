# -*- coding: utf-8 -*-
"""Independent per-frame key-position probe on a fixed band: column mean over rows,
threshold by max*frac, list segments. No judging code involved. """
import sys, os, glob
import numpy as np, cv2

d = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/.hermes/cache/scratch/aoi_l3_frames"
row0, row1 = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 4 else (1560, 1630)
paths = sorted(glob.glob(os.path.join(d, "*.png")))
print("band rows %d..%d" % (row0, row1))
for p in paths:
    g = cv2.imread(p, 0)[row0:row1, :].astype(np.float32).mean(axis=0)
    lvl = g.max() * 0.60
    on = (g >= lvl).astype(np.uint8)
    # segments
    segs = []
    i = 0
    n = len(on)
    while i < n:
        if on[i]:
            j = i
            while j + 1 < n and on[j + 1]:
                j += 1
            if j - i + 1 >= 8:
                segs.append((i, j))
            i = j + 1
        else:
            i += 1
    # keep segments that look like a key row (regular pitch) - just print all
    cen = [(a + b) / 2 for a, b in segs]
    dd = np.diff(cen) if len(cen) > 1 else np.array([])
    print("%-9s nseg=%-3d first=%-12s last=%-12s medpitch=%s" % (
        os.path.basename(p), len(segs),
        str(segs[0] if segs else None), str(segs[-1] if segs else None),
        round(float(np.median(dd)), 1) if dd.size else None))
