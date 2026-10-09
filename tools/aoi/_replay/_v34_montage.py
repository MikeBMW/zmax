# -*- coding: utf-8 -*-
import os, glob, sys
import numpy as np, cv2
S = "/home/ubuntu/.hermes/cache/scratch"
seq = sys.argv[1] if len(sys.argv) > 1 else S + "/aoi_live_frames"
fs = sorted(glob.glob(os.path.join(seq, "*.png")) or glob.glob(os.path.join(seq, "*.jpg")))
print("seq", seq, "n", len(fs))
tiles = []
for f in fs:
    im = cv2.imread(f)
    h, w = im.shape[:2]
    t = cv2.resize(im, (w // 4, h // 4))
    cv2.putText(t, os.path.basename(f), (5, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    tiles.append(t)
rows = [np.hstack(tiles[i:i+3]) for i in range(0, len(tiles), 3)]
Wm = max(r.shape[1] for r in rows)
rows = [np.pad(r, ((0, 0), (0, Wm - r.shape[1]), (0, 0))) for r in rows]
mont = np.vstack(rows)
out = S + "/_v34_montage.jpg"
cv2.imwrite(out, mont, [cv2.IMWRITE_JPEG_QUALITY, 78])
print("montage", mont.shape, out)
for idx in range(len(fs)):
    if idx % 1 == 0:
        g = cv2.cvtColor(cv2.imread(fs[idx]), cv2.COLOR_BGR2GRAY)
        mr = g.mean(axis=1)
        # top-3 row bands
        o = np.argsort(mr)[::-1]
        print(os.path.basename(fs[idx]), "shape", g.shape, "mean%.1f" % g.mean(),
              "p50", int(np.median(g)), "toprows", sorted(o[:3].tolist()))
