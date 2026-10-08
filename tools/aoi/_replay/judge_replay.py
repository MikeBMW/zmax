# -*- coding: utf-8 -*-
"""离线复放台: 一帧原图 x 多档亮度 → render_judge → 根数/几何。用于复现"根数跳"并验证修法。"""
import sys, os, types, json, urllib.request, importlib.util
import numpy as np, cv2

# ① 桩掉相机 SDK 依赖(只为 import, 不跑相机)
# 厂商 SDK 桩: 任何 SciCam*/Mv* 模块都自动建空模块(只为 import 通过; 不跑相机)
import importlib.machinery
class _Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Dummy
    def __call__(self, *a, **k): return _Dummy
class _StubLoader:
    def create_module(self, spec): return types.ModuleType(spec.name)
    def exec_module(self, module):
        module.__dict__["__all__"] = []
        module.__dict__["__getattr__"] = lambda n: _Dummy      # from X import Y -> _Dummy
class _VendorStub:
    def find_module(self, name, path=None): return None
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0].startswith(("SciCam", "Mv", "MvImport")) or name in ("yolo_detector", "gf_crop"):
            return importlib.machinery.ModuleSpec(name, _StubLoader())
        return None
sys.meta_path.insert(0, _VendorStub())

SRC = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v24.py"
spec = importlib.util.spec_from_file_location("judge_under_test", SRC)
M = importlib.util.module_from_spec(spec)
# 模块级就会实例化相机/检测器/裁剪器 ⇒ 先把桩类塞进命名空间(import * 不会覆盖它们)
M.SciCamera = _Dummy; M.YoloDetector = _Dummy; M.GoldFingerCropper = _Dummy; M.annotate = _Dummy
spec.loader.exec_module(M)
print("载入:", os.path.basename(SRC), "· 版本标记:", getattr(M, "_JUDGE_VER", "?"))

# ② 抓一帧原图
raw = urllib.request.urlopen("http://192.168.23.23:10082/picture?kind=origin&grab=1", timeout=60).read()
bgr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
print("原始帧:", bgr.shape)

# ③ 多档亮度 → 判据图
print("\n亮度档 | 根数 | sat_before | 裁列 | 认领跨度 | 中位节距 | 被拒段")
res = []
for s in (0.75, 0.85, 0.92, 1.00, 1.08, 1.18):
    v = np.clip(bgr.astype(np.float32) * s, 0, 255).astype(np.uint8)
    img, met = M.render_judge(v)
    j = met.get("judge") or met
    xm = met.get("x_trim") or (j.get("x_trim") or {})
    res.append((s, j.get("n_keys"), j.get("sat_before"), (xm or {}).get("x_span"), j.get("v24_claims_span"),
                j.get("lattice_pitch_px"), j.get("v24_rejected_edge_segs")))
    print("x%.2f   | %4s | %9.4f | %-12s | %-10s | %6s | %s" % (
        s, j.get("n_keys"), j.get("sat_before") or 0, str((xm or {}).get("dropped_cols")), str(j.get("v24_claims_span")),
        j.get("lattice_pitch_px"), str(j.get("v24_rejected_edge_segs"))[:40]))
    if s == 1.00:
        cv2.imwrite("/home/ubuntu/.hermes/cache/scratch/replay_s100.png", img)
ks = [r[1] for r in res]
print("\n⇒ 根数集合:", sorted(set(ks)), "稳定" if len(set(ks)) == 1 else "❌ 不稳")
