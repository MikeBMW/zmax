# -*- coding: utf-8 -*-
"""v31 渲染门离线验收: 逐帧状态 + 同帧重复输出逐位一致 + 抑制态横幅。
用法: python test_v31_gate.py <mod.py> <img1> [img2 ...]"""
import sys, os, hashlib
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

mod = sys.argv[1]
M = _loader.load(mod, "mv31")
imgs = sys.argv[2:]
for p in imgs:
    bgr = cv2.imread(p, cv2.IMREAD_COLOR)
    if bgr is None:
        print("skip", p); continue
    md5s = []
    for rep in range(3):
        out, met = M.render_judge_gated(bgr, deskew_deg=0.0)
        j = met.get("gate") or {}
        h = hashlib.md5(out.tobytes()).hexdigest()[:12] if out is not None else None
        md5s.append(h)
        if rep == 0:
            print("== %s" % os.path.basename(p))
            print("   v30 n_keys=%s pitch=%s band=%s" % (
                met.get("n_keys"), met.get("lattice_pitch_px"),
                met.get("key_rows") or met.get("kept_rows")))
            print("   GATE state=%s ok=%s n=%s pitch=%s band=%s geo_ok=%s scene_same=%s" % (
                j.get("state"), j.get("ok"), j.get("n_keys"), j.get("pitch"), j.get("band"),
                j.get("geo_ok"), j.get("scene_same")))
            print("   banner=%r" % (met.get("gate_banner", "")))
            print("   boxes=%s" % (met.get("gate_boxes")))
    print("   md5 x3 = %s  ALL_SAME=%s" % (md5s, len(set(md5s)) == 1))
