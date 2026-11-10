# -*- coding: utf-8 -*-
"""inject_cfg.py — 动作注入度规的**参数读取**（真源：config/calib/zmax_manifold.json）

为什么单独一个文件
------------------
`geodesic_inject.py` 的契约是**纯函数**（不读写文件、不 import 中间件），这样它才能被
离线验证脚本、真机、仿真三处共用而不带副作用。参数读取放在这里，只做一件事：
从标定真源读 `inject` 段，缓存，给调用方一个 dict。

真源唯一性
----------
`config/calib/zmax_manifold.json` 是流形标定**单一唯一依据**（见该文件 `_doc`）。
同一个文件里有两段度规，是同一思想的两个层次：

    metric  → 状态空间度规：状态怎么走（测地线 ẍ = −Γẋẋ + g⁻¹F）
    inject  → 动作空间度规：动作往哪个方向修（Δξ = −α·M_act⁻¹∇V）

**不要**在本文件里写死任何数值 —— 缺项一律返回 None 并说明，让调用方降级，
而不是拿一个"看起来合理"的默认值顶上去（那会让标定真源失去意义）。
"""
from __future__ import annotations

import json
import os
import threading
import time

_LOCK = threading.Lock()
_CACHE = {"t": 0.0, "path": None, "cfg": None, "err": None, "mtime": None}
_TTL_S = 5.0


def _repo_root() -> str:
    # policies/manifold/inject_cfg.py → policies → lerobot → src → repo
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def src_path() -> str:
    return os.path.join(_repo_root(), "config", "calib", "zmax_manifold.json")


def _read(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        d = json.load(f) or {}
    inj = d.get("inject")
    if not isinstance(inj, dict):
        return {"_missing": "真源无 inject 段", "_src": path}
    return inj


def load(force: bool = False) -> dict:
    """读注入度规参数。返回 dict（含 `_src` 溯源）；失败时含 `_err`。

    缓存 5s 或文件 mtime 变化即重读 —— 现场改标定不用重启常驻进程。
    数值键: sigma_t / sigma_n / alpha0 / V0 / max_ratio / cap_min_mm / eps_mm / eta_floor
            enabled
    """
    p = src_path()
    try:
        mt = os.path.getmtime(p)
    except OSError as e:
        return {"_err": "真源不存在: %s" % e, "_src": p}

    with _LOCK:
        fresh = (not force and _CACHE["cfg"] is not None
                 and _CACHE["path"] == p and _CACHE["mtime"] == mt
                 and (time.time() - _CACHE["t"]) < _TTL_S)
        if fresh:
            return dict(_CACHE["cfg"])
    try:
        cfg = _read(p)
        cfg["_src"] = os.path.relpath(p, _repo_root())
    except Exception as e:                                          # noqa: BLE001
        cfg = {"_err": "%s: %s" % (type(e).__name__, e), "_src": p}
    with _LOCK:
        _CACHE.update({"t": time.time(), "path": p, "cfg": cfg, "mtime": mt,
                       "err": cfg.get("_err")})
        return dict(cfg)


def geometry(cfg: dict | None = None) -> dict:
    """只取几何/门控参数，给 `geodesic_inject.correct()` 用。

    缺 sigma_t 或 sigma_n ⇒ 返回 {}（调用方据此判"未标定，不注入"），
    **不填默认值** —— 否则标定真源形同虚设。
    """
    c = cfg if cfg is not None else load()
    keys = ("sigma_t", "sigma_n", "alpha0", "V0", "max_ratio",
            "cap_min_mm", "eps_mm", "eta_floor")
    out = {}
    for k in keys:
        v = c.get(k)
        if isinstance(v, (int, float)):
            out[k] = float(v)
    if "sigma_t" not in out or "sigma_n" not in out:
        return {}
    return out


def enabled(cfg: dict | None = None) -> bool:
    c = cfg if cfg is not None else load()
    return bool(c.get("enabled", True)) and not c.get("_missing") and not c.get("_err")


__all__ = ["load", "geometry", "enabled", "src_path"]
