# -*- coding: utf-8 -*-
"""probe: render one frame with a module, print selected meta (v32/v34 diagnostics)."""
import sys, os
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader
mod, frame = sys.argv[1], sys.argv[2]
M = _loader.load(mod, "probe_" + os.path.basename(mod).replace(".", "_"))
bgr = cv2.imread(frame, cv2.IMREAD_COLOR)
img, met = M.render_judge(bgr, deskew_deg=0.0)
j = met.get("judge") or met
keys = ["n_keys", "key_rows", "kept_rows", "key_row_span", "band_pick", "band_hold",
        "lattice_pitch_px", "v24_claims_span", "lattice_note", "merged_segs",
        "v32_autocorr", "v32_twopass", "v32_filt", "v32_slot_filter",
        "why", "err", "bright_level_used"]
print("FRAME", os.path.basename(frame))
for k in keys:
    print("  %-18s %s" % (k, j.get(k)))
print("  ok", img is not None, "shape", None if img is None else img.shape)
# raw anchor info (module private)
try:
    g = M._v25_norm_luma(M._v21_luma(np.asarray(bgr)))
    print("  _v32_anchor_band ->", M._v32_anchor_band(g))
    # raw pass1 band rects
    hs = M._v21_key_windows(g, M._V21_BRIGHT_LEVEL)
    print("  key_windows n=", len(hs), hs[:6])
except Exception as e:
    print("  probe error", e)
