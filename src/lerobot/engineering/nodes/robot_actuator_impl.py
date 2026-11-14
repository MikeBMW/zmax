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
from .library import _SS_STATE, _ss_import   # 与 registry 共用同一份运行时状态 (同源)
from ._single_thread import brk as _brk


def _run_legacy(ctx):
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
        from ..exec import contract as _CT
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
        _ex = ex.RobotExecutor()                       # 🔴 2026-10-29: 实例留住, 校验结论要带出去
        # 🎯 2026-11-01 老倪「右键打开源码要有断点, 在 VSCode 里我要看到执行指令」:
        #   停在这里时 u_sat 已绑定, 下一行 u_vec 就是**真正下发的执行指令**。
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
        u_vec = _ex.execute(np.asarray(u_sat, dtype=float))
        _chk = getattr(_ex, "last_check", None) or {}
        if np.ndim(u_vec) == 0:
            u_vec = np.zeros(4)
        _SS_STATE["u_prev"] = np.asarray(u_vec, dtype=float)[:3]
        if log:
            log(f"🤖 机器人执行器 (真实): execute(u_sat={np.round(u_sat,3)}) → 指令={np.round(u_vec,4)} "
                f"(execution.py) · 校验 {'通过' if _chk.get('valid', True) else '拦下'} "
                f"clip={_chk.get('clip_hint') or '-'} over_rate={_chk.get('over_rate') or '-'}")
        # 🥽 2026-11-01「要真接入 AR 场景」: 本拍真算出的执行指令进 AR 链的 exec 分区
        try:
            from ..exec import ar_bridge as _arb
            _arb.update("exec", {"kind": "exec",
                                 "u": [round(float(x), 6) for x in np.asarray(u_vec, dtype=float).ravel()[:4]],
                                 "u_sat": [round(float(x), 5) for x in np.asarray(u_sat, dtype=float).ravel()[:4]],
                                 "check": {"valid": bool(_chk.get("valid", True)),
                                           "over_rate": _chk.get("over_rate") or []},
                                 "src_file": "execution.py:RobotExecutor.execute"}, src="ssact")
        except Exception:                                                # noqa: BLE001
            pass
        # 🔴 2026-10-29: out1 = 本拍真算出的指令 + 显式零下发声明, 下游(页面/台账)可直接消费
        return {"out1": {"kind": "actuator", "u_sat": [round(float(x), 5) for x in np.asarray(u_sat, dtype=float).ravel()[:4]],
                         "u_cmd": [round(float(x), 6) for x in np.asarray(u_vec, dtype=float).ravel()[:4]],
                         "n": int(np.asarray(u_vec).size), "src": "execution.py:RobotExecutor.execute",
                         "t": time.time(), "real_send": False,
                         "exec_check": _chk,          # NaN/范围/变化率 三项校验真结果 (不是恒等透传)
                         "note": "纯计算·零下发 (下发只走 exec/daemon.py + 8793 授权)",
                         "contract": ("v1" if _CT is not None else "missing"),
                         "gate_order": ([g[0] for g in _CT.GATE_ORDER] if _CT is not None else [])}}
    except Exception as e:
        if log:
            log(f"⚠️ 执行层真实执行失败: {e}")
        return {"out1": None}


def run(ctx):
    """统一出口: 正文在 lerobot.middleware.nodes.impl.robot_actuator_impl(位姿口径 action)。

    2026-11-14 老倪「return action 改成真正的位姿」—— 执行器返回
    pose / joints_deg / grip_* / src, 不再返回 4 维速度; 两份实现并存必然漂移, 故只留一份。
    转发失败(极端情况)才回落本文件历史实现 _run_legacy。
    """
    try:
        from lerobot.middleware.nodes.impl.robot_actuator_impl import run as _run2
        return _run2(ctx)
    except Exception:                                                      # noqa: BLE001
        return _run_legacy(ctx)
