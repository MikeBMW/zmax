# -*- coding: utf-8 -*-
"""🧭 测地线块规划 (Geodesic Chunk Planner) · 真实现  (registry key = n_geoplan)

口径 (老倪 2026-10-29):
    「YOLO → 融合定位 → 状态空间(obs) → 运动规划 ‖ 前馈MLP → 加权 → 动作调制器
      → 安全执行边界 → 原子技能派发 → 动作执行器 → 机器人」
    画布上原来只有「运动规划」(n_moveit = MoveIt 关节空间规划, 在技能之后)；
    这条链里的「运动规划」是**状态空间测地线块规划**, 与前馈 MLP 并列, 同在加权之前。
    本节点就是它 —— 与 n_moveit 是两个不同的东西, 名字和源码都分开, 不许混。

职责: obs43 → ManifoldEngine.project(潜空间) → 目标点(本段目标) → compute_geodesic(H 步)
      → readout 解码 (限幅) → 输出块 chunk[H,4] (dx,dy,dz,grip)。只算块, 不下发、不碰授权。

数学与块流水线**逐行同源** (tools/ss_chunk_pipeline.py::_chunk):
      path = navigator.compute_geodesic(p_now, goal, H);  a = path @ readout + readout_b;
      a = clip(a, action_lo, action_hi)

不造假:
  · 无 obs43 输入         → ok=False, err 说明缺哪个槽
  · 引擎/权重不可用       → ok=False, err 带异常类型
  · 引擎无目标点/project 空 → ok=False, err 如实说 (不出空块冒充成功)
  · readout 未标定         → decode="占位解码(未标定)" 明示, 不当作已标定结果
"""
from __future__ import annotations

import math
import os
import time

import numpy as np

_ROOT = os.path.expanduser("~/zmax")
CKPT = os.path.join(_ROOT, "models", "manifold_engine.npz")
LATENT, STATE_DIM, ACTION_DIM = 16, 43, 4
MANIFOLD_M = 3.643
H_DEF = int(os.environ.get("ZMAX_GEOPLAN_H", "8"))

_ENG = None
_ENG_ERR = ""

# 🧭 工艺规划 (老倪 2026-11-01「测地线规划引导负责工艺规划」): 本节点每拍算
#   "现在该做哪个元任务的哪一步", 与 3D 引导位姿一起 output; 引擎纯逻辑, 不碰硬件。
_CRAFT = {"err": "未调用"}



def _engine():
    """懒加载 ManifoldEngine (单例)。失败不抛, 记错误文本由 run() 如实上报。"""
    global _ENG, _ENG_ERR
    if _ENG is not None:
        return _ENG
    try:
        from lerobot.manifold.manifold_engine import ManifoldEngine

        e = ManifoldEngine(manifold_type="su2", latent_dim=LATENT, state_dim=STATE_DIM,
                           action_dim=ACTION_DIM, manifold_M=MANIFOLD_M,
                           inertia=False, su2_tangent=True)
        if os.path.exists(CKPT):
            e.load(CKPT)
        _ENG = e
    except Exception as exc:                                             # noqa: BLE001
        _ENG_ERR = "%s: %s" % (type(exc).__name__, exc)
        _ENG = None
    return _ENG


def _obs(ctx):
    """从 ctx 取 obs43: ctx['in1'] 可以是 list/np.array(43) 或 {'obs':[...]} 或 {'state':[...]}"""
    v = (ctx or {}).get("in1")
    if isinstance(v, dict):
        v = v.get("obs") or v.get("state") or v.get("vec")
    if v is None:
        return None
    try:
        a = np.asarray(v, float).ravel()
    except Exception:                                                    # noqa: BLE001
        return None
    if a.size < STATE_DIM:
        return None
    return a[:STATE_DIM]


def _goal_state(obs, ctx):
    """目标态: 默认把 obs 的位置槽换成目标槽 obs[36:39] (与 env/前馈同一口径: 36:39 = 目标)。"""
    g = obs.copy()
    tgt = (ctx or {}).get("in2")
    if isinstance(tgt, dict):
        tgt = tgt.get("goal") or tgt.get("target") or tgt.get("pos")
    if tgt is not None:
        try:
            t = np.asarray(tgt, float).ravel()[:3]
            if t.size == 3:
                g[36:39] = t
        except Exception:                                                # noqa: BLE001
            pass
    g[0:3] = g[36:39]
    return g



# ── 📈 时间参数化平滑轨迹 (2026-10-29 老倪: 「要动作与回放的 UPH 轨迹一样平顺, 而且要由 L2 节点实际发出」) ──
#   为什么要它: 站内原来是 10Hz P 环 + 每拍重算速度 + 每拍 IK ⇒ 段首跳支/段间硬切/终点 snap,
#   实测右臂每拍 13~660mm 的台阶。UPH 之所以顺 = 它按**时间**插值 (u = t_in_seg / seg_t)。
#   这里把同一套"时间参数化"做成 L2 节点的输出: 五次多项式 S 曲线 (C2 连续, 首末加速度=0),
#   峰值速度/加速度由段标定 v_cap / a_max 反解 T ⇒ 轨迹本身就是平顺的, 执行端只按时间采样回放。
#   真源: v_cap = zmax_skill_physics.json 的段速度上限; a_max = F/m (同文件), 这里默认 2.0 m/s²。
def smooth_traj(p0, p1, v_cap=0.35, a_max=2.0, dt=0.02, min_T=None):
    """p0→p1 的 S 曲线轨迹 (五次多项式 s=10t³-15t⁴+6t⁵)。
    峰值: |v|max = 1.875·L/T, |a|max = 5.7735·L/T² ⇒ 反解 T ≥ max(1.875L/v_cap, √(5.7735L/a_max))。
    返回 {ok,T,dt,n,L_mm,v_peak_mm_s,a_peak_m_s2,pts[[x,y,z]…],vel[[vx,vy,vz]…],src}
    """
    import math as _m
    import numpy as _np
    a0 = _np.asarray(p0, float).ravel()[:3]
    a1 = _np.asarray(p1, float).ravel()[:3]
    if a0.size != 3 or a1.size != 3 or not (_np.all(_np.isfinite(a0)) and _np.all(_np.isfinite(a1))):
        return {"ok": False, "err": "端点非法"}
    d = a1 - a0
    L = float(_np.linalg.norm(d))
    if L < 1e-6:
        return {"ok": True, "T": 0.0, "dt": dt, "n": 1, "L_mm": 0.0,
                "v_peak_mm_s": 0.0, "a_peak_m_s2": 0.0, "pts": [a0.tolist()], "vel": [[0.0, 0.0, 0.0]],
                "src": "L2 n_geoplan.smooth_traj (零位移)"}
    v = max(0.02, float(v_cap))
    am = max(0.1, float(a_max))
    T = max(1.875 * L / v, _m.sqrt(5.7735 * L / am))
    if min_T:
        T = max(T, float(min_T))
    n = int(_m.ceil(T / dt)) + 1
    pts, vel = [], []
    for k in range(n):
        tau = min(1.0, k * dt / T)
        s = 10 * tau ** 3 - 15 * tau ** 4 + 6 * tau ** 5
        ds = (30 * tau ** 2 - 60 * tau ** 3 + 30 * tau ** 4) / T
        pts.append([round(float(x), 6) for x in (a0 + d * s)])
        vel.append([round(float(x), 6) for x in (d * ds)])
    return {"ok": True, "T": round(T, 4), "dt": dt, "n": n,
            "L_mm": round(L * 1000, 1),
            "v_peak_mm_s": round(1.875 * L / T * 1000, 1),
            "a_peak_m_s2": round(5.7735 * L / (T * T), 3),
            "pts": pts, "vel": vel,
            "src": "L2 n_geoplan.smooth_traj (S 曲线 五次多项式 C2)"}


def _quat_from_rot(flat):
    """obs[24:33] 的 3x3 旋转 (行主序) → [qw,qx,qy,qz]; 退化 (全 0/非正交) 返回 None。"""
    try:
        m = np.asarray(flat, float).ravel()[:9].reshape(3, 3)
    except Exception:                                                    # noqa: BLE001
        return None
    if not np.all(np.isfinite(m)) or abs(float(np.linalg.det(m))) < 1e-6:
        return None
    tr = float(m[0, 0] + m[1, 1] + m[2, 2])
    if tr > 0:
        s = (tr + 1.0) ** 0.5 * 2
        w, x = 0.25 * s, (m[2, 1] - m[1, 2]) / s
        y, z = (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = (1.0 + m[0, 0] - m[1, 1] - m[2, 2]) ** 0.5 * 2
        w, x = (m[2, 1] - m[1, 2]) / s, 0.25 * s
        y, z = (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = (1.0 + m[1, 1] - m[0, 0] - m[2, 2]) ** 0.5 * 2
        w, x = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s
        y, z = 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = (1.0 + m[2, 2] - m[0, 0] - m[1, 1]) ** 0.5 * 2
        w, x = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s
        y, z = (m[1, 2] + m[2, 1]) / s, 0.25 * s
    q = np.array([w, x, y, z], float)
    n = float(np.linalg.norm(q))
    return [round(float(v / n), 5) for v in q] if n > 1e-9 else None


def _craft(ctx=None):
    """工艺步骤 (元任务/第几步/推进判决) —— 委托工艺引擎 sched_impl.run(), 失败不拖垮引导。"""
    global _CRAFT
    try:
        from . import sched_impl as _S
        o = _S.run(ctx or {})
        _CRAFT = {"out1": o.get("out1"), "out2": o.get("out2"), "out3": o.get("out3")}
    except Exception as exc:                                            # noqa: BLE001
        _CRAFT = {"err": "%s: %s" % (type(exc).__name__, exc)}
    return _CRAFT


def _run_guides(ctx=None):
    """一个周期: obs43 → 测地线块 [H,4]。只规划, 不下发。"""
    out = {"node": "n_geoplan", "impl": "nodes/geo_plan_impl.py:run", "h": H_DEF}
    obs = _obs(ctx)
    if obs is None:
        out.update({"ok": False, "err": "无 obs43 输入 (ctx['in1'] 需 43 维: obs[:39] + 触觉4)"})
        return out
    eng = _engine()
    if eng is None:
        out.update({"ok": False, "err": "引擎不可用: %s" % (_ENG_ERR or "ManifoldEngine 未建立")})
        return out
    try:
        p_now = eng.project(obs)
    except Exception as exc:                                             # noqa: BLE001
        out.update({"ok": False, "err": "project 失败: %s: %s" % (type(exc).__name__, exc)})
        return out
    p_now = (p_now or {}).get("p") if isinstance(p_now, dict) else p_now
    if p_now is None:
        out.update({"ok": False, "err": "project 返回空 (无潜空间坐标)"})
        return out
    gs = _goal_state(obs, ctx)
    try:
        gp = eng.project(gs)
        gp = (gp or {}).get("p") if isinstance(gp, dict) else gp
        if gp is None:
            out.update({"ok": False, "err": "目标态 project 返回空"})
            return out
        eng.goal_point = gp
        nav = eng.navigator.compute_geodesic(np.asarray(p_now, float).ravel(),
                                            np.asarray(gp, float).ravel(), H_DEF)
        path = np.asarray(nav["path"], float)
        act = []
        decode = "占位解码(未标定)"
        for p in path:
            if getattr(eng, "readout", None) is not None:
                a = np.asarray(p, float) @ eng.readout + eng.readout_b
                if getattr(eng, "action_lo", None) is not None:
                    a = np.clip(a, eng.action_lo, eng.action_hi)
                decode = "ridge 解码(限幅)"
            else:
                a = np.asarray(p, float)[:ACTION_DIM]
                decode = "占位解码(未标定)"
            act.append(np.asarray(a, float).ravel()[:ACTION_DIM])
        chunk = np.asarray(act, float)
    except Exception as exc:                                             # noqa: BLE001
        out.update({"ok": False, "err": "测地线规划失败: %s: %s" % (type(exc).__name__, exc)})
        return out
    # ── 3D 引导位姿 (视觉 3D 目标 + 测地线方向校验) ──────────────────────
    tcp = np.asarray(obs[0:3], float)
    peg = np.asarray(obs[4:7], float)
    hole = np.asarray(obs[36:39], float)
    use_hole = float(np.linalg.norm(hole - peg)) > 0.005
    tgt_vis = hole if use_hole else peg
    hover = float(os.environ.get("ZMAX_GUIDE_HOVER_MM", "40")) * 0.001
    v_cap = float(os.environ.get("ZMAX_GUIDE_V_CAP", "0.35"))
    dt = float(os.environ.get("ZMAX_GUIDE_DT", "0.1"))
    goal_pos = np.asarray(tgt_vis, float).copy()
    goal_pos[2] = goal_pos[2] + hover            # 先到目标上方 hover, 下落交给下游规划
    d = goal_pos - tcp
    dist = float(np.linalg.norm(d))
    u = d / dist if dist > 1e-9 else np.zeros(3)
    cu = np.asarray(chunk[0][:3], float)
    cn = float(np.linalg.norm(cu))
    cos = float((cu / cn) @ u) if cn > 1e-9 else 0.0
    step = min(dist, v_cap * dt)
    guide_pos = tcp + u * step
    quat = _quat_from_rot(obs[24:33])
    out.update({"ok": True, "goal": [round(float(v), 5) for v in gs[36:39]],
                "p_now": [round(float(v), 5) for v in np.asarray(p_now, float).ravel()[:4]],
                "chunk": [[round(float(x), 5) for x in row] for row in chunk],
                "chunk0": [round(float(x), 5) for x in chunk[0]],
                "chunk_norm": round(float(np.linalg.norm(chunk[0][:3])), 5),
                "geodesic": nav.get("geodesic_kind"),
                "length": round(float(nav.get("length") or 0.0), 5),
                "decode": decode,
                "ckpt": os.path.relpath(CKPT, _ROOT) if os.path.exists(CKPT) else "(缺 ckpt)",
                "guide": {"pos_m": [round(float(v), 5) for v in guide_pos],
                          "pos_mm": [round(float(v) * 1000.0, 1) for v in guide_pos],
                          "quat": quat,
                          "axis": [round(float(v), 4) for v in u],
                          "cos_geodesic": round(cos, 3),
                          "step_mm": round(step * 1000.0, 1),
                          "dist_mm": round(dist * 1000.0, 1),
                          "tgt_src": "视觉3D 孔口" if use_hole else "视觉3D 模块",
                          "dir_src": ("测地线一致 (cos≥0.3)" if cos >= 0.3
                                      else "几何(视觉3D)主导: 测地线方向不一致 cos=%.2f" % cos),
                          "quat_src": ("obs[24:33] 旋转矩阵" if quat
                                       else "姿态槽无效 ⇒ 保持当前姿态")},
                # 下游「运动规划」(n_moveit) 认 ctx["in1"]["value"]["tcp"](mm)
                "value": {"tcp": [round(float(v) * 1000.0, 1) for v in guide_pos],
                          "frame": "base_link",
                          "src": "测地线规划引导 (视觉3D + 测地线方向)"}})
    return out


# ── 理想规划档 (2026-11-01 老倪: 「再从测地线规划引导节点给出理想规划, 保证300UPH, 保证L2的设计逻辑」)
#   现场没有 obs43 落盘 ⇒ 正常档 _run_guides 出不来 (ok=False, 直通)。
#   理想档不假装吃了 obs43: 几何取**执行器同一生成器** cycle_plan 的稳态段表 (与「全流程 UPH」逐段一致),
#   段内用 S² 大圆测地线采样出块 chunk[H,4] —— 输出仍走本节点的口语义 out1(引导位姿)/out2(块),
#   下游 sslimit/sssched 不用改。时序按理想剖面重计时 (抬升/横移 1000, 下落/插入/拔 300)。
IV_FAST, IA_FAST = 1000.0, 4000.0
IV_SLOW, IA_SLOW = 300.0, 2000.0
IPROC = ("insert", "grip", "release")
_IDEAL_CACHE = {"ts": 0.0, "doc": None}


def _ideal_on(ctx=None):
    """是否走理想档: ctx.params.ideal 或环境变量 ZMAX_GEO_IDEAL=1。"""
    try:
        pr = (ctx or {}).get("params") or {}
        if str((pr.get("ideal") if isinstance(pr, dict) else "")).lower() in ("1", "true", "on", "yes"):
            return True
    except Exception:                                                   # noqa: BLE001
        pass
    return os.environ.get("ZMAX_GEO_IDEAL", "0").strip().lower() in ("1", "true", "on", "yes")


def _seg_time(d_mm, kind):
    slow = kind in ("down", "insert", "pull")
    v, a = (IV_SLOW, IA_SLOW) if slow else (IV_FAST, IA_FAST)
    if d_mm <= 1e-9:
        return 0.0
    if d_mm > v * v / a:
        return d_mm / v + v / a
    return 2.0 * math.sqrt(d_mm / a)


def _geodesic_s2(a, b, h):
    """S² 大圆测地线: 方向 slerp + 半径线性 ⇒ 段内 h 个引导点 (mm)。"""
    ra = math.sqrt(sum(x * x for x in a)) or 1.0
    rb = math.sqrt(sum(x * x for x in b)) or 1.0
    ua = [x / ra for x in a]
    ub = [x / rb for x in b]
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(ua, ub))))
    om = math.acos(dot)
    out = []
    for i in range(h):
        t = 0.0 if h == 1 else i / (h - 1)
        r = ra + (rb - ra) * t
        if om < 1e-6:
            d = ua
        else:
            s1 = math.sin((1 - t) * om) / math.sin(om)
            s2 = math.sin(t * om) / math.sin(om)
            d = [s1 * x + s2 * y for x, y in zip(ua, ub)]
        n = math.sqrt(sum(x * x for x in d)) or 1.0
        out.append([d[0] / n * r, d[1] / n * r, d[2] / n * r])
    return out


def build_ideal_plan(h=8, refresh=60.0):
    """理想规划段表 (几何=执行器同一 cycle_plan 稳态窗口, 时序=理想剖面)。缓存 refresh 秒。"""
    now = time.time()
    if _IDEAL_CACHE["doc"] and now - _IDEAL_CACHE["ts"] < refresh:
        return _IDEAL_CACHE["doc"]
    from . import cycle_plan as _cp                                           # noqa: PLC0415
    doc = _cp.build()
    P = doc.get("plan") or doc.get("segments") or []
    L = doc.get("loop") or {}
    ks = L.get("ks") or [2, 3]
    # ⚠️ 段表里的 'k' 是**轮次号**(1,2,3…), loop.ks 比的是它; 动作类型在 'kind' —— 别混。
    kk = lambda s: s.get("k")                                                 # noqa: E731
    i0 = next(i for i, s in enumerate(P) if kk(s) == ks[0])
    i1 = max(i for i, s in enumerate(P) if kk(s) == ks[1])
    W = P[i0:i1 + 1]
    mods = int(L.get("mods") or 4)
    segs, clock = [], 0.0
    for s in W:
        kind = s.get("kind") or "move"
        a, b = s.get("a"), s.get("b")
        d = math.dist(a, b) if (a and b) else 0.0
        t = float(s.get("t") or 0.0) if (kind in IPROC or d <= 1e-9) else _seg_time(d, kind)
        pts = _geodesic_s2(a, b, h) if d > 1e-9 else [[a[0], a[1], a[2]] for _ in range(h)]
        chunk = [[round(p[0], 2), round(p[1], 2), round(p[2], 2),
                  round(t * (i / (h - 1)), 4) if h > 1 else 0.0] for i, p in enumerate(pts)]
        segs.append(dict(i=len(segs) + 1, kind=kind, label=s.get("label"), a=a, b=b,
                         len_mm=round(d, 1), t=round(t, 3), t0=round(clock, 3),
                         src_t=round(float(s.get("t") or 0.0), 3), chunk=chunk))
        clock += t
    tact = clock / mods if mods else clock
    doc = dict(ok=True, src="cycle_plan.build() 稳态窗口 loop.ks=%s" % (ks,),
               model=dict(v_fast=IV_FAST, a_fast=IA_FAST, v_slow=IV_SLOW, a_slow=IA_SLOW, H=h),
               cycle_s=round(clock, 3), tact_s=round(tact, 4),
               uph=round(3600.0 / tact, 1) if tact else 0.0, mods=mods, n_seg=len(segs),
               move_s=round(sum(x["t"] for x in segs if x["kind"] not in IPROC), 3),
               proc_s=round(sum(x["t"] for x in segs if x["kind"] in IPROC), 3),
               ok300=bool(tact and 3600.0 / tact >= 300.0), margin_s=round(12.0 - tact, 4),
               segs=segs)
    _IDEAL_CACHE.update(ts=now, doc=doc)
    return doc


def ideal_run(ctx=None):
    """理想档一个周期: 按时间取当前段 → out1 引导位姿, out2 块 chunk[H,4]。只规划不下发。"""
    h = int(((ctx or {}).get("params") or {}).get("H") or 8)
    doc = build_ideal_plan(h=h)
    el = time.time() % max(1e-6, doc["cycle_s"])          # 循环内相位
    cur = doc["segs"][-1]
    for s in doc["segs"]:
        if el <= s["t0"] + s["t"]:
            cur = s
            break
    u = 0.0 if cur["t"] <= 0 else min(1.0, max(0.0, (el - cur["t0"]) / cur["t"]))
    pos = [cur["a"][i] + (cur["b"][i] - cur["a"][i]) * u for i in range(3)]
    out1 = {"tcp": [round(v, 2) for v in pos], "seg_i": cur["i"], "seg_n": doc["n_seg"],
            "kind": cur["kind"], "label": cur["label"], "u": round(u, 4),
            "cycle_s": doc["cycle_s"], "tact_s": doc["tact_s"], "uph": doc["uph"],
            "ok300": doc["ok300"], "src": "geo_ideal(测地线引导·理想档)"}
    out2 = {"H": h, "chunk": cur["chunk"], "seg_i": cur["i"], "kind": cur["kind"]}
    return {"out1": {"value": out1, "age_s": 0.0, "fresh": True},
            "out2": {"value": out2, "age_s": 0.0, "fresh": True},
            "ok": True, "ideal": True, "cycle_s": doc["cycle_s"], "tact_s": doc["tact_s"],
            "uph": doc["uph"], "ok300": doc["ok300"], "n_seg": doc["n_seg"],
            "status": "理想规划 %d 段 · 循环 %.2f s · 节拍 %.3f s/件 · %.0f UPH %s"
                      % (doc["n_seg"], doc["cycle_s"], doc["tact_s"], doc["uph"],
                         "≥300 ✓" if doc["ok300"] else "<300 ✗")}


def run(ctx=None):
    """🧭 测地线规划引导 = 3D 引导位姿 + 块 + **工艺步骤** (老倪 2026-11-01: 本节点负责工艺规划)。

    三条输出一起出, 下游各取所需:
      · out1.value.tcp     → 运动规划 n_moveit 认的引导位姿 (mm)
      · out2 (chunk)       → 加权/动作调制器
      · out1.craft         → 工艺步骤: 元任务/第几步/推进判决 (来自工艺引擎 sched_impl)
    工艺引擎坏了不影响引导位姿 (craft.err 明示, 不静默丢)。
    """
    if _ideal_on(ctx):
        out = ideal_run(ctx)
        try:
            c = _craft(ctx)
            out["craft"] = {"step": c.get("out1"), "progress": c.get("out2"),
                            "event": c.get("out3"), "err": c.get("err")}
            if isinstance(out["out1"].get("value"), dict) and isinstance(c.get("out1"), dict):
                out["out1"]["value"]["craft"] = c["out1"]
        except Exception as _e:                                         # noqa: BLE001
            out["craft"] = {"err": str(_e)[:120]}
        globals()["LAST_STATUS"] = out.get("status") or ""
        return out
    out = _run_guides(ctx)
    c = _craft(ctx)
    out["craft"] = {"step": c.get("out1"), "progress": c.get("out2"),
                    "event": c.get("out3"), "err": c.get("err")}
    if isinstance(out.get("value"), dict) and isinstance(c.get("out1"), dict):
        out["value"]["craft"] = c["out1"]
    return out


LAST_STATUS = ""
