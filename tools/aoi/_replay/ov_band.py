# -*- coding: utf-8 -*-
"""抓一帧原始图, 离线跑 v30 render_judge, 把 kept_rows 带 + rects 中心画在原图上 → 目检。"""
import sys, os, urllib.request, json
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

BASE = "http://192.168.23.23:10082"
UA = {"User-Agent": "zmax-probe"}
out_png = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/.hermes/cache/scratch/aoi_cap/ov.png"
mod = sys.argv[2] if len(sys.argv) > 2 else "/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v30.py"

# fresh grab (memory frame), no disk write
r = urllib.request.Request(BASE + "/picture?kind=origin&grab=1", headers=UA)
with urllib.request.urlopen(r, timeout=20) as x:
    b = x.read()
bgr = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
print("grabbed", bgr.shape)
# get live angle
try:
    rr = urllib.request.Request(BASE + "/region", headers=UA)
    with urllib.request.urlopen(rr, timeout=10) as x:
        reg = json.loads(x.read())
    ang = (reg.get("region") or {}).get("angle")
except Exception:
    ang = None
print("live region angle:", ang)

M = _loader.load(mod, "mov")
img, met = M.render_judge(bgr, deskew_deg=float(ang or 0.0))
j = met.get("judge") or met
rects = [(int(a), int(b)) for a, b in (j.get("rects") or [])]
kr = j.get("kept_rows") or j.get("key_row_span")
print("offline n_keys=%s kept_rows=%s band_pick=%s" % (j.get("n_keys"), kr, j.get("band_pick")))

vis = bgr.copy()
if kr:
    cv2.rectangle(vis, (0, int(kr[0])), (vis.shape[1] - 1, int(kr[1])), (0, 0, 255), 3)
for i, (a, b) in enumerate(rects):
    cx = int((a + b) / 2)
    cv2.line(vis, (cx, int(kr[0]) - 10 if kr else 0), (cx, (int(kr[1]) + 10) if kr else vis.shape[0]), (0, 255, 0), 3)
crop = vis[1000:1750, :]
cv2.imwrite(out_png, cv2.resize(crop, (1500, int(crop.shape[0] * 1500.0 / crop.shape[1]))))
print("saved", out_png, "n_rects=%d centers=%s" % (len(rects), [int((a+b)/2) for a, b in rects]))
