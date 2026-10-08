# -*- coding: utf-8 -*-
import sys, glob, types, importlib.util, importlib.machinery
import numpy as np, cv2
class _Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return _Dummy
    def __call__(self, *a, **k): return _Dummy
class _StubLoader:
    def create_module(self, spec): return types.ModuleType(spec.name)
    def exec_module(self, module):
        module.__dict__["__all__"] = []
        module.__dict__["__getattr__"] = lambda n: _Dummy
class _VendorStub:
    def find_module(self, name, path=None): return None
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0].startswith(("SciCam", "Mv", "MvImport")) or name in ("yolo_detector", "gf_crop"):
            return importlib.machinery.ModuleSpec(name, _StubLoader())
        return None
sys.meta_path.insert(0, _VendorStub())
def load(p, t):
    s = importlib.util.spec_from_file_location(t, p); M = importlib.util.module_from_spec(s)
    M.SciCamera = _Dummy; M.YoloDetector = _Dummy; M.GoldFingerCropper = _Dummy; M.annotate = _Dummy
    s.loader.exec_module(M); return M
B = "/home/ubuntu/zmax/zmax_data/aoi_v4"
M25 = load(B + "/cam_finger_10082_work_v25.py", "v25")
M26 = load(B + "/cam_finger_10082_work_v26.py", "v26")

# ① 前视: 差异像素有多少、在哪
fr = [cv2.imread("/home/ubuntu/.hermes/cache/scratch/liveF%d.png" % i) for i in range(4)]
for _ in range(2):
    for b in fr:
        i25, m25 = M25.render_judge(b); j25 = m25.get("judge") or m25
        i26, m26 = M26.render_judge(b); j26 = m26.get("judge") or m26
d = (np.abs(i25.astype(int) - i26.astype(int)).max(axis=2) > 8)
ys, xs = np.where(d)
print("前视最后一帧: 差异像素 %d / %d = %.3f%%" % (d.sum(), d.size, 100.0*d.mean()))
if d.sum():
    print("  差异区域 y %d~%d, x %d~%d (图 %s)" % (ys.min(), ys.max(), xs.min(), xs.max(), i25.shape))
    print("  ⇒ 若是窄条/角落 ⇒ 时间戳/版本字; 若覆盖齿列 ⇒ 真几何变化")

# ② 点2: v26 的补格判据在哪些候选上失败(复刻 fill 的数学并打日志)
bgr = cv2.imread("/home/ubuntu/.hermes/cache/scratch/pt2_frames/pt2_1.png", cv2.IMREAD_COLOR)
img, met = M26.render_judge(bgr); j = met.get("judge") or met
rects = [(int(a), int(b)) for a, b in (j.get("rects") or [])]
print("\n点2 frame1: v26 rects=%d 个, 步格=%s" % (len(rects), j.get("v26_note") or "未触发"))
if rects:
    cen = sorted((a + b) / 2.0 for a, b in rects)
    dd = np.diff(cen); med = float(np.median(dd)); near = dd[dd <= 1.6 * med]
    pitch = float(np.median(near)) if near.size >= 3 else med
    prof = np.zeros(1)
    # 用判据记录的带
    ky = j.get("key_rows") or j.get("kept_rows")
    ga = M26._v21_luma(bgr)
    if ky:
        prof = ga[int(ky[0]):int(ky[1]) + 1, :].astype(np.float32).mean(axis=0)
    N = M26._V26_TPL_N
    def shape(c):
        a = int(round(c - pitch*0.5)); b = int(round(c + pitch*0.5))
        if a < 0 or b > len(prof) or b-a < 6: return None
        v = prof[a:b].astype(np.float32)
        if v.size != N: v = np.interp(np.linspace(0, v.size-1, N), np.arange(v.size), v).astype(np.float32)
        v = v - float(v.mean()); n = float(np.linalg.norm(v))
        return (v, n) if n > 1e-6 else None
    refs = [s for s in (shape(c) for c in cen) if s]
    T = np.mean([v/n for v, n in refs], axis=0); T = T/ (np.linalg.norm(T) or 1)
    refs_lvl = [float(prof[max(0,int(round(c-pitch*0.30))):int(round(c+pitch*0.30+1))].mean()) for c in cen]
    ref_l = float(np.median(refs_lvl))
    print("  节距=%.1f 中位槽亮度=%.1f 带=%s" % (pitch, ref_l, ky))
    print("  候选(从右端 center=%.0f 起):" % max(cen))
    c = max(cen)
    for k in range(1, 8):
        c = c + pitch
        s = shape(c)
        cr = float(np.dot(T, s[0]) / s[1]) if s else -1.0
        lv = float(prof[max(0,int(round(c-pitch*0.3))):int(round(c+pitch*0.3+1))].mean())
        print("   +%d格 x=%.0f  lvl=%.1f (%.2f×中位)  corr=%+.3f  %s" % (
            k, c, lv, lv/ref_l, cr, "✅认" if (lv >= 0.65*ref_l and cr >= 0.55) else "✗拒"))
