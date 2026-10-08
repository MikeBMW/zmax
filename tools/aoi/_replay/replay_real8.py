# -*- coding: utf-8 -*-
"""真帧 8 张按序复放: v24 vs v25(带投票)。判据: v25 预热后恒 19。"""
import sys, types, importlib.util, importlib.machinery, json
import numpy as np, cv2
class _Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Dummy
    def __call__(self, *a, **k): return _Dummy
class _StubLoader:
    def create_module(self, spec): return types.ModuleType(spec.name)
    def exec_module(self, m): m.__dict__["__all__"] = []; m.__dict__["__getattr__"] = lambda n: _Dummy
class _V:
    def find_module(self, n, p=None): return None
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0].startswith(("SciCam","Mv","MvImport")) or name in ("yolo_detector","gf_crop"):
            return importlib.machinery.ModuleSpec(name, _StubLoader())
        return None
sys.meta_path.insert(0, _V())
def load(p, tag):
    spec = importlib.util.spec_from_file_location(tag, p)
    m = importlib.util.module_from_spec(spec)
    m.SciCamera = _Dummy; m.YoloDetector = _Dummy; m.GoldFingerCropper = _Dummy; m.annotate = _Dummy
    spec.loader.exec_module(m); return m
V4 = load("/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v24.py", "m24")
V5 = load("/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v25.py", "m25")
frames = [cv2.imread("/home/ubuntu/.hermes/cache/scratch/liveF%d.png" % i) for i in range(8)]
print("帧序号 | v24 根数 | v25 根数 | v25 投票(得票/窗口 · 补回 · 否掉)")
k4, k5 = [], []
for i, f in enumerate(frames * 3):
    _, m4 = V4.render_judge(f); j4 = (m4.get("judge") if isinstance(m4.get("judge"), dict) else m4) or {}
    _, m5 = V5.render_judge(f); j5 = (m5.get("judge") if isinstance(m5.get("judge"), dict) else m5) or {}
    v = j5.get("v25_vote") or {}
    k4.append(j4.get("n_keys")); k5.append(j5.get("n_keys"))
    print("  %d    |   %3s    |   %3s    | raw=%s voted=%s healed=%s vetoed=%s" % (
        i, j4.get("n_keys"), j5.get("n_keys"), v.get("raw_span"), v.get("voted_span"), v.get("healed"), v.get("vetoed")))
print("\nv24:", k4, "  集合", sorted(set(k4)))
print("v25:", k5, "  集合", sorted(set(k5)))
print("v25 预热后(第3帧起):", k5[2:], " 判定:", "✅ 恒 19" if set(k5[2:]) == {19} else "❌ %s" % sorted(set(k5[2:])))
