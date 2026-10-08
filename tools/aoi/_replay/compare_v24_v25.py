# -*- coding: utf-8 -*-
"""v24 vs v25 对照: 同一帧 x 多档亮度 → 根数/跨度。v25 应恒定 19。"""
import sys, types, urllib.request, importlib.util, importlib.machinery
import numpy as np, cv2
class _Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Dummy
    def __call__(self, *a, **k): return _Dummy
class _StubLoader:
    def create_module(self, spec): return types.ModuleType(spec.name)
    def exec_module(self, module):
        module.__dict__["__all__"] = []; module.__dict__["__getattr__"] = lambda n: _Dummy
class _VendorStub:
    def find_module(self, name, path=None): return None
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0].startswith(("SciCam","Mv","MvImport")) or name in ("yolo_detector","gf_crop"):
            return importlib.machinery.ModuleSpec(name, _StubLoader())
        return None
sys.meta_path.insert(0, _VendorStub())

def load(path, tag):
    spec = importlib.util.spec_from_file_location(tag, path)
    m = importlib.util.module_from_spec(spec)
    m.SciCamera = _Dummy; m.YoloDetector = _Dummy; m.GoldFingerCropper = _Dummy; m.annotate = _Dummy
    spec.loader.exec_module(m); return m

V4 = load("/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v24.py", "m24")
V5 = load("/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v25.py", "m25")
print("v24 标记:", V4._JUDGE_VER, "| v25 标记:", V5._JUDGE_VER)

bgr = cv2.imread("/home/ubuntu/.hermes/cache/scratch/frozen_frame.png")   # 冻结帧 ⇒ 可复现
print("帧:", bgr.shape, "\n")

def run(M, v, tag):
    img, met = M.render_judge(v)
    j = (met.get("judge") if isinstance(met.get("judge"), dict) else met) or {}
    return j.get("n_keys"), j.get("v24_claims_span"), img

print("亮度 |  v24 根数/跨度        |  v25 根数/跨度        | 判据图像素差")
k4s, k5s = [], []
for s in (0.75, 0.85, 0.92, 1.00, 1.08, 1.18):
    v = np.clip(bgr.astype(np.float32) * s, 0, 255).astype(np.uint8)
    n4, s4, i4 = run(V4, v, "v24")
    n5, s5, i5 = run(V5, v, "v25")
    k4s.append(n4); k5s.append(n5)
    d = float(np.abs(i4.astype(np.int16) - i5.astype(np.int16)).mean()) if (i4 is not None and i5 is not None) else -1
    dmax = int(np.abs(i4.astype(np.int16) - i5.astype(np.int16)).max()) if (i4 is not None and i5 is not None) else -1
    print("x%.2f | %4s %-14s | %4s %-14s | %.2f (max %d)" % (s, n4, str(s4), n5, str(s5), d, dmax))
    if s == 1.00:
        cv2.imwrite("/home/ubuntu/.hermes/cache/scratch/v24_judge_x100.png", i4)
        cv2.imwrite("/home/ubuntu/.hermes/cache/scratch/v25_judge_x100.png", i5)
print("\nv24 根数集合:", sorted(set(k4s)), " → ", "不稳 ❌" if len(set(k4s)) > 1 else "稳定 ✅")
print("v25 根数集合:", sorted(set(k5s)), " → ", "不稳 ❌" if len(set(k5s)) > 1 else "稳定 ✅")
