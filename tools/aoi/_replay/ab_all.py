# -*- coding: utf-8 -*-
"""把一个模块在所有扫描图上跑一遍, 记录 (path, md5, n, v26b, err) → json。
用法: python ab_all.py <mod> <out.json>"""
import sys, os, glob, json, hashlib
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

mod, out = sys.argv[1], sys.argv[2]
M = _loader.load(mod, "mab_" + os.path.basename(mod).replace(".", "_"))
CANDS = []
for base in ["/home/ubuntu/.hermes/cache/scratch", "/home/ubuntu/zmax/zmax_data/aoi_v4"]:
    for p in glob.glob(base + "/**/*", recursive=True):
        if p.lower().endswith((".png", ".jpg")) and "build" not in p and "_rend" not in p:
            CANDS.append(p)
CANDS = sorted(set(CANDS))
recs = []
for p in CANDS:
    im = cv2.imread(p, cv2.IMREAD_COLOR)
    if im is None or im.shape[0] != 2048:
        continue
    try:
        o, met = M.render_judge(im)
        j = met.get("judge") or met
    except Exception as e:                                               # noqa: BLE001
        recs.append(dict(p=p, err=repr(e))); continue
    recs.append(dict(p=p, md5=(hashlib.md5(o.tobytes()).hexdigest() if o is not None else None),
                     n=j.get("n_keys"), v26b=bool(j.get("v26b")), err=j.get("err")))
json.dump(recs, open(out, "w"))
print("wrote", out, len(recs))
