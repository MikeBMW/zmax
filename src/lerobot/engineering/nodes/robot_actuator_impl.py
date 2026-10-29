# -*- coding: utf-8 -*-
"""🤖 机器人执行器 (RobotExecutor.execute) / 🌍 物理世界 (PhysicalWorld 质量/惯量)

老倪 2026-10-28「把执行链上的节点按顺序迁出来」——
  实现正文从 registry 大文件 nodes/library.py 迁到本文件；library.node_ss_exec 只剩薄壳转调，
  右键「打开源代码」直接落到本文件 `run()`（registry key = `ss_act`）。

执行链位置: 运动规划 → 🤖 机器人执行器 (RobotExecutor.execute) / 🌍 物理世界 (PhysicalWorld 质量/惯量) → 动作执行器 → 机器人执行器
铁律: 只读真值 / 不造数 / 不下发动作 (下发只走 l2_daemon + 8793 授权)。
本文件正文与迁移前逐字一致 (仅补显式 import 与文件头)。
"""
from __future__ import annotations
import time
from .library import _SS_STATE, _ss_import   # 与 registry 共用同一份运行时状态 (同源)
from ._single_thread import brk as _brk


def run(ctx):
    _brk("act")          # ZMAX_DEBUG_BREAK=act 时停在这里
    log = ctx.get("log")
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
        u_vec = _ex.execute(np.asarray(u_sat, dtype=float))
        _chk = getattr(_ex, "last_check", None) or {}
        if np.ndim(u_vec) == 0:
            u_vec = np.zeros(4)
        _SS_STATE["u_prev"] = np.asarray(u_vec, dtype=float)[:3]
        if log:
            log(f"🤖 机器人执行器 (真实): execute(u_sat={np.round(u_sat,3)}) → 指令={np.round(u_vec,4)} "
                f"(execution.py) · 校验 {'通过' if _chk.get('valid', True) else '拦下'} "
                f"clip={_chk.get('clip_hint') or '-'} over_rate={_chk.get('over_rate') or '-'}")
        # 🔴 2026-10-29: out1 = 本拍真算出的指令 + 显式零下发声明, 下游(页面/台账)可直接消费
        return {"out1": {"kind": "actuator", "u_sat": [round(float(x), 5) for x in np.asarray(u_sat, dtype=float).ravel()[:4]],
                         "u_cmd": [round(float(x), 6) for x in np.asarray(u_vec, dtype=float).ravel()[:4]],
                         "n": int(np.asarray(u_vec).size), "src": "execution.py:RobotExecutor.execute",
                         "t": time.time(), "real_send": False,
                         "exec_check": _chk,          # NaN/范围/变化率 三项校验真结果 (不是恒等透传)
                         "note": "纯计算·零下发 (下发只走 l2_daemon+8793 授权)"}}
    except Exception as e:
        if log:
            log(f"⚠️ 执行层真实执行失败: {e}")
        return {"out1": None}
