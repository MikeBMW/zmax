# -*- coding: utf-8 -*-
"""把产线 AOI 程序**原样**加载成一个本机模块。

用法:
    m = load("gold")     # -> 产线 cam_finger_10082_work_v20.py 的模块对象
    img, meta = m.render_judge_gated(bgr, 0.0)
    img2, meta2 = load("surface").render_judge_surface(bgr)

为什么要 exec 而不是普通 import:
  * 文件名以数字/下划线组成, 且它们顶层就 `m_Device = SciCamera()` / `detector = YoloDetector()`
    (Windows SDK), 必须先把桩装进 sys.modules 再 exec。
  * 每个 kind 一个**独立模块命名空间** + 独立工作目录: 产线文件里有 `_LAST_GOOD_JUDGE`
    这类跨帧全局量, 金手指与表面跑在同一进程里会互相污染 (技能: "复放对照必须每视角独立进程")。
"""
from __future__ import annotations

import os
import threading
import types

try:                                   # 包内 import
    from . import stubs
except ImportError:                    # 直接跑脚本 (本机镜像不依赖 lerobot 包初始化)
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    import stubs                        # type: ignore[no-redef]

HERE = os.path.dirname(os.path.abspath(__file__))
PROD = os.path.join(HERE, "prod")

KINDS = {
    # kind -> (文件名, 工作目录名, 环境变量前缀)
    "gold": ("gold_10082_prod.py", "gold_10082", "ZMAX_AOI_LOCAL_GOLD"),
    "surface": ("surface_10083_prod.py", "surface_10083", "ZMAX_AOI_LOCAL_SURFACE"),
}

PROD_SHA256 = {
    "gold": "a595c39eb12dae399dc9f87428aa2875b7a2552db41ef225f72bcbd4aca97ecf",
    "surface": "0f9206b5d994fc5d7fed00809d21dc3df57f38d704f6d2b5820683f1e4bfe727",
}

_LOCK = threading.Lock()
_LOADED: dict[str, types.ModuleType] = {}


def workdir(kind: str) -> str:
    """每个视角一个可写目录 (产线文件会往 ./ 落图)。"""
    base = os.environ.get("ZMAX_AOI_LOCAL_DATA") or os.path.expanduser("~/zmax/zmax_data/aoi_local")
    d = os.path.join(base, KINDS[kind][1])
    os.makedirs(d, exist_ok=True)
    return d


def load(kind: str) -> types.ModuleType:
    """加载 (或取缓存) 产线模块。kind ∈ {gold, surface}。"""
    if kind not in KINDS:
        raise KeyError(f"未知视角 {kind!r}, 可选 {sorted(KINDS)}")
    with _LOCK:
        if kind in _LOADED:
            return _LOADED[kind]
        stubs.install()
        fn = os.path.join(PROD, KINDS[kind][0])
        if not os.path.exists(fn):
            raise FileNotFoundError(fn)
        mod = types.ModuleType(f"aoi_prod_{kind}")
        mod.__file__ = fn
        mod.__package__ = f"aoi_prod_{kind}"
        old = os.getcwd()
        try:
            os.chdir(workdir(kind))            # 产线文件到处用相对路径
            with open(fn, "rb") as f:
                code = f.read()
            exec(compile(code, fn, "exec"), mod.__dict__)   # noqa: S102 - 就是要原样跑产线代码
        finally:
            os.chdir(old)
        mod.__dict__.setdefault("_LOCAL_MIRROR", True)
        _LOADED[kind] = mod
        return mod


def judge_gold(bgr, deskew_deg: float = 0.0):
    """金手指判据图 (与产线同一个 render_judge_gated, 含 19 根门/v33 保留画面)。"""
    m = load("gold")
    return m.render_judge_gated(bgr, float(deskew_deg or 0.0))


def judge_surface(bgr):
    """表面判据图 (与产线同一个 render_judge_surface)。返回 (img|None, meta)。"""
    m = load("surface")
    return m.render_judge_surface(bgr)


def info() -> dict:
    """本机镜像的自我说明 (谁是真源/哪些能力本机没有)。"""
    out = {"prod_dir": PROD, "kinds": {}}
    for k, (fn, _wd, _pfx) in KINDS.items():
        p = os.path.join(PROD, fn)
        out["kinds"][k] = {"file": fn, "exists": os.path.exists(p),
                           "bytes": os.path.getsize(p) if os.path.exists(p) else 0,
                           "sha256": PROD_SHA256.get(k)}
    out["stubbed"] = ["SciCam_*", "yolo_detector(加密权重)", "gf_crop(模板裁剪)"]
    out["native"] = ["render_judge_gated/gold", "render_judge_surface", "全部路由语义"]
    return out
