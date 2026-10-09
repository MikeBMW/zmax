# -*- coding: utf-8 -*-
"""把某模块的 n_keys 齿列中心画在原图带区上 → 目检哪一根是"多出来的"。
用法: python overlay_teeth.py <mod> <img> <out.png>"""
import sys, os
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

mod, img_p, out = sys.argv[1], sys.argv[2], sys.argv[3]
M = _loader.load(mod, "mov_" + os.path.basename(mod).replace(".", "_"))
bgr = cv2.imread(img_p, cv2.IMREAD_COLOR)
o, met = M.render_judge(bgr); j = met.get("judge") or met
rects = [(int(a), int(b)) for a, b in (j.get("rects") or [])]
ky0, ky1 = j.get("key_row_span") or j.get("key_rows")
x0, x1 = j.get("strip_x") or [0, bgr.shape[1]]
print("n=%s pitch=%s tooth_w=%s band=%s..%s strip=%s..%s v26b=%s lock=%s" % (
    j.get("n_keys"), j.get("lattice_pitch_px"), j.get("width_uniform_px"), ky0, ky1, x0, x1,
    j.get("v26b"), j.get("v26b_lat_lock")))
# 画在原图带区(上下各留 30 行)
Y0 = max(0, int(ky0) - 30); Y1 = min(bgr.shape[0], int(ky1) + 30)
crop = bgr[Y0:Y1, :].copy()
for i, (a, b) in enumerate(rects):
    cv2.line(crop, (int((a + b) / 2), 0), (int((a + b) / 2), crop.shape[0]), (0, 220, 0), 2)
    cv2.putText(crop, str(i + 1), (int((a + b) / 2) - 8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
# 画 merged_segs 边界(红)
for a, b in (j.get("merged_segs") or []):
    cv2.rectangle(crop, (int(a), 2), (int(b), crop.shape[0] - 3), (0, 0, 255), 1)
cv2.imwrite(out, crop)
print("saved", out, crop.shape, "centers:", [int((a + b) / 2) for a, b in rects])
