# -*- coding: utf-8 -*-
"""ss_mani_eng — 节点实现正文 (文件名 = 画布节点: ss_mani_eng)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_mani_eng   ·   registry key: ss_mani_eng
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _MANIFOLD_DIR,
    _MANI_ENG_CACHE,
    _NodeOut,
    _REPO_ROOT,
    _SS_STATE,
    _mani_product_block,
    _ss_engine_idx,
    _ss_traj_files,
    os,
    sys,
    time,
)

def node_ss_mani_eng(ctx):
    """🧮 流形引擎 — 高维状态 → 低维流形 (编码/投影/度量/导航/反馈 五阶段真跑)。

    🏷 本节点同时是**产品标识**与**空间质数结构化理解能力**的输出口 (老倪 2026-10-13):
      产品标识 (550A 原创版 / 550B 标定版 / 550C 量产版) 与版本段回读配置真源
      config/platform/zmax_product.json 的 active_product; 能力集合由质数指纹给出唯一编码
      (可逆分解, 无冗余); 当前发布指纹回读真源台账; 结构理解把"当前结构" (产品能力里的元数据
      基元 + 本帧工序阶段) 与记忆库比对, 报出已知/未见 (未见结构 = 自主进化的输入); 并给
      谱对称正则项 / 锚点稀疏度 / 采样课程当前值 (只读, 不改写度量张量)。
      返回 dict (见 _mani_product_block): product_id / version_segment / cap_signature / fingerprint /
      understand{signature,known,seen_structures,novel_events,evolution_input} / symmetry / anchor_* /
      sample_rate; 另带 ok = 本节点真跑成功与否 (与改造前的 True/False 同义)。
    """
    log = ctx.get("log")
    # 🕒 2026-10-31 老倪「怎么超节拍了」: 本节点每拍 ~22-38ms (质数结构理解里 json.dump 大对象),
    #   再撞上 ssyolo 真推理那一拍 (40-60ms) ⇒ 合计 107ms > 100ms 预算 (10Hz 每 5 拍超一次)。
    #   本节点输出是标量/指纹级, 没必要 10Hz 重算 ⇒ 按 ZMAX_MANI_PERIOD_S (默认 0.25s) 节流,
    #   其余拍回放上次结果 (带 cached_ago_s), 下游每拍照样有值。
    _now_t = time.monotonic()
    _per_t = float(os.environ.get("ZMAX_MANI_PERIOD_S", "0.25"))
    _c_t = _MANI_ENG_CACHE
    if _c_t.get("out") is not None and (_now_t - float(_c_t.get("t") or 0.0)) < _per_t:
       _o_t = dict(_c_t["out"])
       _o_t["cached_ago_s"] = round(_now_t - float(_c_t["t"]), 3)
       return _NodeOut(_o_t)

    def _ret(ok):
        """返回**结果字典** (含 ok=本节点真跑成功与否, 与改造前的 True/False 同义)。

        2026-10-29: 原来只带产品标识块 (_prod), 几何/健康/扭矩算完却没进返回值 ⇒ 下游拿不到。
        现在把 _mani_geo (dim/mode/min_eig/det_g/kappa/tau/H) 一并带出; 变量未定义时安全降级。
        """
        try:
            _d = dict(_prod if isinstance(_prod, dict) else {})
        except NameError:                                                    # noqa: BLE001
            _d = {}
        _d["ok"] = bool(ok)
        try:
            if isinstance(_mani_geo, dict):
                _d["mani_geo"] = dict(_mani_geo)
                for _k in ("dim", "mode", "scale", "min_eig", "det_g", "kappa",
                           "geodesic_dev", "tau", "H", "H_metric", "H_vitality"):
                    if _k in _mani_geo:
                        _d[_k] = _mani_geo[_k]
        except NameError:                                                    # noqa: BLE001
            _d["mani_geo"] = None
        _MANI_ENG_CACHE["out"] = dict(_d)          # 供下一拍节流回放
        _MANI_ENG_CACHE["t"] = time.monotonic()
        return _NodeOut(_d)

    # ⓪ 🆕 2026-10-12 老倪: 「主参数 M 的功能, 要由**流形引擎节点**实现, 通过一个结构, 承接要实现的功能」。
    #   ⇒ 本节点先消费**配置单映射出的主参数 M** (= 度量张量 g_ij(x)=M·G_ij(x) 的尺度), 真跑算:
    #     ① 度量几何量 (dim/mode/独立分量/正定 min_eig/det g/联络 ‖Γ‖/曲率 κ=‖R‖)
    #     ② 健康度 H (= 度量几何健康 × 内稳态生命力; 内稳态真跑 homeostasis.py)
    #     ③ 扭矩 τ = M·‖Γ v v‖ (曲率回正力矩: 等效惯量 M × 测地线弯曲加速度; 各向同性 ⇒ Γ=0 ⇒ τ=0, 零回归)
    # ── 🏷 产品标识 + 空间质数结构化理解 (真跑先出: 与轨迹无关, 任何返回路径都带上) ──
    _g_metric = None
    try:
        import importlib.util as _ilu_me
        import numpy as _np_me
        _s_me = _ilu_me.spec_from_file_location("config_to_M", os.path.join(_REPO_ROOT, "tools", "config_to_M.py"))
        _cm = _ilu_me.module_from_spec(_s_me)
        sys.modules["config_to_M"] = _cm
        _s_me.loader.exec_module(_cm)
        _sp = _cm.compute_M()                                       # 配置单 → M (与主参数 M 节点同一映射函数)
        import lerobot.manifold.metric_field as _MF
        _mf = _MF.MetricField(dim=int(_sp["dim"]), scale=float(_sp["scale"]), mode=str(_sp["mode"]),
                              diag=_sp["diag"], comps=_sp["components"], gain=_sp["gain"])
        _okp, _mn, _detg = _mf.is_positive_definite()
        _spec_g = _mf.spec()
        _cr = _mf.curvature_report()
        _kappa = float(_cr.get("‖R‖_F", 0.0))
        _x0 = _np_me.zeros(int(_sp["dim"]))
        _v0 = _np_me.zeros(int(_sp["dim"]))
        _v0[0] = 1.0
        _geo = _mf.geodesic_curve(_x0, _v0, steps=5, dt=0.05)[-1]
        _dev = float(_np_me.linalg.norm(_geo - (_x0 + _v0 * 0.25)))
        _g_metric = _mf.shape(_x0)                                  # 度量真值形状 → 谱对称正则项用 (只读)
        _Gam = _mf.christoffel(_x0)
        _tau = float(_sp["scale"]) * float(_np_me.linalg.norm(_np_me.einsum("kij,i,j->k", _Gam, _v0, _v0)))
        _H_metric = 1.0 if (bool(_okp) and abs(float(_np_me.linalg.det(_mf.shape(_x0))) - 1.0) < 1e-9) else 0.0
        try:
            from lerobot.manifold.homeostasis import HomeostasisEngine as _HE
            _H_vit = float((_HE().drive(dt=0.01) or {}).get("vitality", 1.0))
        except Exception:                                                       # noqa: BLE001
            _H_vit = None
        _H = _H_metric * (_H_vit if _H_vit is not None else 1.0)
        _mani_geo = {"task": _sp["task_id"], "dim": _sp["dim"], "mode": _sp["mode"], "scale": _sp["scale"],
                     "min_eig": _mn, "det_g": _detg, "kappa": _kappa, "geodesic_dev": _dev, "tau": _tau,
                     "H_metric": _H_metric, "H_vitality": _H_vit, "H": _H, "audit_sha": _sp["audit_sha"]}
        _SS_STATE["mani_geo"] = _mani_geo
        if log:
            log("🧮 流形引擎 · 用主参数 M 算几何/健康/扭矩 (M ← 配置单 %s 映射, 审计 %s)"
                % (_sp["task_id"], _sp["audit_sha"][:12]))
            log("   ① 度量 g=M·G: dim=%d · mode=%s · 独立分量 %d · M=%.4g · 正定 %s (min_eig %.4g) · det g %.4g"
                % (_spec_g["dim"], _spec_g["mode"], _spec_g["独立分量数"], _spec_g["尺度 M"],
                   "✅" if _okp else "❌", _mn, _detg))
            log("   ② κ (曲率) = ‖R‖_F = %.6g · 联络 ‖Γ‖_F = %.6g · 测地线偏离欧氏直线 %.4g"
                " (常度量 gain=0 ⇒ Γ=0)" % (_kappa, float(_cr.get("‖Γ‖_F", 0.0)), _dev))
            log("   ③ 健康度 H = %.4g (= 度量几何健康 %.3g × 内稳态生命力 %s)"
                % (_H, _H_metric, ("%.5g" % _H_vit) if _H_vit is not None else "N/A"))
            log("   ④ 扭矩 τ = M·‖Γ v v‖ = %.6g (曲率回正力矩: 等效惯量 M × 测地线弯曲加速度; 常度量⇒0)"
                % _tau)
    except Exception as _e:                                                     # noqa: BLE001
        if log:
            log("⚠️ 主参数 M 几何层不可用 (流形引擎续跑): %r" % (_e,))
    # ── 🏷 产品标识 (550A/550B/550C) + 空间质数结构化理解能力: 真源回读, 与轨迹无关 ──
    _mod_now = ctx.get("module") if isinstance(ctx, dict) else None
    _step_now = int(getattr(_mod_now, "_ss_round", 0) or 0) or 1
    _prod = _mani_product_block(ctx, log=log, g=_g_metric, step=_step_now)
    _SS_STATE["mani_product"] = _prod                    # 进链路缓存: 画布/控制台/外部可读
    if isinstance(ctx, dict):
        ctx["mani_product"] = _prod                      # 调用方也能直接取 (不改其它节点契约)
    try:
        import importlib.util as _ilu
        import numpy as np
        path = os.path.join(_MANIFOLD_DIR, "manifold_engine.py")
        _mn = "lerobot.manifold.manifold_engine"
        spec = _ilu.spec_from_file_location(_mn, path)
        m = _ilu.module_from_spec(spec)
        # 🔴 2026-10-29 老倪「流形引擎断点在哪里 / 这里进不去」: 少了这一行, pydevd 按模块名在
        #   sys.modules 里找不到这个文件 ⇒ manifold_engine.py 里**所有断点都绑不上**
        #   (函数照跑, VSCode 不停, 也不报错)。旁边的 prime_structure 一直有注册, 这里漏了。
        import sys as _sys_mani
        _sys_mani.modules[_mn] = m
        spec.loader.exec_module(m)
        mod = ctx.get("module")
        tr = getattr(mod, "_ss_tr", None) if mod is not None else None
        _tsrc, _tidx = "module._ss_tr (GUI 播放)", None
        if tr is not None and tr.get("t"):
            _tidx = int(min(getattr(mod, "_ss_round", 0) or 0, len(tr["t"]) - 1))
        else:
            # L4 统一帧回退 (2026-10-29 老倪「流形引擎要真正接入运行」):
            #   常驻循环没有 GUI module, 原来这里直接 return False ⇒ 流形引擎核心一次没跑过。
            #   回退到真实 episode 轨迹 (obs[400][43] + u_exec_vec[400][4]), 帧号跟 engine_latest.idx 同步。
            _d, _srcf = _ss_traj_files()
            _ob = (_d or {}).get("obs")
            if _ob:
                _n = len(_ob)
                tr = {"t": [i * 0.1 for i in range(_n)], "obs": _ob,
                      "u_exec_vec": (_d or {}).get("u_exec_vec") or []}
                _tidx = max(0, min(_ss_engine_idx(), _n - 1))
                _tsrc = "ss_traj_last.json ← %s" % (_srcf or "?")
        if tr is None or not tr.get("t"):
            if log:
                log("⚠️ 流形引擎: 无帧真源 — GUI 播放态与 ss_traj_last.json 都取不到 (不造状态)")
            return _ret(False)                       # 产品标识/结构理解已在上面真跑出 (照旧返回)
        idx = _tidx if _tidx is not None else 0
        O = np.asarray(tr["obs"], dtype=float)
        if O.ndim != 2 or O.shape[1] < 43:
            if log:
                log(f"⚠️ 流形引擎: 轨迹 obs 维数 {O.shape} 不足 43 → 无法编码 (如实报, 不补造)")
            return _ret(False)
        eng = m.ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4)
        ck = os.path.join(_REPO_ROOT, "models", "manifold_engine.npz")
        loaded = eng.load(ck)
        calib_note = f"标定 {os.path.basename(ck)}" if loaded else "未标定 → 用本段轨迹现场拟合"
        if not loaded:
            U = np.asarray(tr.get("u_exec_vec") or np.zeros((len(O), 4)), dtype=float)[:len(O), :4]
            eng.fit(O[:, :43], U)
        goal = eng.project(O[-1, :43])["p"]            # 目标 = 末帧收敛态 (真值锚, 非自选)
        eng.goal_point = goal
        r = eng.project(O[idx, :43])
        gf = eng.gradient_flow()
        p_next = eng.navigator.step(r["p"], gf["descent"], dt=0.01)
        nav = eng.navigate(goal, T=16)
        st = eng.step(O[idx, :43], dt=0.01)
        fb = eng.feedback_update(O[min(idx + 1, len(O) - 1), :r["p"].size] -
                                 O[idx, :r["p"].size])
        lat = eng.latency_report()
        meta = r["meta"]
        hom = st.get("homeostasis")                              # ⚖ 内稳态 (2026-10-10)
        _SS_STATE["mani_eng"] = {"p": r["p"].tolist(), "phi": gf["phi"], "conf": r["confidence"],
                                 "anomaly": r["anomaly"], "action": st["action"].tolist(),
                                 "residual": r["residual"], "drift": r["drift"], "idx": idx,
                                 "hom": hom}
        if hom:
            eng.hom.write_state()                               # 快照落盘 → 画布/控制台/外部可读
        if log:
            reg = m.MANIFOLD_REGISTRY
            ready = [k for k, v in reg.items() if v["status"] == "ready"]
            log(f"🧮 流形引擎 · L4 核心内核 (帧 {idx}/{len(O)-1} · {calib_note})")
            log(f"   流形 {eng.manifold_type} · 约束「{reg[eng.manifold_type]['constraint']}」· "
                f"度量「{reg[eng.manifold_type]['metric']}」· 测地线「{reg[eng.manifold_type]['geodesic']}」"
                f" · 状态 {reg[eng.manifold_type]['status']}")
            log(f"   可用流形 {len(ready)}/{len(reg)}: {' · '.join(ready)}")
            log(f"   未实现(如实登记): " + " · ".join(f"{k}({v.get('why','')[:22]})"
                                                     for k, v in reg.items() if v["status"] != "ready"))
            log(f"   ① 编码: {O.shape[1]}D → z({eng.encoder.latent_dim}D)  ② 投影: p={np.round(r['p'], 3)}"
                + (f" · θ={meta.get('theta')} visibility={meta.get('visibility')}" if "theta" in meta else ""))
            log(f"   ③ 约束违例 {r['residual']:.2e} · 投影改动 {r['drift']:.4f} · 置信 {r['confidence']:.3f}"
                f" · 异常 {'是 ⚠' if r['anomaly'] else '否'}"
                + (f" · 潜维补齐 {meta.get('need')}←{meta.get('got')}" if meta.get("latent_padded") else ""))
            log(f"   ④ 势能 Φ={gf['phi']:.5f} · 梯度范数 {gf['norm']:.4f} (切空间 −∇Φ, 向收敛态)")
            log(f"   ⑤ 测地线→收敛态: 长度 {nav['length']:.4f} · {nav['geodesic_kind']} · 终点误差 {nav['end_error']:.2e}"
                f" · {nav.get('t_navigate_ms')}ms")
            log(f"   ⑥ 动作建议 a={np.round(st['action'], 3)} ({st['decode_src']}) · "
                f"有界反馈 ‖Δ‖={fb['norm']:.4f}{' (已限幅)' if fb['clamped'] else ''}")
            log(f"   ⏱ 延迟: 编码 {lat.get('encode', {}).get('mean_ms')}ms · 投影 {lat.get('project', {}).get('mean_ms')}ms"
                f" · 梯度 {lat.get('metric', {}).get('mean_ms')}ms · 测地线 {lat.get('navigate', {}).get('mean_ms')}ms"
                f" · 端到端 {lat.get('total_mean_ms')}ms (上限 ~{lat.get('implied_max_hz')}Hz)")
            if hom:
                sd = hom["state"]; est = [k for k, v in (hom.get("estimated") or {}).items() if v]
                log(f"   ⚖ 内稳态: 生命力 {hom['vitality']:.3f} · 模式 {hom['mode']} · "
                    f"主导驱动 {hom['dominant']}({hom['dominant_urgency']:.3f})"
                    + ("  ⛔危险(动作全零)" if hom["kind"] == "veto" else "")
                    + ("  ⚠抢占" if hom["kind"] == "interrupt" else ""))
                log(f"      身体: 能量 {sd['energy']:.3f} · 温度 {sd['temperature']:.3f} · 磨损 {sd['wear']:.3f}"
                    f" · 姿态 {sd['balance']:.3f} · 对齐 {sd['alignment']:.3f}"
                    f"   (无传感器仅按衰减外推: {'/'.join(est) or '无'})")
                log(f"      紧迫度→行为权重 {hom['urgency']} · 动作调制 ×{hom['action_gain']:.3f}"
                    f"{' (已调制)' if hom.get('modulated') else ' (未调制/死区)'} · "
                    f"硬闸 {'开' if hom['is_critical'] else '关'}"
                    + (f" · ♻去充电" if hom["mode"] == "recharge" else ""))
                log(f"      快照落盘 zmax_data/ss_live/manifold_homeostasis.json (可被画布/控制台/DDS 切面读)")
            log("   🔒 只读旁路: 结论进数据总线/日志, 不下发动作 (动作须人工授权)")
        return _ret(True)
    except Exception as e:                                                      # noqa: BLE001
        if log:
            log(f"⚠️ 流形引擎失败: {type(e).__name__}: {e}")
        return _ret(False)


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_mani_eng
