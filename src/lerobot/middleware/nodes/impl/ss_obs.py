# -*- coding: utf-8 -*-
"""ss_obs — 节点实现正文 (文件名 = 画布节点: ss_obs)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_su2   ·   registry key: ss_obs
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
import os

from .shared_runtime import (  # noqa: F401
    _SS_FRAME_SRC,
    _SS_STATE,
    _ss_ensure_obs43,
    _ss_import,
    _ss_node_frame,
    _ss_su2_frame,
)

def compute_layer_weights(frame, obs43, l5):
    """层可靠度权重 (人: 「谁准听谁的」) —— 抽成函数便于单独验三档 (新鲜/过期/缺失)。

    返回 (weights, reasons)。规则:
      L2: obs43 在位 = 1.0 (没有 = 0, 该层本来就单位元)
      L3/L4: 引擎帧里该组读数非零才参与 (全 0 = 这拍没有该层证据)
      L5: 按帧龄线性衰减 w = 1 - age/TTL, 超 TTL = 0 —— 不拿旧意图当新证据
    """
    w = {"L2": 1.0 if obs43 is not None else 0.0,
         "L3": 0.0, "L4": 0.0, "L5": 0.0}
    r = {"L2": "obs43 在位" if w["L2"] else "obs43 缺失",
         "L3": "规划读数全 0", "L4": "安全读数全 0", "L5": "无 L5 意图 (该层单位元)"}
    _su2 = _ss_import("su2")                      # 延迟导入: 避免模块级循环依赖

    def _sc(v):
        try:
            return _su2._scalar(v, 0.0)
        except Exception:                                        # noqa: BLE001
            return 0.0

    try:
        fr = frame or {}
        if sum(abs(_sc(fr.get(k))) for k in ("mani_progress", "mani_dperp", "mani_rem")) > 1e-12:
            w["L3"], r["L3"] = 1.0, "规划读数在位"
        if sum(abs(_sc(fr.get(k))) for k in ("u_sat", "contact_p", "mani_eta")) > 1e-12:
            w["L4"], r["L4"] = 1.0, "安全/动作读数在位"
    except Exception:                                            # noqa: BLE001
        pass
    if l5:
        age = float(l5.get("age_s") or 0.0)
        ttl = float(os.environ.get("SS_L5_TTL_S", "60") or 60)
        w["L5"] = float(max(0.0, min(1.0, 1.0 - age / max(ttl, 1e-9))))
        r["L5"] = "L5 帧龄 %.1fs/%.0fs → 权重 %.2f" % (age, ttl, w["L5"])
    return w, r


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
        # ── 层可靠度权重 (2026-11-12: 「谁准听谁的」, 见 compute_layer_weights) ──
        _W, _R = compute_layer_weights(frame, obs43, _l5)
        # 加权: 权重作用在「该层的角贡献」上 (群内缩放, 剥离残余仍为 0)
        layers_raw = su2.encode_layers(frame, obs43)
        scene, layers = su2.scene_with_weights(layers_raw, _W)
        u = su2.understand(scene, layers)
        # ── 预测先行: 用前两拍外推本拍, 残差 = 预测 vs 实测 (只读, 不入下发) ──
        #   2026-11-12 实测: 直接对「群元素」做等角速度外推, 稳态残差就有 3~8° (编码是 tanh 非线性,
        #   群元素的变化率不是常数), 阶段突变被淹没 ⇒ 改成人真正的做法: **先预测输入, 再编码**。
        #   输入层标量 (progress/dperp/u_sat…) 线性外推, 再走同一套 encode+加权, 与实测场景比。
        _fp1 = _SS_STATE.get("_su2_frame_prev1")
        _fp2 = _SS_STATE.get("_su2_frame_prev2")
        _pred = None
        _NO_PREDICT = ("L2_quat", "L5_intent")     # 当下观测/慢先验: 不参与外推, 原样带过去
        if isinstance(_fp1, dict) and isinstance(_fp2, dict):
            try:
                _pred_fr = {}
                for _k, _v1 in _fp1.items():
                    _v2 = _fp2.get(_k)
                    if _k in _NO_PREDICT or isinstance(_v1, (list, tuple, dict, str)):
                        _pred_fr[_k] = _v1            # 非标量不外推 (外推四元数会推出非单位四元数 → 假残差)
                        continue
                    try:
                        _f1 = float(_v1)
                        _f2 = float(_v2) if _v2 is not None else _f1
                        _pred_fr[_k] = _f1 + (_f1 - _f2)          # 一阶外推: 2*f_{t-1} - f_{t-2}
                    except Exception:                            # noqa: BLE001
                        _pred_fr[_k] = _v1
                _pl = su2.encode_layers(_pred_fr, obs43)
                _pred, _ = su2.scene_with_weights(_pl, _W)
            except Exception:                                    # noqa: BLE001
                _pred = None
        _resid = su2.predict_residual(_pred, scene)
        _SS_STATE["_su2_frame_prev2"] = _fp1
        _SS_STATE["_su2_frame_prev1"] = dict(frame or {})
        _SS_STATE["su2_weights"] = {"w": _W, "reason": _R}
        _SS_STATE["su2_predict"] = _resid
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
                log("   %s %s  [权重 w=%.2f · %s]" % (L, layers[L].describe(), _W[L],
                                                    _SS_STATE["su2_weights"]["reason"][L]))
            log("   预测先行: 上一拍外推 vs 实测残差 %s° (只读, 不入下发)" % (
                "n/a (首拍无历史)" if _resid["residual_deg"] is None else "%.2f" % _resid["residual_deg"]))
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
        # 端口必须真产 —— 画布上 ssobs.out1/out2 喂 ssff·ssest·ssreason·ssvideo·ss_moe·n_geoplan,
        #   out3 喂 ss_mani_eng。原来只 return True ⇒ 6 个下游全部读到 None (2026-11-10 实测)
        # 2026-11-12 改: out2 不再复制一份 43D (那一份没有第二个信息量), 改为**分层结构体**
        #   (每层 θ/n̂/|w|/权重/剥离贡献), 下游要"按层取数"就取 out2, 要原始观测取 out1。
        import numpy as np
        # 同一拍必须同一份观测: L2 编码用的 obs43 与 out1 发出的必须是同一份 ——
        #   原来这里无条件再调 _ss_ensure_obs43 (演示帧/环境会重采样), 出现过"L2 与 out1 不同帧"。
        if obs43 is not None:
            _obs_src = obs43
            _same_frame = True
        else:
            _obs_src = _ss_ensure_obs43(log)
            _same_frame = False          # 演示帧: L2 用缓存, out1 取实时 (如实标注, 不假装同帧)
        _obs = [round(float(x), 6) for x in np.asarray(_obs_src, dtype=float).ravel()[:43]]
        _body = {"kind": "obs43", "dim": len(_obs),
                 "obs": _obs, "obs43": _obs,
                 "obs39": _obs[:39], "tactile": _obs[39:43],
                 "tcp": _obs[0:3], "grip": _obs[3:4], "peg": _obs[4:7],
                 "hole": _obs[36:39], "R": _obs[24:33],
                 "src": _SS_STATE.get("obs43_src", ""),
                 "same_frame_as_L2": _same_frame,
                 "layout": "0:3tcp 3grip 4:7peg 7:10rel 12:18q 18:24dq 24:33R 33:36target 36:39hole 39:43tactile"}
        _layers_body = {
            "L2": {"theta": round(float(layers["L2"].theta()), 6),
                   "axis": [round(float(v), 4) for v in layers["L2"].axis()],
                   "visibility": round(float(layers["L2"].visibility()), 4),
                   "weight": round(float(_W["L2"]), 4),
                   "contribution": round(float(u["layer_peel"]["L2"]["layer_theta"]), 6)},
            "L3": {"theta": round(float(layers["L3"].theta()), 6),
                   "axis": [round(float(v), 4) for v in layers["L3"].axis()],
                   "visibility": round(float(layers["L3"].visibility()), 4),
                   "weight": round(float(_W["L3"]), 4),
                   "contribution": round(float(u["layer_peel"]["L3"]["layer_theta"]), 6)},
            "L4": {"theta": round(float(layers["L4"].theta()), 6),
                   "axis": [round(float(v), 4) for v in layers["L4"].axis()],
                   "visibility": round(float(layers["L4"].visibility()), 4),
                   "weight": round(float(_W["L4"]), 4),
                   "contribution": round(float(u["layer_peel"]["L4"]["layer_theta"]), 6)},
            "L5": {"theta": round(float(layers["L5"].theta()), 6),
                   "axis": [round(float(v), 4) for v in layers["L5"].axis()],
                   "visibility": round(float(layers["L5"].visibility()), 4),
                   "weight": round(float(_W["L5"]), 4),
                   "contribution": round(float(u["layer_peel"]["L5"]["layer_theta"]), 6)},
        }
        return {"out1": dict(_body),
                "out2": {"kind": "su2_layers", "dim": 4,
                         "layers": _layers_body,
                         "weights": dict(_W),
                         "weight_reason": dict(_SS_STATE["su2_weights"]["reason"]),
                         "dominant_layer": u.get("dominant_layer"),
                         "scene": {"theta": round(float(scene.theta()), 6),
                                   "axis": [round(float(v), 4) for v in scene.axis()],
                                   "visibility": round(float(scene.visibility()), 4)}},
                "out3": {"kind": "su2", "dim": 43,
                         "readout": u.get("readout"),
                         "dominant_layer": u.get("dominant_layer"),
                         "layer_peel": u.get("layer_peel"),
                         "noncommutativity": u.get("noncommutativity"),
                         "weights": dict(_W),
                         "predict": dict(_resid),
                         # 🧩 位姿链入口: 参考姿态 (姿态真值 q_fused) —— 段表写 quat_ref 即可被执行器采用。
                         #   🔴 分量顺序: quat_truth 内部是 (w,x,y,z), 这里**转成执行器口径 (x,y,z,w)**
                         #   并显式标 order —— 实测不转会把"z 对 −z"发成"z 对 +z"(差 180°)。
                         #   没有姿态真值就是 None (不编造姿态), 下游按"保持当前"处理。
                         "quat_ref": ([round(float(_SS_STATE["quat_truth"]["q_fused"][1]), 6),
                                       round(float(_SS_STATE["quat_truth"]["q_fused"][2]), 6),
                                       round(float(_SS_STATE["quat_truth"]["q_fused"][3]), 6),
                                       round(float(_SS_STATE["quat_truth"]["q_fused"][0]), 6)]
                                      if isinstance(_SS_STATE.get("quat_truth"), dict)
                                      and len(_SS_STATE["quat_truth"].get("q_fused") or []) == 4 else None),
                         "quat_ref_order": "xyzw",
                         "quat_ref_src": (_SS_STATE.get("quat_truth") or {}).get("axis"),
                         "layers": {k: (v.describe() if hasattr(v, "describe") else str(v))
                                    for k, v in (layers or {}).items()}},
                "ok": True}
    except Exception as e:                                              # noqa: BLE001
        if log:
            log("⚠️ SU(2) 统一状态映射失败: %s" % e)
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_su2
