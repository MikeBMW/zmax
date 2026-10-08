#!/usr/bin/env python3
"""27 张**真·失败帧**(从工控机内存捞的)上做 v21 vs v22 正面对照。"""
import os, sys, glob, types, importlib.util, hashlib
import numpy as np
HERE = "/home/ubuntu/zmax/zmax_data/aoi_v4"; S = "/home/ubuntu/.hermes/cache/scratch"
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "_stub"))
os.environ.setdefault("TEMP", os.path.join(S, "_rend_tmp")); os.makedirs(os.environ["TEMP"], exist_ok=True)
import cv2
yd = types.ModuleType("yolo_detector")
class _YD:
    def __init__(s, *a, **k): pass
    def detect(s, *a, **k): return {"detections": [], "saved_incoming": None}
yd.YoloDetector = _YD; sys.modules["yolo_detector"] = yd
def load(n, p):
    sp = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(sp)
    sys.modules[n] = m; sp.loader.exec_module(m); return m
V21 = load("aoix21", os.path.join(HERE, "cam_finger_10082_work_v21.py"))
V22 = load("aoix22", os.path.join(HERE, "cam_finger_10082_work_v22.py"))

fs = sorted(glob.glob(S + "/fail_*.png")) + sorted(glob.glob(S + "/fail_live_*.png"))
fs = [f for f in fs if "_v22_" not in f and "_v21_" not in f]
print("cv2 %s  真失败帧 %d 张" % (cv2.__version__, len(fs)))
v21f = v22ok = v22f = 0
rec = []
for f in fs:
    im = cv2.imread(f)
    if im is None:
        continue
    o1, m1 = V21.render_judge(im)
    o2, m2 = V22.render_judge(im)
    if o1 is None: v21f += 1
    if o2 is not None: v22ok += 1
    else: v22f += 1
    rec.append((os.path.basename(f), o1 is None, m1.get("why"), round(float(m1.get("sat_before") or -1), 3),
                m1.get("key_row_span"), [z["y0"] for z in (m1.get("_hits") or [])],
                o2 is not None, m2.get("attempt"), m2.get("band_used"), m2.get("n_keys"),
                m2.get("sat_before"), m2.get("black_frac"), (m2.get("attempts_note") or m2.get("last_why") or "")))
print("\n%-24s %-7s %-30s %-7s %-12s %-22s %-7s %-4s %-12s %-5s %-6s %-6s" %
      ("帧", "v21", "v21 why", "sat", "带", "命中窗y0", "v22", "遍", "救回带", "键", "sat", "黑底"))
for r in rec:
    print("%-24s %-7s %-30s %-7s %-12s %-22s %-7s %-4s %-12s %-5s %-6s %-6s" %
          (r[0][:24], "失败" if r[1] else "成功", str(r[2])[:30], r[3], str(r[4]),
           str(r[5])[:22], "成功" if r[6] else "拒绝", r[7], str(r[8]), r[9], r[10], r[11]))
print("\n合计: v21 失败 %d/%d | v22 救回 %d | v22 如实拒绝 %d" % (v21f, len(rec), v22ok, v22f))
why = {}
for r in rec:
    if not r[6]:
        why[str(r[12])[:60]] = why.get(str(r[12])[:60], 0) + 1
for k, v in why.items():
    print("   拒绝原因 x%d: %s" % (v, k))
# 存 2 张救回图供目检
for i, f in enumerate(fs[:2]):
    im = cv2.imread(f); o2, m2 = V22.render_judge(im)
    if o2 is not None:
        cv2.imwrite(os.path.join(S, "v22_real_recovered_%d.png" % i), o2)
        print("救回图 %d: %s %s" % (i, os.path.basename(f), o2.shape))
