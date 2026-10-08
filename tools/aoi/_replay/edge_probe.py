# -*- coding: utf-8 -*-
"""冻结 8 张真帧 + 复现 _v21_strip_cols 的左端判决, 看 x∈[400,560] 的边缘profile为什么跳。"""
import sys, types, urllib.request, importlib.util, importlib.machinery, json
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
spec = importlib.util.spec_from_file_location("m24", "/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v24.py")
M = importlib.util.module_from_spec(spec)
M.SciCamera = _Dummy; M.YoloDetector = _Dummy; M.GoldFingerCropper = _Dummy; M.annotate = _Dummy
spec.loader.exec_module(M)

frames = []
for i in range(8):
    r = urllib.request.urlopen("http://192.168.23.23:10082/picture?kind=origin&grab=1", timeout=60).read()
    f = cv2.imdecode(np.frombuffer(r, np.uint8), cv2.IMREAD_COLOR)
    frames.append(f)
    cv2.imwrite("/home/ubuntu/.hermes/cache/scratch/liveF%d.png" % i, f)
print("已冻结 8 帧")
print("\n帧 | 左端点 | 右端点 | 根数 | e[430:520] 抽样(每6列) | e 峰值位置")
for i, f in enumerate(frames):
    g = M._v21_luma(f)
    hits = M._v21_key_windows(g, M._V21_BRIGHT_LEVEL)
    ky0 = min(h["y0"] for h in hits); ky1 = max(h["y1"] for h in hits)
    left, right, rsrc, lsrc, band = M._v21_strip_cols(g, ky0, ky1)
    img, met = M.render_judge(f); j = (met.get("judge") if isinstance(met.get("judge"), dict) else met) or {}
    # 复算边缘 profile(与 _v21_strip_cols 内部同口径)
    hh, ww = g.shape; mid = (ky0 + ky1) // 2
    b0 = max(0, mid - M._V21_EDGE_BAND_H // 2); b1 = min(hh, b0 + M._V21_EDGE_BAND_H)
    e = np.abs(np.diff(g[b0:b1, :], axis=0)).mean(axis=0); e = M._v21_smooth1d(e, 7)
    seg = e[430:520]
    samp = " ".join("%.1f" % seg[k] for k in range(0, 90, 6))
    print("%2d | %6s | %6s | %4s | %s" % (i, left, right, j.get("n_keys"), samp))
    print("     e[430:520] 最大值 %.1f @ x=%d; 超过门限 %.1f 的列数=%d" % (
        seg.max(), 430 + int(seg.argmax()), M._V21_EDGE_CUT, int((seg >= M._V21_EDGE_CUT).sum())))
