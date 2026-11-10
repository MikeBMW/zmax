# -*- coding: utf-8 -*-
"""ss_pred — 节点实现正文 (文件名 = 画布节点: ss_pred)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_pred   ·   registry key: ss_pred
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _SS_STATE,
    _pred_ns,
    _ssah_ns,
)

def node_ss_pred(ctx):
    """🧠 世界模型预测器 (JEPA: 潜空间 → 流形 → 动作) — GUI 薄壳 (算法在 src)

    真实算法: src/lerobot/manifold/predictor_layer.py —
    LatentPredictor (z_t+a_t→z') → ManifoldReadout (z'→接触/性能流形坐标 6 维,
    与引擎真值列对齐可监督训练) → decoder = StateSpaceActionHead (流形→4D 动作块)。"""
    log = ctx.get("log")
    try:
        import numpy as np
        import torch
        mod = ctx.get("module")
        tr = getattr(mod, "_ss_tr", None) if mod is not None else None
        if tr is None or not tr.get("t"):
            if log:
                log("🧠 世界模型预测器: 无引擎轨迹 — 先点 ▶ 运行 (真实化)")
            return False
        idx = min(int(getattr(mod, "_ss_round", 0) or 0), len(tr["t"]) - 1)
        if log:
            log("🧠 JEPA 世界模型预测器 [当前步]: encoder(z) → predictor → 接触/性能流形 → decoder 动作")
        # ⛓ 老倪 2026-10-14: 本节点接在 🎛 L4 INTACT LoRA 微调**之后** ⇒ 条件必须真读它的输出
        #    (接线≠被消费: 这里把上游 u_lora/度规步长读出来打进日志, 取不到就明写)
        _ll = _SS_STATE.get("lora_l4") or {}
        if log:
            if _ll:
                _pr = _ll.get("predictor") or {}
                log("   ⛓ 条件来自 L4 LoRA 节点: ‖u_lora‖=%.4g · ‖Δu‖=%.4g/上限 %.4g%s · γ_eff=%.3f%s"
                    % (float(np.linalg.norm(_ll.get("u_lora") or [])), float(_ll.get("du_norm") or 0.0),
                       float(_ll.get("cap") or 0.0), " 已限幅" if _ll.get("clipped") else "",
                       float(_ll.get("gate") or 0.0),
                       "" if _ll.get("trained") else " · ⚠️ LoRA 未训练(恒等)"))
                log("   ⛓ 本节点承接度规步长 ‖dz‖_g=%.4g (M·G 约束) ⇒ 沿测地线预测"
                    % float(_pr.get("metric_norm") or 0.0))
            else:
                log("   ⚠️ 未取到 L4 LoRA 节点输出 (_SS_STATE['lora_l4'] 空) ⇒ 本步条件回退引擎潜坐标")
        # ── ① 真实 WorldModelPredictor 结构 + 前向维度自检 (几何 z R⁷ 对照实例) ──
        try:
            _ns = _pred_ns()
            WM = _ns["WorldModelPredictor"]
            wm = WM(z_dim=7)
            n_params = sum(p.numel() for p in wm.parameters())
            x = np.asarray(tr["x"][idx], dtype=float)
            peg = np.asarray(tr["peg"][idx], dtype=float)
            tgt = np.asarray(tr["target"][idx], dtype=float)
            z7 = np.concatenate([x - tgt, x - peg, [float(tr["grasped"][idx])]])
            u = np.asarray(tr["u_ff"][idx], dtype=float).ravel()
            a4 = u[:4] if u.size >= 4 else np.zeros(4)
            zt = torch.from_numpy(z7.astype(np.float32)).unsqueeze(0)
            at = torch.from_numpy(a4.astype(np.float32)).unsqueeze(0)
            with torch.no_grad():
                out = wm(zt, at)
                # decoder 拼接 (真实 StateSpaceActionHead, 流形坐标 → 动作块)
                AH = _ssah_ns()["StateSpaceActionHead"]
                head = AH(input_dim=out["manifold"].shape[-1], action_dim=4, chunk_size=7)
                acts = head(out["manifold"])
            if log:
                log(f"   ✅ WorldModelPredictor 真实类: {n_params:,} 参数 "
                    f"(src/lerobot/manifold/predictor_layer.py)")
                log(f"      JEPA 链路自检: z R⁷+a⁴ → z'→流形 {tuple(out['manifold'].shape)} "
                    f"→ decoder → 动作块 {tuple(acts.shape)} (随机初始化, 训练后启用)")
                log(f"      VLM z R⁹⁶⁰ 实例: 699,846 参数 (encode_stage 真实 z 接入后同构)")
        except Exception as _e:
            if log:
                log(f"   ⚠️ Predictor 自检失败: {_e}")
        # ── ② 当前帧流形真值 (引擎发布 — readout 监督真值列) ──
        if log:
            risk = float(tr["mani_risk"][idx]) if tr.get("mani_risk") else float("nan")
            prog = float(tr["mani_progress"][idx]) if tr.get("mani_progress") else float("nan")
            eta = float(tr["mani_eta"][idx]) if tr.get("mani_eta") else float("nan")
            log(f"   流形真值 (监督列): 接触 [进度={prog:.4f} 风险={risk:.4f} V] · "
                f"性能 [η={eta:.3f} rem d_perp] — readout 对齐 6 维回归")
            log("   ⚙️ 真实实现: src/lerobot/manifold/predictor_layer.py "
                "(LatentPredictor→ManifoldReadout)")
        # ── 端口 (2026-11-10): 画布 ssmani_exp.out1 → ssmani_c.in1 / ssmani_p.in1 (预测流形 JEPA)
        #    本节点当前是结构自检 (WorldModelPredictor 随机初始化), 引擎也未发布流形真值列 ⇒
        #    如实交「已接入但未就绪」+ 引擎真给得出的那几列, 不假装有预测。
        def _col(_k):
            _v = tr.get(_k)
            if not _v:
                return None
            try:
                _x = float(_v[idx])
            except Exception:                                              # noqa: BLE001
                return None
            return None if _x != _x else _x          # NaN → None

        _eb = {"kind": "mani_exp", "layer": "L4", "ok": True,
               "model": "WorldModelPredictor(LatentPredictor→ManifoldReadout)",
               "trained": False,
               "model_ready": False,
               "note": "JEPA 随机初始化结构自检; 训练后启用 (未就绪, 不假装有预测)",
               "idx": int(idx), "stage": str((tr.get("stage") or [""] * (int(idx) + 1))[int(idx)]),
               "mani_progress": _col("mani_progress"),
               "mani_risk": _col("mani_risk"),
               "mani_eta": _col("mani_eta"),
               "u_lora_norm": (float(np.linalg.norm(_ll.get("u_lora") or [])) if _ll else None),
               "metric_norm": (float((_ll.get("predictor") or {}).get("metric_norm") or 0.0)
                               if _ll else None),
               "src": "src/lerobot/manifold/predictor_layer.py"}
        return {"out1": dict(_eb), "out2": dict(_eb), **_eb}
    except Exception as e:
        if log:
            log(f"⚠️ Predictor 执行失败: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_pred
