# -*- coding: utf-8 -*-
"""v34 harness: render one module over one sequence in THIS process; print per-frame n_keys + md5.
usage: _v34_run.py <mod.py> <seqdir_or_glob> [--gated] [--deskew D] [--reset]
"""
import sys, os, glob, hashlib
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

args = list(sys.argv[1:])
gated = "--gated" in args
if gated:
    args.remove("--gated")
deskew = 0.0
if "--deskew" in args:
    i = args.index("--deskew"); deskew = float(args[i + 1]); del args[i:i + 2]
reset = "--reset" in args
if reset:
    args.remove("--reset")
mod, seq = args[0], args[1]
M = _loader.load(mod, "v34_" + os.path.basename(mod).replace(".", "_"))
if os.path.isdir(seq):
    paths = sorted(glob.glob(os.path.join(seq, "*.png"))) or sorted(glob.glob(os.path.join(seq, "*.jpg")))
else:
    paths = sorted(glob.glob(seq))
fn = M.render_judge_gated if gated else M.render_judge
out = []
for p in paths:
    bgr = cv2.imread(p, cv2.IMREAD_COLOR)
    if reset:
        try:
            with M._V25_SEEN_LOCK: M._V25_SEEN.clear()
        except Exception: pass
        try:
            M._V26_BAND_HOLD["band"] = None; M._V26_BAND_HOLD["ts"] = 0.0
        except Exception: pass
    img, met = fn(bgr, deskew_deg=deskew)
    j = met.get("judge") or met
    md5 = hashlib.md5(np.ascontiguousarray(img).tobytes()).hexdigest()[:12] if img is not None else None
    out.append((os.path.basename(p), img is not None, j.get("n_keys"), md5,
                j.get("kept_rows") or j.get("key_row_span"), j.get("lattice_pitch_px")))
print("MOD=%s SEQ=%s n=%d gated=%s" % (os.path.basename(mod), os.path.basename(seq.rstrip('/')), len(paths), gated))
for r in out:
    print("  %-16s ok=%-5s n=%-4s md5=%-12s band=%-14s pitch=%s" % r)
print("NSEQ", [r[2] for r in out])
print("MD5SEQ", [r[3] for r in out])
