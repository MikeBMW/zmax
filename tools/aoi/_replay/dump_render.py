# -*- coding: utf-8 -*-
"""Render one module over a frame glob in THIS process and save each judge image + meta.
Separate process per (module, view). usage: dump_render.py <mod.py> <glob> <outdir>
"""
import sys, os, glob, json
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

mod, pat, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(outdir, exist_ok=True)
M = _loader.load(mod, "dr_" + os.path.basename(mod).replace(".", "_"))
paths = sorted(glob.glob(pat))
rows = []
for p in paths:
    bgr = cv2.imread(p, cv2.IMREAD_COLOR)
    img, met = M.render_judge(bgr, deskew_deg=0.0)
    j = met.get("judge") or met
    base = os.path.splitext(os.path.basename(p))[0]
    if img is None:
        rows.append(dict(frame=base, ok=False, n=j.get("n_keys")))
    else:
        fp = os.path.join(outdir, base + ".png")
        cv2.imwrite(fp, img)
        rows.append(dict(frame=base, ok=True, file=fp, shape=list(img.shape), n=j.get("n_keys")))
json.dump(rows, open(os.path.join(outdir, "_index.json"), "w"), ensure_ascii=False)
print("rendered %d frames -> %s" % (len(rows), outdir))
