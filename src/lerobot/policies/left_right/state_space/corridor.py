"""原子技能 · 3D 约束通道 (corridor) —— 把运动学/动力学约束落到"几何通道"上

老倪 2026-10-31: 「根据 3D 坐标信息和动作状态、节拍, 调整运动学和动力学约束, 实现根据 3D 坐标
就能把每个原子动作都约束在有效的约束通道之内; 每个技能的通道边界要画到 AR 场景里。」

口径 (与 atomic_skills.clamp 的 ①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤单拍位移 同一套数字):
  · 通道 = 一段 3D 圆柱: 轴 A→B (mm), 半径 r_mm (来自工艺间隙/标定, 不是拍脑袋的唯一来源),
    轴长 L_mm。
  · 每拍把动作拆成 **轴向** (沿 A→B) 与 **横向** (垂直轴) 两个分量分别约束:
      轴向: s 越界 (s<0 或 s>L) ⇒ 轴向速度归零/回拉; v_along ≤ min(v_cap, L/tact)。
      横向: dev_mm > r ⇒ 产生回中的横向速度 (速率 = 超出量/dt, 上限 a_max·dt),
            并把向外的横向速度整段切掉 ⇒ 下一拍一定回到通道内。
  · 节拍 (tact_s) 参与: ticks = tact/dt, 单拍允许行程 s_tick = min(s_step, L/ticks),
    所以"节拍越快通道越紧"是同一套公式的自动结果, 不需要另设一套参数。

单位: 对外一律 mm (pos/a/b); 速度 m/s (与技能 clamp 输出一致); dt s。
纯函数, 无 IO/无 Qt/无 numpy 依赖 (只用 math), 便于在引擎/画布/GUI/工具里同源调用。
"""
from __future__ import annotations

import math
import os

# 每段的通道半径 (mm) —— 工艺间隙/标定留白; 标定好后由 config/calib/zmax_corridor.json 覆盖
DEFAULT_R_MM = {
    "接近": 25.0,
    "对位": 8.0,
    "下降": 4.0,
    "抓取": 2.0,
    "抬起": 25.0,
    "转移": 20.0,
    "插入": 1.5,
    "拔出": 3.0,
    "AOI转移": 20.0,
    "AOI检测": 10.0,
    "回程": 25.0,
    "放下": 4.0,
    "放入": 4.0,
    "完成": 5.0,
}


def _sub(a, b):
    return [float(a[0]) - float(b[0]), float(a[1]) - float(b[1]), float(a[2]) - float(b[2])]


def _add(a, b):
    return [float(a[0]) + float(b[0]), float(a[1]) + float(b[1]), float(a[2]) + float(b[2])]


def _mul(a, k):
    return [float(a[0]) * k, float(a[1]) * k, float(a[2]) * k]


def _dot(a, b):
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1]) + float(a[2]) * float(b[2])


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a, fallback=(0.0, 0.0, 1.0)):
    n = _norm(a)
    if n < 1e-9:
        return list(fallback)
    return [float(a[0]) / n, float(a[1]) / n, float(a[2]) / n]


def _perp_basis(u):
    """给轴向 u 造两个正交基 (横向平面), 用于算横向偏差/画通道四边。"""
    ref = [0.0, 0.0, 1.0] if abs(u[2]) < 0.9 else [1.0, 0.0, 0.0]
    e1 = _unit([u[1] * ref[2] - u[2] * ref[1],
                u[2] * ref[0] - u[0] * ref[2],
                u[0] * ref[1] - u[1] * ref[0]])
    e2 = _unit([u[1] * e1[2] - u[2] * e1[1],
                u[2] * e1[0] - u[0] * e1[2],
                u[0] * e1[1] - u[1] * e1[0]])
    return e1, e2


def radius_mm(stage: str, r_override=None) -> float:
    if r_override is not None:
        return float(r_override)
    try:
        p = os.environ.get("ZMAX_CORRIDOR_CALIB") or ""
        if p and os.path.isfile(p):
            import json
            d = json.load(open(p, encoding="utf-8"))
            v = (d.get("radius_mm") or {}).get(str(stage))
            if v is not None:
                return float(v)
    except Exception:                                                      # noqa: BLE001
        pass
    return float(DEFAULT_R_MM.get(str(stage), 10.0))


def build(stage, a_mm, b_mm, *, v_cap=0.35, a_max=4.166667, jerk_max=15.0,
          s_step_m=0.035, dt=0.1, tact_s=None, r_mm=None):
    """造一条通道: 轴/长度/半径 + 由约束和节拍算出的每拍预算。"""
    a = [float(x) for x in a_mm[:3]]
    b = [float(x) for x in b_mm[:3]]
    d = _sub(b, a)
    L = _norm(d)
    u = _unit(d)
    e1, e2 = _perp_basis(u)
    r = radius_mm(stage, r_mm)
    dt = float(dt) or 0.1
    ticks = max(1, int(round((float(tact_s) / dt))) if tact_s else 1)
    # 轴向速度上限: 既要满足拍数预算, 又不能超过 v_cap
    v_along_cap = float(v_cap)
    if tact_s and L > 0:
        v_along_cap = min(v_along_cap, (L / 1000.0) / max(float(tact_s), dt))
    s_tick_mm = min(float(s_step_m) * 1000.0, (L / ticks) if L > 0 else float(s_step_m) * 1000.0)
    return {
        "stage": str(stage), "a": a, "b": b, "axis": u, "e1": e1, "e2": e2,
        "L_mm": round(L, 3), "r_mm": round(r, 3), "dt": dt, "ticks": ticks,
        "tact_s": (round(float(tact_s), 3) if tact_s else None),
        "v_cap": round(float(v_cap), 4), "v_along_cap": round(v_along_cap, 5),
        "a_max": round(float(a_max), 4), "jerk_max": round(float(jerk_max), 3),
        "s_tick_mm": round(s_tick_mm, 3),
    }


def poly_axis(pts):
    """折线通道: 返回 (总长 mm, 段轴列表)。pts 为 mm 点列。"""
    segs = []
    L = 0.0
    for i in range(len(pts) - 1):
        d = _sub(pts[i + 1], pts[i])
        n = _norm(d)
        if n < 1e-9:
            continue
        segs.append((pts[i], _unit(d), n))
        L += n
    return L, segs


def closest_on_poly(pts, pos):
    """pos 到折线的最近点: 返回 (dev_mm, s_mm, axis_of_seg)。s 沿折线累计。"""
    L, segs = poly_axis(pts)
    best = (1e18, 0.0, _unit(_sub(pts[-1], pts[0])) if len(pts) > 1 else (0.0, 0.0, 1.0))
    acc = 0.0
    for p0, ax, n in segs:
        rel = _sub(pos, p0)
        t = max(0.0, min(n, _dot(rel, ax)))
        d = _norm(_sub(rel, _mul(ax, t)))
        if d < best[0]:
            best = (d, acc + t, ax)
        acc += n
    return best


def build_poly(stage, pts_mm, *, r_mm=None, v_cap=0.35, a_max=4.166667, tact_s=None,
               dmdt=0.1, m_kg=1.2, f_max_n=5.0, dt=0.1):
    """按**实际轨迹折线**建通道: pts 是这台机器真实走过的点 (不是编的端到端直线)。

    通道 = 折线的扫掠包络: 轴心 = 实际轨迹, 半径 = 工具/工件外廓 (r_mm)。
    这样"通道外表面"就是实际运动轨迹的包络面, 机器人只能在这个面内跑。
    """
    _raw = [[float(p[0]), float(p[1]), float(p[2])] for p in pts_mm]
    pts = [_raw[0]]                              # 去重相邻同点 (零长度段会让端环基向量退化成 0)
    for q in _raw[1:]:
        if _norm(_sub(q, pts[-1])) > 1e-6:
            pts.append(q)
    if len(pts) < 2:
        raise ValueError("折线至少 2 个不同点")
    L, segs = poly_axis(pts)
    axis = _unit(_sub(pts[-1], pts[0]))
    r = float(r_override if (r_override := r_mm) is not None else radius_mm(stage))
    tact = float(tact_s) if tact_s else None
    v_along_cap = float(v_cap)
    if tact and tact > 0:
        v_along_cap = min(v_along_cap, (L / 1000.0) / tact)
    s_tick = 0.035 * 1000.0
    if tact and tact > 0:
        ticks = max(1.0, tact / dt)
        s_tick = min(s_tick, L / ticks)
    e1, e2 = _perp_basis(axis)
    return {"stage": stage, "pts": pts, "n_seg": len(segs), "a": pts[0], "b": pts[-1],
            "axis": list(axis), "e1": list(e1), "e2": list(e2), "L_mm": round(L, 3),
            "r_mm": r, "tact_s": tact, "v_cap": v_cap, "a_max": a_max,
            "v_along_cap": round(v_along_cap, 5), "s_tick_mm": round(s_tick, 3), "dt": dt}


def closest_on_polys(polys, pos):
    """pos 到**多条**折线(同一技能的全部实际机动)的最近点: 返回 (dev_mm, s_mm, axis, k)。"""
    best = (1e18, 0.0, (0.0, 0.0, 1.0), 0)
    for k, pts in enumerate(polys):
        d, s, ax = closest_on_poly(pts, pos)
        if d < best[0]:
            best = (d, s, ax, k)
    return best


def build_polys(stage, polys_mm, *, r_mm=None, v_cap=0.35, a_max=4.166667, tact_s=None, dt=0.1):
    """一条技能 = 多段**实际机动**的包络集合 (例如 14 次下降各在一个槽位)。

    通道 = ∪ 每条实际折线的扫掠包络; 机器人任何一次该动作都只能落在自己的那条管子里。
    """
    polys = []
    for pts in polys_mm:
        clean = [[float(p[0]), float(p[1]), float(p[2])] for p in pts]
        ded = [clean[0]]
        for q in clean[1:]:
            if _norm(_sub(q, ded[-1])) > 1e-6:
                ded.append(q)
        if len(ded) >= 2:
            polys.append(ded)
    if not polys:
        raise ValueError("没有有效折线")
    L = sum(poly_axis(pl)[0] for pl in polys)
    r = float(r_mm if r_mm is not None else radius_mm(stage))
    tact = float(tact_s) if tact_s else None
    v_along_cap = float(v_cap)
    if tact and tact > 0:
        v_along_cap = min(v_along_cap, (L / 1000.0) / tact)
    s_tick = 0.035 * 1000.0
    if tact and tact > 0:
        s_tick = min(s_tick, max(0.2, L / max(1.0, tact / dt)))
    a, b = polys[0][0], polys[-1][-1]
    axis = _unit(_sub(b, a))
    e1, e2 = _perp_basis(axis)
    return {"stage": stage, "polys": polys, "n_poly": len(polys), "a": a, "b": b,
            "pts": polys[0], "axis": list(axis), "e1": list(e1), "e2": list(e2),
            "L_mm": round(L, 3), "r_mm": r, "tact_s": tact, "v_cap": v_cap, "a_max": a_max,
            "v_along_cap": round(v_along_cap, 5), "s_tick_mm": round(s_tick, 3), "dt": dt}


def edges(corr, n_side=4):
    """通道边界线 (给 AR 场景画): 轴 1 条 + 四边 n_side 条。返回 [(p1_mm, p2_mm, kind)]"""
    a, b = corr["a"], corr["b"]
    r = float(corr["r_mm"])
    out = [(list(a), list(b), "axis")]
    for k in range(n_side):
        ang = 2.0 * math.pi * k / max(1, n_side)
        off = _add(_mul(corr["e1"], r * math.cos(ang)), _mul(corr["e2"], r * math.sin(ang)))
        out.append((_add(a, off), _add(b, off), "edge"))
    return out


def project_stage(stage, u, pos_mm, corr, *, dt=None, v_prev=None):
    """把动作 (m/s, 前三维) 投影进通道。返回 (u_out, info)。

    info: in_channel / dev_mm / s_mm / why / r_mm / L_mm / tick_mm —— 逐个技能可核。
    """
    dt = float(dt or corr.get("dt") or 0.1)
    v = [float(u[0]), float(u[1]), float(u[2])]
    r = float(corr["r_mm"])
    L = float(corr["L_mm"])
    if corr.get("polys"):                              # 🔵 多段实际机动的包络集合
        dev, s, ax, _k = closest_on_polys(corr["polys"], pos_mm)
        pts_best = corr["polys"][_k]
        acc, cp = 0.0, pts_best[0]
        for p0, axx, n in poly_axis(pts_best)[1]:
            if s <= acc + n + 1e-9:
                cp = _add(p0, _mul(axx, max(0.0, min(n, s - acc))))
                ax = axx
                break
            acc += n
        lat = _sub(pos_mm, cp)
    elif corr.get("pts"):                              # 🔵 折线包络通道 (实际轨迹)
        dev, s, ax = closest_on_poly(corr["pts"], pos_mm)
        acc, cp = 0.0, corr["pts"][0]
        for p0, axx, n in poly_axis(corr["pts"])[1]:
            if s <= acc + n + 1e-9:
                cp = _add(p0, _mul(axx, max(0.0, min(n, s - acc))))
                ax = axx
                break
            acc += n
        lat = _sub(pos_mm, cp)
    else:                                              # 直线通道 (旧口径, 兼容)
        a = corr["a"]
        ax = corr["axis"]
        rel = _sub(pos_mm, a)
        s = _dot(rel, ax)                                  # 轴向已走 (mm)
        lat = _sub(rel, _mul(ax, s))                       # 横向偏差矢量 (mm)
        dev = _norm(lat)
    why = []
    v_along = _dot(v, ax)
    v_lat = _sub(v, _mul(ax, v_along))
    # ① 轴向: s<0 还没进通道 / s>L 已过终点 ⇒ 轴向归零 (不许继续冲)
    if s < 0.0 and v_along < 0:
        v_along = 0.0
        why.append("通道·未入轴")
    elif s > L and v_along > 0:
        v_along = 0.0
        why.append("通道·已过终点")
    # ② 轴向速度上限 (节拍预算)
    cap = float(corr.get("v_along_cap") or corr.get("v_cap") or 0.35)
    if abs(v_along) > cap > 0:
        v_along = math.copysign(cap, v_along)
        why.append("通道·轴向节拍")
    # ③ 横向: 超界 ⇒ 切掉向外分量 + 生成回中速度 (速率=超出/dt, 上限 2 倍一档加速度)
    if dev > r:
        out_dir = _unit(lat)
        outward = _dot(v_lat, out_dir)
        if outward > 0:
            v_lat = _sub(v_lat, _mul(out_dir, outward))
            why.append("通道·横向切外")
        need = (dev - r) / dt / 1000.0                 # mm/s → m/s
        hard = 2.0 * float(corr.get("a_max") or 4.166667) * dt
        need = min(need, hard)
        v_lat = _sub(v_lat, _mul(out_dir, need))
        why.append("通道·回中")
    # ④ 单拍行程 (含横向修正后的总步长)
    v_out = _add(_mul(ax, v_along), v_lat)
    n = _norm(v_out)
    step_mm = n * dt * 1000.0
    s_tick = float(corr.get("s_tick_mm") or 1e9)
    if step_mm > s_tick > 0:
        v_out = _mul(v_out, s_tick / step_mm)
        why.append("通道·单拍行程")
    u_out = [float(u[0]), float(u[1]), float(u[2]), *[float(x) for x in list(u)[3:]]]
    u_out[0], u_out[1], u_out[2] = v_out[0], v_out[1], v_out[2]
    info = {
        "stage": corr.get("stage"), "in_channel": bool(dev <= r + 1e-9),
        "dev_mm": round(dev, 3), "excess_mm": round(max(0.0, dev - r), 3),
        "s_mm": round(s, 3), "L_mm": L, "r_mm": r,
        "v_along": round(v_along, 5), "v_along_cap": cap,
        "step_mm": round(_norm([u_out[0], u_out[1], u_out[2]]) * dt * 1000.0, 3),
        "s_tick_mm": s_tick, "why": "+".join(why) or "通道内",
    }
    return u_out, info


# ── 文件级缓存 (引擎/画布每拍调用, 不能每拍读盘) ──────────────────────────
_CACHE: dict = {"mtime": None, "data": {}, "path": None}


def load_corridors(path=None):
    """读通道真源 (tools/ss_corridor_build.py 写的 json)。缺文件/坏档 ⇒ {}。"""
    p = path or os.environ.get("ZMAX_CORRIDOR_PATH") or _default_path()
    try:
        mt = os.path.getmtime(p)
    except Exception:                                                      # noqa: BLE001
        return {}
    if _CACHE["path"] == p and _CACHE["mtime"] == mt:
        return _CACHE["data"] or {}
    try:
        import json
        d = json.load(open(p, encoding="utf-8")) or {}
        data = {k: v for k, v in (d.get("corridors") or {}).items() if isinstance(v, dict)}
    except Exception:                                                      # noqa: BLE001
        data = {}
    _CACHE["path"] = p
    _CACHE["mtime"] = mt
    _CACHE["data"] = data
    return data


def _default_path():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isdir(os.path.join(d, "zmax_data")) and os.path.isdir(os.path.join(d, "src")):
            return os.path.join(d, "zmax_data", "ss_live", "skill_corridors.json")
        d = os.path.dirname(d)
    return os.path.join("zmax_data", "ss_live", "skill_corridors.json")


def apply(stage, u, pos_mm=None, *, dt=None, enabled=None):
    """技能过闸后统一入口: 有通道真源且给了 3D 位置 ⇒ 投影进通道; 否则原样返回。

    返回 (u_out, info|None)。info=None 表示"本段没有通道/没有 3D 位置", 不代表越界。
    """
    if enabled is None:
        enabled = os.environ.get("ZMAX_CORRIDOR", "1") != "0"
    if not enabled:
        return list(u), None
    corr = (load_corridors() or {}).get(str(stage))
    if not corr:
        return list(u), None
    if pos_mm is None:
        pos_mm = _live_pos_mm()
        if pos_mm is None:
            return list(u), None
    out, info = project_stage(stage, u, pos_mm, corr, dt=dt)
    info["pos_src"] = "live"
    return out, info


def _live_pos_mm():
    """当前末端 3D 坐标 (mm) —— 与 AR 场景同源: zmax_data/ss_live/trace_live.json 的 末端 (m)。

    取不到返回 None (如实退回, 不编坐标)。文件 mtime 用单调钟判新鲜 (NTP 回拨安全)。
    """
    try:
        import json
        import time
        d = _default_path()
        root = os.path.dirname(os.path.dirname(os.path.dirname(d)))    # zmax_data/..
        p = os.path.join(root, "zmax_data", "ss_live", "trace_live.json")
        if not os.path.isfile(p):
            return None
        if time.time() - os.path.getmtime(p) > 30.0:
            return None
        t = json.load(open(p, encoding="utf-8")) or {}
        e = t.get("末端") or t.get("tcp") or t.get("end")
        if not (isinstance(e, (list, tuple)) and len(e) >= 3):
            return None
        return [float(e[0]) * 1000.0, float(e[1]) * 1000.0, float(e[2]) * 1000.0]
    except Exception:                                                      # noqa: BLE001
        return None
