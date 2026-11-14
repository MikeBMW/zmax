# -*- coding: utf-8 -*-
"""📍 点位真源读取 (工程配置 → mm) — 规划节点统一从这里取目标点, 代码里不再留坐标常量。

老倪 2026-10-28: 「每个槽位的位置, 要通过工程配置的点读出来, 然后由 plan 节点进行规划」
  ⇒ 本模块是唯一入口: 配置改一个点 → 规划/段表跟着变; 读不到就如实报缺, 不回落常量。

三个真源 (按 frame 区分, 单位一律归一成 mm):
  1. config/points/cell_points.json            frame=sim_base · mm  · 仿真场景槽位/孔位/AOI/废料 (AR 段表用)
  2. data/skills/l2_atomic/taught_points.json  frame=base_link · 米 · 现场示教点位 (真机执行链用)
  3. config/calib/zmax_calib.json → cell_geometry.points
                                               frame=base_link · 米 · 现场示教几何 (peg_head/hole …)

铁律:
  · 单位按文件声明换算 (米 <10 ⇒ ×1000), 不做"看着像就乘"的猜测: 每份文件显式声明 units;
  · frame 不同的点**不许混用** (仿真基座系 ≠ 真机 base_link, 实测 x 差约 -157mm) —— 调用方要校验;
  · 返回值都带 src (文件:键) 与 ts, 让"这个数从哪来"可追溯到具体配置。
"""
from __future__ import annotations

import json
import os
import time

_ROOT = os.path.expanduser("~/zmax")

SOURCES = [
    {"id": "cell_points", "path": os.path.join(_ROOT, "config", "points", "cell_points.json"),
     "frame": "sim_base", "units": "mm", "desc": "仿真场景槽位/孔位/AOI/废料"},
    {"id": "taught_points", "path": os.path.join(_ROOT, "data", "skills", "l2_atomic", "taught_points.json"),
     "frame": "base_link", "units": "m", "desc": "现场示教点位"},
    {"id": "cell_geometry", "path": os.path.join(_ROOT, "config", "calib", "zmax_calib.json"),
     "frame": "base_link", "units": "m", "desc": "现场示教几何", "section": "cell_geometry.points"},
    {"id": "vision_points", "path": os.path.join(_ROOT, "zmax_data", "ss_live", "vision_points.json"),
     "frame": "base_link", "units": "mm", "desc": "L2 视觉 3D 观测点 (带 conf/err/ts)"},
]

_CACHE: dict = {}


def _load(src):
    """读一份真源, 返回 (data, age_s) 或 (None, None)。按 mtime 缓存。"""
    p = src["path"]
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return None, None
    if src["id"] in _CACHE and _CACHE[src["id"]][0] == mt:
        return _CACHE[src["id"]][1], time.time() - mt
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:                                                       # noqa: BLE001
        return None, None
    if src.get("section"):
        for part in src["section"].split("."):
            d = (d or {}).get(part) if isinstance(d, dict) else None
    _CACHE[src["id"]] = (mt, d)
    return d, time.time() - mt


def _to_mm(v, units):
    k = 1000.0 if units == "m" else 1.0
    return [round(float(x) * k, 3) for x in v[:3]]


def _iter_points(src):
    """把一份真源摊平成 [{'name','pos','quat','ts','conf','err_mm'}]。"""
    d, _age = _load(src)
    if d is None:
        return []
    out = []

    def add(name, pos, quat=None, ts=None, conf=None, err=None):
        out.append({"name": name, "pos": pos, "quat": quat, "ts": ts, "conf": conf, "err_mm": err})

    if src["id"] == "vision_points":
        for name, v in (d.get("points") or {}).items():
            if isinstance(v, dict) and isinstance(v.get("pos_mm"), (list, tuple)):
                add(v.get("id") or name, v["pos_mm"], None, v.get("ts"), v.get("conf"), v.get("err_mm"))
        return out
    if src["id"] == "cell_points":
        for s in d.get("slots") or []:
            add(s.get("name"), s.get("pos"), None, d.get("_generated_at"))
        for s in d.get("sides") or []:
            add(s.get("name"), s.get("pos"), None, d.get("_generated_at"))
        for s in d.get("scrap") or []:
            add(s.get("name"), s.get("pos"), None, d.get("_generated_at"))
        if d.get("golden"):
            add("golden", d["golden"], None, d.get("_generated_at"))
        for h in d.get("holes") or []:
            add("%s·孔口" % h.get("name"), h.get("mouth"), None, d.get("_generated_at"))
            add("%s·插到底" % h.get("name"), h.get("insert"), None, d.get("_generated_at"))
        return out
    pts = (d.get("points") or {}) if isinstance(d, dict) else {}
    if src["id"] == "cell_geometry":
        for name, v in pts.items():
            if isinstance(v, dict) and all(k in v for k in ("x", "y", "z")):
                add(name, [v["x"], v["y"], v["z"]], v.get("quat"), v.get("ts_str"))
        return out
    for name, v in pts.items():
        if isinstance(v, dict) and isinstance(v.get("pos"), (list, tuple)):
            add(name, v["pos"], v.get("quat"), v.get("ts") or v.get("recorded_at")
                or v.get("ts_str") or d.get("updated_at"))
    return out


def list_points(frame=None):
    """全部点位 (归一成 mm)。frame 给了就只列该坐标系。"""
    res = []
    for src in SOURCES:
        if frame and src["frame"] != frame:
            continue
        for it in _iter_points(src):
            name, pos = it["name"], it["pos"]
            if not name or not isinstance(pos, (list, tuple)) or len(pos) < 3:
                continue
            res.append({"name": name, "frame": src["frame"], "pos_mm": _to_mm(pos, src["units"]),
                        "quat": it["quat"], "ts": it["ts"], "conf": it.get("conf"),
                        "err_mm": it.get("err_mm"),
                        "src": "%s:%s" % (os.path.basename(src["path"]), name)})
    return res


def find(name, frame=None):
    """按名取点 (支持 '槽5' / 'slot5' / '孔2·插到底' / 'golden' / 任意示教名)。取不到给 None。"""
    key = str(name or "").strip()
    if not key:
        return None
    want = key.lower()
    for p in list_points(frame):
        if p["name"] == key or p["name"].lower() == want:
            return p
    return None


def slot(n, frame="sim_base"):
    """槽位按序号取: 槽N (sim_base) / slotN (base_link)。"""
    n = int(n)
    cand = ["槽%d" % n, "slot%d" % n]
    for p in list_points(frame):
        if p["name"] in cand:
            return p
    return None


def vision_doc():
    """视觉观测契约原文 (含 verified/gaps) —— plan 侧判"这帧够不够格"用它。"""
    for src in SOURCES:
        if src["id"] == "vision_points":
            d, _age = _load(src)
            return d
    return None


def sources_status():
    """每份真源的可用性 (给诊断/节点日志用)。"""
    out = []
    for src in SOURCES:
        d, age = _load(src)
        out.append({"id": src["id"], "path": src["path"], "frame": src["frame"], "units": src["units"],
                    "ok": d is not None, "age_s": (round(age, 1) if age is not None else None),
                    "n_points": len(_iter_points(src))})
    return out
