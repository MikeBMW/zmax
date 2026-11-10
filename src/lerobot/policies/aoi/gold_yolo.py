# -*- coding: utf-8 -*-
"""金手指 10082 —— 本机 YOLO 推理 (AOI 算法层)。

与 gold.py(搬运工控机判决) **并列**, 不是替代: 来源 src="local-yolo", 话题前缀「AOI.本机YOLO_」。

· 取图: GET /picture?kind=origin —— **只读内存帧, 不带 grab** ⇒ 不抢相机、不触发产线检测。
· 推理: models/yolo_gold_v2.pt (gold_module 单类, imgsz=512)。
· 🔴 默认**只观测不判决**: 该权重由 120 张同场景微扰自蒸馏而来(训练集 val 4/4 conf 0.98,
  泛化未验证) ⇒ 要它参与判决须显式 ZMAX_GOLD_YOLO_GATE=1。未证明提升不进默认档。
"""
from __future__ import annotations

import os
import time as _t

_MODEL = {"m": None, "path": None, "load_ms": None, "err": None}
_LAST = {"t": 0.0, "ms": None, "n": None}


def gold_yolo_model(weights=None, log=None):
    """懒加载单例。每拍重载会直接打死 10Hz 循环 (首载 ~3.6s, 热推 ~15ms/4060 · ~2.5s/550C-CPU)。"""
    _p = weights or os.environ.get("ZMAX_GOLD_YOLO_W") or _default_weights()
    if _MODEL["m"] is not None and _MODEL["path"] == _p:
        return _MODEL["m"]
    if _MODEL["err"] and _MODEL["path"] == _p:
        return None
    try:
        from ultralytics import YOLO
        t0 = _t.time()
        _m = YOLO(_p)
        _MODEL.update({"m": _m, "path": _p, "load_ms": round((_t.time() - t0) * 1000, 1), "err": None})
        if log:
            log(f"🧠 金手指本机模型就位: {os.path.basename(_p)} · 类别 {list(_m.names.values())} "
                f"· 加载 {_MODEL['load_ms']}ms")
        return _m
    except Exception as _e:                                            # noqa: BLE001
        _MODEL.update({"m": None, "path": _p, "err": f"{type(_e).__name__}: {_e}"})
        if log:
            log(f"⚠️ 金手指本机模型加载失败: {_MODEL['err']} — 旁路跳过, 不影响搬运那一路")
        return None


def _default_weights():
    """仓库根/models/yolo_gold_v2.pt —— 从本文件位置回推 (policies/aoi/ → src/lerobot → repo)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, "..", "..", "..", ".."))
    return os.path.join(repo, "models", "yolo_gold_v2.pt")


def gold_yolo_bypass(log=None, cache=None, publish=None, host=None, weights=None):
    """本机推理一帧 → dict + 话题。模型缺/取图失败返回 None(调用方如实记 gap)。"""
    try:
        import urllib.request as _urq
        if cache is None:
            cache = {}
        if os.environ.get("ZMAX_GOLD_YOLO") == "0":
            return None
        _host = host or os.environ.get("ZMAX_AOI_GOLD_HOST", "192.168.23.23")
        _model = gold_yolo_model(weights, log)
        if _model is None:
            return None
        _req = _urq.Request(f"http://{_host}:10082/picture?kind=origin",
                            headers={"User-Agent": "zmax-probe"})
        t0 = _t.time()
        try:
            with _urq.urlopen(_req, timeout=2.0) as _r:
                _buf = _r.read()
        except Exception as _e:                                        # noqa: BLE001
            if log:
                log(f"🌑 金手指本机 YOLO 旁路: 取图失败 {type(_e).__name__} — 跳过本拍")
            return None
        import cv2 as _cv2
        import numpy as _np
        _arr = _cv2.imdecode(_np.frombuffer(_buf, _np.uint8), _cv2.IMREAD_COLOR)
        if _arr is None:
            return None
        _grab_ms = round((_t.time() - t0) * 1000, 1)
        t1 = _t.time()
        # 🔴 2026-11-10 实测: GPU 被自主进化训练占满时, ultralytics 默认 cuda 会抛
        #   `RuntimeError: CUDA-capable device(s) is/are busy or unavailable` ⇒ 整拍旁路挂掉。
        #   旁路是"附加观测", 绝不能因为抢占不到显存就失效 ⇒ CUDA 失败**回落 CPU 并记住**,
        #   只记一句日志(不每拍刷屏); 要强制设备用 ZMAX_GOLD_YOLO_DEVICE=cpu|xpu|cuda:0。
        _dev = os.environ.get("ZMAX_GOLD_YOLO_DEVICE")
        _kw = {"imgsz": int(os.environ.get("ZMAX_GOLD_YOLO_IMGSZ", "512")), "conf": 0.25, "verbose": False}
        if _dev:
            _kw["device"] = _dev
        elif _MODEL.get("dev_fallback"):
            _kw["device"] = "cpu"
        try:
            _rr = _model.predict(_arr, **_kw)[0]
        except RuntimeError as _ce:
            if "CUDA" not in str(_ce) and "cuda" not in str(_ce):
                raise
            _MODEL["dev_fallback"] = "cpu"
            _kw["device"] = "cpu"
            if log:
                log("🧠 金手指本机 YOLO: GPU 不可用(被训练占用?) → 回落 CPU 推理, 后续各拍沿用")
            _rr = _model.predict(_arr, **_kw)[0]
        _inf_ms = round((_t.time() - t1) * 1000, 1)
        _boxes = [{"cls": _model.names[int(_b.cls[0])], "conf": round(float(_b.conf[0]), 3),
                   "box": [round(float(v), 1) for v in _b.xyxy[0].tolist()]} for _b in _rr.boxes]
        _n = len(_boxes)
        _best = max([b["conf"] for b in _boxes], default=None)
        _present = _n > 0
        res = {"ok": True, "kind": "gold_yolo", "src": "local-yolo(yolo_gold_v2.pt)",
               "n": _n, "best_conf": _best, "present": _present, "boxes": _boxes,
               "infer_ms": _inf_ms, "grab_ms": _grab_ms,
               "img_shape": [int(_arr.shape[1]), int(_arr.shape[0])],
               "gate": os.environ.get("ZMAX_GOLD_YOLO_GATE") == "1",
               "note": None if _present else "本帧无检出 ⇒ 工件不在位或没对准(本机模型只在训练场景验证过)"}
        cache["gold_yolo"] = res
        _LAST.update({"t": _t.time(), "ms": _inf_ms, "n": _n})
        _sig = {"AOI.本机YOLO_检出数": float(_n),
                "AOI.本机YOLO_在位": 1.0 if _present else 0.0,
                "AOI.本机YOLO_推理_ms": float(_inf_ms),
                "AOI.本机YOLO_取图_ms": float(_grab_ms)}
        if _best is not None:
            _sig["AOI.本机YOLO_最高conf"] = float(_best)
        if _boxes:
            _b0 = _boxes[0]["box"]
            _sig["AOI.本机YOLO_框宽_px"] = float(_b0[2] - _b0[0])
            _sig["AOI.本机YOLO_框高_px"] = float(_b0[3] - _b0[1])
        if publish:
            publish(_sig, log)
        if log and _n != _LAST.get("_logged_n"):
            _LAST["_logged_n"] = _n
            log("🧠 金手指本机 YOLO 旁路: 检出 %d · 最高 conf %s · %sms (取图 %sms) · %s"
                % (_n, ("-" if _best is None else "%.2f" % _best), _inf_ms, _grab_ms,
                   "在位" if _present else "未在位(工件/对准)"))
        return res
    except Exception as _e:                                            # noqa: BLE001
        if log:
            log(f"⚠️ 金手指本机 YOLO 旁路异常: {type(_e).__name__}: {_e}")
        return None
