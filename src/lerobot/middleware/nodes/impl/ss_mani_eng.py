# -*- coding: utf-8 -*-
"""ss_mani_eng — 节点实现正文 (文件名 = 画布节点: ss_mani_eng)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_mani_eng   ·   registry key: ss_mani_eng
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
import json
import os

import numpy as np

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

# ── 🧠 引擎双通道 provider (进程内缓存, 只 build 一次) ────────────────────
#   语义通道 hjepa   : H-JEPA 三层潜 (z1/z2/z3 + 每层能量) → 观测/异常/条件
#   几何通道 hjepa_mr: state7(真机 TCP) → ξ∈se(3) + v∈TS² + 接触/性能流形诊断
#   两通道并存不替代 (manifold_engine.py:756 口径: 语义与几何揉在单一欧氏 latent 会互相污染)
_MR_CACHE = {"prov": None, "note": "", "tried": False}
_SEM_CACHE = {"prov": None, "note": "", "tried": False}
# 当前拍的画布输入 (provider 的 state_fn 每拍从这里取 —— 这样画布 in1 是被**真消费**的,
# 不是摆设; 与 provider 缓存配合, 注册一次、每拍取新值)
_CUR_CTX = {"in1": None, "in3": None, "in4": None, "in5": None}
_LAST_STATE7_SRC = {}


def _state7_from_truth():
    """引擎 obs 的 state7 = [x,y,z(m), rx,ry,rz(rad), grip]。

    🔴 分量来源分两处, 各自真源, 不混报:
       位置 [0:3] + 夹爪 [3]  ← **画布 in1 的 43D** (obs43 布局 [0:3]手位置 [3]夹爪)
       姿态 [3:6]            ← TCP 位姿真值 (43D 里**只有位置没有姿态**, 拿不到就 0 并在 src 标明)
    43D 取不到 ⇒ 位置也退回 TCP。全部写进 _LAST_STATE7_SRC, 供输出核对。
    """
    global _LAST_STATE7_SRC
    in1 = _CUR_CTX.get("in1")
    v = in1.get("value") if (isinstance(in1, dict) and "value" in in1) else in1
    o = None
    try:
        if v is not None:
            o = np.asarray(v, float).ravel()
            if o.size < 7:
                o = None
    except Exception:                                                      # noqa: BLE001
        o = None

    pos, grip, pos_src = None, 0.0, "TCP 真值"
    if o is not None:
        pos = o[:3].copy(); pos_src = "画布 in1 43D[0:3]"
        if o.size >= 4:
            grip = float(o[3])

    rpy, tpos = np.zeros(3, float), np.zeros(3, float)
    try:
        from lerobot.manifold.se3_chain import read_pose_truth, R_to_rpy
        pt = read_pose_truth(_REPO_ROOT)
        if pt is not None:
            rpy = R_to_rpy(pt.T[:3, :3])
            tpos = pt.T[:3, 3].copy()
    except Exception:                                                      # noqa: BLE001
        pass
    rot_src = "TCP 真值 rpy" if float(np.any(rpy)) else "无姿态 (全 0)"
    if pos is None:
        pos = tpos
        pos_src = "TCP 真值" if float(np.any(tpos)) else "无位姿 (全 0)"
    _LAST_STATE7_SRC = {"pos": pos_src, "rot": rot_src, "grip": ("画布 in1 43D[3]" if o is not None else "0 (无)")}
    return np.array([pos[0], pos[1], pos[2], rpy[0], rpy[1], rpy[2], grip], float)


def _read_calib_from_ctx(in3):
    """解析画布 in3 (sscalib 标定层 out2) → 势场要用的标定量。

    真源: calibration_layer.py 的 ATTRACTION_CALIB / REPULSION_CALIB / MANIFOLD_CALIB
          (Kp=1.2 比例引导增益, u_clip=±0.5, safety_limit=0.6, M=等效惯量)
    解析不出 ⇒ 返回 {} 并用模块默认值, 同时在输出里标明"标定未提供"(不拿默认值冒充标定)。
    """
    v = in3.get("value") if (isinstance(in3, dict) and "value" in in3) else in3
    out = {}
    if v is None:
        return out
    if isinstance(v, dict):
        for k in ("Kp", "kp", "u_clip", "safety_limit", "M", "contact_gain", "K_kalman"):
            if v.get(k) is not None:
                try:
                    out["Kp" if k == "kp" else k] = float(v[k])
                except Exception:                                          # noqa: BLE001
                    pass
        for sub in ("attr", "attraction", "rep", "repulsion", "manifold"):
            d = v.get(sub)
            if isinstance(d, dict):
                for k, val in d.items():
                    try:
                        out.setdefault(k, float(val))
                    except Exception:                                      # noqa: BLE001
                        pass
        return out
    try:                                    # 标量 ⇒ 按 M (主标定参数) 解释
        out["M"] = float(v)
    except Exception:                                                      # noqa: BLE001
        pass
    return out


def _get_mr_provider():
    """几何通道 (H-JEPA-MR)。返回 None = 未就绪 (缺 torch/首步失败), 调用方如实标缺。"""
    if _MR_CACHE["tried"]:
        return _MR_CACHE["prov"]
    _MR_CACHE["tried"] = True
    try:
        from lerobot.manifold.hjepa_manifold_provider import HJEPAManifoldProvider
        pr = HJEPAManifoldProvider(state_fn=_state7_from_truth, mode="weak")
        ok, why = pr.start()
        if ok:
            _MR_CACHE["prov"] = pr
        else:
            _MR_CACHE["note"] = str(why)[:160]
    except Exception as e:                                                 # noqa: BLE001
        _MR_CACHE["note"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return _MR_CACHE["prov"]


def _get_sem_provider():
    """语义通道 = HJEPAStateProvider (state7 → z1/z2/z3 三层潜, **接口与引擎对齐**)。

    🔴 别用 HJEPALiveProvider: 它 __call__ 返回裸 ndarray z, 而引擎 _hjepa_read 要
       dict{z1,z2,z3,energy}, 实测 `if not out` 直接 ValueError (truth value of an array)。
    🔴 图像支路: 该权重实测近似常数 ⇒ 没帧时用零图, 但 note 明写"图像=零输入", 不假装有视觉。
    """
    if _SEM_CACHE["tried"]:
        return _SEM_CACHE["prov"]
    _SEM_CACHE["tried"] = True
    try:
        from lerobot.manifold.hjepa_state import HJEPAStateProvider
        fp = (os.environ.get("HJEPA_FRAME_PATH")
              or os.path.join(_REPO_ROOT, "zmax_data", "ss_live", "aoi_modelin.png"))
        use_fp = fp if os.path.isfile(fp) else ""
        pr = HJEPAStateProvider(root=_REPO_ROOT, state_fn=_state7_from_truth,
                                frame_path=use_fp, every=1)
        ok, why = pr.start()
        if ok:
            _SEM_CACHE["prov"] = pr
            _SEM_CACHE["frame_src"] = ("帧文件 %s" % os.path.basename(use_fp)) if use_fp else "零图 (无帧)"
        else:
            _SEM_CACHE["note"] = str(why)[:160]
    except Exception as e:                                                 # noqa: BLE001
        _SEM_CACHE["note"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return _SEM_CACHE["prov"]


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
        # 🌐 SE(3) 输出必须进端口 (原来只写 _SS_STATE ⇒ 画布 5 个端口都拿不到,
        #    下游/断点看到的还是旧的 su2 块, 等于"算完没给出去")
        try:
            _mg = _SS_STATE.get("mani_eng") or {}
            if isinstance(_mg.get("se3"), dict):
                _d["se3"] = dict(_mg["se3"])
        except Exception:                                                    # noqa: BLE001
            pass
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
        # 端口必须真产 (画布: ss_mani_eng.out5→sssched.in4 "动作指令 a"; 其余 out1..out6 同理)
        #   原来只返回扁平 dict ⇒ 画布声明的 6 个端口全空 (2026-11-10 实测)
        _o = dict(_d)                              # 拷贝在挂 out 之前, 不会自我引用
        for _pn in ("out1", "out2", "out3", "out4", "out5", "out6"):
            _d[_pn] = dict(_o)
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
        # 🧭 2026-11-15 老倪「直接切」: 引擎主流形 = SE(3)。
        #   位姿真源 = 真机 TCP (rokae SDK 直读) —— 不用 obs 前 9 维 (那是关节角, SVD 后没有物理意义);
        #   目标 = 215 点真值表; 切向 = 6 维 twist [ρ; φ]。SS_MANI_TYPE=su2 可回退旧 S³ 路径。
        # 把画布输入放进实时槽: 双通道 provider 的 state_fn 每拍从这里取 ⇒ in1 真被消费
        _CUR_CTX["in1"] = ctx.get("in1")
        _CUR_CTX["in5"] = ctx.get("in5")
        _CUR_CTX["in3"] = ctx.get("in3")
        _CUR_CTX["in4"] = ctx.get("in4")
        _mt = str(os.environ.get("SS_MANI_TYPE") or "se3").strip().lower()
        eng = m.ManifoldEngine(manifold_type=_mt, latent_dim=16, state_dim=43, action_dim=4)
        # ── 双通道注册 (未就绪不挂, 输出如实标缺; 绝不拿空 dict 假装已接) ──
        _prov = {"semantic": None, "geometric": None}
        _mr = _get_mr_provider()
        if _mr is not None:
            try:
                eng.set_hjepa_mr_provider(_mr, note="H-JEPA-MR 几何分支 · 真机 TCP 位姿")
                _prov["geometric"] = "H-JEPA-MR (state7 ← TCP 真值)"
            except Exception as _e:                                        # noqa: BLE001
                _prov["geometric"] = "注册失败: %s" % str(_e)[:80]
        else:
            _prov["geometric"] = "未就绪: %s" % (_MR_CACHE.get("note") or "首步失败")
        _sem = _get_sem_provider()
        if _sem is not None:
            try:
                eng.set_hjepa_provider(_sem, note="H-JEPA 三层潜 (L5 视觉/语义)")
                _prov["semantic"] = "H-JEPA 三层潜 (图像=%s)" % _SEM_CACHE.get("frame_src", "?")
            except Exception as _e:                                        # noqa: BLE001
                _prov["semantic"] = "注册失败: %s" % str(_e)[:80]
        else:
            _prov["semantic"] = "未就绪: %s" % (_SEM_CACHE.get("note") or "首步失败")
        ck = os.path.join(_REPO_ROOT, "models", "manifold_engine.npz")
        if _mt == "se3":
            # 🔴 别 load su2 的 npz: 它内部存了 manifold_type=su2, load 会把
            #    engine.manifold_type / projector.type / navigator.type **全部改回 su2**
            #    (实测: 创建时 se3 → load 后 su2, project 从 12 维掉到 4 维,
            #     navigator 走 sphere 分支 ⇒ ValueError: (4,) vs (6,))。
            #    SE(3) 的标定是位姿真值 + 215 点表, 不在这份 npz 里。
            loaded = False
            calib_note = "SE3 模式: 不加载 su2 标定 (npz 会把引擎改回 S³) · 位姿真值=TCP · 目标=215点表"
        else:
            loaded = eng.load(ck)
            calib_note = f"标定 {os.path.basename(ck)}" if loaded else "未标定 → 用本段轨迹现场拟合"
        se3_out = None
        if _mt == "se3":
            import json as _json
            from lerobot.manifold.se3_chain import (T_from_rot_t, potential,
                                                    quat_to_R, read_pose_truth, se3_log)
            pt = read_pose_truth(_REPO_ROOT)
            if pt is None:
                if log:
                    log("🧭 SE3 引擎: 位姿真值不可用 (tcp_out 缺失或 >2s 陈旧) ⇒ 不出数, 不编")
                return _ret(False)
            T = pt.T
            p12 = np.concatenate([T[:3, :3].ravel(), T[:3, 3]])
            # 🧠 L5 语义引导 (老倪「结合语义引导流形引擎」):
            #    有阶段判读 ⇒ 目标 = 该阶段的 215 点区间出口; 无判读 ⇒ 退回 SS_SE3_GOAL_IDX/0
            #    (不拿"默认目标"假装 L5 在引导 —— 输出里 l5.ok 会如实写)
            _l5 = None
            try:
                from lerobot.manifold.l5_guide import L5Guide
                # 画布端口优先 (in5=ss_moe 阶段先验, in1=n_vlm_llm 语义), 文件兜底
                _pd = {"in5": ctx.get("in5"), "in3": ctx.get("in3"), "in4": ctx.get("in4"), "in1": ctx.get("in1")}
                _l5 = L5Guide(_REPO_ROOT, log=log).guide(port_data=_pd)
            except Exception as _le:                                          # noqa: BLE001
                _l5 = {"ok": False, "why": ["L5Guide 异常: %s: %s" % (type(_le).__name__, _le)],
                       "k_l5": 0.0, "stage": None}
            Tg, gsrc, gidx = None, None, 0
            if _l5 and _l5.get("ok") and _l5.get("T_goal") is not None:
                Tg = np.asarray(_l5["T_goal"], float).reshape(4, 4)
                gidx = int(_l5.get("goal_idx") or 0)
                gsrc = "L5 语义: 阶段=%s 区间=%s (%s) conf=%.2f k=%.2f" % (
                    _l5.get("stage"), _l5.get("stage_range"), _l5.get("range_src"),
                    float(_l5.get("conf") or 0.0), float(_l5.get("k_l5") or 0.0))
            try:
                with open(os.path.join(_REPO_ROOT, "tools/web/real_traj_joints.json"),
                          encoding="utf-8") as _f:
                    _fr = (_json.load(_f).get("frames") or [])
                if _fr and Tg is None:      # L5 已给目标 ⇒ 不覆盖
                    gidx = int(os.environ.get("SS_SE3_GOAL_IDX") or 0)
                    gidx = max(0, min(len(_fr) - 1, gidx))
                    Tg = T_from_rot_t(quat_to_R(_fr[gidx]["q"]),
                                      np.asarray(_fr[gidx]["p"], float))
                    gsrc = "215点真值表 idx=%d/%d (无 L5 阶段语义)" % (gidx, len(_fr) - 1)
            except Exception as _ge:                                          # noqa: BLE001
                if log:
                    log("🧭 SE3 引擎: 215 点目标读取失败 %s" % _ge)
            if Tg is None:
                if log:
                    log("🧭 SE3 引擎: 无目标位姿 ⇒ 不出数 (不拿当前位姿假装目标)")
                return _ret(False)
            goal = np.concatenate([Tg[:3, :3].ravel(), Tg[:3, 3]])
            eng.goal_point = goal
            # 🐛 必须绕过 eng.project(): 它会先 encoder.encode(state)→16维潜向量再投影,
            #    SE(3) 的 p 是**位姿本身**不是潜向量 ⇒ 走 encoder 会把 R/t 洗成单位阵+零平移
            #    (实测输出 R=I、t=[0,0,0])。这里直接用 projector 对 12 维位姿做 SVD 正交化。
            _p, _resid, _pmeta = eng.projector.project(p12)
            r = {"p": _p, "residual": float(_resid), "drift": float(_pmeta.get("drift") or 0.0),
                 "meta": _pmeta,
                 "confidence": round(float(np.exp(-float(_pmeta.get("drift") or 0.0))), 4),
                 "anomaly": bool(float(_resid) > 1e-9), "z": None}
            eng.current_manifold_point = _p
            # 🔴 方向: navigator 做的是 T·exp(ξ·dt)（体坐标右乘）⇒ 必须用「当前→目标」的体 twist
            #    log(T⁻¹Tg)。原来用 log(Tg⁻¹T) 再取负，那是目标系误差, 右乘后不进反退
            #    (实测距离 18.130mm → 18.169mm 变大)。
            xi = se3_log(np.linalg.inv(T) @ Tg)            # 6 维 [ρ(m); φ(rad)] = 当前→目标(体)
            # ⚠️ 序不一致: se3_chain 的 ξ = [ρ; φ] (平移在前), 而 Navigator.step 的 v = [ω; v]
            #    (旋转在前, 见 manifold_engine.py:511 的 w=v[:3]/v[3:6])。不重排就会把
            #    平移当旋转转、旋转当平移移 —— 实测距离反而单调变大 (18.13→20.04mm)。
            descent = np.concatenate([xi[3:], xi[:3]])     # [φ; ρ] 供 navigator
            _k5 = float((_l5 or {}).get("k_l5") or 0.0) if (_l5 or {}).get("ok") else 0.0
            _k5 = 0.0 if _k5 <= 0 else _k5          # L5 未引导 ⇒ 不加权 (不拿 0.5 假装中等信任)
            # 🧭 势场度量权重: 读自动标定产物 (zmax_data/calib/se3_metric_calib.json),
            #   没有标定才退回旧硬编码。标定口径: 让"典型平移步长"与"典型转角步长"贡献等权。
            #   旧硬编码 [1000,1000,1000,1,1,1] 实测 平移:旋转=1000:1 ⇒ 旋转几乎不参与收敛。
            _w_def = np.array([1000.0, 1000.0, 1000.0, 1.0, 1.0, 1.0])
            _calib_path = os.path.join(_REPO_ROOT, "zmax_data", "calib", "se3_metric_calib.json")
            try:
                with open(_calib_path, encoding="utf-8") as _f:
                    _mc = json.load(_f)
                _wm = np.asarray(_mc.get("w_m"), float)
                if _wm.size == 6 and np.all(np.isfinite(_wm)) and np.all(_wm > 0):
                    w_m = _wm
                    _metric_src = "自动标定 se3_metric_calib.json (t=%.3fmm/r=%.3f°, 平移:旋转=%.1f:1)" % (
                        float(_mc.get("t_scale_m") or 0) * 1000, np.degrees(float(_mc.get("r_scale_rad") or 0)),
                        float(_wm[0] / _wm[3]))
                else:
                    w_m, _metric_src = _w_def, "标定文件 w_m 形状非法 ⇒ 退回硬编码"
            except Exception:                                                  # noqa: BLE001
                w_m, _metric_src = _w_def, "无标定文件 ⇒ 退回硬编码 [1000,1000,1000,1,1,1]"
            if _k5 > 0:
                w_m = w_m * (1.0 + _k5)             # 引导时放大势场 (更"坚定"地朝 L5 目标收敛)

            # ── in3 ← sscalib 标定层 → 势场尺度/限幅 (真源 calibration_layer) ──
            _cal = _read_calib_from_ctx(ctx.get("in3"))
            _kp = float(_cal.get("Kp") or 1.2)                       # 比例引导增益 (基准 1.2)
            _kp_scale = max(0.2, min(3.0, _kp / 1.2))                # 限幅防标定异常把权重拉爆
            w_m = w_m * _kp_scale
            _safety = float(_cal.get("safety_limit") or 0.6)         # 安全执行边界 (m/步)
            _calib_src = ("sscalib: Kp=%.2f (×%.2f), safety_limit=%.2fm%s"
                          % (_kp, _kp_scale, _safety,
                             (", M=%.4g" % float(_cal["M"])) if _cal.get("M") is not None else "")) \
                if _cal else "标定未提供 (in3 空) ⇒ Kp 用模块默认 1.2, safety_limit=0.6m"
            # ── in6 ← n_calib_mani: 主标定参数 M (等效惯量) → 步长尺度 ──
            #   物理直觉: M 大 = 同一势场下"更重" ⇒ 每步位移小 (a = F/M 的直觉);
            #   限幅 0.3~3.0 防止标定值异常把收敛变爬行或跳过目标。
            _M = _cal.get("M")
            _m_scale = 1.0
            if _M is not None:
                _Mv = float(_M)
                if _Mv > 0:
                    _m_scale = 1.0 / max(0.3, min(3.0, _Mv))
                    descent = np.concatenate([descent[:3] * _m_scale, descent[3:]])

            # ── in2 ← ssobs: SU(2) 四元数 vs T 的 R ⇒ 姿态一致性诊断 (不驱动 p) ──
            #   两路姿态若不一致, 说明 SU2 状态与真机位姿不同源, 必须让人看见, 不能静默。
            _att_diag = {"used": False, "why": "in2 空"}
            _in2 = ctx.get("in2")
            _q2 = (_in2.get("value") if (isinstance(_in2, dict) and "value" in _in2) else _in2)
            try:
                if _q2 is not None:
                    _qv = np.asarray(_q2, float).ravel()
                    if _qv.size >= 4:
                        q = _qv[:4] / max(1e-9, float(np.linalg.norm(_qv[:4])))
                        from lerobot.manifold.se3_chain import quat_to_R
                        R2 = quat_to_R(q)
                        dR = R2.T @ T[:3, :3]
                        ang = float(np.degrees(np.arccos(np.clip((np.trace(dR) - 1) / 2, -1, 1))))
                        _att_diag = {"used": True, "angle_deg": round(ang, 3),
                                     "consistent": bool(ang < 5.0),
                                     "note": "SU2 路姿态 vs T 的 R 夹角; >5° ⇒ 两路不同源"}
                        if log and ang >= 5.0:
                            log("🧮 in2 SU2 姿态与 T 差 %.1f° (>5°, 两路不同源, 仅诊断不干预)" % ang)
            except Exception as _e:                                        # noqa: BLE001
                _att_diag = {"used": False, "why": "%s: %s" % (type(_e).__name__, str(_e)[:80])}

            # ── in4 ← sslat: 接触点诊断 (contact_p 是潜空-流形给的接触位置, 只记录不驱动 p) ──
            _contact = {"used": False, "why": "in4 空"}
            _in4 = ctx.get("in4")
            _v4 = (_in4.get("value") if (isinstance(_in4, dict) and "value" in _in4) else _in4)
            try:
                if isinstance(_v4, dict):
                    _cp = _v4.get("contact_p")
                    _contact = {"used": bool(_cp is not None),
                                "contact_p": (np.round(np.asarray(_cp, float).ravel()[:3], 4).tolist()
                                              if _cp is not None else None),
                                "stage": _v4.get("stage"), "speed": _v4.get("speed"),
                                "note": "接触点来自潜空-流形; 只诊断, 不改 T/p (位姿以 TCP 真值为准)"}
            except Exception as _e:                                        # noqa: BLE001
                _contact = {"used": False, "why": "%s: %s" % (type(_e).__name__, str(_e)[:80])}

            # 单步位移钳制到安全边界 (descent 是 6 维 [ρ;φ], 只钳平移分量)
            _step_m = float(np.linalg.norm(descent[:3]))
            _clamped = False
            if _step_m > _safety > 0:
                descent = np.concatenate([descent[:3] * (_safety / _step_m), descent[3:]])
                _clamped = True
            _phi, _grad = potential(T, Tg, w=w_m)
            gf = {"phi": float(_phi), "descent": descent,
                  "norm": float(np.linalg.norm(_grad)), "src": "SE(3) 李代数误差"}
            p_next = eng.navigator.step(r["p"], descent, dt=0.01)     # 严格螺旋
            nav = eng.navigate(goal, T=16)
            # SE(3) 不含夹爪 ⇒ action 只给平移分量, 第 4 维留 0 并如实标注
            st = {"action": np.concatenate([descent[:3], [0.0]]),
                  "decode_src": "SE(3) twist 平移分量 (夹爪不在流形内)"}
            fb = {"norm": 0.0, "clamped": False,
                  "note": "SE(3) 路径不做 obs 差分反馈 (位姿真值已是最新)"}
            se3_out = {"ok": True, "manifold": "se3", "p_dim": int(r["p"].size),
                       "T": T.tolist(), "t_mm": (T[:3, 3] * 1000.0).round(3).tolist(),
                       "quat_xyzw": np.round(np.array([0, 0, 0, 1.0]), 6).tolist(),
                       "xi": np.round(xi, 9).tolist(),
                       "phi": round(float(_phi), 6), "grad_norm": round(float(np.linalg.norm(_grad)), 4),
                       "trans_mm": round(float(np.linalg.norm(xi[:3])) * 1000.0, 3),
                       "rot_deg": round(float(np.degrees(np.linalg.norm(xi[3:]))), 3),
                       "goal": goal.tolist(), "goal_src": gsrc, "goal_idx": gidx,
                       "p_next": np.round(p_next, 6).tolist(),
                       "pose_age_s": round(pt.age_s, 3), "pose_src": pt.src,
                       "calib": {"src": _calib_src, "Kp": _kp, "w_scale": round(_kp_scale, 3),
                                 "safety_limit_m": _safety, "step_clamped": _clamped,
                                 "M": _M, "m_step_scale": round(_m_scale, 4), "raw": _cal},
                       "attitude": _att_diag,
                       "metric": {"src": _metric_src, "w_m": np.round(w_m, 4).tolist()},
                       "contact": _contact,
                       "l5": (None if _l5 is None else {
                           "ok": bool(_l5.get("ok")), "stage": _l5.get("stage"),
                           "conf": _l5.get("conf"), "k_l5": _l5.get("k_l5"),
                           "range_src": _l5.get("range_src"), "stage_range": _l5.get("stage_range"),
                           "cam_hint": _l5.get("cam_hint"), "why": _l5.get("why"),
                           "degraded": _l5.get("degraded")}),
                       "goal_src_kind": ("L5_semantic" if (_l5 or {}).get("ok") else "traj_default"),
                       "providers": _prov,
                       "ports": {
                           "in1": {"used": True,
                                   "what": "43D[0:3]→state7 位置, [3]→夹爪; stage 语义→L5Guide",
                                   "src": dict(_LAST_STATE7_SRC)},
                           "in5": {"used": True,
                                   "what": "阶段先验 → L5Guide 选 215 点区间 → T_goal + k_l5"},
                           "in2": {"used": True,
                                   "what": "SU(2) 四元数 vs T 的 R → 姿态一致性诊断 (夹角°, 不驱动 p)"},
                           "in3": {"used": True,
                                   "what": "sscalib 标定 → 势场尺度 (Kp/1.2 限幅 0.2~3.0) + 单步位移钳制 (safety_limit)"},
                           "in4": {"used": True,
                                   "what": "sslat.out1 (已从空端口 out2 改连) → stage 供 L5Guide; contact_p 作接触诊断"},
                           "in6": {"used": True,
                                   "what": "M 等效惯量 → 步长尺度 1/M 限幅 0.3~3.0 (a=F/M 直觉)"},
                       }}
            # ── 双通道读数 (每拍真前向) ──
            try:
                se3_out["hjepa"] = eng._hjepa_read()
            except Exception as _e:                                        # noqa: BLE001
                se3_out["hjepa"] = {"ok": False, "why": "%s: %s" % (type(_e).__name__, str(_e)[:100])}
            try:
                se3_out["hjepa_mr"] = eng._hjepa_mr_read()
            except Exception as _e:                                        # noqa: BLE001
                se3_out["hjepa_mr"] = {"ok": False, "why": "%s: %s" % (type(_e).__name__, str(_e)[:100])}
        else:
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
        _SS_STATE["mani_eng"] = {"se3": se3_out,
                                 "p": r["p"].tolist(), "phi": gf["phi"], "conf": r["confidence"],
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
            import traceback as _tb
            log(f"⚠️ 流形引擎失败: {type(e).__name__}: {e}")
            for _ln in _tb.format_exc().strip().splitlines()[-6:]:
                log("   " + _ln)
        return _ret(False)


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_mani_eng
