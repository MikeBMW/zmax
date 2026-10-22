"""matplotlib 最小桩 —— 只够 ultralytics import，不碰绘图。

背景：Intel venv 是 Python 3.12，现成 matplotlib 及其 C 扩展是 3.11 编的，
ABI 不兼容；外网 50KB/s 逐个下 cp312 依赖不现实。
ultralytics 训练主流程不用 matplotlib，只在 import 期引用 font_manager、
画曲线时用 pyplot。训练传 plots=False 就不会碰绘图。

注意：不要用"万能 __getattr__ 返回任意对象"那种桩 —— 它会污染 inspect /
posixpath 之类的标准库探测（实测 TypeError: expected str ... not _Anything）。
这里只给明确、有限的名字。

用法（必须在 import ultralytics 之前）：
    import sys; sys.path.insert(0, "tools"); import mpl_stub  # noqa
"""
import sys
import types


def _mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _NoOp:
    """什么都没做，但属性访问返回自己、调用返回自己。只给绘图对象用。"""
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        return _NoOp()

    def __call__(self, *a, **k):
        return _NoOp()

    def __getitem__(self, k):
        return _NoOp()

    def __setitem__(self, k, v):
        pass

    def __iter__(self):
        return iter([])

    def __float__(self):
        return 0.0

    def __int__(self):
        return 0


def install():
    fm = _mod("matplotlib.font_manager",
              FontProperties=_NoOp,
              findfont=lambda *a, **k: "stub-font",
              findSystemFonts=lambda *a, **k: [],
              get_font=lambda *a, **k: _NoOp(),
              fontManager=_NoOp(),
              addfont=lambda *a, **k: None)

    pyplot = _mod("matplotlib.pyplot",
                  plot=lambda *a, **k: _NoOp(),
                  figure=lambda *a, **k: _NoOp(),
                  savefig=lambda *a, **k: None,
                  close=lambda *a, **k: None,
                  subplots=lambda *a, **k: (_NoOp(), _NoOp()),
                  imshow=lambda *a, **k: _NoOp(),
                  axis=lambda *a, **k: None,
                  title=lambda *a, **k: None,
                  xlabel=lambda *a, **k: None,
                  ylabel=lambda *a, **k: None,
                  legend=lambda *a, **k: None,
                  grid=lambda *a, **k: None,
                  tight_layout=lambda *a, **k: None,
                  cm=None,
                  ion=lambda *a, **k: None,
                  ioff=lambda *a, **k: None,
                  backend="agg")

    colors = _mod("matplotlib.colors", Normalize=_NoOp, ListedColormap=_NoOp,
                  to_rgb=lambda c: (0.0, 0.0, 0.0))
    patches = _mod("matplotlib.patches", Rectangle=_NoOp, Circle=_NoOp,
                   Polygon=_NoOp, Arrow=_NoOp)
    cm = _mod("matplotlib.cm", get_cmap=lambda *a, **k: _NoOp(), viridis=_NoOp())
    pyplot.cm = cm

    mpl = _mod("matplotlib",
               __version__="0.0.0-stub",
               use=lambda *a, **k: None,
               get_backend=lambda: "agg",
               rcParams={},
               rc=lambda *a, **k: None,
               font_manager=fm,
               pyplot=pyplot,
               colors=colors,
               patches=patches,
               cm=cm)
    return mpl


install()
