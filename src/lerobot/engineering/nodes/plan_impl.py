# -*- coding: utf-8 -*-
"""🧭 运动规划 (plan) 节点 · 真实现  (registry key = n_moveit, 源码落点 = 本文件)

老倪 2026-10-28: 「运动规划节点的源代码怎么能是 library.py 呢？应该是 plan 的代码」——
  原来 node_moveit 的实现正文写在 registry 大文件 library.py 里（而且只做了"可用性探针"），
  右键「打开源代码」自然落到 library.py。本文件就是它的**真身**：
  library.node_moveit 只剩一个薄壳转调 run()，源码映射一律指向这里。

职责: 原子技能意图 + 安全限制 → **段表 (PlanSegments)**。
      只规划，永不动作：本文件不 import 任何下发接口，不写 exec 文件，不碰授权。

真源 (只读):
  起点 = zmax_data/rokae_sdk/tcp_out/latest.json   (真机 TCP 真值, 采样器 50Hz 写: x/y/z + ts)
  目标 = ctx["in1"]                                ({"tcp":[x,y,z]} / {"pos":[..]} / [x,y,z])
  安全 = ctx["in2"]                                ({"max_step_mm":50,"max_down_mm":20,...})

口径 (实测过、写在台账里的那套):
  · 起点年龄 > ZMAX_PLAN_STALE_S(默认 2s) ⇒ **拒出段表**，如实报 stale —— 绝不拿旧位姿规划；
  · 后端 rule(确定性): 抬升 → 横移 → 下落 → 末端对位；绕奇异/避碰先抬 LIFT_MM；
    单步 ≤ max_step_mm，向下段 ≤ max_down_mm (与执行器守卫同一口径)；
  · moveit 后端只在 move_group 真可用时报 available，**不冒充**能规划 (MoveItPlan.plan 目前只是探针)；
  · 每段带 abs_mm (= 段终点的绝对坐标 mm) —— l2_daemon 段表要求带绝对坐标。
"""
from __future__ import annotations

import json
import os
import time

_ROOT = os.path.expanduser("~/zmax")
_TCP = os.path.join(_ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
STALE_S = float(os.environ.get("ZMAX_PLAN_STALE_S", "2.0"))
DEF_STEP = 50.0          # mm · 单步上限 (执行器守卫口径)
DEF_DOWN = 20.0          # mm · 向下单步上限
LIFT_MM = 50.0           # mm · 抬升量 (绕奇异 50102 / 避碰的安全高度增量)
MAX_SEGS = 40
MIN_CONF = float(os.environ.get("ZMAX_PLAN_MIN_CONF", "0.7"))    # 视觉观测点最低置信度
OBS_STALE_S = float(os.environ.get("ZMAX_PLAN_OBS_STALE_S", "2.0"))  # 视觉观测点最长时效

LAST_STATUS = ""


# ── 真值 / 输入 ─────────────────────────────────────────────────────────────
def _tcp_now():
    """真机当前 TCP 末端的 (x,y,z, age_s)，单位统一成 **mm**；读不到给 (None, None)。

    ⚠️ latest.json 里的 x/y/z 是**米**(真机 SDK 口径)，而段表/执行器要的是 mm ⇒ 这里 ×1000。
    只读，不动臂。
    """
    try:
        with open(_TCP, encoding="utf-8") as fh:
            d = json.load(fh)
        age = time.time() - float(d.get("ts") or 0)
        p = [float(d.get("x")) * 1000.0, float(d.get("y")) * 1000.0, float(d.get("z")) * 1000.0]
        return p, age
    except Exception:                                                       # noqa: BLE001
        return None, None


def _as_point(v):
    """把裸坐标写法归一成 [x,y,z] mm；认不出给 None。"""
    if v is None:
        return None
    if isinstance(v, dict):
        for k in ("tcp", "pos", "xyz", "target", "goal", "to"):
            if k in v:
                r = _as_point(v[k])
                if r:
                    return r
        if all(k in v for k in ("x", "y", "z")):
            return [float(v["x"]), float(v["y"]), float(v["z"])]
        return None
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        try:
            return [float(v[0]), float(v[1]), float(v[2])]
        except Exception:                                                   # noqa: BLE001
            return None
    return None


def _ps():
    """取 points_source (包内相对导入; 单独跑脚本时补 sys.path)。"""
    try:
        from . import points_source as PS                                      # noqa: PLC0415
    except ImportError:
        import sys                                                             # noqa: PLC0415
        sys.path.insert(0, os.path.join(_ROOT, "src"))
        from lerobot.engineering.nodes import points_source as PS              # noqa: PLC0415
    return PS


def _target(ctx, start_frame="base_link"):
    """目标点: 优先按**工程配置里的点名/槽号**取 (§老倪 2026-10-28), 也接受裸坐标。

    认这几种写法 (ctx["in1"].value):
      {"point": "slot5"} / {"point": "槽5", "frame": "sim_base"} / {"slot": 5} / {"slot": 5, "frame":"base_link"}
      {"tcp": [x,y,z]} / [x,y,z]                    ← 裸坐标, 视为 base_link
    返回 {"pos": [mm], "frame", "src", "name", "ts"} ; 取不到给 {"error": ...}。
    """
    PS = _ps()
    v = ((ctx or {}).get("in1") or {}).get("value")
    if isinstance(v, dict):
        frame = v.get("frame") or start_frame
        _obs = v.get("obs")
        if not _obs and isinstance(v.get("point"), str) and v["point"].startswith("obs:"):
            _obs = v["point"][4:]
        if _obs:
            p = PS.find(_obs, frame=frame)
            if not p:
                return {"error": "obs_not_found", "want": _obs, "frame": frame}
            return {"pos": p["pos_mm"], "frame": p["frame"], "src": p["src"], "name": p["name"],
                    "ts": p.get("ts"), "conf": p.get("conf"), "err_mm": p.get("err_mm"), "is_obs": True}
        if v.get("point"):
            p = PS.find(v["point"], frame=frame)
            if not p:
                return {"error": "point_not_found", "want": v["point"], "frame": frame}
            return {"pos": p["pos_mm"], "frame": p["frame"], "src": p["src"],
                    "name": p["name"], "ts": p.get("ts")}
        if v.get("slot") is not None:
            try:
                p = PS.slot(int(v["slot"]), frame=frame)
            except Exception:                                                # noqa: BLE001
                p = None
            if not p:
                return {"error": "slot_not_found", "want": v["slot"], "frame": frame}
            return {"pos": p["pos_mm"], "frame": p["frame"], "src": p["src"],
                    "name": p["name"], "ts": p.get("ts")}
    r = _as_point(v)
    if r:
        return {"pos": r, "frame": start_frame, "src": "in1(裸坐标)", "name": None, "ts": None}
    return None


def _limits(ctx):
    v = ((ctx or {}).get("in2") or {}).get("value") or {}
    if not isinstance(v, dict):
        v = {}
    return {"step": float(v.get("max_step_mm") or DEF_STEP),
            "down": float(v.get("max_down_mm") or DEF_DOWN)}


# ── 确定性分段 (rule 后端) ──────────────────────────────────────────────────
def _split(a, b, cap):
    """把 a→b 按长度上限 cap 均分，返回 [(起, 终), …]（不含起点的重复）。"""
    d = [b[i] - a[i] for i in range(3)]
    dist = (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5
    if dist <= 1e-9:
        return []
    n = max(1, int(-(-dist // max(cap, 1e-6))))          # ceil
    return [([a[i] + d[i] * k / n for i in range(3)],
             [a[i] + d[i] * (k + 1) / n for i in range(3)]) for k in range(n)]


def _segments(start, goal, lim):
    """抬升 → 横移 → 下落 → 对位。第三分量 = 高度(mm)，与段表/画布口径一致。"""
    x0, y0, z0 = start
    x1, y1, z1 = goal
    segs = []

    def add(kind, a, b):
        segs.append({"i": len(segs) + 1, "kind": kind,
                     "a": [round(v, 2) for v in a], "b": [round(v, 2) for v in b],
                     "abs_mm": [round(v, 2) for v in b],
                     "len_mm": round(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2
                                      + (b[2] - a[2]) ** 2) ** 0.5, 2)})

    flat = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    # ① 抬到安全高度 (原地) —— 水平要走且现在不高, 就先抬; 已在安全高度以上则跳过
    h_safe = max(z0, z1) + (LIFT_MM if flat > 1.0 else 0.0)
    if h_safe - z0 > 0.5:
        for a, b in _split([x0, y0, z0], [x0, y0, h_safe], lim["step"]):
            add("lift", a, b)
    # ② 横移 (保持安全高度)
    if flat > 0.5:
        for a, b in _split([x0, y0, max(z0, h_safe)], [x1, y1, max(z0, h_safe)], lim["step"]):
            add("move", a, b)
    # ③ 下落 (向下单步受 max_down_mm 限)
    z_from = max(z0, h_safe)
    if z_from - z1 > 0.5:
        for a, b in _split([x1, y1, z_from], [x1, y1, z1], lim["down"]):
            add("down", a, b)
    return segs[:MAX_SEGS]


# ── 节点入口 (registry / middleware 都调它) ─────────────────────────────────
def run(ctx=None):
    """一个周期: 起点(真值) + 目标(意图) + 安全限制 → 段表。只规划，不下发。"""
    global LAST_STATUS
    out = {"node": "n_moveit", "impl": "nodes/plan_impl.py:run"}
    start, age = _tcp_now()
    if start:
        out["start"] = [round(v, 2) for v in start]
        out["start_age_s"] = (round(age, 2) if age is not None else None)
    tgt = _target(ctx)
    goal = (tgt or {}).get("pos") if isinstance(tgt, dict) else None
    lim = _limits(ctx)
    out["limits"] = lim
    if isinstance(tgt, dict) and tgt.get("pos"):
        out.update({"goal_src": tgt.get("src"), "goal_frame": tgt.get("frame"),
                    "goal_name": tgt.get("name"), "goal_ts": tgt.get("ts"),
                    "goal_conf": tgt.get("conf"), "goal_err_mm": tgt.get("err_mm")})

    # moveit 只报可用性 (MoveItPlan.plan 是探针, 不冒充能规划)
    try:
        from lerobot.arm.arm_control import MoveItPlan                    # noqa: PLC0415
        out["moveit"] = MoveItPlan.plan([0, 0, 0], [0, 0, 0])
    except Exception as e:                                                   # noqa: BLE001
        out["moveit"] = {"available": False, "note": "读不到 MoveItPlan: %s" % type(e).__name__}

    # ① 起点不可用 / 陈旧 ⇒ 拒出段表 (不许拿旧位姿规划)
    if not start:
        LAST_STATUS = "无真机 TCP 真值 (%s 读不到) ⇒ 不出段表" % _TCP
        out.update({"ok": False, "reason": "no_tcp", "backend": "rule", "segments": [], "n": 0})
        print("[plan 节点] " + LAST_STATUS)
        return out
    if age is not None and age > STALE_S:
        LAST_STATUS = "起点陈旧 (%.1fs > %.1fs) ⇒ 不出段表" % (age, STALE_S)
        out.update({"ok": False, "reason": "tcp_stale", "backend": "rule", "segments": [], "n": 0})
        print("[plan 节点] " + LAST_STATUS)
        return out
    # ①b 目标点取不到 / 坐标系不符 ⇒ 拒出段表 (仿真基座系 ≠ 真机 base_link, 不许混用)
    if isinstance(tgt, dict) and tgt.get("error"):
        LAST_STATUS = ("目标点取不到 (%s: %s, frame=%s) ⇒ 不出段表"
                       % (tgt.get("error"), tgt.get("want"), tgt.get("frame")))
        out.update({"ok": False, "reason": tgt.get("error"), "backend": "rule", "segments": [], "n": 0})
        print("[plan 节点] " + LAST_STATUS)
        return out
    if goal and str((tgt or {}).get("frame") or "base_link") != "base_link":
        LAST_STATUS = ("目标点在 %s 系, 起点是真机 base_link ⇒ 不混用坐标系, 不出段表"
                       % (tgt or {}).get("frame"))
        out.update({"ok": False, "reason": "frame_mismatch", "backend": "rule", "segments": [], "n": 0})
        print("[plan 节点] " + LAST_STATUS)
        return out
    # ①c 视觉观测点三道闸: 未取证(verified=false) / 置信度 / 时效
    if isinstance(tgt, dict) and tgt.get("is_obs"):
        _vd = _ps().vision_doc()
        if _vd is not None and _vd.get("verified") is False:
            LAST_STATUS = ("观测点未取证 (frame=%s · gaps=%s) ⇒ 不出段表"
                           % (_vd.get("frame"), (_vd.get("source") or {}).get("gaps")))
            out.update({"ok": False, "reason": "obs_unverified", "backend": "rule",
                        "segments": [], "n": 0})
            print("[plan 节点] " + LAST_STATUS)
            return out
    # ①c' 置信度/时效两道闸: 置信度不足 / 观测超龄 ⇒ 拒出段表 (不猜, 不按旧点硬规划)
    if isinstance(tgt, dict) and tgt.get("is_obs"):
        _conf = tgt.get("conf")
        if _conf is None or float(_conf) < MIN_CONF:
            LAST_STATUS = ("观测点置信度不足 (conf=%s < %.2f, 源 %s) ⇒ 不出段表"
                           % (_conf, MIN_CONF, tgt.get("src")))
            out.update({"ok": False, "reason": "low_conf", "backend": "rule", "segments": [], "n": 0})
            print("[plan 节点] " + LAST_STATUS)
            return out
        _age = (time.time() - float(tgt.get("ts") or 0)) if tgt.get("ts") else None
        if _age is None or _age > OBS_STALE_S:
            LAST_STATUS = ("观测点超龄 (%.1fs > %.1fs, 源 %s) ⇒ 不出段表"
                           % ((_age if _age is not None else -1), OBS_STALE_S, tgt.get("src")))
            out.update({"ok": False, "reason": "obs_stale", "backend": "rule", "segments": [], "n": 0})
            print("[plan 节点] " + LAST_STATUS)
            return out
    # ② 没有目标 ⇒ 只报可用性 (与原探针行为一致, 但不假装规划了)
    if not goal:
        LAST_STATUS = "无目标(只报可用性) · 起点 %.0f,%.0f,%.0f · 真机零指令" % tuple(start)
        out.update({"ok": True, "backend": "rule", "segments": [], "n": 0,
                    "note": "in1 没给目标 ⇒ 段表为空"})
        print("[plan 节点] " + LAST_STATUS)
        return out
    # ③ 真出段表
    segs = _segments(start, goal, lim)
    out.update({"ok": True, "backend": "rule", "goal": [round(v, 2) for v in goal],
                "segments": segs, "n": len(segs),
                "total_mm": round(sum(s["len_mm"] for s in segs), 1),
                "note": "确定性分段(抬升→横移→下落) · 只规划, 不动真机"})
    LAST_STATUS = ("段表 %d 段 / %.0fmm · 起点年龄 %.2fs · 单步≤%.0fmm 向下≤%.0fmm"
                   % (len(segs), out["total_mm"], (age or 0.0), lim["step"], lim["down"]))
    out["status"] = LAST_STATUS
    print("[plan 节点] " + LAST_STATUS)
    return out


def status():
    return LAST_STATUS
