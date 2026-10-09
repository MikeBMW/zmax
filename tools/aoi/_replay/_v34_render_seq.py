# -*- coding: utf-8 -*-
"""Render a whole sequence with render_judge_gated (stateful) and save selected frames.
usage: _v34_render_seq.py <mod.py> <seqdir> <outprefix> [indices...]"""
import sys, os, glob
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader
mod, seq, pre = sys.argv[1], sys.argv[2], sys.argv[3]
idxs = [int(x) for x in sys.argv[4:]] or [len(glob.glob(seq + "/*.png")) - 1]
M = _loader.load(mod, "rs_" + os.path.basename(mod).replace(".", "_"))
paths = sorted(glob.glob(seq + "/*.png")) or sorted(glob.glob(seq + "/*.jpg"))
for i, p in enumerate(paths):
    bgr = cv2.imread(p, cv2.IMREAD_COLOR)
    img, met = M.render_judge_gated(bgr, deskew_deg=0.0)
    j = met.get("judge") or met
    g = met.get("gate") or {}
    print("f%-9s n=%-4s gate=%-10s state=%s" % (os.path.basename(p), j.get("n_keys"), g.get("state"), j.get("state")))
    if i in idxs and img is not None:
        fp = "%s_%02d.png" % (pre, i)
        cv2.imwrite(fp, img)
        print("   wrote", fp, img.shape)
