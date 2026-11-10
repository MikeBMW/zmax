# -*- coding: utf-8 -*-
"""🖐 Marker 触觉跟踪 — gen_tactile.synth_tactile 从 39D 合成 4D (夹持/接触/方向)

老倪 2026-10-28「把执行链上的节点按顺序迁出来」——
  实现正文从 registry 大文件 nodes/library.py 迁到本文件；library.node_yolo_tactile 只剩薄壳转调，
  右键「打开源代码」直接落到本文件 `run()`（registry key = `yolo_tactile`）。

执行链位置: 运动规划 → 🖐 Marker 触觉跟踪 → 动作执行器 → 机器人执行器
铁律: 只读真值 / 不造数 / 不下发动作 (下发只走 l2_daemon + 8793 授权)。
本文件正文与迁移前逐字一致 (仅补显式 import 与文件头)。
"""
from __future__ import annotations
from .shared_runtime import _SS_STATE, _ss_env_obs, _ss_tactile_mod   # 与 registry 共用同一份运行时状态 (同源)


def run(ctx):
    log = ctx["log"]
    try:
        import numpy as np
        obs39 = _SS_STATE.get("obs39")
        if obs39 is None:
            obs39, _ = _ss_env_obs(log)
            _SS_STATE["obs39"] = obs39
        tac = np.asarray(_ss_tactile_mod().synth_tactile(obs39.reshape(1, 39))).reshape(4)
        _SS_STATE["tactile4"] = tac
        if log:
            log(f"📍 Marker 触觉 (真实): grasp={tac[0]:.3f} contact={tac[1]:.3f} "
                f"dir=({tac[2]:.2f},{tac[3]:.2f}) (gen_tactile.py)")
        # 端口必须真产 (画布: sstactile.out1→sssensor.in3 "触觉 4D (力/接触)")
        #   原来 return True ⇒ 融合定位建图的触觉输入一直是 None (2026-11-10 实测)
        _t = [round(float(v), 6) for v in np.asarray(tac, dtype=float).ravel()[:4]]
        return {"out1": {"kind": "tactile4", "layer": "L2", "dim": len(_t),
                         "tactile": _t,
                         "grasp": _t[0] if _t else None,
                         "contact": _t[1] if len(_t) > 1 else None,
                         "dir": _t[2:4],
                         "source": "policies/yolo_3d/gen_tactile.py synth_tactile"},
                "ok": True}
    except Exception as e:
        if log:
            log(f"⚠️ 触觉合成真实执行失败: {e}")
        return False
