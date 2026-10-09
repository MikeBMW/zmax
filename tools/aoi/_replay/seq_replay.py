# -*- coding: utf-8 -*-
"""sequence replay (no per-frame reset) + full meta dump. One process = one view.

usage: python seq_replay.py <mod.py> <frame_glob_or_dir> [--deskew DEG] [--reset]
prints per-frame: n_keys, wset, pitch, band, band_pick, claims_span, merged, mask_bbox, err
"""
import sys, os, glob, json
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

args = [a for a in sys.argv[1:]]
reset = "--reset" in args
if reset:
    args.remove("--reset")
deskew = 0.0
if "--deskew" in args:
    i = args.index("--deskew")
    deskew = float(args[i + 1])
    del args[i:i + 2]
mod, seq = args[0], args[1]

M = _loader.load(mod, "seq_" + os.path.basename(mod).replace(".", "_"))
if os.path.isdir(seq):
    paths = sorted(glob.glob(os.path.join(seq, "*.png")))
    if not paths:
        paths = sorted(glob.glob(os.path.join(seq, "*.jpg")))
else:
    paths = sorted(glob.glob(seq))

print("mod=%s frames=%d reset=%s deskew=%s" % (os.path.basename(mod), len(paths), reset, deskew))
rows = []
prev_thumb = None
for p in paths:
    bgr = cv2.imread(p, cv2.IMREAD_COLOR)
    if reset:
        with M._V25_SEEN_LOCK:
            M._V25_SEEN.clear()
        M._V26_BAND_HOLD["band"] = None
        M._V26_BAND_HOLD["ts"] = 0.0
    img, met = M.render_judge(bgr, deskew_deg=deskew)
    j = met.get("judge") or met
    rects = [(int(a), int(b)) for a, b in (j.get("rects") or [])]
    ws = sorted(set(b - a + 1 for a, b in rects))
    cen = sorted((a + b) / 2.0 for a, b in rects)
    dd = np.diff(cen) if len(cen) > 1 else np.array([])
    pitch = float(np.median(dd)) if dd.size else 0.0
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    thumb = cv2.resize(g, (32, 24)).astype(np.float32)
    td = None if prev_thumb is None else float(np.abs(thumb - prev_thumb).mean())
    prev_thumb = thumb
    cl = j.get("v24_claims_span")
    extra = missing = None
    if cl:
        slots = set(range(int(cl[0]), int(cl[1]) + 1)); truth = set(range(0, 19))
        extra = sorted(slots - truth); missing = sorted(truth - slots)
    rec = dict(frame=os.path.basename(p), ok=img is not None, n=j.get("n_keys"),
               wset=ws, pitch=round(pitch, 1),
               band=j.get("key_row_span"), band_pick=j.get("band_pick"),
               band_hold=j.get("band_hold"), strip_x=j.get("strip_x"),
               lat_pitch=j.get("lattice_pitch_px"), cl=cl, extra=extra, missing=missing,
               merged=j.get("merged_segs"), outl_drop=j.get("outlier_dropped"),
               rejected=j.get("v24_rejected_edge_segs"), bbox=j.get("mask_bbox"),
               thumb_diff=(round(td, 2) if td is not None else None), err=j.get("err"))
    rows.append(rec)
    print("f=%-9s ok=%-5s n=%-3s wset=%-14s pitch=%-7s band=%-14s cl=%-10s thumb_d=%s err=%s" % (
        rec["frame"], rec["ok"], rec["n"], str(ws)[:14], rec["pitch"], str(rec["band"]),
        str(cl), rec["thumb_diff"], rec["err"]))
    if rec["band_pick"]:
        bp = rec["band_pick"]
        print("      band_pick: clusters=%s hits=%s cluster_hits=%s band=%s cand=%s" % (
            bp.get("clusters"), bp.get("hits"), bp.get("cluster_hits"), bp.get("band"), bp.get("cand")))
print("n_keys seq =", [r["n"] for r in rows])
js = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_last_seq.json")
json.dump(rows, open(js, "w"), ensure_ascii=False)
print("wrote", js)
