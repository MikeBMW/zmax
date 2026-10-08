# -*- coding: utf-8 -*-
"""序列 A/B: v25 vs v26 —— 前视(liveF0-7, 已验收 19) 必须逐帧逐像素不变; 点2 应稳定到 19。
   注意: v25 的短窗投票有状态 ⇒ 必须按序复放(3 轮, 看预热后的稳态), 不能单帧比。"""
import sys, os, glob, types, importlib.util, importlib.machinery
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

def load(path, tag):
    spec = importlib.util.spec_from_file_location(tag, path)
    M = importlib.util.module_from_spec(spec)
    M.SciCamera = _Dummy; M.YoloDetector = _Dummy; M.GoldFingerCropper = _Dummy; M.annotate = _Dummy
    spec.loader.exec_module(M)
    return M

B = "/home/ubuntu/zmax/zmax_data/aoi_v4"
M25 = load(B + "/cam_finger_10082_work_v25.py", "v25")
M26 = load(B + "/cam_finger_10082_work_v26.py", "v26")

def seq(M, frames, rounds=3):
    """按序复放, 返回 [(n_keys, img), ...] 全长(含预热)。"""
    out = []
    for _ in range(rounds):
        for bgr in frames:
            img, met = M.render_judge(bgr)
            j = met.get("judge") or met
            out.append((j.get("n_keys"), img, j))
    return out

def run(tag, paths, rounds=3):
    fr = [cv2.imread(p, cv2.IMREAD_COLOR) for p in paths]
    a = seq(M25, fr, rounds)
    b = seq(M26, fr, rounds)
    warm = len(paths)
    na = [x[0] for x in a[warm:]]
    nb = [x[0] for x in b[warm:]]
    same_px = all((x[1] is not None and y[1] is not None and x[1].shape == y[1].shape
                   and np.array_equal(x[1], y[1])) for x, y in zip(a, b))
    print("\n%s  (%d 帧 x %d 轮, 预热 %d 帧后统计)" % (tag, len(paths), rounds, warm))
    print("  v25 稳态序列:", na)
    print("  v26 稳态序列:", nb)
    print("  逐帧逐像素全等:", "✅ 是" if same_px else "❌ 否 —— 前视被改了, 不许上线")
    adds = [x[2].get("v26_note") for x in b[warm:] if x[2].get("v26_note")]
    print("  v26 补格动作:", (set(adds) if adds else "无(不触发)"))
    for tagm, lst in (("v25", a), ("v26", b)):
        errs = [x[2].get("err") for x in lst[warm:] if x[2].get("err")]
        atts = sorted({x[2].get("attempt") for x in lst[warm:]})
        notes = sorted({str(x[2].get("attempts_note"))[:52] for x in lst[warm:]})
        print("   %s: err=%s attempt=%s note=%s" % (tagm, (set(errs) if errs else "无"), atts, notes))
    return na, nb, same_px

run("前视 liveF0-7(已验收 19)", ["/home/ubuntu/.hermes/cache/scratch/liveF%d.png" % i for i in range(8)])
run("点2 pt2_1-8(真值 19)", sorted(glob.glob("/home/ubuntu/.hermes/cache/scratch/pt2_frames/pt2_*.png")))
