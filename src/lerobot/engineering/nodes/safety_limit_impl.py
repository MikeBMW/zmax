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


def run(ctx):
    log = ctx.get("log")
    try:
        import numpy as np
        name = ctx.get("name", "")
        if "边界" in name:
            u = _SS_STATE.get("u", np.zeros(4))
            u_sat = _ss_import("safety").saturate(np.asarray(u, dtype=float), limit=0.6)
            _SS_STATE["u_sat"] = np.asarray(u_sat, dtype=float)
            if log:
                log(f"🛡 安全执行边界 (真实): saturate(u={np.round(u,3)}, limit=0.6) → "
                    f"u_sat={np.round(u_sat,3)} (safety.py)")
            return True
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
