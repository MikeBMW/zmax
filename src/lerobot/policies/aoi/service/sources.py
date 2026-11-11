# -*- coding: utf-8 -*-
"""本机 AOI 镜像服务的「帧源」—— 判据代码是产线的，像素从哪来必须写明。

方案 (按 `ZMAX_AOI_LOCAL_<KIND>_SRC` 选, KIND=GOLD|SURFACE):
    remote:<host>   工控机上的取图口 (产线的 AOI 程序, 或轻量 provider:
                    tools/aoi/cam_provider.py 只做 抓帧→JPEG, 不起模型/不写盘) (gold 优先 /preview.jpg, 否则 /picture?kind=origin&grab=1;
                    surface 用 /picture?kind=origin&grab=1 —— v20 起有这个口)
    cam:<url>       直接抓一个 JPEG 的 URL (如本机 8797: http://127.0.0.1:8797/snap/gold.jpg)
    file:<path>     指定一张图 (回放/取证)
    dir:<path>      目录里最新的图 (录制回放)
    push            只接受 POST /frame 推上来的帧 —— 工控机停机时唯一可用且不造假的方式

🔴 任何源失败都如实返回 ("no frame"), 绝不返回一张旧图/合成图冒充本轮画面。
"""
from __future__ import annotations

import glob
import os
import time

import cv2
import numpy as np

_UA = {"User-Agent": "zmax-aoi-local-mirror"}      # 工控机的服务不看 UA, 但保持一致
_TIMEOUT = float(os.environ.get("ZMAX_AOI_LOCAL_HTTP_TIMEOUT", "8"))
_EXT = ("*.png", "*.jpg", "*.jpeg", "*.bmp")


def _decode(buf: bytes):
    if not buf:
        return None
    return cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)


def _http_get(url: str, timeout: float | None = None, bounded: bool = True):
    """有界取图: 工控机 10083 的 grab 会永久挂死 (技能记过), 所以走工作线程 + 总时限。"""
    import threading
    import urllib.request as _u

    box = {}

    def _work():
        try:
            req = _u.Request(url, headers=_UA)
            with _u.urlopen(req, timeout=timeout or _TIMEOUT) as r:
                box["buf"] = r.read()
                box["ct"] = r.headers.get("Content-Type", "")
        except Exception as e:                                        # noqa: BLE001
            box["err"] = f"{type(e).__name__}: {e}"

    if not bounded:
        _work()
    else:
        th = threading.Thread(target=_work, daemon=True)
        th.start()
        th.join((timeout or _TIMEOUT) + 1.0)
        if th.is_alive():
            box["err"] = "timeout (bounded)"
    return box.get("buf"), box.get("err")


def kind_src(kind: str) -> str:
    return (os.environ.get(f"ZMAX_AOI_LOCAL_{kind.upper()}_SRC")
            or os.environ.get("ZMAX_AOI_LOCAL_SRC")
            or "remote:192.168.23.23")


def grab(kind: str, spec: str | None = None):
    """取一帧 → (bgr|None, meta)。meta 里写明 source/how/ms/why。"""
    spec = (spec or kind_src(kind)).strip()
    t0 = time.time()
    met = {"kind": kind, "spec": spec, "src": spec.split(":", 1)[0], "ok": False, "ms": None, "why": ""}
    try:
        if spec.startswith("remote:"):
            host = spec.split(":", 1)[1] or "192.168.23.23"
            urls = []
            if kind == "gold":
                urls = [f"http://{host}:10082/preview.jpg?scale=1.0&q=92",
                        f"http://{host}:10082/picture?kind=origin&grab=1"]
            else:
                urls = [f"http://{host}:10083/picture?kind=origin&grab=1"]
            errs = []
            for u in urls:
                buf, err = _http_get(u)
                bgr = _decode(buf) if buf else None
                if bgr is not None:
                    met.update(ok=True, how=u, frame=[int(bgr.shape[1]), int(bgr.shape[0])])
                    return bgr, _done(met, t0)
                errs.append(f"{u.split('/', 3)[-1]} → {err or '空响应'}")
            met["why"] = "远端取图失败: " + " | ".join(errs)
            return None, _done(met, t0)

        if spec.startswith("cam:"):
            u = spec.split(":", 1)[1]
            buf, err = _http_get(u)
            bgr = _decode(buf) if buf else None
            if bgr is None:
                met["why"] = f"cam 取图失败: {err or '空响应'}"
                return None, _done(met, t0)
            met.update(ok=True, how=u, frame=[int(bgr.shape[1]), int(bgr.shape[0])])
            return bgr, _done(met, t0)

        if spec.startswith("file:"):
            p = os.path.expanduser(spec.split(":", 1)[1])
            bgr = cv2.imread(p)
            if bgr is None:
                met["why"] = f"读图失败: {p}"
                return None, _done(met, t0)
            met.update(ok=True, how=p, frame=[int(bgr.shape[1]), int(bgr.shape[0])])
            return bgr, _done(met, t0)

        if spec.startswith("dir:"):
            d = os.path.expanduser(spec.split(":", 1)[1])
            files = []
            for pat in _EXT:
                files += glob.glob(os.path.join(d, pat))
            if not files:
                met["why"] = f"目录里没有图: {d}"
                return None, _done(met, t0)
            p = max(files, key=os.path.getmtime)
            bgr = cv2.imread(p)
            if bgr is None:
                met["why"] = f"读图失败: {p}"
                return None, _done(met, t0)
            met.update(ok=True, how=p, frame=[int(bgr.shape[1]), int(bgr.shape[0])])
            return bgr, _done(met, t0)

        if spec.startswith("push"):
            met["why"] = "帧源=push: 请先 POST /frame 推一张 (工控机停机时的正常用法)"
            return None, _done(met, t0)

        met["why"] = f"未知帧源 {spec!r} (remote:/cam:/file:/dir:/push)"
        return None, _done(met, t0)
    except Exception as e:                                            # noqa: BLE001
        met["why"] = f"{type(e).__name__}: {e}"
        return None, _done(met, t0)


def _done(met: dict, t0: float) -> dict:
    met["ms"] = round((time.time() - t0) * 1000, 1)
    return met
