# -*- coding: utf-8 -*-
"""fence_store.py — AR 三维视图里画的 3D 围栏 (长方体 / 直线) 的真源 + 碰撞判定

老倪 2026-10-18: 「我需要在上面画 3D 对象, 例如长方体、正方体(输入对角线点的坐标)、直线(可编辑
起点和终点); 坐标在 base 世界系里; 这些东西是你的地图围栏, 不能碰撞」

坐标口径: **base 世界系, 单位米** (与 /api/tcp 的 x/y/z 同系)。页面上按毫米输入, 这里统一存米。

数据: zmax_data/ar_rs/fences.json
  {"items": [{"id","type":"box|line","name","p1":[x,y,z],"p2":[x,y,z],
              "color","enabled":true,"note","at"}],
   "margin_mm": 10, "at": "HH:MM:SS"}

判定:
  · box   —— 轴对齐包围盒 (AABB): 取两对角点各轴 min/max, 再按 margin 外扩
  · line  —— 线段: 点到线段距离 < radius(margin) 视为碰撞
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import uuid

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
PATH = os.path.join(REPO, "zmax_data", "ar_rs", "fences.json")
_LOCK = threading.Lock()


def _load() -> dict:
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d.get("items"), list):
            d["items"] = []
        d.setdefault("margin_mm", 10.0)
        return d
    except Exception:                                                             # noqa: BLE001
        return {"items": [], "margin_mm": 10.0}


def _save(d: dict) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    d["at"] = time.strftime("%H:%M:%S")
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATH)

# ── 回退 (undo) ──────────────────────────────────────────────────────────────
# 老倪 2026-10-27: 「刚才我不小心用鼠标挪动了料盘的位置; 增加一个回退功能; 回到上一步」
# 做法: 每次写操作**之前**把 fences.json 原样存一份 (fences_<时间戳>.json),
#      undo() 用最近一份覆盖回去。回退前也存一份 ⇒ 可以连续回退, 也能再撤回来。
HIST_DIR = os.path.join(REPO, "zmax_data", "ar_rs", "fences_history")
HIST_KEEP = 60                       # 只留最近 60 步, 防止历史把磁盘塞满


def _snapshot(action: str = "") -> None:
    """把当前 fences.json 存成一份历史快照。调用方必须已持有 _LOCK。"""
    try:
        if not os.path.exists(PATH):
            return
        os.makedirs(HIST_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S") + "_%03d" % int((time.time() % 1) * 1000)
        with open(PATH, encoding="utf-8") as f:
            raw = f.read()
        dst = os.path.join(HIST_DIR, "fences_%s.json" % ts)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(raw)
        with open(dst + ".meta", "w", encoding="utf-8") as f:
            json.dump({"action": action, "at": time.strftime("%F %T")}, f, ensure_ascii=False)
        files = sorted(x for x in os.listdir(HIST_DIR)
                       if x.startswith("fences_") and x.endswith(".json"))
        for old in files[:-HIST_KEEP]:
            for p in (os.path.join(HIST_DIR, old), os.path.join(HIST_DIR, old + ".meta")):
                try:
                    os.remove(p)
                except OSError:
                    pass
    except Exception:                                                             # noqa: BLE001
        pass                          # 快照失败不能挡住正常写操作


def history(n: int = 10) -> list:
    """最近 n 步可回退的历史 (最新在前), 给页面显示"这一步是什么操作"。"""
    try:
        files = sorted((x for x in os.listdir(HIST_DIR)
                        if x.startswith("fences_") and x.endswith(".json")), reverse=True)
    except OSError:
        return []
    out = []
    for x in files[:max(1, int(n))]:
        meta = {}
        try:
            with open(os.path.join(HIST_DIR, x + ".meta"), encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:                                                         # noqa: BLE001
            meta = {}
        out.append({"snap": x, "action": meta.get("action", ""), "at": meta.get("at", "")})
    return out


def undo(steps: int = 1) -> dict:
    """回到上一步: 用最近一份快照覆盖当前 fences.json。steps>1 一次退多步。"""
    steps = max(1, int(steps))
    with _LOCK:
        try:
            files = sorted((x for x in os.listdir(HIST_DIR)
                            if x.startswith("fences_") and x.endswith(".json")), reverse=True)
        except OSError:
            files = []
        if not files:
            return {"ok": False, "error": "没有可回退的历史"}
        target = files[min(steps, len(files)) - 1]
        src = os.path.join(HIST_DIR, target)
        try:
            with open(src, encoding="utf-8") as f:
                snap = json.load(f)
        except Exception as e:                                                    # noqa: BLE001
            return {"ok": False, "error": "快照读不出: %s" % e}
        if not isinstance(snap.get("items"), list):
            return {"ok": False, "error": "快照损坏 (没有 items)"}
        _snapshot("undo 前(可再撤回)")
        _save(snap)
        try:
            os.remove(src)
            os.remove(src + ".meta")
        except OSError:
            pass
        return {"ok": True, "restored_from": target, "n_items": len(snap["items"]),
                "at": snap.get("at", ""), "remaining": len(files) - 1}


def _norm(p1, p2):
    """盒子两对角点归一化: p1=min, p2=max (手填反/拖过头都不会出负尺寸)"""
    a, b = _f3(p1), _f3(p2)
    return [min(a[i], b[i]) for i in range(3)], [max(a[i], b[i]) for i in range(3)]


def _f3(v):
    if v is None or len(v) < 3:
        raise ValueError("需要 3 个坐标")
    return [round(float(v[0]), 6), round(float(v[1]), 6), round(float(v[2]), 6)]


def _box_bounds(it, margin_m):
    p1, p2 = it["p1"], it["p2"]
    lo = [min(p1[i], p2[i]) - margin_m for i in range(3)]
    hi = [max(p1[i], p2[i]) + margin_m for i in range(3)]
    return lo, hi


def _pt_seg_dist(p, a, b):
    ab = [b[i] - a[i] for i in range(3)]
    ap = [p[i] - a[i] for i in range(3)]
    den = sum(v * v for v in ab)
    t = 0.0 if den <= 1e-12 else max(0.0, min(1.0, sum(ap[i] * ab[i] for i in range(3)) / den))
    q = [a[i] + ab[i] * t for i in range(3)]
    return math.dist(p, q)


# ─────────────────────────── CRUD ───────────────────────────
def add(kind: str, p1, p2, name: str = "", color: str = "", note: str = "", pts=None) -> dict:
    """加一个 3D 元素。

    kind: box(轴对齐长方体) / line(线段) / points(轨迹点序列 —— 老倪 2026-10-26
    「工程配置里，对应的轨迹点，规划的轨迹点，没看到，补充上」)。
    points 只做**显示与留档**, 不进碰撞判定 (轨迹本身就是机器人要走的路, 拿它当围栏
    等于把路全堵死); check_point() 里显式跳过 type=points。
    """
    kind = (kind or "box").lower()
    if kind not in ("box", "line", "points"):
        raise ValueError("type 只能是 box / line / points")
    if kind == "points":
        if not pts or len(pts) < 2:
            raise ValueError("points 需要至少 2 个点 (pts=[[x,y,z]m,...])")
        P = [_f3(q) for q in pts]
        with _LOCK:
            _snapshot("add points")
            d = _load()
            it = {"id": "F" + uuid.uuid4().hex[:6], "type": "points",
                  "name": name or "轨迹点-%d" % (len(d["items"]) + 1),
                  "p1": P[0], "p2": P[-1], "pts": P,
                  "color": color or "#39d0ff",
                  "enabled": True, "note": note, "at": time.strftime("%F %T"),
                  "n": len(P)}
            d["items"].append(it)
            _save(d)
            return it
    with _LOCK:
        _snapshot("add %s" % kind)
        d = _load()
        it = {"id": "F" + uuid.uuid4().hex[:6], "type": kind,
              "name": name or ("长方体" if kind == "box" else "直线") + "-%d" % (len(d["items"]) + 1),
              "p1": _norm(p1, p2)[0] if kind == "box" else _f3(p1),
              "p2": _norm(p1, p2)[1] if kind == "box" else _f3(p2),
              "color": color or ("#ff9f1c" if kind == "box" else "#ff5d9e"),
              "enabled": True, "note": note, "at": time.strftime("%F %T")}
        d["items"].append(it)
        _save(d)
        return it


def update(fid: str, **kw) -> dict:
    with _LOCK:
        _snapshot("update %s" % fid)
        d = _load()
        for it in d["items"]:
            if it["id"] != fid:
                continue
            for k in ("p1", "p2"):
                if kw.get(k) is not None:
                    it[k] = _f3(kw[k])
            if it.get("type") == "box":                 # 盒子两端点归一化成 min/max (拖过头/手填反都不出错)
                it["p1"], it["p2"] = _norm(it["p1"], it["p2"])
            for k in ("name", "color", "note"):
                if kw.get(k) is not None:
                    it[k] = str(kw[k])
            if kw.get("enabled") is not None:
                it["enabled"] = bool(kw["enabled"])
            # 直线元素记住"走得通的末端姿态(deg)": 同一段直线换个腕部构型会走到一半停,
            # 记下成功那次的 abc_deg, 下次 Follow 直接沿用
            if "rpy_deg" in kw:
                v = kw["rpy_deg"]
                it["rpy_deg"] = [round(float(x), 3) for x in v] if v else None
            _save(d)
            return it
        raise KeyError("没有这个围栏: %s" % fid)


def delete(fid: str) -> dict:
    with _LOCK:
        _snapshot("delete %s" % fid)
        d = _load()
        n0 = len(d["items"])
        d["items"] = [it for it in d["items"] if it["id"] != fid]
        _save(d)
        return {"deleted": n0 - len(d["items"]), "id": fid}


def clear() -> dict:
    with _LOCK:
        _snapshot("clear all")
        d = _load()
        n = len(d["items"])
        d["items"] = []
        _save(d)
        return {"cleared": n}


def set_margin(mm: float) -> dict:
    with _LOCK:
        _snapshot("set margin %s" % mm)
        d = _load()
        d["margin_mm"] = max(0.0, float(mm))
        _save(d)
        return d


def listing() -> dict:
    d = _load()
    d["ok"] = True
    d["n"] = len(d["items"])
    return d


# ─────────────────────────── 判定 ───────────────────────────
def check_point(p, margin_mm: float | None = None) -> dict:
    """点是否落进任何启用的围栏 ⇒ {inside:[{id,name,type,dist_mm}], hit:bool}"""
    d = _load()
    mg = (d.get("margin_mm", 10.0) if margin_mm is None else float(margin_mm)) / 1000.0
    inside = []
    for it in d["items"]:
        if not it.get("enabled", True):
            continue
        if it["type"] == "points":
            continue                     # 轨迹点 = 参考路径, 不是围栏: 不参与碰撞 (否则把自己的路堵死)
        if it["type"] == "box":
            lo, hi = _box_bounds(it, mg)
            if all(lo[i] <= p[i] <= hi[i] for i in range(3)):
                # 到盒子表面最近距离 (负=在内部)
                dd = min(min(p[i] - lo[i], hi[i] - p[i]) for i in range(3))
                inside.append({"id": it["id"], "name": it["name"], "type": "box",
                               "dist_mm": round(dd * 1000, 2)})
        else:
            dist = _pt_seg_dist(p, it["p1"], it["p2"])
            if dist <= mg:
                inside.append({"id": it["id"], "name": it["name"], "type": "line",
                               "dist_mm": round(dist * 1000, 2)})
    return {"ok": True, "hit": bool(inside), "inside": inside, "n_fences": len(d["items"])}


def check_points(pts, margin_mm: float | None = None) -> dict:
    """一批点(路径)逐点判定; 返回首个命中的点序号 + 统计"""
    hits = []
    for i, p in enumerate(pts):
        r = check_point(p, margin_mm)
        if r["hit"]:
            hits.append({"i": i, "p": [round(float(v), 4) for v in p[:3]], "by": r["inside"]})
            if len(hits) >= 5:
                break
    return {"ok": True, "hit": bool(hits), "first": hits[0] if hits else None,
            "n_hits": len(hits), "n_pts": len(pts)}
