# -*- coding: utf-8 -*-
"""单模块 + 单序列 + 单进程 复放, 记录每帧判据图的 md5 与 n_keys → 供跨进程逐位比较。
用法: python one_view.py <mod> <glob> <rounds> <out.json>"""
import sys, os, glob, json, hashlib
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

mod, pat, rounds, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
M = _loader.load(mod, "mv_" + os.path.basename(mod).replace(".", "_"))
paths = sorted(glob.glob(pat))
recs = []
for rep in range(rounds):
    for p in paths:
        bgr = cv2.imread(p, cv2.IMREAD_COLOR)
        img, met = M.render_judge(bgr)
        j = met.get("judge") or met
        if img is None:
            recs.append(dict(rep=rep, frame=os.path.basename(p), ok=False, md5=None, n=j.get("n_keys")))
        else:
            recs.append(dict(rep=rep, frame=os.path.basename(p), ok=True,
                             md5=hashlib.md5(img.tobytes()).hexdigest(),
                             shape=list(img.shape), n=j.get("n_keys")))
json.dump(recs, open(out, "w"))
print("wrote", out, len(recs), "recs")
