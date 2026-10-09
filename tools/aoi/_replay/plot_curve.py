# -*- coding: utf-8 -*-
"""把平场归一列剖面画成曲线(每帧一行, 波形), 叠加阈值线与合并峰位置。"""
import sys, os, glob
import numpy as np, cv2
sys.path.insert(0, "/home/ubuntu/zmax/tools/aoi/_replay")
import _loader
M = _loader.load("/home/ubuntu/zmax/tools/aoi/_wip/cam_finger_10082_work_v26.py", "mplot2")
SEQ = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/.hermes/cache/scratch/aoi_frozen"
paths = sorted(glob.glob(os.path.join(SEQ, "*.png"))) or sorted(glob.glob(os.path.join(SEQ, "*.jpg")))
ROWH = 150
profs = []
for p in paths:
    bgr = cv2.imread(p, cv2.IMREAD_COLOR)
    im, met = M.render_judge(bgr); j = met.get("judge") or met
    ky0, ky1 = j["key_row_span"]; x0, x1 = j["strip_x"]
    g = M._v21_luma(bgr); ga = M._v25_norm_luma(g)
    nrm, nk = M._v26_flat_profile(ga, int(ky0), int(ky1), int(x0), int(x1))
    profs.append((os.path.basename(p).replace(".png", "").replace(".jpg", ""), nrm))
W = len(profs[0][1])
allv = np.concatenate([v for _, v in profs])
lo, hi = float(np.min(allv)), float(np.max(allv))
canvas = np.full((ROWH * len(profs), W, 3), 20, np.uint8)
for r, (name, v) in enumerate(profs):
    y0 = r * ROWH
    yy = (ROWH - 20 - (np.clip((v - lo) / max(hi - lo, 1e-6), 0, 1) * (ROWH - 30))).astype(int)
    for x in range(1, W):
        cv2.line(canvas, (x - 1, y0 + yy[x - 1]), (x, y0 + yy[x]), (0, 255, 0), 1)
    cv2.putText(canvas, name, (4, y0 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)
    cv2.line(canvas, (0, y0), (W, y0), (90, 90, 90), 1)
for x in range(0, W, 100):
    cv2.line(canvas, (x, 0), (x, canvas.shape[0]), (45, 45, 45), 1)
cv2.imwrite("/tmp/curve_%s.png" % os.path.basename(SEQ.rstrip("/")), canvas)
# 左端 600-1300 放大
zoom = canvas[:, 560:1360]
cv2.imwrite("/tmp/curve_zoom_%s.png" % os.path.basename(SEQ.rstrip("/")),
            cv2.resize(zoom, (zoom.shape[1] * 2, zoom.shape[0] * 2), interpolation=cv2.INTER_NEAREST))
print("saved /tmp/curve_%s.png %s" % (os.path.basename(SEQ.rstrip("/")), canvas.shape))
