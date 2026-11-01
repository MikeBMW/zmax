# -*- coding: utf-8 -*-
"""🛡 安全执行边界 (饱和限幅) / 🧭 动作调制器 — 认知决策收口 (8 阶段状态机 + 饱和限幅)

老倪 2026-10-28「把执行链上的节点按顺序迁出来」——
  实现正文从 registry 大文件 nodes/library.py 迁到本文件；library.node_ss_s3 只剩薄壳转调，
  右键「打开源代码」直接落到本文件 `run()`（registry key = `ss_limit`）。

执行链 (老倪 2026-11-01 定序): 规划引导 → 动作调制 → 安全执行 → 技能 → 运动规划 → 动作执行器 → 机器人执行器
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
        _in2 = ctx.get("in3") or ctx.get("in2")      # 连线: 测地线引导 out1 → 本节点 in3
        _pv = _in2.get("value") if isinstance(_in2, dict) else None
        # 位姿守护只归「安全边界」那一路; 调制器不抢 (它 in2 接的是元任务预测, 不是位姿)
        if ("调制器" not in name) and isinstance(_pv, dict) and (_pv.get("tcp") or _pv.get("pos") or _pv.get("xyz")):
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
            # 端口优先: 连线 sssched.out1 → sslimit.in1 (调制器的输出必须真的被限幅, 不能只读模块状态)
            _pin1 = (ctx.get("in1") or {}).get("value") if isinstance(ctx.get("in1"), dict) else ctx.get("in1")
            _u_port = None
            if isinstance(_pin1, dict):
                _u_port = _pin1.get("u") or _pin1.get("u_sat") or _pin1.get("u_ff")
            elif isinstance(_pin1, (list, tuple)) and _pin1 and isinstance(_pin1[0], (int, float)):
                _u_port = list(_pin1)
            if _u_port is not None and len(_u_port) >= 3:
                u = np.asarray(_u_port, dtype=float).ravel()[:4]
                _SS_STATE["u_src"] = "in1(动作调制器)"
            else:
                u = _SS_STATE.get("u", np.zeros(4))
                _SS_STATE.setdefault("u_src", "SS_STATE.u")
            _u_in = np.asarray(u, dtype=float).ravel()[:4]
            u_sat = _ss_import("safety").saturate(np.asarray(u, dtype=float), limit=0.6)
            _SS_STATE["u_sat"] = np.asarray(u_sat, dtype=float)
            _clip_n = int(np.sum(np.abs(np.asarray(u_sat, dtype=float).ravel()[:4] - _u_in) > 1e-9))
            if log:
                log(f"🛡 安全执行边界 (真实): saturate(u={np.round(_u_in,3)}, limit=0.6) → "
                    f"u_sat={np.round(u_sat,3)} (safety.py) · 被裁 {_clip_n} 维 · "
                    f"u_src={_SS_STATE.get('u_src','(无)')}")
            # 🔴 2026-10-29 接口对齐: 原来 return True ⇒ 壳判「非 dict → 直通」⇒ 下游拿不到业务字段
            # 🆕 2026-11-01 老倪「plan 的上游端口必须对正」: out1 = 限幅结果, **out3 = 规划安全约束**
            #   (单步/向下限 = 执行器守卫 GATE 同一口径, 不再让 plan 自己写死 50/20)
            try:
                from lerobot.arm.arm_control import GATE as _GATE          # noqa: PLC0415
                _lim = {"max_step_mm": float(_GATE.get("max_step_mm") or 50.0),
                        "max_down_mm": float(_GATE.get("max_down_mm") or 20.0),
                        "require_idle": bool(_GATE.get("require_idle", True)),
                        "require_power_on": bool(_GATE.get("require_power_on", True)),
                        "src": "arm_control.GATE (执行器守卫同一口径)"}
            except Exception as _ge:                                        # noqa: BLE001
                _lim = {"max_step_mm": 50.0, "max_down_mm": 20.0,
                        "src": "默认 (读 GATE 失败: %s)" % type(_ge).__name__}
            return {"out1": {"kind": "safety_limit",
                             "u_in": [round(float(x), 6) for x in _u_in],
                             "u_sat": [round(float(x), 6) for x in np.asarray(u_sat, dtype=float).ravel()[:4]],
                             "limit": 0.6, "clipped_dims": _clip_n,
                             "u_src": _SS_STATE.get("u_src"), "u_degraded": _SS_STATE.get("u_degraded"),
                             "src": "safety.py saturate (纯数值, 不下发真机)"},
                    "out3": _lim}
        # ── 🧭 动作调制器 (2026-11-01 老倪「在 AR 场景有效果么 / 按建议执行, 确保 300uph」) ────
        #   旧实现: 只读模块级 _SS_STATE, 九路端口一个不认, 末尾 return True ⇒ 壳判「非 dict」直通,
        #           所以 PURE 打开也是"假执行"。现在: 端口优先, 读不到才退回 _SS_STATE,
        #           关键输入全缺 ⇒ 明确回退直通并给 why; 输出业务字典 (out1=调制结果, out2=取证)。
        cog = _ss_import("cognition")

        def _pick(port, keys):
            """从端口载荷里按候选键取数值向量/标量 (各家载荷口径不同, 只认明确字段)。"""
            pv = ctx.get(port)
            v = pv.get("value") if isinstance(pv, dict) else pv
            if isinstance(v, (list, tuple)) and v and isinstance(v[0], (int, float)):
                return [float(x) for x in v], port
            if isinstance(v, dict):
                for k in keys:
                    x = v.get(k)
                    if isinstance(x, (list, tuple)) and x and isinstance(x[0], (int, float)):
                        return [float(y) for y in x], "%s.%s" % (port, k)
                    if isinstance(x, (int, float)):
                        return [float(x)], "%s.%s" % (port, k)
            return None, ""

        _ports = {"u_ff": "", "u_fb": "", "cp": "", "residual": ""}
        u_ff, _p = _pick("in6", ("u", "vec", "chunk0", "a", "best"))      # ⚡ 前馈加速器
        if u_ff:
            _ports["u_ff"] = _p
        else:
            u_ff, _p = _pick("in9", ("chunk0", "u", "vec", "a"))          # 🧭 测地线块 (老倪 11-01 接的 in9)
            _ports["u_ff"] = _p or ""
        u_fb, _pf = _pick("in8", ("u_fb", "residual", "res", "err", "u"))  # 🧪 状态校正器
        res_v, _pr = _pick("in8", ("residual", "res", "err", "u"))
        cp, _pc = _pick("in4", ("contact_p", "p_contact", "cp"))           # 🧮 流形引擎
        if cp is None:
            cp, _pc = _pick("in5", ("contact_p", "p", "score"))            # 🔍 AOI
        _ports.update({"u_fb": _pf or "", "residual": _pr or "", "cp": _pc or ""})

        if not u_ff:
            # 关键输入缺: 不装"已生效", 明确直通并交代缺哪路
            _why = "缺前馈 (in6 前馈加速器 / in9 测地线块 都没有数值) ⇒ 直通, 调制器未生效"
            if log:
                log("🧭 动作调制器: %s" % _why)
            return {"out1": {"kind": "modulator_skipped", "why": _why, "u": None,
                             "src": "cognition.ActionModulator (未调用)"},
                    "out2": {"ok": False, "why": _why, "ports": _ports}}

        u_ff = np.asarray(u_ff, dtype=float).ravel()
        if u_ff.size < 4:
            u_ff = np.concatenate([u_ff, np.zeros(4 - u_ff.size)])
        u_ff = u_ff[:4]
        u_fb = np.asarray(u_fb if u_fb else np.zeros(4), dtype=float).ravel()
        u_fb = (np.concatenate([u_fb, np.zeros(4 - u_fb.size)]) if u_fb.size < 4 else u_fb)[:4]
        _cp = float(np.asarray(cp, float).ravel()[0]) if cp else float(_SS_STATE.get("contact_p", 0.1))
        _res = res_v if res_v is not None else _SS_STATE.get("residual", np.zeros(4))
        r = float(np.linalg.norm(np.asarray(_res, dtype=float).ravel()[:3]))

        mod = cog.ActionModulator()
        u, stage = mod.decide(np.asarray(u_ff, dtype=float), u_fb, _cp, r)
        if np.ndim(u) == 0:
            u = np.zeros(4)
        u = np.asarray(u, dtype=float).copy()
        u[3] = mod.gripper_cmd(u_ff[3])
        if not np.all(np.isfinite(u)):
            return {"out1": {"kind": "modulator_nan", "why": "输出非有限值 ⇒ 拒用", "u": None},
                    "out2": {"ok": False, "ports": _ports}}
        _n_req = float(np.linalg.norm(u_ff[:3]))
        _n_out = float(np.linalg.norm(u[:3]))
        _k = (_n_out / _n_req) if _n_req > 1e-9 else 1.0
        _dir = float((u[:3] / _n_out) @ (u_ff[:3] / _n_req)) if (_n_out > 1e-9 and _n_req > 1e-9) else 0.0
        _SS_STATE.update({"u": u, "stage": stage, "u_ff": u_ff})
        if log:
            log(f"🧭 动作调制器 (真实): 阶段「{stage}」· u_ff={np.round(u_ff[:3],3)}({_ports['u_ff'] or '缺'}) "
                f"→ u={np.round(u[:3],3)} · 幅度×{_k:.2f} · 方向余弦 {_dir:.3f} · 夹爪 {u[3]:.2f}")
        return {"out1": {"kind": "modulator", "u": [round(float(x), 6) for x in u],
                         "u_ff": [round(float(x), 6) for x in u_ff],
                         "stage": stage, "amp_ratio": round(_k, 4), "dir_cos": round(_dir, 3),
                         "contact_p": round(_cp, 4), "residual": round(r, 4),
                         "src": "cognition.ActionModulator.decide (端口 in6/in9→in8→in4/in5)"},
                "out2": {"ok": True, "ports": _ports,
                         "gripper": round(float(u[3]), 4),
                         "rule": "①否决(残差) ②前馈+反馈相加 ③按阶段限速(只削幅不改方向) ④元任务门控(默认关)"}}
    except Exception as e:
        if log:
            log(f"⚠️ 认知决策层真实执行失败: {e}")
        return False
