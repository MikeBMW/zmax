# -*- coding: utf-8 -*-
"""🧪 状态校正器 (state_correction) / 📈 先验动力学预测器 (PriorDynamicsPredictor)

老倪 2026-10-28「把执行链上的节点按顺序迁出来」——
  实现正文从 registry 大文件 nodes/library.py 迁到本文件；library.node_ss_dyn 只剩薄壳转调，
  右键「打开源代码」直接落到本文件 `run()`（registry key = `ss_correct`）。

执行链位置: 运动规划 → 🧪 状态校正器 (state_correction) / 📈 先验动力学预测器 (PriorDynamicsPredictor) → 动作执行器 → 机器人执行器
铁律: 只读真值 / 不造数 / 不下发动作 (下发只走 l2_daemon + 8793 授权)。
本文件正文与迁移前逐字一致 (仅补显式 import 与文件头)。
"""
from __future__ import annotations
from .shared_runtime import _SS_STATE, _ss_ensure_obs43, _ss_env_obs, _ss_import, _ss_tactile_mod   # 与 registry 共用同一份运行时状态 (同源)


def run(ctx):
    log = ctx.get("log")
    try:
        import numpy as np
        name = ctx.get("name", "")
        obs43 = _ss_ensure_obs43(log)
        act4 = np.concatenate([_SS_STATE.get("u_prev", np.zeros(3)), [0.0]])
        if "校正" in name:
            cog = _ss_import("cognition")
            prior = _SS_STATE.get("prior")
            if prior is None:
                dyn = _ss_import("dynamics")
                lat = _SS_STATE.get("latent", obs43[:4])
                prior = dyn.PriorDynamicsPredictor(A=1.0, B=0.02).predict(np.asarray(lat, dtype=float), act4)
                _SS_STATE["prior"] = np.asarray(prior, dtype=float)
            obs39 = _SS_STATE.get("obs39")
            if obs39 is None:
                obs39, _ = _ss_env_obs(log)
            tac = np.asarray(_ss_tactile_mod().synth_tactile(obs39.reshape(1, 39))).reshape(4)
            z_k = np.concatenate([obs39[0:3], [tac[1]]])
            corrected, residual = cog.state_correction(np.asarray(prior, dtype=float), z_k, K=0.5)
            r = float(np.linalg.norm(residual))
            cp = float(cog.contact_probability(r, gain=8.0))
            _SS_STATE.update({"residual": np.asarray(residual, dtype=float), "contact_p": cp,
                              "corrected": np.asarray(corrected, dtype=float)})
            if log:
                log(f"🧪 状态校正器 (真实): state_correction(prior,z_k) → residual={np.round(residual,4)} · "
                    f"接触概率={cp:.3f} (cognition.py)")
            # 端口必须真产 (画布: ssinnov.out1→sssched.in8 / out2→sssensor.in5);
            #   只写 _SS_STATE ⇒ 走端口的下游读到 None (2026-11-10 实测空口)
            _res = [round(float(x), 6) for x in np.asarray(residual, dtype=float).ravel()]
            return {"out1": {"kind": "state_correct", "layer": "L2",
                             "u_fb": _res, "residual": _res, "contact_p": round(cp, 4),
                             "K": 0.5, "source": "cognition.py state_correction"},
                    "out2": {"kind": "corrected_state",
                             "corrected": [round(float(x), 6) for x in np.asarray(corrected, dtype=float).ravel()],
                             "latent": [round(float(x), 6) for x in np.asarray(corrected, dtype=float).ravel()]},
                    "ok": True}
        dyn = _ss_import("dynamics")
        lat = _SS_STATE.get("latent", obs43[:4])
        _dn = dyn.PriorDynamicsPredictor(A=1.0, B=0.02)
        prior = _dn.predict(np.asarray(lat, dtype=float), act4)
        _SS_STATE["prior"] = np.asarray(prior, dtype=float)
        if log:
            log(f"📈 先验动力学预测器 (真实): predict(latent,act) → next_obs={np.round(prior,4)} (dynamics.py)")
        # 端口必须真产 (画布: sspred.out1→ssinnov.in2 "next_obs 预测")
        return {"out1": {"kind": "dyn_prior", "layer": "L2",
                         "next_obs": [round(float(x), 6) for x in np.asarray(prior, dtype=float).ravel()],
                         "prior": [round(float(x), 6) for x in np.asarray(prior, dtype=float).ravel()],
                         "contact_p": (getattr(_dn, "last_contact", None)
                                       if getattr(_dn, "last_contact", None) is None
                                       else round(float(_dn.last_contact), 4)),
                         "A": 1.0, "B": 0.02, "n_wm": _dn.n_wm, "n_linear": _dn.n_linear,
                         "source": "dynamics.py PriorDynamicsPredictor"},
                "ok": True}
    except Exception as e:
        if log:
            log(f"⚠️ 动力学预测-校正真实执行失败: {e}")
        return False
