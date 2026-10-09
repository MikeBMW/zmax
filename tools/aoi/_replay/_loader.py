# -*- coding: utf-8 -*-
"""共享加载器: 把 vendored 依赖(SciCam/Mv/gf_crop/flask)全部 stub 掉, 只留纯算法。
用于离线复放 v25(在役基线) / v26(WIP) 的 render_judge。"""
import sys, types, importlib.util, importlib.machinery

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
        root = name.split(".")[0]
        if root.startswith(("SciCam", "Mv", "MvImport")) or root in ("yolo_detector", "gf_crop", "flask"):
            return importlib.machinery.ModuleSpec(name, _StubLoader())
        return None

def install():
    sys.meta_path.insert(0, _VendorStub())

def load(path, tag):
    install()
    spec = importlib.util.spec_from_file_location(tag, path)
    M = importlib.util.module_from_spec(spec)
    M.SciCamera = _Dummy; M.YoloDetector = _Dummy; M.GoldFingerCropper = _Dummy; M.annotate = _Dummy
    spec.loader.exec_module(M)
    return M
