# -*- coding: utf-8 -*-
"""离线跑 v30 render_judge, dump judge meta(kept_rows/rects/n_keys/band_pick...) + 存判据图。
用法: python rend30.py <mod.py> <origin.png|glob> [outdir]"""
import sys, os, glob, json
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

mod = sys.argv[1]
pat = sys.argv[2]
outdir = sys.argv[3] if len(sys.argv) > 3 else "."
os.makedirs(outdir, exist_ok=True)
M = _loader.load(mod, "mv_" + os.path.basename(mod).replace(".", "_"))
paths = sorted(glob.glob(pat))
for p in paths:
    bgr = cv2.imread(p, cv2.IMREAD_COLOR)
    if bgr is None:
        continue
    try:
        img, met = M.render_judge(bgr)
    except Exception as e:
        print(p, "EXC", repr(e)); continue
    j = met.get("judge") or met
    rects = [(int(a), int(b)) for a, b in (j.get("rects") or [])]
    cen = sorted((a + b) / 2.0 for a, b in rects)
    dd = np.diff(cen) if len(cen) > 1 else np.array([])
    print("== %s  n_keys=%s ok=%s state=%s" % (os.path.basename(p), j.get("n_keys"), img is not None, j.get("state")))
    for k in ("kept_rows", "key_row_span", "key_rows", "x_trim", "band_pick", "band_hold",
              "width_uniform_px", "lattice_pitch_px", "attempt", "deskew_deg", "sat_before"):
        if k in j:
            print("   %-18s = %s" % (k, str(j[k])[:200]))
    print("   widths:", [b - a + 1 for a, b in rects])
    print("   centers:", [int(c) for c in cen], "pitch=%.1f" % (float(np.median(dd)) if dd.size else 0))
    if img is not None:
        cv2.imwrite(os.path.join(outdir, "rend_" + os.path.basename(p)), img)
