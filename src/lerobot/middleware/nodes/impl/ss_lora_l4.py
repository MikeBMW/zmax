# -*- coding: utf-8 -*-
"""ss_lora_l4 — 节点实现正文 (文件名 = 画布节点: ss_lora_l4)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_lora_l4   ·   registry key: ss_lora_l4
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _REPO_ROOT,
    _SS_STATE,
)

def node_ss_lora_l4(ctx):
    """🎛 L4 · INTACT LoRA 微调 (在役链路位置: INTACT 意图解码器 → **本节点** → 流形专家预测器)

    老倪 2026-10-14: 「不想动 INTACT 原始模型权重，只需要修改 LoRA 节点；元任务预测节点的输出也要
    接到 INTACT LoRA 微调节点；然后向后连接流形专家预测器，以及接触流形、性能流形。」

    数学 (src/lerobot/manifold/manifold_chain.py, 可单跑自检):
      ① LoRA 层: u_lora = u_int + γ·Δu,  Δu = γ_eff·(α/r)·mean_j(B_j A_j φ)   ← 原权重 W0 **冻结**
         γ_eff = g(元任务预测值)  (L4/L5 层元任务预测得分的焦点权重 ⇒ 增益)
         限幅: ‖Δu‖ ≤ ρ·容量, 容量=(α/r)‖B_j‖_F‖A_j‖_F‖φ_j‖  (ρ=0.35, 可复核上界)
      ② 流形专家预测器: ẑ = z − δ·g⁻¹∇Φ(z) + R(z,u_lora);  g=M·G(x), det G=1
      ③ 接触流形约束: 法向/切向分解 + Coulomb 摩擦锥 (‖f_t‖≤μf_n, 越锥投影) + 穿透罚 Φ_c
      ④ 性能流形约束: V_p=½δᵀWδ · η=exp(−V_p/σ²) · 黎曼梯度 g_p⁻¹∇V_p · 帕累托非劣闸
    """
    import json as _j
    import os as _o7
    import numpy as _np

    log = ctx.get("log")
    sys_path = _o7.path.join(_REPO_ROOT, "src")
    if sys_path not in __import__("sys").path:
        __import__("sys").path.insert(0, sys_path)
    try:
        from lerobot.manifold.manifold_chain import (ContactConstraint, L4Adapter,
                                                     ManifoldExpert, PerformanceConstraint)
    except Exception as e:                                                # noqa: BLE001
        if log:
            log(f"❌ L4 LoRA 链导入失败: {type(e).__name__}: {str(e)[:110]}")
        return False

    # ── ① 产物真源 (LoRA 包装 ckpt: 只有它含 lora_A/B; merged_* 已折叠=改了原权重, 不用) ──
    ad = L4Adapter(_REPO_ROOT)
    ok_a, note_a = ad.load()
    if log:
        log("🎛 L4 · INTACT LoRA 微调 (INTACT 意图解码器 → 本节点 → 流形专家预测器)")
        log(f"   原权重: 冻结 (base.weight 不动) · 产物: {note_a}")

    # ── ② 意图输入 u_int (真源优先级: 上游节点写入 > 引擎潜坐标 > 轨迹帧 > 无) ──
    u_int, u_src = None, ""
    st = _SS_STATE.get("lora_in") or {}
    if isinstance(st, dict) and st.get("u_int"):
        u_int = _np.asarray(st["u_int"], float); u_src = str(st.get("src") or "上游节点写入")
    mod = ctx.get("module")
    tr = getattr(mod, "_ss_tr", None) if mod is not None else None
    if u_int is None:
        me = _SS_STATE.get("mani_eng") or {}
        z_eng = me.get("z") if isinstance(me, dict) else None
        if z_eng is not None:
            u_int = _np.asarray(z_eng, float); u_src = "流形引擎 L4 潜坐标 z"
    def _has_tr(_t):        # tr["t"] 可能是 list 也可能是 ndarray ⇒ 不能用布尔真值判断 (实测 ambiguous)
        try:
            return bool(_t) and (len(_t.get("t")) > 0 if _t.get("t") is not None else False)
        except Exception:                                                # noqa: BLE001
            return False
    if u_int is None and _has_tr(tr):
        idx = int(min(getattr(mod, "_ss_round", 0) or 0, len(tr["t"]) - 1))
        u_int = _np.asarray(tr["obs"][idx][:16], float) if tr.get("obs") else None
        u_src = f"轨迹帧 obs[:16] (idx={idx})"
    if u_int is None:
        u_int = _np.zeros(16)
        u_src = "无意图输入 (占位 0) ⇒ Δu 平凡"

    # ── ③ 元任务预测值 (门控真源: zmax_data/ss_live/meta_pred.json) ──
    meta_pred = None
    mp_path = _o7.path.join(_REPO_ROOT, "zmax_data", "ss_live", "meta_pred.json")
    if _o7.path.exists(mp_path):
        try:
            meta_pred = _j.load(open(mp_path, encoding="utf-8"))
        except Exception:                                                 # noqa: BLE001
            meta_pred = None

    # ── ④ 链路一步: LoRA → 专家预测 → 接触流形 → 性能流形 ──
    stage = str(_SS_STATE.get("mani_frame", {}).get("stage") or _SS_STATE.get("stage") or "")
    r_lora = ad.forward(u_int, meta_pred, stage)
    grad_phi = _np.asarray((_SS_STATE.get("mani_eng") or {}).get("grad") or _np.zeros(16), float)
    expo = ManifoldExpert(M=float(_SS_STATE.get("M") or 3.643))
    r_pred = expo.step(r_lora["u_lora"], grad_phi)
    cc = ContactConstraint()
    hand = f_vec = axis = v_vec = None
    h_pen = 0.0
    if _has_tr(tr):
        idx = int(min(getattr(mod, "_ss_round", 0) or 0, len(tr["t"]) - 1))
        try:
            hand = _np.asarray(tr["x"][idx], float)
            peg_head = _np.asarray(tr["peg_head"][idx], float)
            target = _np.asarray(tr["target"][idx], float)
            v_vec = _np.asarray(tr["v_vec"][idx], float) if tr.get("v_vec") else _np.zeros(3)
            from lerobot.manifold.manifold_layer import ContactManifold  # noqa: PLC0415
            cm = ContactManifold()
            dec = cm.decompose(hand, peg_head, target, v_vec, stage)
            axis = dec.get("axis")
            f_vec = _np.concatenate([_np.asarray(dec.get("e_par", _np.zeros(3)), float),
                                     _np.asarray(dec.get("e_perp", _np.zeros(3)), float)])[:3]
        except Exception:                                                 # noqa: BLE001
            pass
    if axis is None:
        axis = _np.array([1.0, 0.0, 0.0])
    if f_vec is None:
        f_vec = _np.asarray(r_lora["du"][:3], float)
        f_src = "Δu 前 3 维 (无轨迹帧 ⇒ 无真实接触力, 如实)"
    else:
        f_src = "轨迹帧 e∥/e⊥ 合成 (真实几何误差作接触力输入)"
    r_contact = cc.apply(f_vec, axis, v=v_vec, h=h_pen)
    pc = PerformanceConstraint()
    d_perf = None
    if _has_tr(tr):
        try:
            d_perf = _np.asarray(tr["peg_head"][idx], float) - _np.asarray(tr["target"][idx], float)
        except Exception:                                                 # noqa: BLE001
            d_perf = None
    r_perf = pc.evaluate(_np.zeros(3) if d_perf is None else d_perf)

    # ── ⑤ 交给下游 (流形专家预测器/接触流形/性能流形 节点真读这里) ──
    _SS_STATE["lora_l4"] = {
        "u_int": r_lora["u_int"].tolist(), "u_lora": r_lora["u_lora"].tolist(),
        "du_norm": r_lora["du_norm"], "capacity": r_lora["capacity"], "cap": r_lora["cap"],
        "clipped": bool(r_lora["clipped"]), "trained": bool(r_lora["trained"]),
        "gate": float(r_lora["gate"][0]), "src": r_lora["src"], "note": note_a,
        "predictor": {"z_next": r_pred["z_next"].tolist(), "metric_norm": r_pred["metric_norm"]},
        "contact": {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in r_contact.items()},
        "performance": {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in r_perf.items()},
    }
    if log:
        log(f"   意图输入 u_int: {u_src} · ‖u_int‖={float(_np.linalg.norm(r_lora['u_int'])):.4g}")
        log("   " + ad.summary(r_lora))
        log(f"   元任务预测门控: {r_lora['gate_note']}")
        log("   " + expo.summary(r_pred))
        log(f"   接触流形 [{f_src}]: " + cc.summary(r_contact))
        log("   性能流形: " + pc.summary(r_perf) + ("" if d_perf is not None
            else " ⚠️ 无轨迹帧 ⇒ δ=0 (平凡, 不是真性能)"))
        if not r_lora["trained"]:
            log("   ⚠️ 未训练/无产物 ⇒ Δu=0 (恒等, 零回归) —— 没有假装有微调")
        else:
            log("   ⏳ 待办: LoRA A/B 与统一主干/阶段专家同口径 A/B (留出集+平凡基线) 有提升才切在役指针")
    # ── 端口 (2026-11-10): 画布 ss_lora_l4.out1..out4 分别喂 预测器/接触流形/性能流形/动作头 L4 条件,
    #    原实现只 return True ⇒ 4 路全空 (值为 _SS_STATE["lora_l4"] 里已算好的那些, 这里如实交出)
    _lb = dict(_SS_STATE["lora_l4"])
    _lb.update({"kind": "lora_l4", "layer": "L4", "ok": True,
                "src_node": "src/lerobot/middleware/nodes/impl/ss_lora_l4.py::node_ss_lora_l4"})
    return {"out1": dict(_lb), "out2": dict(_lb), "out3": dict(_lb), "out4": dict(_lb), **_lb}


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_lora_l4
