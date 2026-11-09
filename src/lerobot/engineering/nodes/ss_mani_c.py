# -*- coding: utf-8 -*-
"""ss_mani_c — 节点实现正文 (文件名 = 画布节点: ss_mani_c)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_mani   ·   registry key: ss_mani_c
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _MANIFOLD_DIR,
    _NodeOut,
    _SS_STATE,
    _load_mod,
    _ss_frame,
    os,
)

def node_ss_mani(ctx):
    """🧮 流形层 — 接触流形 (插拔通道: 切向进度/法向偏离/V) ‖ 性能流形 (对准代价 V_p/η)
    源码: src/lerobot/manifold/manifold_layer.py (ContactManifold / PerformanceManifold)
    回路外元层: 从引擎轨迹当前帧取真实量 (obs/peg_head/target/v/stage) 实算,
    断点可进; 不参与推理, 不新增安全通道 (唯一三层安全=否决+限幅+Sys0)"""
    log = ctx.get("log")
    try:
        import numpy as np
        path = os.path.join(_MANIFOLD_DIR, "manifold_layer.py")
        m = _load_mod("lerobot.manifold.manifold_layer", path)          # 正常 import (断点可绑)
        name = ctx.get("name", "")
        # 当前帧真源: GUI 播放态 module._ss_tr → 无 GUI 时 ss_traj_last.json (L4 统一帧, 见 _ss_frame)
        fr = _ss_frame(ctx)
        if fr is None:
            if log:
                log("⚠️ 流形层: 无帧真源 — GUI 播放态与 ss_traj_last.json 都取不到")
            return False
        idx, stage = int(fr["idx"]), fr["stage"]
        hand, peg_head, target, v = fr["hand"], fr["peg_head"], fr["target"], fr["v"]
        _SS_STATE["mani_frame"] = {"idx": idx, "stage": stage, "src": fr["src"], "from": fr["from"]}
        if "接触" in name:
            cm = m.ContactManifold()
            r = cm.decompose(hand, peg_head, target, v, stage)
            _SS_STATE["contact_mani"] = r
            # ⛓ 承接 L4 LoRA 节点算出的接触约束 (摩擦锥/穿透罚) —— 同一组数, 不另算一套
            _ll = _SS_STATE.get("lora_l4") or {}
            _lc = _ll.get("contact") or {}
            if log and _lc:
                log("   ⛓ 来自 L4 LoRA 节点的接触约束: f_n=%.3f ‖f_t‖=%.3f 锥余量 %.3f → %s · Φ_c=%.4g"
                    % (float(_lc.get("f_n") or 0.0), float(_lc.get("f_t_norm") or 0.0),
                       float(_lc.get("slack") or 0.0),
                       "在锥内" if _lc.get("inside_cone") else "越锥(已投影)",
                       float(_lc.get("phi_c") or 0.0)))
            if log:
                log(f"🧮 接触流形 (真实·t={fr['t']:.2f}s {stage} · {fr['from']}帧{idx}): {cm.summarize(r)}")
                if r["axis"] is not None:
                    log(f"   通道轴 â={np.round(r['axis'],3)} · 切向进度 "
                        f"‖e∥‖={r['progress']:.4f}m · 法向偏离 ‖e⊥‖={r['risk']:.4f}m "
                        f"(阈 {r['risk_th']}m) · V̇={r['Vdot']:.3e} (负=沿测地线收敛)")
                else:
                    log(f"   自由空间 (转移段无接触约束) · ‖e‖={r['progress']:.4f}m · "
                        f"V̇={r['Vdot']:.3e}")
            return _NodeOut({
                "kind": "contact_manifold", "layer": "L4", "ok": True,
                "stage": stage, "idx": idx, "t": round(float(fr["t"]), 3),
                "frame_src": fr["src"], "frame_from": fr["from"],
                "axis": (None if r.get("axis") is None else [float(x) for x in r["axis"]]),
                "progress_m": float(r.get("progress") or 0.0),
                "risk_m": float(r.get("risk") or 0.0),
                "risk_th_m": float(r.get("risk_th") or 0.0),
                "Vdot": float(r.get("Vdot") or 0.0),
                "summary": str(cm.summarize(r)),
                "src": "src/lerobot/manifold/manifold_layer.py::ContactManifold.decompose",
            })
        if "性能" in name:
            _ll2 = _SS_STATE.get("lora_l4") or {}
            _lp = _ll2.get("performance") or {}
            if log and _lp:
                log("   ⛓ 来自 L4 LoRA 节点的性能流形: V_p=%.4g · η=%.4f · 黎曼梯度范数 %.4g (g_p 度量)"
                    % (float(_lp.get("V_p") or 0.0), float(_lp.get("eta") or 0.0),
                       float(np.linalg.norm(np.asarray(_lp.get("riemann_grad") or [0.0], float)))))
            pm = m.PerformanceManifold()
            r = pm.evaluate(peg_head, stage=stage)
            _SS_STATE["perf_mani"] = r
            if log:
                log(f"🧮 性能流形 (真实·t={fr['t']:.2f}s {stage} · {fr['from']}帧{idx}): {pm.summarize(r)}")
                log(f"   修正方向 ∇V_p={np.round(r['grad'],4)} (最优对准 = 沿 −∇ 下山到 δ→0)")
            return _NodeOut({
                "kind": "perf_manifold", "layer": "L4", "ok": True,
                "stage": stage, "idx": idx, "t": round(float(fr["t"]), 3),
                "frame_src": fr["src"], "frame_from": fr["from"],
                "V_p": float(r.get("V_p") or 0.0),
                "eta": float(r.get("eta") or 0.0),
                "grad": ([float(x) for x in r["grad"]] if r.get("grad") is not None else []),
                "summary": str(pm.summarize(r)),
                "src": "src/lerobot/manifold/manifold_layer.py::PerformanceManifold.evaluate",
            })
        if log:
            log("⚠️ 流形层: 节点名未识别接触/性能分派")
        return False
    except Exception as e:
        if log:
            log(f"⚠️ 流形层执行失败: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_mani
