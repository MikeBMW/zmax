# -*- coding: utf-8 -*-
"""把平场归一列剖面画成热力图(每帧一行), 并叠加峰位置 —— 直接看"齿"在哪、哪里在翻。"""
import sys, os, glob
import numpy as np, cv2
sys.path.insert(0, "/home/ubuntu/zmax/tools/aoi/_replay")
import _loader
M = _loader.load("/home/ubuntu/zmax/tools/aoi/_wip/cam_finger_10082_work_v26.py", "mplot")
SEQ = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/.hermes/cache/scratch/aoi_frozen"
paths = sorted(glob.glob(os.path.join(SEQ, "*.png"))) or sorted(glob.glob(os.path.join(SEQ, "*.jpg")))
rows = []
profs = []
for p in paths:
    bgr = cv2.imread(p, cv2.IMREAD_COLOR)
    im, met = M.render_judge(bgr); j = met.get("judge") or met
    ky0, ky1 = j["key_row_span"]; x0, x1 = j["strip_x"]
    g = M._v21_luma(bgr); ga = M._v25_norm_luma(g)
    nrm, nk = M._v26_flat_profile(ga, int(ky0), int(ky1), int(x0), int(x1))
    profs.append((os.path.basename(p), nrm))
# 归一化到 0..255 供显示
allv = np.concatenate([v for _, v in profs])
lo, hi = float(np.percentile(allv, 2)), float(np.percentile(allv, 98))
H = 40
canvas = np.zeros((len(profs) * (H + 12), len(profs[0][1]), 3), np.uint8)
for r, (name, v) in enumerate(profs):
    disp = np.clip((v - lo) / max(hi - lo, 1e-6), 0, 1)
    strip = np.repeat((disp[None, :] * 255).astype(np.uint8), H, axis=0)
    y = r * (H + 12)
    canvas[y:y + H] = cv2.cvtColor(strip, cv2.COLOR_GRAY2BGR)
    cv2.putText(canvas, name, (4, y + H - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
# 每 250px 一条竖线刻度
for x in range(0, canvas.shape[1], 250):
    cv2.line(canvas, (x, 0), (x, canvas.shape[0]), (60, 60, 60), 1)
    cv2.putText(canvas, str(x), (x + 2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (120, 220, 120), 1)
out = "/tmp/flat_profile_%s.png" % os.path.basename(SEQ.rstrip("/"))
cv2.imwrite(out, canvas)
print("saved", out, canvas.shape)
