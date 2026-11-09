# -*- coding: utf-8 -*-
"""ss_obs — 节点实现正文 (文件名 = 画布节点: ss_obs)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_su2   ·   registry key: ss_obs
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _SS_FRAME_SRC,
    _SS_STATE,
    _ss_ensure_obs43,
    _ss_import,
    _ss_node_frame,
    _ss_su2_frame,
)

def node_ss_su2(ctx):
    """🧩 SU(2) 统一状态空间 — 真实执行 su2.py::SU2UnifiedState (群映射, 非拼接)

    L2(43D 几何误差) ⊗ L3(流形规划) ⊗ L4(安全动作) ⊗ L5(大模型意图) → 场景群元素;
    输出: 状态方向 n̂ / 偏离角 θ / 收敛度|w| + 逐层剥离贡献 + 层间不可交换性 (全实测量)。

    ctx["demo_light"]=True (▶运行 播放路径): **不冷加载** YOLO/metaworld, obs43 只取缓存
    (_SS_STATE["obs43"]); 群运算是纯 numpy ~1ms, 不会卡播放 — 且**真实执行 su2.py**,
    所以在 su2.py 里设的断点在 ▶运行 时也能命中 (2026-09-20 老倪: "运行后断点不进入")。
    """
    log = ctx.get("log")
    light = bool(ctx.get("demo_light"))
    try:
        mod = ctx.get("module")
        su2 = _ss_import("su2")
        if light:
            obs43 = _SS_STATE.get("obs43")          # 仅缓存, 不触发采样
            if obs43 is None and log:
                log("🧩 SU(2) (演示帧): L2 无缓存 obs43 → 该层为单位元 (不冷加载 YOLO/metaworld)")
        else:
            obs43 = _ss_ensure_obs43(log)
        frame = _ss_su2_frame(mod, log)
        # 🧠 L5 层真输入 (2026-11-03): DeepSeek 意图 → frame["L5_intent"] (3 维, 基座系方向)。
        #   l5_intent 内部单飞+TTL 缓存, **不阻塞节拍**; 没有结果就不写这个字段 ⇒ L5 落单位元
        #   (su2.encode_layer 本来就这么写: 未接入 = 单位元, 不编造), 但这里会把"为什么没有"打进日志。
        _l5 = None
        try:
            _stage = None
            try:
                _tr0 = getattr(mod, "_ss_tr", None) or {}
                _st0 = _tr0.get("stage") or []
                if _st0:
                    _stage = str(_st0[min(int(getattr(mod, "_ss_round", 0) or 0), len(_st0) - 1)])
            except Exception:                                            # noqa: BLE001
                _stage = None
            _l5 = _ss_import("l5_intent").intent(
                obs43, {**frame, "stage": _stage or frame.get("stage")})
            if _l5 and _l5.get("vec"):
                frame = {**frame, "L5_intent": [float(v) for v in _l5["vec"]]}
                _SS_STATE["l5_intent"] = _l5
        except Exception as _e:                                          # noqa: BLE001
            if log:
                log("⚠️ L5 大模型意图不可用 (%s: %s) → L5 层落单位元" % (type(_e).__name__, _e))
        # 🧩 四元数真值 (记忆基准) + 感知补偿 (2026-11-03 策略): L2 用**精确四元数**, 不走 tanh 压缩
        #   真值 = 记忆技能库轴向 (data/memory/l2_store/skills.json) + 离线 IK 验证过的 yaw;
        #   补偿 = obs43 的 光模块→孔位 方向 (新鲜才参与, 过期 w=0, 不拿旧测量当新证据);
        #   输出 = q_fused 给群/流形/规划, 并写 quat_truth_latest.json 供下游消费。
        try:
            import numpy as _np
            _qt = _ss_import("quat_truth")
            _axis, _meas_q, _age = "z_pos", None, None
            _src = str(_SS_STATE.get("obs43_src") or "")
            try:
                if obs43 is not None and len(obs43) >= 39:
                    _e = _np.asarray(obs43[4:7], float) - _np.asarray(obs43[36:39], float)
                    _n = float(_np.linalg.norm(_e))
                    if _n > 1e-9:
                        _d = -_e                                    # 插入方向 = 孔位−光模块
                        if abs(_d[0]) >= abs(_d[2]):
                            _axis = "x_pos" if _d[0] >= 0 else "x_neg"
                        else:
                            _axis = "z_pos" if _d[2] >= 0 else "z_neg"
                        _meas_q = _qt.q_for_axis(-_e / _n)          # 插入方向 = 孔位−光模块
                        _age = 0.0 if _src.startswith("yolo") else None
            except Exception:                                        # noqa: BLE001
                pass
            _qr = _qt.observe(axis=_axis, meas_q=_meas_q, meas_age_s=_age)
            frame = {**frame, "L2_quat": list(_qr["q_fused"])}
            _SS_STATE["quat_truth"] = _qr
            try:
                _qt.write_contract(_qr)
            except Exception:                                        # noqa: BLE001
                pass
            if log and int(getattr(mod, "_ss_round", 0) or 0) % 20 == 0:
                log("🧩 四元数真值: 轴=%s 偏差 %.3f° 势 V=%.6f 测量权重 %.2f 引力|%.4f| 源=%s"
                    % (_qr["axis"], _qr["err_deg"], _qr["V"], _qr["w_meas"],
                       float(_np.linalg.norm(_qr["gravity"])), _src or "obs43"))
        except Exception as _e:                                      # noqa: BLE001
            if log:
                log("⚠️ 四元数真值层不可用 (%s: %s) → L2 回 43D 误差指示器" % (type(_e).__name__, _e))
        st = _SS_STATE.get("_su2_state")
        if st is None:
            st = su2.SU2UnifiedState(log=None)
            _SS_STATE["_su2_state"] = st
        scene, layers, u = st.push(frame, obs43)
        _SS_STATE["su2_scene"] = scene
        _SS_STATE["su2_layers"] = layers
        _SS_STATE["su2_readout"] = u
        try:
            _nf = _ss_node_frame(mod, log)
            nodes = su2.encode_nodes(_nf) if _nf else {}
            if nodes:
                _SS_STATE["su2_nodes"] = nodes
                _SS_STATE["su2_nodes_src"] = "%s, %d 节点" % (_SS_FRAME_SRC.get("src"), len(nodes))
        except Exception:                                               # noqa: BLE001
            pass
        if log:
            log("🧩 SU(2) 统一状态空间 (二阶特殊酉群): %s" % u["readout"])
            for L in ("L2", "L3", "L4", "L5"):
                log("   %s %s" % (L, layers[L].describe()))
            if _l5:
                log("   🧠 L5 源=%s conf=%s · 意图=%s · why=%s · age=%ss · 时延=%sms%s"
                    % (_l5.get("src"), _l5.get("conf"), _l5.get("vec"), _l5.get("why"),
                       _l5.get("age_s"), _l5.get("latency_ms"),
                       " · ⚠️与孔位方向不符(cos=%.2f)" % _l5["cos_vs_to_hole"]
                       if _l5.get("suspicious") and _l5.get("cos_vs_to_hole") is not None else
                       (" · cos(指向孔)=%.2f" % _l5["cos_vs_to_hole"]
                        if _l5.get("cos_vs_to_hole") is not None else "")))
            else:
                log("   🧠 L5 意图: 暂无新鲜结果 (DeepSeek 后台单飞, 实测 60~130s/次) → 该层为单位元")
            log("   群反演剥离: 残余 θ=%.2e (≈0 ⇒ 分解自洽) · 主导层=%s · 层间不可交换 L2|L4=%.4f"
                % (u["layer_peel"]["_residual"]["theta"], u["dominant_layer"],
                   u["noncommutativity"].get("L2|L4", 0.0)))
            log("   (43D obs = 群里的 L2 输入块; 其余节点数据按 NODE_SPECS 各自映射成群元素)")
        return True
    except Exception as e:                                              # noqa: BLE001
        if log:
            log("⚠️ SU(2) 统一状态映射失败: %s" % e)
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_su2
