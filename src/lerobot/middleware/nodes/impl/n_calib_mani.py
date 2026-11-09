# -*- coding: utf-8 -*-
"""n_calib_mani — 节点实现正文 (文件名 = 画布节点: n_calib_mani)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_calib_mani   ·   registry key: n_calib_mani
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _MANIFOLD_DIR,
    _NodeOut,
    _REPO_ROOT,
    _SS_STATE,
    _load_mod,
    _ss_engine_idx,
    _ss_traj_files,
    os,
    sys,
    time,
)

def node_ss_calib_mani(ctx):
    """🧮 流形引擎标定 — 主参数 M (状态空间结构参数/等效惯量): 同一场 有惯性 vs 过阻尼 两臂真跑"""
    log = ctx.get("log")
    # 🔴 2026-10-29: 本节点单次 300~320ms (ManifoldEngine project/navigate/feedback 全跑 + 配置装载),
    #   10Hz 常驻循环里每拍跑会掉 3 帧 ⇒ 内部节流 (默认 5s 一次真算, 其间返回上次结果并标 cached/age)。
    #   要每次真算: ZMAX_L4_CALIB_PERIOD_S=0
    _cache = _SS_STATE.get("calib_mani_cache")
    _per = float(os.environ.get("ZMAX_L4_CALIB_PERIOD_S", "5") or 0)
    if _cache and _per > 0:
        _agec = time.time() - float(_cache.get("t") or 0)
        if _agec < _per:
            _v = dict(_cache.get("v") or {})
            _v.update({"cached": True, "cache_age_s": round(_agec, 2), "cache_period_s": _per})
            return _NodeOut(_v)

    # ①e 🆕 2026-10-12 老倪设计: **主参数 M 是张量** —— 度量张量 g_ij(x) = M · G_ij(x) (det G = 1)。
    #   真源实现 src/lerobot/manifold/metric_field.py; 本节点真跑给出几何量 (正定性/联络/曲率/测地线)。
    mf = None
    try:
        import os as _os2
        import numpy as _np2
        import importlib as _il2
        _mf2 = _il2.import_module("lerobot.manifold.metric_field")
        mf = _mf2.MetricField.from_config(path=_os2.path.join(_REPO_ROOT, "config", "calib", "zmax_manifold.json"))
        _sp = mf.spec()
        _okp, _mn, _det = mf.is_positive_definite()
        _cr = mf.curvature_report()
        _x0 = _np2.zeros(mf.dim)
        _v0 = _np2.zeros(mf.dim)
        _v0[0] = 1.0
        _lin = _x0 + _v0 * 0.25                                            # 欧氏直线 (对照)
        _geo = mf.geodesic_curve(_x0, _v0, steps=5, dt=0.05)[-1]           # 真测地线
        _dev = float(_np2.linalg.norm(_geo - _lin))
        if log:
            log("🧭 主参数 M = 度量张量 g_ij(x) = M·G_ij(x): dim=%d · mode=%s · 独立分量 %d · M=%.3g"
                % (_sp["dim"], _sp["mode"], _sp["独立分量数"], _sp["尺度 M"]))
            log("   正定: %s (min_eig %.4g · det g %.4g) · 曲率: %s"
                % ("✅" if _okp else "❌", _mn, _det, ("‖Γ‖=%.3g ‖R‖=%.3g" % (_cr["‖Γ‖_F"], _cr["‖R‖_F"]))
                   if _cr.get("full_tensor") else ("子空间抽样 ‖R‖=%.3g" % _cr["‖R‖_F"])))
            log("   测地线 (v=e1, t=0.25): 度量走 %s vs 欧氏直线 %s → 偏离 %.4g (各向同性 ⇒ 0 = 零回归)"
                % (_np2.round(_geo, 4).tolist(), _np2.round(_lin, 4).tolist(), _dev))
    except Exception as _e:                                                 # noqa: BLE001
        if log:
            log("⚠️ 度量张量口径不可用 (退回标量 M): %r" % (_e,))
    # ①f 🆕 2026-10-12 老倪: 「配置中心的参数, 要映射到主参数 M … 这个逻辑在**主参数 M 节点**实现, 主要是映射关系」。
    #   ⇒ 本节点 = **配置单 → M 的映射关系** (唯一映射函数 tools/config_to_M.py::compute_M):
    #     读配置单 (任务/注册表/MCD/绑定/快照/性能指标) → 按 R1~R5 显式映射表定 M →
    #     写回本节点 params (m_metric/m_mapping/…) → 逐条打印**映射依据**(每条都带来源)。
    try:
        import importlib.util as _ilu_cm
        _s_cm = _ilu_cm.spec_from_file_location("config_to_M", os.path.join(_REPO_ROOT, "tools", "config_to_M.py"))
        _cm = _ilu_cm.module_from_spec(_s_cm)
        sys.modules["config_to_M"] = _cm
        _s_cm.loader.exec_module(_cm)
        _spec_cm = _cm.compute_M((ctx.get("params") or {}).get("task") or None)      # 缺省=活跃配置单
        _w_cm = _cm.write_into_node(_spec_cm)                                        # 写回本节点 params (记 m_*)
        _SS_STATE["config_to_M"] = {"task": _spec_cm["task_id"], "dim": _spec_cm["dim"], "mode": _spec_cm["mode"],
                                    "scale": _spec_cm["scale"], "diag": _spec_cm["diag"], "comps": _spec_cm["components"],
                                    "gain": _spec_cm["gain"], "audit_sha": _spec_cm["audit_sha"],
                                    "node_write_ok": bool(_w_cm.get("ok"))}
        if log:
            log("🧮 主参数 M ← 配置单 [%s] 的显式映射 (R1~R5 · 审计哈希 %s · 映射函数 tools/config_to_M.py::compute_M)"
                % (_spec_cm["task_id"], _spec_cm["audit_sha"][:16]))
            for _r in _spec_cm["mapping_table"]:
                log("   [%s] %-16s = %-22s ⇐ %s"
                    % (_r["id"], _r["target"], str(_r.get("value"))[:22], str(_r["source"])[:64]))
                _ev = _r.get("evidence") if isinstance(_r.get("evidence"), list) else [_r.get("evidence")]
                for _e2 in [x for x in _ev if x][:3]:
                    log("        · %s" % str(_e2)[:104])
                if _r.get("axis_tolerance"):
                    for _a in _r["axis_order"]:
                        log("        · 轴 %-3s ε=%-8.4g ⇐ %s"
                            % (_a, _r["axis_tolerance"][_a], str(_r["tolerance_sources"][_a])[:66]))
                if _r.get("input_sources"):
                    for _k, _v in _r["input_sources"].items():
                        log("        · 输入 %-10s ⇐ %s" % (_k, str(_v)[:66]))
            log("   ⇒ 主参数 M = (dim=%d · mode=%s · scale=%.3g [能级 %s] · diag %s · gain %s)"
                % (_spec_cm["dim"], _spec_cm["mode"], _spec_cm["scale"], _spec_cm["energy_level"],
                   _spec_cm["diag"], _spec_cm["gain"]))
            log("   📥 写回本节点 params: %s (键 %s)"
                % ("✅" if _w_cm.get("ok") else "❌ " + str(_w_cm.get("err")), ",".join(_w_cm.get("written") or [])[:110]))
            log("   🔗 「用 M 实现功能」在**流形引擎节点** (ss_mani_eng): 度量几何/健康度 H/扭矩 τ")
    except Exception as _e:                                                 # noqa: BLE001
        if log:
            log("⚠️ 配置单→主参数 M 映射不可用 (不影响标量标定): %r" % (_e,))
    try:
        import importlib.util as _ilu
        import numpy as np

        # ① 读 M (标定层单一真源: config/calib/zmax_manifold.json → tools/zmax_params.py)
        M, inertia, rng, unit, src, zm = None, None, None, None, None, None
        try:
            _s = _load_mod("zmax_params", os.path.join(_REPO_ROOT, "tools", "zmax_params.py"))
            M, inertia = zm.manifold_M(), zm.manifold_inertia()
            sp = zm.manifold_spec()
            rng, unit, src = sp.get("range"), sp.get("unit"), sp.get("_src")
        except Exception as _e:                                                 # noqa: BLE001
            M, inertia, rng, unit, src = 1.0, False, [0.0, 8.0], "等效惯量尺度", f"默认 (读 zmax_params 失败: {_e})"

        # ①c 🆕 2026-10-11 老倪: 「这个节点的代码要加载配置中心的**数据库文件, json文件, yaml文件**等, 直接指导模型工作」
        #     全量装载 → 一份主参数引导快照 (config/cc_snapshot.json 同源, 可审计); 失败则如实退回单文件读 (零回归)
        cc, g, _ccmod, _ccspec = {}, {}, None, ""
        try:
            _s3 = _ilu.spec_from_file_location("config_center_load",
                                               os.path.join(_REPO_ROOT, "tools", "config_center_load.py"))
            _ccmod = _ilu.module_from_spec(_s3)
            _s3.loader.exec_module(_ccmod)
            cc = _ccmod.build(write=True)          # 48 配置文件 (json/yaml) + 工程库 SQLite
            g = cc.get("guide") or {}
            _ccspec = _ccmod.spec(cc)
            if g.get("M") is not None:
                M = float(g["M"])                   # 主参数以配置中心装载值为准 (与标定真源同源)
            if g.get("inertia") is not None:
                inertia = bool(g["inertia"])
        except Exception as _e:                                                 # noqa: BLE001
            if log:
                log("⚠️ 配置中心全量装载失败 → 退回单文件读 zmax_params: %s: %s" % (type(_e).__name__, _e))

        # ①d 🆕 2026-10-12 老倪: 「这个配置中心的配置数据, 要写入状态空间的 标定诊断测量 主参数M 节点,
        #     我右键打开这个节点, 要直接定位到, 导入配置文件的位置, 而且要能够运行, 要有能加载配置文件的逻辑」
        #   ⇒ 本节点运行 = 真加载**配置文件真源** (8 项 json/proj 真源 + 工程库 SQLite + 工单) 并**写回本节点 params**
        #   (cfg_entries / cfg_snapshot / cfg_loaded_at / cfg_files)。右键「打开源码」由节点 params.source +
        #   source_symbol 直达导入函数 (src/lerobot/engineering/config_import.py::import_config_files)。
        ci = {}
        try:
            import importlib as _il
            _ci = _il.import_module("lerobot.engineering.config_import")
            ci = _ci.load_config()              # 真加载 + 真写回 (print 逐文件清单)
            if log:
                _s = (ci.get("import") or {})
                log("📥 配置导入: 真源 %s/%s · 工程库 %s · 参数 %s/%s 就绪 · 任务 %s · 活跃 %s · 工单 %s · 写回 %s"
                    % (_s.get("files_ok"), _s.get("files_total"), "✅" if _s.get("db_ok") else "❌",
                       _s.get("params_ready"), _s.get("params_total"), _s.get("tasks"),
                       _s.get("active_task"), _s.get("orders"),
                       "✅" if (ci.get("write") or {}).get("ok") else "❌"))
                if _s.get("missing"):
                    log("   ⚠️ 缺文件: %s" % ", ".join(_s["missing"]))
        except Exception as _e:                                                 # noqa: BLE001
            if log:
                log("⚠️ 配置导入失败 (不影响主参数 M 标定): %r" % (_e,))

        # ①b 可写口 (可选): 画布节点 params 带数值 write_M 且 zmax_params 可用 → 真写盘并复读
        wrote = None
        _wv = (ctx.get("params") or {}).get("write_M")
        if _wv is not None and zm is not None:
            wrote = zm.write_manifold_M(float(_wv), (ctx.get("params") or {}).get("inertia"))
            M, inertia = wrote["M"], wrote["inertia"]

        # ② 流形引擎 (真件) + 权威规格
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
        msp = m.manifold_M_spec()
        dt = float(g.get("dt") or 0.01)      # 控制周期: 配置中心有就按它, 没有就 0.01 (如实标注)

        mod = ctx.get("module")
        tr = getattr(mod, "_ss_tr", None) if mod is not None else None
        O, idx = None, 0
        _usrc = "module._ss_tr (GUI 播放)"
        if tr is not None and tr.get("t"):
            O = np.asarray(tr["obs"], dtype=float)
            if O.ndim == 2 and O.shape[1] >= 43 and len(tr["t"]) > 0:
                idx = int(min(getattr(mod, "_ss_round", 0) or 0, len(tr["t"]) - 1))
            else:
                O = None
        if O is None:
            # L4 统一帧回退 (2026-10-29): 常驻循环无 GUI module, 用真实 episode 轨迹文件
            _d, _srcf = _ss_traj_files()
            _ob = (_d or {}).get("obs")
            if _ob:
                _O = np.asarray(_ob, dtype=float)
                if _O.ndim == 2 and _O.shape[1] >= 43:
                    O, idx = _O, max(0, min(_ss_engine_idx(), _O.shape[0] - 1))
                    _usrc = "ss_traj_last.json ← %s" % (_srcf or "?")
        real = O is not None

        if real:      # 真引擎帧 (su2 流形): 编码→投影→梯度流 → 取力
            eng = m.ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4,
                                   manifold_M=M, inertia=bool(inertia))
            ck = os.path.join(_REPO_ROOT, "models", "manifold_engine.npz")
            loaded = eng.load(ck)
            if not loaded:
                # 拟合用的动作列: GUI 播放态 tr → 无 GUI 时同一份轨迹文件 (都不造假)
                _uu = (tr or {}).get("u_exec_vec")
                if not _uu:
                    _dd, _ = _ss_traj_files()
                    _uu = (_dd or {}).get("u_exec_vec")
                U = np.asarray(_uu if _uu else np.zeros((len(O), 4)), dtype=float)[:len(O), :4]
                eng.fit(O[:, :43], U)
            goal = eng.project(O[-1, :43])["p"]              # 目标 = 末帧收敛态 (真值锚)
            eng.goal_point = goal
            r = eng.project(O[idx, :43])
            gf = eng.gradient_flow()
            frame = (f"引擎帧 {idx}/{len(O)-1} · 流形 {eng.manifold_type} · "
                     f"{'标定 npz' if loaded else '本段轨迹现场拟合'}")
        else:         # 无引擎轨迹 → 合成势场小实验 (与 M 同构; 如实标注, 不假装有真机帧)
            eng = m.ManifoldEngine(manifold_type="euclidean", latent_dim=2, state_dim=2, action_dim=2,
                                   manifold_M=M, inertia=bool(inertia))
            goal = np.array([1.0, 0.0])
            eng.goal_point = goal
            r = eng.project(np.zeros(2))
            gf = eng.gradient_flow()
            frame = "无引擎轨迹 → 合成势场小实验 (如实标注, 非真机帧; 建议先点 ▶ 运行状态空间)"

        # ③ 两臂: 过阻尼 (旧行为) vs 有惯性 (M 带动量) — 严格同一起点/同一场
        p_od = eng.navigator.step(r["p"], gf["descent"], dt)     # 过阻尼 = 旧行为 (未改的 navigator)
        _M_used = float(M) if (M is not None and float(M) > 0) else 1.0
        eng.inertia, eng.M, eng.velocity = True, _M_used, None
        p_in = eng._evolve(r["p"], gf["descent"], dt)
        mom = 0.0 if eng.velocity is None else float(np.linalg.norm(eng.velocity))
        d_od = float(np.linalg.norm(np.asarray(p_od, float) - np.asarray(r["p"], float)))
        d_in = float(np.linalg.norm(np.asarray(p_in, float) - np.asarray(r["p"], float)))
        _SS_STATE["calib_mani"] = {"M": M, "inertia_read": bool(inertia), "range": rng, "unit": unit,
                                   "M_used": _M_used, "momentum": mom, "wrote": wrote,
                                   "dx_overdamped": d_od, "dx_inertial": d_in,
                                   "real_frame": real,
                                   "goal": None if goal is None else np.asarray(goal).ravel().tolist()}
        # ④ 🆕 配置中心的**限值/档位/几何**直接指导本次执行 (老倪: 配置要直接指导模型工作)
        import re as _re
        _lim, _cap, _clip = dict(g.get("limits") or {}), None, 0
        _vmax = next((float(v) for k2, v in _lim.items()
                      if _re.search(r"v_max|速度", str(k2)) and isinstance(v, (int, float))), None)
        if _vmax:
            _cap = float(_vmax) * float(dt)
            _clip = int(d_od > _cap) + int(d_in > _cap)
            d_od, d_in = min(d_od, _cap), min(d_in, _cap)
        _SS_STATE["cc_guide"] = g
        _SS_STATE["calib_mani"].update({"limits": _lim, "cap": _cap, "clips": _clip,
                                        "cc_counts": cc.get("counts"), "cc_spec": _ccspec})
        if log:
            log("🧮 流形引擎标定 · L4 标定层 主参数 M (状态空间结构参数 / 等效惯量)")
            log(f"   ① M = {M} (范围 {rng} · 单位「{str(unit)[:24]}…」· 真源 {src})"
                + (f" · 本次真写盘 {wrote}" if wrote else ""))
            if cc:
                log("   📚 配置中心全量装载 → 本次模型执行: " + _ccspec)
                _tk = g.get("task") or {}
                log("      · 直接指导: 主参数 M=%s · 惯性 %s · dt=%ss · 限值 %s 项 %s · 档位开 %d (%s) · "
                    "启用节点 %d · 几何 内参=%s 手眼=%s"
                    % (g.get("M"), g.get("inertia"), dt, len(_lim), dict(list(_lim.items())[:3]),
                       _tk.get("n_run_cfg_on", 0), ",".join(_tk.get("run_cfg_on") or [])[:60],
                       _tk.get("n_enabled_nodes", 0), (g.get("geometry") or {}).get("has_K"),
                       (g.get("geometry") or {}).get("has_handeye")))
                log("      · 限值生效: %s" % (("步长按速度上限钳制 %d 次 (上限 %.6g/步)" % (_clip, _cap)) if _clip else
                                              "本节点输出未触发限值 (无速度上限配置 ⇒ 不钳制, 力阈值见 limits)"))
            log(f"   ② 现场读 inertia = {inertia} ({'有惯性二阶 a=F/M' if inertia else '过阻尼一阶 = 旧行为, 零回归'})"
                f" · 数据 {frame}")
            log(f"   ③ 同一起点/同一场两臂: 过阻尼 Δx={d_od:.6g} (速度∝力, 旧行为) vs "
                f"有惯性 M={_M_used} Δx={d_in:.6g} (a=F/M, 动量 ‖v‖={mom:.6g}) → 差 {abs(d_in - d_od):.3g}")
            log(f"   ④ 物理: {msp['physical']}")
            log(f"   ⑤ 信息: {msp['information']}")
            log(f"   ⑥ 可写口: tools/zmax_params.py --m <值> [--inertia on|off] → config/calib/zmax_manifold.json")
            log(f"   ⑦ {msp['not_free_param']}")
            log("   🔒 只读旁路: 只标定/对比, 不下发动作 (动作须人工授权)")
        _ret_v = {
            "kind": "calib_mani", "layer": "L4", "ok": True,
            "M": M, "M_used": _M_used, "inertia": bool(inertia), "dt": dt,
            "range": rng, "unit": str(unit)[:60], "param_src": src, "wrote": bool(wrote),
            "frame_real": bool(real), "frame_idx": idx, "frame_desc": frame,
            "frame_src": (_usrc if real else "无引擎轨迹 → 合成势场小实验 (如实标注)"),
            "dx_overdamped": d_od, "dx_inertial": d_in, "momentum": mom,
            "goal": (None if goal is None else np.asarray(goal).ravel().tolist()[:8]),
            "cap_step": _cap, "clips": _clip,
            "cached": False,
            "src": "src/lerobot/manifold/manifold_engine.py::ManifoldEngine (project/gradient_flow/_evolve)",
        }
        _SS_STATE["calib_mani_cache"] = {"t": time.time(), "v": dict(_ret_v)}
        return _NodeOut(_ret_v)
    except Exception as e:                                                      # noqa: BLE001
        if log:
            log(f"⚠️ 流形引擎标定失败: {type(e).__name__}: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_calib_mani
