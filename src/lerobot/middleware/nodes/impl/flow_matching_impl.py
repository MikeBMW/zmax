# -*- coding: utf-8 -*-
"""🎯 Flow-Matching Action Head (DiT) — L3 层真执行 · **SmolVLA+LEW 正式启用**

老倪 2026-10-29:「继续接入 L3 层, 从万有引力节点和 flow matching 节点接入;
                 原则上, L2 层是基础输出, L3 是加权修正」
老倪 2026-10-29:「SmolVLA+LEW L3 层 用上这个模型, 正式启用, 用到 AR 场景,
                 保证接口对齐, 节点真实代码」

=== 正式启用的模型 (不是自检占位) ===
`src/lerobot/engineering/nodes/smolvla_lew_l3.py` — 真加载
`outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model` (实测跑通全链的版本:
insert 341 步 / full 865 步 + AOI PASS)。加载/预处理/反归一化口径与
`engine/runtime.py::_l3_forward` 逐条对齐 (128×128 LANCZOS、tasks.parquet 原串、post 反归一化、
device_processor 覆盖、类级缓存、熔断)。

=== 三个输入各自有真源 ===
  observation.image  ← AR 场景帧 (8797 /snap/local.jpg, 本机在线那路; 其余相机走产线)
  observation.state  ← trace_live.json 构造 metaworld 同构 39 维 (填充 31/39, 缺 8 维四元数如实标)
  task               ← 训练数据 tasks.parquet 原串「metaworld 光模块插拔」

=== L2 基础 / L3 修正 的显式分层 ===
  base_L2      = chunk_latest.ff[0]        (L2 前馈 MLP —— 基础输出, 未被模型替代)
  nominal_L3   = **SmolVLA+LEW 前向输出**  (L3 加权修正的来源, 正式启用)
  geodesic_ref = chunk_latest.chunk[0]     (测地线规划的块 —— 只作对照/回落, 不再当 L3 名义)
  delta        = nominal_L3 − base_L2      (修正量, 给万有引力 in3)

模型不可用(熔断/无帧/无观测)时 → **不伪装**: nominal 回落到 geodesic_ref 并标 `degraded` 与原因。

=== 接口 (画布连线为唯一依据, 本次不改线) ===
  out1 → n_moveit.in3 / ssff     (L3 名义动作 + 分层字段)
  out2 → ss_grav_h.in3           (L3 修正量矢量 → 万有引力分层力)

铁律: 只读真值 / 不造数 / 不下发动作 (下发只走 l2_daemon + 8793 授权)。
"""
from __future__ import annotations
import os
import time
from .shared_runtime import _REPO_ROOT
from ._single_thread import brk as _brk

_USE = "ZMAX_L3_SMOLVLA"          # =0 回退到测地线块 (默认 1 = 正式启用)


def _read_json(p):
    import json
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:                                                        # noqa: BLE001
        return None


def _vec(a, n=4):
    try:
        v = [float(x) for x in (a or [])[:n]]
        return v if len(v) == n else None
    except Exception:                                                        # noqa: BLE001
        return None


def _l4_in_summary(ctx):
    """把画布入端口上的 L4 数据摘出来 (in1: 潜空间 z/L4 条件; in5: 接触/性能流形坐标)。

    只做**透传**, 不注入模型: ckpt 里没有训练 l4_cond 通道 (action_head.ensure_l4_cond 是懒创建,
    权重随机 scale=0.02), 喂进去等于给动作加随机扰动 ⇒ 输出里如实标 l4_cond_injected=false。
    """
    out = {}
    for port in ("in1", "in5"):
        item = ctx.get(port)
        val = item.get("value") if isinstance(item, dict) else None
        if not isinstance(val, dict):
            out[port] = None
            continue
        keep = {}
        for k in ("kind", "layer", "progress_m", "risk_m", "risk_th_m", "Vdot",
                  "V_p", "eta", "tau", "M", "H", "stage", "idx", "ok", "frame_from"):
            if k in val:
                keep[k] = val[k]
        for k in ("grad", "axis", "vec"):
            a = val.get(k)
            if isinstance(a, (list, tuple)) and a:
                keep[k] = [round(float(y), 5) for y in a[:3] if isinstance(y, (int, float))]
        if not keep:
            keep = {"keys": sorted(val.keys())[:8]}
        keep["_age_s"] = (item.get("age_s") if isinstance(item, dict) else None)
        out[port] = keep
    # ⚠️ 画布 ssdec.in5 接了 3 条上游(接触流形/性能流形/潜空间), 而引擎 _collect_inputs
    #    是 ins[port]=src「最后一条覆盖」⇒ 只留最后那条, 另外两个流形信号被丢。
    #    这里从两个流形节点写的 _SS_STATE 补齐, 让动作头同时看到 contact + performance。
    try:
        from .shared_runtime import _SS_STATE as _SST
        _extra = {}
        _cm = _SST.get("contact_mani")
        if isinstance(_cm, dict):
            _extra["contact"] = {k: _cm.get(k) for k in
                                 ("progress", "risk", "risk_th", "Vdot", "axis") if k in _cm}
        _pm = _SST.get("perf_mani")
        if isinstance(_pm, dict):
            _extra["performance"] = {k: _pm.get(k) for k in ("V_p", "eta", "grad") if k in _pm}
        if _extra:
            out["in5_sources"] = _extra
    except Exception:                                                  # noqa: BLE001
        pass
    return out


def run(ctx):
    log = ctx.get("log")
    root = ctx.get("root") or _REPO_ROOT
    live = os.path.join(root, "zmax_data", "ss_live")
    try:
        # ── ① 真数据基线: L2 基础(ff) / 测地线参照块 ──────────────────────────
        ck = _read_json(os.path.join(live, "chunk_latest.json"))
        if not ck:
            if log:
                log("🎯 Flow-Matching: 缺 chunk_latest.json ⇒ 不出数, 不造数")
            return {"out1": None, "out2": None}
        age = time.time() - os.path.getmtime(os.path.join(live, "chunk_latest.json"))
        ch = _vec((ck.get("chunk") or [None])[0], 4)
        ff = _vec((ck.get("ff") or [None])[0], 4)
        u0 = _vec((ck.get("u") or [None])[0], 4)
        if ch is None and ff is None:
            if log:
                log("🎯 Flow-Matching: chunk[0]/ff[0] 都取不到 ⇒ 不出数")
            return {"out1": None, "out2": None}

        # ── ② SmolVLA+LEW 真前向 (AR 场景观测) ───────────────────────────────
        use_model = os.environ.get(_USE, "1") not in ("0", "false", "off")
        obs, obs_meta = (None, {"skipped": "开关关闭"})
        img, img_meta = (None, {"skipped": "开关关闭"})
        act, m_meta = (None, {"skipped": "开关关闭"})
        if use_model:
            from . import smolvla_lew_l3 as SL
            obs, obs_meta = SL.build_obs39(root, log)
            img, img_meta = SL.fetch_ar_frame()
            if obs is not None and img is not None:
                # 🔒 2026-10-29 老倪「550B 单线程模式, 除 GUI 外所有节点都单线程运行」:
                #   默认走 infer_async = 起 "l3-smolvla" 后台线程 ⇒ 断点停不住、线程数说不清。
                #   单线程模式改同步: 本线程内算完再往下, 一次一拍、可单步、可断点。
                try:
                    from . import _single_thread as _ST
                    _single = _ST.enabled()
                except Exception:                                          # noqa: BLE001
                    _single = os.environ.get("ZMAX_SINGLE_THREAD", "") == "1"
                if _single:
                    act, m_meta = SL.infer(img, obs, root, log)
                    m_meta = dict(m_meta or {})
                    m_meta["mode"] = "sync (ZMAX_SINGLE_THREAD=1 · 不起线程)"
                else:
                    act, m_meta = SL.infer_async(
                        img, obs, root, log,
                        min_period_s=float(os.environ.get("ZMAX_L3_PERIOD_S", "1.5")))
            else:
                m_meta = {"err": "观测或图像缺失", "obs_err": obs_meta.get("err"),
                          "img_err": img_meta.get("err")}

        # ── ③ 分层取舍: 模型可用 ⇒ L3 名义; 否则如实降级 ──────────────────────
        degraded, why = False, None
        if act is not None:
            nominal = [round(float(x), 6) for x in act[:4]]
            _ck_name = str(m_meta.get("ck") or "")
            nominal_src = "SmolVLA+LEW 前向 (%s)" % ("/".join(_ck_name.split("/")[-3:-1]) or "?")
        elif ch is not None:
            nominal, degraded = ch, True
            why = m_meta.get("err") or "模型尚无结果 (首拍加载中)"
            nominal_src = "降级: 测地线块 (模型未就绪)"
        else:
            nominal, degraded = ff, True
            why = "模型与测地线都没有"
            nominal_src = "降级: 前馈 ff"
        delta = [round(nominal[i] - ff[i], 6) for i in range(3)] if ff else None

        # ── ③b L4 几何注入 (2026-11-10 新增): 解析式, 不依赖未训练的 l4_cond 通道 ──
        #    L4 流形给出的 ∇V_p / 接触轴 / η 直接作用于 L3 名义动作:
        #      Δξ = −α M⁻¹∇V_p,  M = σ_t²P_t + σ_n²P_n (装配容差各向异性)
        #    实测(tools/verify_l4_injection.py): 1.0mm 横向偏差 3 拍收敛到 0.018mm、
        #    各向异性 400× 与 (σ_n/σ_t)² 吻合、257 段零限幅越界、Lyapunov 100%。
        _inj = {"injected": False, "reason": "未执行"}
        try:
            import numpy as np
            _l4sum = _l4_in_summary(ctx)
            _src5 = (_l4sum.get("in5_sources") or {})
            _perf = _src5.get("performance") or {}
            _cont = _src5.get("contact") or {}
            _grad = _perf.get("grad")
            _axis = _cont.get("axis")
            _pj = str((ctx.get("params") or {}).get("l4_inject", "on")).lower()
            # 🔑 参数真源: config/calib/zmax_manifold.json#inject (流形标定单一唯一依据)。
            #   画布 params.l4_inject_cfg 只做**现场临时覆盖**, 不改真源。
            #   真源缺 σt/σn ⇒ 不注入(不填默认值) —— 否则标定真源形同虚设。
            from lerobot.policies.manifold import inject_cfg as _icfg
            _cfg_src = _icfg.load()
            _oc = (ctx.get("params") or {}).get("l4_inject_cfg")
            if _pj in ("off", "0", "false") or os.environ.get("ZMAX_L4_INJECT") == "0":
                _inj = {"injected": False, "reason": "开关关闭(画布 l4_inject=off)"}
            elif not _icfg.enabled(_cfg_src):
                _inj = {"injected": False,
                        "reason": "真源 inject 关闭或缺失(%s)" % (_cfg_src.get("_missing") or _cfg_src.get("_err") or "enabled=false"),
                        "cfg_src": _cfg_src.get("_src")}
            elif _grad is None or len(_grad) < 3:
                _inj = {"injected": False, "reason": "性能流形未出 ∇V_p(无真值)"}
            else:
                _geo = _icfg.geometry(_cfg_src)
                if isinstance(_oc, dict):
                    _geo.update({k: float(v) for k, v in _oc.items() if isinstance(v, (int, float))})
                if not _geo:
                    _inj = {"injected": False,
                            "reason": "真源未标定 σt/σn ⇒ 不注入(不填默认值)",
                            "cfg_src": _cfg_src.get("_src")}
                else:
                    from lerobot.policies.manifold.geodesic_inject import correct as _geo_correct
                    nominal, _inj = _geo_correct(
                        nominal, _grad, _axis or [1.0, 0.0, 0.0],
                        eta=_perf.get("eta"), V_p=_perf.get("V_p"), cfg=_geo)
                    _inj["grad_src"] = "ssmani_p.grad (∇V_p = Wδ)"
                    _inj["cfg_src"] = _cfg_src.get("_src")
                    _inj["cfg_overridden"] = bool(isinstance(_oc, dict))
                if log and _inj.get("injected"):
                    log("🧭 L4 几何注入: Δξ=%s (径向 %.4f 轴向 %.4f) α=%.3f  [M: σ_t=%.2f σ_n=%.2f]"
                        % (np.round(_inj["delta"], 4), _inj["radial"], _inj["axial"],
                           _inj["alpha"],
                           float(_inj["metric"]["sigma_t_mm"]), float(_inj["metric"]["sigma_n_mm"])))
            # 📡 数据总线落地: 真注入才发信号 (未注入不发 —— 不填 0 冒充)
            #   注册键见 config/topics/scene_tags.json (场景=插拔场景, 信号分析页可见)
            if _inj.get("injected"):
                try:
                    from .shared_runtime import _REPO_ROOT as _RR, _load_mod as _LM
                    _bus = _LM("ar_aoi_bus", os.path.join(_RR, "tools", "ar_aoi_bus.py"))
                    _m = _inj.get("metric") or {}
                    _st = float(_m.get("sigma_t_mm") or 0.0)
                    _sn = float(_m.get("sigma_n_mm") or 0.0)
                    _bus.publish({
                        "L4注入.生效": 1.0,
                        "L4注入.Δξ_径向_mm": round(float(_inj.get("radial") or 0.0), 6),
                        "L4注入.Δξ_轴向_mm": round(float(_inj.get("axial") or 0.0), 6),
                        "L4注入.门控alpha": round(float(_inj.get("alpha") or 0.0), 6),
                        "L4注入.各向异性_比": (round((_sn / _st) ** 2, 1) if _st > 1e-9 else 0.0),
                        "L4注入.Vp代价_mm2": round(float(_inj.get("V_p") or 0.0), 6),
                        "L4注入.η置信度": round(float(_inj.get("eta") or 0.0), 6),
                    }, meta={"by": "ssdec L4 几何注入"}, quiet=True)
                except Exception as _be:                                   # noqa: BLE001
                    if log:
                        log("⚠️ L4 注入信号总线写入失败: %s" % _be)
        except Exception as _e:                                            # noqa: BLE001
            _inj = {"injected": False, "reason": "注入异常: %s" % _e}


        # ── ④ 输出 (端口字段与上一版兼容, 只增不改) ───────────────────────────
        _model = {k: m_meta.get(k) for k in
                  ("ck", "dev", "task", "load_ms", "infer_ms", "img_sz", "n_infer",
                   "n_done", "n_skip", "busy", "age_s", "mode", "min_period_s", "err")}
        if _model.get("ck"):
            try:
                _model["ck"] = os.path.relpath(str(_model["ck"]), root)
            except Exception:                                                # noqa: BLE001
                pass
        out1 = {
            "kind": "l3_nominal", "layer": "L3", "role": "加权修正",
            "base_L2": ff, "nominal_L3": nominal, "delta": delta,
            "nominal_src": nominal_src, "degraded": degraded, "degraded_why": why,
            "geodesic_ref": ch,                       # 测地线块: 只作对照
            "l4_in": _l4_in_summary(ctx),
            "l4_cond_injected": bool(_inj.get("injected")),
            "l4_inject": _inj,
            "l4_cond_note": (
                ("L4 几何量已【解析注入】动作: Δξ=−α·M⁻¹∇V_p, M=σt²Pt+σn²Pn (各向异性度规); "
                 "不依赖未训练的 l4_cond 通道, Lyapunov 保证 ∇VᵀΔξ≤0"
                 if _inj.get("injected") else
                 ("L4 几何注入未生效: %s —— 不造数, 动作保持 L3 名义值" % _inj.get("reason")))
                + " ; 另: ckpt 的 l4_cond 网络通道仍未训练(ensure_l4_cond 随机投影), 故不喂网络"),
            "sub_ref": (u0 if u0 else None),
            "model": _model,
            "obs39": {k: obs_meta.get(k) for k in
                      ("src", "age_s", "state_fill", "fill_ratio", "missing_dims",
                       "missing_note", "prev_src", "goal_src", "stage", "err")},
            "image": {k: img_meta.get(k) for k in ("cam", "shape", "url", "err", "tried")},
            "stage": ck.get("stage"), "cycle": ck.get("cycle"),
            "chunk_src": str(ck.get("chunk_src") or "")[:120],
            "ff_mode": ck.get("ff_mode"),
            "age_s": round(age, 3), "fresh": bool(age <= 5.0),
            "src": "SmolVLA+LEW(v10_1h/004000) + zmax_data/ss_live/{chunk_latest,trace_live}.json",
            "domain_gap": "训练域=metaworld 渲染 128×128; 推理域=AR 真机相机 —— 域不同, 不按训练成绩解读",
            "t": float(ck.get("ts") or time.time()),
        }
        # 🔴 2026-10-29 300UPH 链路补口 —— **action 断链的真因**:
        #   L3 名义动作此前只写 out1.nominal_L3 落盘, 从不写 _SS_STATE["u"]。
        #   而 sslimit 读的是 _SS_STATE["u"] ⇒ 永远 zeros ⇒ u_sat=zeros ⇒ ssact u_cmd=zeros。
        #   也就是说: 模型算得再对, 臂也拿不到 —— 全链只有 ssdec 有真值, 执行侧恒 0。
        try:
            from .shared_runtime import _SS_STATE as _SST
            import numpy as _np
            _SST["u"] = _np.asarray(nominal, dtype=float).ravel()[:4]
            _SST["u_src"] = str(nominal_src)
            _SST["u_degraded"] = bool(degraded)
            _SST["u_ts"] = float(time.time())
        except Exception as _e:                                              # noqa: BLE001
            if log:
                log(f"⚠️ L3 写 _SS_STATE[u] 失败: {type(_e).__name__}: {_e}")
        out2 = {
            "layer": "L3",
            "vec": delta if delta is not None else nominal[:3],
            "vec_semantics": ("修正量 nominal_L3−base_L2 (模型相对 L2 基础)" if delta is not None
                              else "L3 名义动作绝对量"),
            "nominal": nominal[:3], "base": (ff[:3] if ff else None),
            "model_ok": (act is not None), "degraded": degraded,
            "w_hint": "权重在 config/calib/layer_forces.json 的 w.L3 (热读, 见万有引力节点)",
            "age_s": round(age, 3), "fresh": bool(age <= 5.0),
            "src": nominal_src,
        }
        # ── ⑤ 落盘 (页面/信号分析/取证读同一份; 原子替换, 唯一写入者=本节点) ──
        try:
            import json as _j
            _p = os.path.join(live, "l3_latest.json")
            _t = _p + ".tmp"
            with open(_t, "w", encoding="utf-8") as fh:
                _j.dump({"out1": out1, "out2": out2, "t": time.time()},
                        fh, ensure_ascii=False, indent=1, default=float)
            os.replace(_t, _p)
        except Exception as _we:                                             # noqa: BLE001
            if log:
                log("⚠️ l3_latest.json 落盘失败: %s: %s" % (type(_we).__name__, _we))

        if log:
            log("🎯 Flow-Matching (L3 加权修正): 名义=%s [%s] · L2 基础=%s · 修正Δ=%s"
                % ([round(x, 4) for x in nominal[:3]], "模型" if act is not None else "降级",
                   ([round(x, 4) for x in ff[:3]] if ff else None), delta))
            if act is not None:
                log("   SmolVLA: infer=%.0fms · 动作龄=%.1fs · 在算=%s · 帧=%s · 观测填充 %.1f%% · 已推 %s 次"
                    % ((m_meta.get("infer_ms") or 0), (m_meta.get("age_s") or 0),
                       m_meta.get("busy"), img_meta.get("cam"),
                       (obs_meta.get("fill_ratio") or 0) * 100, m_meta.get("n_done")))
            else:
                log("   降级原因: %s" % why)
        return {"out1": out1, "out2": out2}
    except Exception as e:                                                   # noqa: BLE001
        if log:
            log("⚠️ Flow-Matching 节点失败: %s: %s" % (type(e).__name__, e))
        return {"out1": None, "out2": None}


def status():
    """供 /api 或页面查: 模型缓存状态 (不含大对象)。"""
    try:
        from . import smolvla_lew_l3 as SL
        return SL.cache_status()
    except Exception as e:                                                   # noqa: BLE001
        return {"err": "%s: %s" % (type(e).__name__, e)}
