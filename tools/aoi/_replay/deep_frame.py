# -*- coding: utf-8 -*-
"""Deep dump for one frame: full merged segs, outlier flags, rejected, column profile.
usage: python deep_frame.py <mod.py> <frame.png> [--band y0 y1]
"""
import sys, os, glob, json
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

args = list(sys.argv[1:])
band = (1550, 1639)
if "--band" in args:
    i = args.index("--band"); band = (int(args[i + 1]), int(args[i + 2])); del args[i:i + 3]
mod, fp = args[0], args[1]
M = _loader.load(mod, "df_" + os.path.basename(mod).replace(".", "_"))
bgr = cv2.imread(fp, cv2.IMREAD_COLOR)
with M._V25_SEEN_LOCK:
    M._V25_SEEN.clear()
M._V26_BAND_HOLD["band"] = None; M._V26_BAND_HOLD["ts"] = 0.0
img, met = M._v21_render_core(bgr, deskew_deg=0.0, band=band)
j = met.get("judge") or met
for k in ("n_keys", "raw_segs", "merged_segs", "n_merged", "widths_detected", "outlier_flags",
          "outlier_dropped", "kept_segs", "lattice_pitch_px", "lattice_phase_px",
          "v24_claims_span", "v24_rejected_edge_segs", "v24_multi_lo_px", "v24_multi_hi_px",
          "v24_pad_lo_px", "v24_pad_hi_px", "strip_x", "strip_cols", "col_bright_level",
          "centers"):
    print("%-26s %s" % (k, j.get(k)))
# recompute the column profile in the same domain to inspect the right end
src = np.asarray(bgr).astype(np.uint8)
g = M._v21_luma(src)
ga = M._v25_norm_luma(g)
ky0, ky1 = band
rows = np.arange(ky0, ky1 + 1)
cx0, cx1 = j.get("strip_x")
lvl_col = j.get("col_bright_level")
segs, cf, cl = M._v21_key_cols(ga, rows, cx0, cx1, lvl_col)
print("cf len=%d  (x from %d)" % (len(cf), cx0))
np.save("/tmp/cf_%s.npy" % os.path.basename(fp), cf)
prof = ga[rows, :].astype(np.float32).mean(axis=0)
np.save("/tmp/prof_%s.npy" % os.path.basename(fp), prof)
# print cf right half coarsely
idx = np.arange(len(cf))
right = cf > 0.0
print("cf[min..max]=%.3f..%.3f  median=%.3f" % (cf.min(), cf.max(), float(np.median(cf))))
# step through last 800 px
xs = cx0 + np.arange(len(cf))
for a in range(max(0, len(cf) - 900), len(cf), 25):
    print("x=%4d cf=%.3f prof=%.1f" % (xs[a], cf[a], prof[xs[a]]))
