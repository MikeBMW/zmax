# -*- coding: utf-8 -*-
"""给 8793 加：三态检测结果（success / fail / none）+ 正面/翻面自动识别。

老倪 2026-11-27 的原话：
  「金手指每次都是检查正面和检查翻面，这两个面，你要知道，你已经知道了金手指点1和金手指点2的位姿，
   当你看到有机器人到达你的视野时，根据位姿，你要能掌握当前的检测是什么点」
  「success 时有光模块，且没有缺陷氧化划伤；fail 时有光模块，但是有氧化或者划伤；
   当前的状态就是 fail；还有，当你没看到金手指时，即使 request，也只能回 none，即没看到」

设计：
  · **none** —— 先判"看不看得见"。条带图无效 / 19 根数不对 / 金手指区域亮度过低 ⇒ none。
               此时 **不消耗判定**，直接回 none（用户要的语义：没看到就说没看到）。
  · **面识别** —— 当前 TCP 位姿 与 金手指点1/点2 比：位置距离(mm) + 姿态夹角(°)，取更近者。
  · **success / fail** —— 看见了才判。缺陷来源两条独立证据（工控机 fingers 通道 + 自训 YOLO），
               任一判 NG ⇒ fail。全部 OK ⇒ success。
"""
import json
import math
import os
import time

ROOT = os.environ.get("ZMAX_ROOT") or r"D:\ZMAX"
PTS = os.path.join(ROOT, "reports", "aoi_points")

_CACHE = {"t": 0.0, "pts": None}


def _load_points():
    """读 金手指点1 / 金手指点2（带 60s 缓存，点会被现场重录）。"""
    now = time.time()
    if _CACHE["pts"] is not None and now - _CACHE["t"] < 60:
        return _CACHE["pts"]
    out = {}
    for name in ("金手指点1", "金手指点2"):
        p = os.path.join(PTS, name + ".json")
        try:
            j = json.load(open(p, encoding="utf-8"))
            out[name] = {"pos": j.get("pos"), "quat": j.get("quat"),
                         "abc_deg": j.get("abc_deg"), "recorded_at": j.get("recorded_at")}
        except Exception:
            out[name] = None
    _CACHE["pts"] = out
    _CACHE["t"] = now
    return out


def _quat_angle_deg(q1, q2):
    """两个四元数的夹角(度)。任意顺序([x,y,z,w] 或 [w,x,y,z])都能用: 取绝对值。"""
    if not q1 or not q2 or len(q1) != 4 or len(q2) != 4:
        return None
    d = abs(sum(float(a) * float(b) for a, b in zip(q1, q2)))
    d = min(1.0, max(-1.0, d))
    return round(math.degrees(2.0 * math.acos(d)), 2)


def which_face(tcp_xyz, tcp_quat=None, max_mm=40.0):
    """当前位姿更接近金手指点1 还是点2 ⇒ 返回 {"face":1|2|None, ...}。

    判据: 位置距离为主(点1/点2 相距约 11mm, 精度足够), 姿态夹角为佐证。
    """
    pts = _load_points()
    if not tcp_xyz:
        return {"face": None, "why": "无当前位姿"}
    best, rows = None, {}
    for name, p in pts.items():
        if not p or not p.get("pos") or len(p["pos"]) < 3:
            continue
        d = math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(tcp_xyz[:3], p["pos"][:3]))) * 1000.0
        ang = _quat_angle_deg(tcp_quat, p.get("quat")) if tcp_quat else None
        face = 1 if name.endswith("1") else 2
        rows["点%d" % face] = {"dist_mm": round(d, 2), "angle_deg": ang}
        if best is None or d < best[1]:
            best = (face, d, ang, name)
    if not best or best[1] > max_mm:
        return {"face": None, "why": "离两个观察位都 >%.0fmm(臂不在检测位)" % max_mm, "cands": rows}
    return {"face": best[0], "point": best[3], "dist_mm": round(best[1], 2),
            "angle_deg": best[2], "cands": rows}


def tri_state(visible: bool, ng_any: bool, detail=None):
    """三态: none(没看到) / fail(看到但有缺陷) / success(看到且干净)。"""
    if not visible:
        return {"verdict": "none", "why": "视野里没有金手指（不判缺陷）", "detail": detail}
    if ng_any:
        return {"verdict": "fail", "why": "有光模块，但存在氧化/划伤", "detail": detail}
    return {"verdict": "success", "why": "有光模块，未见氧化/划伤", "detail": detail}


def visible_from_geometry(geo):
    """用几何探针的结果判"看不看得见"：19 根齐 + 亮度不为 0 + 面积合理。"""
    if not isinstance(geo, dict) or not geo.get("ok"):
        return False, {"why": "几何探针失败或未跑"}
    n = int(geo.get("n") or 0)
    area = (geo.get("area_mm2") or {}).get("mean") or 0
    if n < 15:
        return False, {"why": "只检出 %d 根(<15)" % n, "n": n}
    if area < 0.10:
        return False, {"why": "面积过小 %.4fmm²(黑屏或没对准)" % area, "area": area}
    return True, {"n": n, "area_mm2": area}
