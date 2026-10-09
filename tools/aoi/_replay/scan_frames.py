# -*- coding: utf-8 -*-
"""扫描所有可用帧: 打印每帧 n_keys/pitch/v26b/merged_segs[0]/mask_bbox/key_rows —— 找出
"前视(节距47 / merged_segs 含[586,773] w=188 / 掩膜停1607)" 与 "点2" 两组真源。"""
import sys, glob, os, json
import numpy as np, cv2
sys.path.insert(0, "/home/ubuntu/zmax/tools/aoi/_replay")
import _loader

M = _loader.load("/home/ubuntu/zmax/tools/aoi/_wip/cam_finger_10082_work_v26.py", "mscan")

CANDS = []
for base in ["/home/ubuntu/.hermes/cache/scratch", "/home/ubuntu/zmax/zmax_data/aoi_v4",
             "/home/ubuntu/zmax/zmax_data/aoi_v4/snapshots"]:
    for p in glob.glob(base + "/**/*", recursive=True):
        if p.lower().endswith((".png", ".jpg")) and "build" not in p and "_rend" not in p:
            CANDS.append(p)
CANDS = sorted(set(CANDS))
print("scan %d images" % len(CANDS))
for p in CANDS:
    im = cv2.imread(p, cv2.IMREAD_COLOR)
    if im is None or im.shape[0] != 2048:
        continue
    try:
        o, met = M.render_judge(im)
        j = met.get("judge") or met
    except Exception as e:
        print("%-70s ERR %s" % (p[-68:], e)); continue
    ms = j.get("merged_segs") or []
    bbox = j.get("mask_bbox")
    print("%-58s n=%-3s pitch=%-5s v26b=%-5s ms0=%-14s bbox=%s kr=%s w%d" % (
        p.replace("/home/ubuntu/.hermes/cache/scratch/", "sc/").replace("/home/ubuntu/zmax/zmax_data/aoi_v4/", "av/")[-58:],
        j.get("n_keys"), j.get("lattice_pitch_px"), j.get("v26b"),
        str(ms[0] if ms else None), bbox, j.get("key_rows"), j.get("width_uniform_px") or 0))
