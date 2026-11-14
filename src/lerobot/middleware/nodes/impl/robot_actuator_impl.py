# -*- coding: utf-8 -*-
"""🤖 机器人执行器 (RobotExecutor.execute) / 🌍 物理世界 (PhysicalWorld 质量/惯量)

老倪 2026-10-28「把执行链上的节点按顺序迁出来」——
  实现正文从 registry 大文件 nodes/library.py 迁到本文件；library.node_ss_exec 只剩薄壳转调，
  右键「打开源代码」直接落到本文件 `run()`（registry key = `ss_act`）。

执行链 (老倪 2026-11-01 定序): 规划引导 → 动作调制 → 安全执行 → 技能 → 运动规划 → 动作执行器 → 机器人执行器
铁律: 只读真值 / 不造数 / 不下发动作 (下发只走 l2_daemon + 8793 授权)。
本文件正文与迁移前逐字一致 (仅补显式 import 与文件头)。
"""
from __future__ import annotations
import time
from .shared_runtime import _SS_STATE, _ss_import   # 与 registry 共用同一份运行时状态 (同源)
from ._single_thread import brk as _brk


def _exec_action_verbatim(ctx, act, log):
    """🤖 执行契约 (老倪 2026-11-15): 规划节点给的 action ⇒ **只执行, 不重算**。

    禁止事项 (这条就是分工的红线): 不重跑 IK、不重解段表、不用 4 维速度再推一次位姿。
    校验 (缺一即拒): 位姿三个分量有限 · 单拍幅度 ≤ align.max_step_mm · 真值新鲜(age≤1s)。
    真实下发仍只走 exec.contract.dispatch / l2_daemon + 8793 授权; 本节点只做"执行 + 留证"。
    """
    import math as _m
    import time as _t
    pose = (act or {}).get("pose") or {}
    al = (act or {}).get("align") or {}
    probs = []
    try:
        px, py, pz = float(pose.get("x")), float(pose.get("y")), float(pose.get("z"))
        if not all(_m.isfinite(v) for v in (px, py, pz)):
            probs.append("位姿非有限数")
    except Exception:                                                     # noqa: BLE001
        probs.append("位姿缺 x/y/z")
        px = py = pz = None
    step = al.get("step_mm")
    lim = al.get("max_step_mm") or 25.0
    if step is not None and float(step) > float(lim):
        probs.append("单拍幅度 %.1fmm > %.1fmm" % (float(step), float(lim)))
    fresh = al.get("truth_fresh")
    if fresh is False:
        probs.append("真值陈旧(age=%s)" % al.get("truth_age_s"))
    ok = not probs
    out = {"kind": "actuator", "mode": "verbatim", "ok": ok, "problems": probs,
           "action": act, "src": (act or {}).get("src"), "pose": pose,
           "grip_act": (act or {}).get("grip_act"), "grip_mm": (act or {}).get("grip_mm"),
           "seg": al.get("seg_kind") or ((act or {}).get("plan") or {}).get("seg_kind"),
           "plan_id": ((act or {}).get("plan") or {}).get("plan_id"),
           "real_send": False,
           "note": "动作来自运动规划节点的 action(位姿口径) · 本节点不重算 · 下发另走授权链"}
    if not ok:
        if log:
            log("🤖 机器人执行器 (逐字执行) 拒收: %s" % " / ".join(probs))
        _SS_STATE["action"] = act
        return {"out1": out}
    try:
        from lerobot.policies.left_right.state_space import action_bus as _ab
        _m2 = dict(act)
        _m2["executed"] = {"by": "robot_actuator", "mode": "verbatim", "ts": _t.time()}
        _ab.publish(_m2)
        _SS_STATE["action"] = _m2
        _SS_STATE["pose_out"] = pose
        if (act or {}).get("src") != "traj215":
            _SS_STATE["u_prev"] = [0.0, 0.0, 0.0]
        _SS_STATE["dd_active"] = False
    except Exception:                                                     # noqa: BLE001
        pass
    try:
        from lerobot.engineering.exec import ar_bridge as _arb
        _arb.update("exec", {"kind": "exec", "src": (act or {}).get("src"), "pose": pose,
                             "joints_deg": (act or {}).get("joints_deg"),
                             "step_mm": step, "seg_i": al.get("seg_i"),
                             "exec_mode": "verbatim", "exec_by": "robot_actuator"},
                    src="ssact")
    except Exception:                                                     # noqa: BLE001
        pass
    if log:
        log("🤖 机器人执行器 (逐字执行规划 action): x=%.2f y=%.2f z=%.2f a=%.2f b=%.2f c=%.2f · "
            "单拍 %.1fmm · 段 %s · plan#%s"
            % (px or 0, py or 0, pz or 0, float(pose.get("a") or 0), float(pose.get("b") or 0),
               float(pose.get("c") or 0), float(step or 0), out["seg"], out["plan_id"]))
    return {"out1": out}


def run(ctx):
    # 🔴 2026-10-29 事实记录 (不受调试器/env 影响): 每次节点被真正调用就往
    #   zmax_data/ss_live/actuator_calls.log 追加一行。用来回答"右键运行节点到底有没有
    #   走到这个函数"—— 有日志=走到了(问题在断点绑定), 没日志=根���没调用(问题在 GUI 分派)。
    try:
        import os as _os
        _p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(
            _os.path.dirname(_os.path.abspath(__file__)))))), "zmax_data", "ss_live", "actuator_calls.log")
        if _os.path.isdir(_os.path.dirname(_p)):
            with open(_p, "a", encoding="utf-8") as _f:
                _f.write("%s pid=%s name=%s\n" % (time.strftime("%H:%M:%S"), _os.getpid(),
                                                  str(ctx.get("name"))[:20]))
    except Exception:                                                      # noqa: BLE001
        pass
    log = ctx.get("log")
    # 🧭 2026-11-01 老倪「l2_daemon 不能脱离状态空间工程, 放机器人执行器节点比较合理?」
    #   结论落在本节点: **执行契约 (段表/闸序/回执) 归这里声明**, 常驻进程仍在 exec/daemon.py。
    #   回执 = 只读 (每拍都可调); 下发 = 必须显式 (ctx["dispatch_segs"]), 画布每拍绝不自动发。
    try:
        from lerobot.engineering.exec import contract as _CT
    except Exception:                                                      # noqa: BLE001
        try:
            import importlib as _il
            _CT = _il.import_module("lerobot.engineering.exec.contract")
        except Exception:                                                  # noqa: BLE001
            _CT = None
    if _CT is not None:
        _name0 = str(ctx.get("name") or "")
        if ctx.get("dispatch_segs"):
            _r = _CT.dispatch(ctx["dispatch_segs"], speed_mm_s=ctx.get("speed_mm_s"),
                              dry=bool(ctx.get("dry")), stage=ctx.get("stage"))
            if log:
                log("🤖 机器人执行器 (契约下发): %s" % _r)
            return {"out1": dict(_r, kind="exec_dispatch", contract="v1", src="exec.contract.dispatch")}
        if (not ctx.get("in1")) or ctx.get("contract"):
            _rc = _CT.receipt()
            if log:
                log("🤖 机器人执行器 (契约回执): phase=%s seg=%s/%s residual=%s age=%ss"
                    % (_rc.get("phase"), _rc.get("seg"), _rc.get("n_seg"),
                       _rc.get("residual_mm"), _rc.get("age_s")))
            return {"out1": dict(_rc, kind="exec_receipt", contract="v1",
                                 gate_order=[g[0] for g in _CT.GATE_ORDER],
                                 src="exec.contract.receipt")}
    try:
        import numpy as np
        name = ctx.get("name", "")
        ex = _ss_import("execution")
        if "物理" in name:
            w = ex.PhysicalWorld()
            _SS_STATE["world"] = w
            if log:
                try:
                    gm = np.asarray(w.generalized_mass())
                    gd = np.round(np.diag(gm)[:4], 3) if gm.ndim == 2 and gm.shape[0] == gm.shape[1] else np.round(gm.ravel()[:4], 3)
                except Exception:
                    gd = "?"
                log(f"🌍 物理世界 (真实): total_mass={w.total_mass}kg · 广义质量≈{gd} · "
                    f"7自由度 (execution.py)")
            # 🔴 2026-10-29: 返回 dict 才落成「实现执行」; 纯计算, 零下发
            return {"out1": {"kind": "physical_world", "total_mass": float(getattr(w, "total_mass", 0.0)),
                             "gen_mass_diag": [float(x) for x in (gd if isinstance(gd, (list,)) else [])],
                             "src": "execution.py:PhysicalWorld", "t": time.time(),
                             "real_send": False, "note": "纯计算·零下发 (下发只走 l2_daemon+8793 授权)"}}
        u_sat = _SS_STATE.get("u_sat", np.zeros(4))
        # 🎯 老倪 2026-11-15「运动规划节点输出 action, 机器人节点是执行」
        #   规划节点已给 action(位姿口径) ⇒ 本节点只执行, 绝不重算/重规划
        _in1 = ctx.get("in1")
        _act_in = None
        if isinstance(_in1, dict):
            if isinstance(_in1.get("action"), dict):
                _act_in = _in1["action"]
            elif _in1.get("pose") and str(_in1.get("src")) in ("plan", "ss", "traj215"):
                _act_in = _in1
        if isinstance(_act_in, dict) and _act_in.get("pose"):
            return _exec_action_verbatim(ctx, _act_in, log)

        _ex = ex.RobotExecutor()                       # 🔴 2026-10-29: 实例留住, 校验结论要带出去
        # 🎯 2026-11-01 老倪「右键打开源码要有断点, 在 VSCode 里我要看到执行指令」:
        #   停在这里时 u_sat 已绑定, 下一行 action 就是**真正下发的执行指令**。
        #   只在显式 ZMAX_BREAK_EXEC=1 时停 (GUI 里 breakpoint() 会冻界面 ⇒ 只在 CLI/调试档用)。
        if _os.getenv("ZMAX_BREAK_EXEC") == "1":
            # 走 debugpy 的原生断点: VSCode 里会真的停在调试器 UI 上 (变量面板能看 u_sat)
            try:
                import debugpy as _dbg                       # noqa: PLC0415
                if _dbg.is_client_connected():
                    _dbg.breakpoint()
                else:
                    breakpoint()                             # noqa: T100
            except Exception:                                # noqa: BLE001
                breakpoint()                                 # noqa: T100
        _allow_traj = bool(_os.getenv("ZMAX_DD_TRAJ_FALLBACK") == "1"
                           or _SS_STATE.get("dd_traj_fallback"))
        # 🎯 2026-11-14 老倪「execution.py:291 return action 改成真正的位姿, 你来重构」
        #   ⇒ execute() 现在返回 **Action(dict, 位姿口径)**: pose / joints_deg / grip_* / src / u / check
        #   ⇒ 这里不再自己拼位姿, 也不再把 4 维速度当"指令"; np.asarray(action) 仅作兼容
        action = _ex.execute(np.asarray(u_sat, dtype=float), allow_traj_fallback=_allow_traj)
        _chk = getattr(_ex, "last_check", None) or (action.get("check") if isinstance(action, dict) else {}) or {}
        _src = str(action.get("src") or "ss") if isinstance(action, dict) else "ss"
        _pose = (action.get("pose") if isinstance(action, dict) else None)
        _joints_deg = (action.get("joints_deg") if isinstance(action, dict) else None)
        try:
            _cmd = np.asarray(action, dtype=float).ravel()
        except Exception:                                                  # noqa: BLE001
            _cmd = np.zeros(4)
        if _cmd.size == 0:
            _cmd = np.zeros(4)
        _SS_STATE["pose_out"] = _pose
        _SS_STATE["_pose_dt"] = float(action.get("dt_s") or _SS_STATE.get("_pose_dt") or 0.1) \
            if isinstance(action, dict) else 0.1
        # 🎯 action = 状态空间工程的最终输出(唯一一份): 直接摊平执行器返回的 action 落盘
        _act = None
        try:
            from lerobot.policies.left_right.state_space import action_bus as _ab
            from lerobot.policies.left_right.state_space import direct_drive_guard as _ddg
            _v = _ddg.last() or {}
            _deny = ("护栏未放行 mode=%s ok=%s/%s %s"
                     % (_v.get("mode"), _v.get("ok_ticks"), _v.get("need"),
                        ("· " + str(_v.get("why"))[:40]) if _v.get("why") else ""))
            if _src == "ss" and not _v.get("allow"):
                # 护栏没放行 ⇒ 不认这份直驱, 落 215 点真值(与改造前同一判断)
                _act = _ab.from_traj215(why="215 点回放 · " + _deny)
            else:
                _act = _ab.from_action(action, deny=("" if _src != "ss" else _deny))
            _ab.publish(_act)
        except Exception:                                                  # noqa: BLE001
            _act = None
        _SS_STATE["action"] = _act
        if _src == "traj215":
            # 回退档: 输出的是 215 点关节真值(6 维, deg) ⇒ 不能当速度写 u_prev
            _SS_STATE["traj_cmd_deg"] = [float(x) for x in (_joints_deg or _cmd)]
            _SS_STATE["dd_active"] = False
            _SS_STATE["u_prev"] = np.zeros(3)      # 别把上一拍的直驱速度留在账上当"本拍指令"
        else:
            _SS_STATE["u_prev"] = np.asarray(action.get("u") or _cmd, dtype=float)[:3]
            _SS_STATE["dd_active"] = bool(_allow_traj)
        if log:
            _pz = _pose or {}
            log("🤖 机器人执行器 (真实): action[%s] 位姿 x=%.2f y=%.2f z=%.2f a=%.2f b=%.2f c=%.2f "
                "· 关节 %s · 夹爪 %smm/%s · 校验 %s clip=%s over_rate=%s"
                % (_src, _pz.get("x") or 0, _pz.get("y") or 0, _pz.get("z") or 0,
                   _pz.get("a") or 0, _pz.get("b") or 0, _pz.get("c") or 0,
                   ["%.2f" % float(v) for v in (_joints_deg or [])[:6]] or "-",
                   action.get("grip_mm") if isinstance(action, dict) else "-",
                   action.get("grip_act") if isinstance(action, dict) else "-",
                   "通过" if _chk.get("valid", True) else "拦下",
                   _chk.get("clip_hint") or "-", _chk.get("over_rate") or "-"))
        # 🥽 2026-11-01「要真接入 AR 场景」: 本拍 action 进 AR 链的 exec 分区
        try:
            from lerobot.engineering.exec import ar_bridge as _arb
            _arb.update("exec", {"kind": "exec",
                                 "src": _src,
                                 "u": ([] if _src == "traj215" else [round(float(x), 6) for x in (_cmd[:4] if _cmd.size >= 4 else [])]),
                                 "u_dim": int(_cmd.size),
                                 "pose": _pose,
                                 "joints_deg": ([round(float(x), 3) for x in _joints_deg] if _joints_deg else None),
                                 "fallback": _chk.get("fallback"),
                                 "u_sat": [round(float(x), 5) for x in np.asarray(u_sat, dtype=float).ravel()[:4]],
                                 "check": {"valid": bool(_chk.get("valid", True)),
                                           "over_rate": _chk.get("over_rate") or [],
                                           "fallback": _chk.get("fallback")},
                                 "src_file": "execution.py:RobotExecutor.execute → Action(pose)"}, src="ssact")
        except Exception:                                                # noqa: BLE001
            pass
        # 🔴 2026-10-29: out1 = 本拍真算出的 action + 显式零下发声明, 下游(页面/台账)可直接消费
        return {"out1": {"kind": "actuator",
                         "u_sat": [round(float(x), 5) for x in np.asarray(u_sat, dtype=float).ravel()[:4]],
                         # 🎯 工程最终输出 = action(位姿口径): 位姿/关节/夹爪/来源
                         "action": _act,
                         "src": _src,
                         "pose": _pose,
                         "joints_deg": _joints_deg,
                         "grip_mm": (action.get("grip_mm") if isinstance(action, dict) else None),
                         "u": (action.get("u") if isinstance(action, dict) else []),
                         "u_cmd": ([round(float(x), 6) for x in _cmd] if _cmd.size == 4 else []),
                         "u_cmd_dim": int(_cmd.size),
                         "fallback": _chk.get("fallback"),
                         "traj_cmd_deg": (_joints_deg if _src == "traj215" else _chk.get("traj_joint_deg")),
                         "n": int(_cmd.size), "src_file": "execution.py:RobotExecutor.execute",
                         "t": time.time(), "real_send": False,
                         "exec_check": _chk,          # NaN/范围/变化率 三项校验真结果 (不是恒等透传)
                         "note": "纯计算·零下发 (下发只走 exec/daemon.py + 8793 授权)",
                         "contract": ("v1" if _CT is not None else "missing"),
                         "gate_order": ([g[0] for g in _CT.GATE_ORDER] if _CT is not None else [])}}
    except Exception as e:
        if log:
            log(f"⚠️ 执行层真实执行失败: {e}")
        return {"out1": None}
