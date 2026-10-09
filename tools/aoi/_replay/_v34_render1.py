# -*- coding: utf-8 -*-
"""Render a frame with a module (optionally gated) and save the PNG for inspection."""
import sys, os
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader
mod, frame, out = sys.argv[1], sys.argv[2], sys.argv[3]
gated = "--gated" in sys.argv
M = _loader.load(mod, "rn_" + os.path.basename(mod).replace(".", "_"))
bgr = cv2.imread(frame, cv2.IMREAD_COLOR)
fn = M.render_judge_gated if gated else M.render_judge
img, met = fn(bgr, deskew_deg=0.0)
j = met.get("judge") or met
print("n_keys", j.get("n_keys"), "band", j.get("kept_rows") or j.get("key_row_span"),
      "pitch", j.get("lattice_pitch_px"), "gate", j.get("gate"), "state", j.get("state"),
      "img", None if img is None else img.shape)
if img is not None:
    cv2.imwrite(out, img)
    print("wrote", out)
