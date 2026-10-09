# -*- coding: utf-8 -*-
"""Force the true band per frame -> pure layer③ (key split) numbers, single-frame isolated.
usage: python force_band.py <mod.py> <dir> [--band y0 y1] [--deskew D]
"""
import sys, os, glob, json
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

args = list(sys.argv[1:])
band = (1550, 1639)
if "--band" in args:
    i = args.index("--band"); band = (int(args[i + 1]), int(args[i + 2])); del args[i:i + 3]
deskew = 0.0
if "--deskew" in args:
    i = args.index("--deskew"); deskew = float(args[i + 1]); del args[i:i + 2]
mod, seq = args[0], args[1]
M = _loader.load(mod, "fb_" + os.path.basename(mod).replace(".", "_"))
paths = sorted(glob.glob(os.path.join(seq, "*.png"))) if os.path.isdir(seq) else sorted(glob.glob(seq))
print("mod=%s frames=%d forced band=%s" % (os.path.basename(mod), len(paths), band))
ns = []
for p in paths:
    bgr = cv2.imread(p, cv2.IMREAD_COLOR)
    with M._V25_SEEN_LOCK:
        M._V25_SEEN.clear()
    M._V26_BAND_HOLD["band"] = None; M._V26_BAND_HOLD["ts"] = 0.0
    img, met = M._v21_render_core(bgr, deskew_deg=deskew, band=band)
    j = met.get("judge") or met
    rects = [(int(a), int(b)) for a, b in (j.get("rects") or [])]
    ws = sorted(set(b - a + 1 for a, b in rects))
    cen = sorted((a + b) / 2.0 for a, b in rects)
    dd = np.diff(cen) if len(cen) > 1 else np.array([])
    pitch = float(np.median(dd)) if dd.size else 0.0
    cl = j.get("v24_claims_span")
    ns.append(j.get("n_keys"))
    print("f=%-9s ok=%-5s n=%-3s wset=%-14s pitch=%-7s cl=%-10s merged=%-40s drop=%s err=%s" % (
        os.path.basename(p), img is not None, j.get("n_keys"), str(ws)[:14], round(pitch, 1),
        str(cl), str(j.get("merged_segs"))[:40], j.get("outlier_dropped"), j.get("err")))
print("n_keys =", ns)
