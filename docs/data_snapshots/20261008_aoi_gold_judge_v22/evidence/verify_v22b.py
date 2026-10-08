#!/usr/bin/env python3
"""v22 第二组验收: 复现"键行带过曝"这一类失败帧, 并验证 v22 的两条出路。
 - 部分过曝(键还在) ⇒ v22 应**逐窗救回**一张正确口径的判据图
 - 整带过曝(键没了) ⇒ v21/v22 都应拒绝渲染; v22 必须拒绝"可疑救回"(验收闸), 由上层端上一张好图
再顺手 diff warp_goldfinger_topview 确认没被误改。
"""
import os, sys, glob, types, importlib.util, hashlib, json, difflib
import numpy as np
HERE = "/home/ubuntu/zmax/zmax_data/aoi_v4"
S = "/home/ubuntu/.hermes/cache/scratch"
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

V21 = load("aoiv21b", os.path.join(HERE, "cam_finger_10082_work_v21.py"))
V22 = load("aoiv22b", os.path.join(HERE, "cam_finger_10082_work_v22.py"))
F = S + "/live_grab_origin.png"
base = cv2.imread(F)
print("帧 %s %s" % (os.path.basename(F), base.shape))

# 先看真实命中带在哪(用它做"过曝区")
g = V22._v21_luma(base)
hits = V22._v21_key_windows(g, V22._V21_BRIGHT_LEVEL)
by0 = min(z["y0"] for z in hits); by1 = max(z["y1"] for z in hits)
print("真实命中窗 %d 个, 合并带 y=[%d,%d]" % (len(hits), by0, by1))
o0, m0 = V22.render_judge(base)
print("原帧 v22: %s n_keys=%s sat=%s black=%s\n" % ("OK" if o0 is not None else "失败", m0.get("n_keys"),
                                                    m0.get("sat_before"), m0.get("black_frac")))

def blow(img, y0, y1, x0=200, x1=None, val=255):
    out = img.copy()
    x1 = x1 or img.shape[1] - 200
    out[max(0, y0):y1, x0:x1] = val
    return out

for tag, (ay0, ay1) in (("部分过曝(键还在)", (by0, by0 + 36)), ("整带过曝(键没了)", (by0 - 20, by1 + 20))):
    fr = blow(base, ay0, ay1)
    o1, m1 = V21.render_judge(fr)
    o2, m2 = V22.render_judge(fr)
    print("--- %s  y=[%d,%d] ---" % (tag, ay0, ay1))
    print("  v21: %s why=%s keys=%s sat_before=%s" % ("失败" if o1 is None else "成功",
                                                     m1.get("why"), m1.get("n_keys"), m1.get("sat_before")))
    print("  v22: %s attempt=%s band_used=%s gate=%s keys=%s sat=%s black=%s" % (
        "成功" if o2 is not None else "失败", m2.get("attempt"), m2.get("band_used"), m2.get("gate_used"),
        m2.get("n_keys"), m2.get("sat_before"), m2.get("black_frac")))
    print("  说明: %s" % (m2.get("attempts_note") or m2.get("last_why") or m2.get("first_why")))
    if o2 is not None:
        cv2.imwrite(os.path.join(S, "v22_blow_%s.png" % ("part" if "部分" in tag else "full")), o2)
    cv2.imwrite(os.path.join(S, "v21_blow_%s_input.png" % ("part" if "部分" in tag else "full")), fr)
    print()

def src_of(mod, fn):
    s = open(mod.__file__, encoding="utf-8").read()
    i = s.index("def %s(" % fn); j = s.find("\ndef ", i + 10)
    return s[i:j if j > 0 else len(s)]
a, b = src_of(V21, "warp_goldfinger_topview"), src_of(V22, "warp_goldfinger_topview")
print("⑤ warp_goldfinger_topview 差异行数=%d" % sum(1 for _ in difflib.unified_diff(a.split("\n"), b.split("\n"))))
for ln in list(difflib.unified_diff(a.split("\n"), b.split("\n")))[:12]:
    print("   ", ln)
