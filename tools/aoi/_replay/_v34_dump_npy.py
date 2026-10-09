# -*- coding: utf-8 -*-
"""Render one module over one sequence into a .npy stack (one process = one module+view).
usage: _v34_dump_npy.py <mod.py> <seqdir_or_glob> <out.npy> [--gated]"""
import sys, os, glob
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader
args = [a for a in sys.argv[1:]]
gated = "--gated" in args
if gated: args.remove("--gated")
mod, seq, out = args[0], args[1], args[2]
M = _loader.load(mod, "dn_" + os.path.basename(mod).replace(".", "_"))
if os.path.isdir(seq):
    paths = sorted(glob.glob(os.path.join(seq, "*.png"))) or sorted(glob.glob(os.path.join(seq, "*.jpg")))
else:
    paths = sorted(glob.glob(seq))
fn = M.render_judge_gated if gated else M.render_judge
arrs = []
for p in paths:
    bgr = cv2.imread(p, cv2.IMREAD_COLOR)
    img, met = fn(bgr, deskew_deg=0.0)
    arrs.append(img if img is not None else np.zeros((0, 0, 3), np.uint8))
np.save(out, np.array(arrs, dtype=object), allow_pickle=True)
print("saved", out, len(arrs))
