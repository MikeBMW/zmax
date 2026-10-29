# -*- coding: utf-8 -*-
"""🛡 安全执行边界 (饱和限幅) / 🧭 动作调制器 — 认知决策收口 (8 阶段状态机 + 饱和限幅)

老倪 2026-10-28「把执行链上的节点按顺序迁出来」——
  实现正文从 registry 大文件 nodes/library.py 迁到本文件；library.node_ss_s3 只剩薄壳转调，
  右键「打开源代码」直接落到本文件 `run()`（registry key = `ss_limit`）。

执行链位置: 运动规划 → 🛡 安全执行边界 (饱和限幅) / 🧭 动作调制器 → 动作执行器 → 机器人执行器
铁律: 只读真值 / 不造数 / 不下发动作 (下发只走 l2_daemon + 8793 授权)。
本文件正文与迁移前逐字一致 (仅补显式 import 与文件头)。
"""
from __future__ import annotations
from .library import _SS_STATE, _ss_import   # 与 registry 共用同一份运行时状态 (同源)


# ── 🛡 位姿守护 (2026-10-29 老倪: 「测地线规划引导的位姿，能向后传么？进到安全…」) ──────
#   语义: 安全执行边界原来只削**控制量 u** (saturate 0.6)。引导位姿是**目标**不是指令,
#        所以这里加一条「位姿守护」: 工作空间包围盒 + 单步位移上限 + 台面高度下限,
#        通过就原样透传 (带 why), 不通过就**夹到边界**并标明 clipped —— 不静默放行、也不假报 ok。
import os as _os
from ._single_thread import brk as _brk

WS_M = {"x": (0.15, 1.05), "y": (-0.65, 1.15), "z": (0.005, 0.95)}      # 工作空间 (m, base_link)
STEP_MAX_MM = float(_os.environ.get("ZMAX_POSE_GUARD_STEP_MM", "45"))    # 与执行器单步同口径
TABLE_Z_M = float(_os.environ.get("ZMAX_POSE_GUARD_TABLE_Z", "0.0"))     # 台面 (AR 场景顶面 z=0)


def guard_pose(pose, cur_mm=None):
    """位姿守护: 返回 {ok, why[], pose_mm, clipped}。pose 可给 tcp/pos/xyz (mm 或 m 自动判)。"""
    import numpy as _np
    if isinstance(pose, dict):
        raw = pose.get("tcp") or pose.get("pos") or pose.get("xyz")
        frame = pose.get("frame") or "base_link"
    else:
        raw, frame = pose, "base_link"
    if raw is None:
        return {"ok": False, "why": ["无位姿输入"], "pose_mm": None, "clipped": False, "frame": frame}
    a = _np.asarray(raw, dtype=float).ravel()[:3]
    if a.size != 3 or not _np.all(_np.isfinite(a)):
        return {"ok": False, "why": ["位姿非法 (非 3 维/含 NaN)"], "pose_mm": None,
                "clipped": False, "frame": frame}
    mm = a * 1000.0 if float(_np.linalg.norm(a)) < 5.0 else a      # 米 → 毫米自动判
    why, clipped = [], False
    lo_hi = {k: (v[0] * 1000.0, v[1] * 1000.0) for k, v in WS_M.items()}
    out = mm.copy()
    for i, k in enumerate(("x", "y", "z")):
        lo, hi = lo_hi[k]
        if mm[i] < lo:
            out[i] = lo
            clipped = True
            why.append("%s 低于工作空间下限 %.1f < %.1f mm" % (k, mm[i], lo))
        elif mm[i] > hi:
            out[i] = hi
            clipped = True
            why.append("%s 超出工作空间上限 %.1f > %.1f mm" % (k, mm[i], hi))
    if out[2] < TABLE_Z_M * 1000.0 + 5.0:
        out[2] = TABLE_Z_M * 1000.0 + 5.0
        clipped = True
        why.append("z 低于台面+5mm (撞台面)")
    if cur_mm is not None:
        d = float(_np.linalg.norm(out - _np.asarray(cur_mm, dtype=float).ravel()[:3]))
        if d > STEP_MAX_MM:
            u = (out - _np.asarray(cur_mm, dtype=float).ravel()[:3]) / max(d, 1e-9)
            out = _np.asarray(cur_mm, dtype=float).ravel()[:3] + u * STEP_MAX_MM
            clipped = True
            why.append("单步 %.1f > %.1f mm ⇒ 按方向截断" % (d, STEP_MAX_MM))
    return {"ok": len(why) == 0, "why": why, "pose_mm": [round(float(v), 2) for v in out],
            "clipped": clipped, "frame": frame}


def run(ctx):
    log = ctx.get("log")
    try:
        import numpy as np
        name = ctx.get("name", "")
        # 🛡 位姿守护支路: 上游 (测地线规划引导) 把位姿放进 in2 ⇒ 校验后原样/截断往下传
        _in2 = ctx.get("in2")
        _pv = _in2.get("value") if isinstance(_in2, dict) else None
        if isinstance(_pv, dict) and (_pv.get("tcp") or _pv.get("pos") or _pv.get("xyz")):
            _cur = (_SS_STATE.get("tcp_mm") if isinstance(_SS_STATE.get("tcp_mm"), (list, tuple)) else None)
            g = guard_pose(_pv, cur_mm=_cur)
            _SS_STATE["guide_pose"] = g
            if log:
                log("🛡 位姿守护(真实): %s%s → %s" % (
                    "通过" if g["ok"] else "截断/拒绝",
                    "" if not g["why"] else " · " + " / ".join(g["why"]),
                    g["pose_mm"]))
            return {"ok": g["ok"], "value": {"tcp": g["pose_mm"], "frame": g["frame"],
                                             "src": "安全位姿守护 (工作空间/单步/台面)"},
                    "why": g["why"], "clipped": g["clipped"], "pose_mm": g["pose_mm"]}
        if "边界" in name:
            u = _SS_STATE.get("u", np.zeros(4))
            _u_in = np.asarray(u, dtype=float).ravel()[:4]
            u_sat = _ss_import("safety").saturate(np.asarray(u, dtype=float), limit=0.6)
            _SS_STATE["u_sat"] = np.asarray(u_sat, dtype=float)
            _clip_n = int(np.sum(np.abs(np.asarray(u_sat, dtype=float).ravel()[:4] - _u_in) > 1e-9))
            if log:
                log(f"🛡 安全执行边界 (真实): saturate(u={np.round(_u_in,3)}, limit=0.6) → "
                    f"u_sat={np.round(u_sat,3)} (safety.py) · 被裁 {_clip_n} 维 · "
                    f"u_src={_SS_STATE.get('u_src','(无)')}")
            # 🔴 2026-10-29 接口对齐: 原来 return True ⇒ 壳判「非 dict → 直通」⇒ 下游拿不到业务字段
            return {"kind": "safety_limit",
                    "u_in": [round(float(x), 6) for x in _u_in],
                    "u_sat": [round(float(x), 6) for x in np.asarray(u_sat, dtype=float).ravel()[:4]],
                    "limit": 0.6, "clipped_dims": _clip_n,
                    "u_src": _SS_STATE.get("u_src"), "u_degraded": _SS_STATE.get("u_degraded"),
                    "src": "safety.py saturate (纯数值, 不下发真机)"}
        cog = _ss_import("cognition")
        u_ff = _SS_STATE.get("u_ff", np.zeros(4))
        cp = _SS_STATE.get("contact_p", 0.1)
        res = _SS_STATE.get("residual", np.zeros(4))
        r = float(np.linalg.norm(res))
        u_fb = np.concatenate([np.clip(0.5 * np.asarray(res, dtype=float)[:3], -0.5, 0.5), [0.0]])
        mod = cog.ActionModulator()
        u, stage = mod.decide(np.asarray(u_ff, dtype=float), u_fb, float(cp), r)
        if np.ndim(u) == 0:
            u = np.zeros(4)
        u = np.asarray(u, dtype=float).copy()
        u[3] = mod.gripper_cmd(u_ff[3])
        _SS_STATE.update({"u": u, "stage": stage})
        if log:
            log(f"🧭 动作调制器 (真实): decide(u_ff,u_fb,cp={cp:.2f},r={r:.3f}) → 阶段「{stage}」· "
                f"u={np.round(u,3)} (cognition.py)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 认知决策层真实执行失败: {e}")
        return False
