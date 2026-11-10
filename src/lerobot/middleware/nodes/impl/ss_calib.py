# -*- coding: utf-8 -*-
"""ss_calib — 节点实现正文 (文件名 = 画布节点: ss_calib)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_calib   ·   registry key: ss_calib
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _CALIB_DIR,
    _SS_STATE,
    _load_mod,
    os,
)

def node_ss_calib(ctx):
    """🧮 标定层 — 引力(快速动作)/斥力(状态预测) 二分超参数 + 平衡点
    源码: src/lerobot/calibration/calibration_layer.py (CalibrationLayer) — 与 datasets/policies 同级别
    回路外元层: 收集/展示标定参数, 不参与引擎推理, 不改变拓扑/流程/架构"""
    log = ctx.get("log")
    try:
        import numpy as np
        path = os.path.join(_CALIB_DIR, "calibration_layer.py")
        m = _load_mod("lerobot.calibration.calibration_layer", path)   # 正常 import (断点可绑)
        layer = m.CalibrationLayer()
        # 当前运行状态: 画布播放中从 module._ss_tr 取当前步 (与 _ss_tick idx 同映射)
        mod = ctx.get("module")
        stage, speed, residual, contact_p = "接近", 0.0, 0.0, 0.0
        tr = getattr(mod, "_ss_tr", None) if mod is not None else None
        if tr is not None and tr.get("x") is not None and len(tr["x"]) > 0:
            idx = int(min(getattr(mod, "_ss_round", 0), len(tr["t"]) - 1))
            stage = str(tr["stage"][idx]).replace("阶段 ", "")
            # 🐛 2026-09-03: tr["u_sat"] 存的是标量范数 (float), 不是向量 —
            #   [:3] 索引 0-d 数组抛 "too many indices" (既有 bug, 被 try 吞)
            _us = tr["u_sat"][idx] if "u_sat" in tr else tr.get("u_sat_vec", [0])[idx]
            speed = float(np.linalg.norm(np.asarray(_us, dtype=float)) )
            residual = float(tr["residual"][idx])
            contact_p = float(tr["contact_p"][idx])
        gap = layer.equilibrium_gap(stage, speed, residual, contact_p)
        _SS_STATE["calib"] = {"layer": layer, "stage": stage, "gap": gap,
                              "attr": layer.attr, "rep": layer.rep, "lat": layer.lat}
        # 端口: 画布 sscalib.out1 → sslat.in1 / out2 → ss_mani_eng.in3(度量/势场参数)
        #       / out3 → n_calib_mani.in1(标定层单一唯一依据)。原实现只 return True ⇒ 三路全空。
        _rb = {"kind": "calib", "layer": "L4", "ok": True,
               "stage": str(stage), "speed": float(speed), "residual": float(residual),
               "contact_p": float(contact_p),
               "gap": (float(gap) if isinstance(gap, (int, float)) else None),
               "attr": dict(layer.attr), "rep": dict(layer.rep), "lat": dict(layer.lat),
               "Kp": layer.attr.get("Kp"),
               "K_kalman": layer.rep.get("K_kalman"),
               "contact_gain": layer.rep.get("contact_gain"),
               "veto_th": layer.rep.get("veto_th"),
               "latent_dim": (layer.lat or {}).get("latent_dim"),
               "state_dim": (layer.lat or {}).get("state_dim"),
               "summary": str(layer.summarize(stage, speed, residual, contact_p))[:200],
               "src": "src/lerobot/calibration/calibration_layer.py::CalibrationLayer"}
        if log:
            log(f"🧮 标定层 (真实): {layer.summarize(stage, speed, residual, contact_p)}")
            log(f"   引力标定 (快速动作): Kp={layer.attr['Kp']} · 当前阶段速度上限 "
                f"{layer.attr['stage_v_cap'].get(stage, '—')} m/s")
            log(f"   斥力标定 (状态预测): K_kalman={layer.rep['K_kalman']} · 残差EMA={layer.rep['res_ema']} · "
                f"接触增益={layer.rep['contact_gain']} · 否决阈值={layer.rep['veto_th']}")
            log(f"   {layer.latent_summary()}")
        return {"out1": dict(_rb), "out2": dict(_rb), "out3": dict(_rb), **_rb}
    except Exception as e:
        if log:
            log(f"⚠️ 标定层执行失败: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_calib
