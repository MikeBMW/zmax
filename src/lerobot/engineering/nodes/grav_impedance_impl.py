# -*- coding: utf-8 -*-
"""🌍 万有引力 · SE(3) 几何阻抗 + H=K+U — 全层力场仲裁 **L2/L3/L4/L5 四层力对齐**

老倪 2026-10-29:「万有引力节点, 要对齐 L2 L3 以及即将接入的 L4 L5 层的力」
老倪 2026-10-28:「把执行链上的节点按顺序迁出来」—— 实现正文在 nodes/, library 只留转调。

两条口径同时给, 各有唯一真源 (不各算一套):
  ① **能量层** `H=K+U` —— 真源 `src/lerobot/manifold/state_space_energy.py::live_energy`
     (读 zmax_data/ss_live/trace_live.json 的实测 ξ / ξ_e)
  ② **分层力** F_l (l=L2/L3/L4/L5) —— 真源 `tools/layer_forces.py::layer_forces` (老倪 2026-10-19 定)
     L2 = chunk_latest.ff[0]      前馈 MLP          (基础输出, 主力)
     L3 = chunk_latest.chunk[0]   动作头 chunk      (加权修正)
     L4 = metric_M/m_ref × ff     流形引擎度量张量
     L5 = l5_scene_vec.json       VL 场景理解矢量   (未接入 ⇒ 如实标缺, 不造数)
     每层 w / k 从 config/calib/layer_forces.json **热读** (改文件即生效)

铁律: 只读真值 / 不造数 / 不下发动作 (下发只走 l2_daemon + 8793 授权)。
      某层取不到 ⇒ vec=None + src 写明缺什么; 绝不用别的层的数顶替。
"""
from __future__ import annotations
import os                                    # 正文里 os.path.join 用 (原在 library 模块级)
from .library import _HAM_CACHE, _NodeOut, _REPO_ROOT   # 与 registry 共用同一份运行时状态 (同源)
from ._single_thread import brk as _brk

_LAYERS = ("L2", "L3", "L4", "L5")
_ROLE = {"L2": "基础输出(前馈 MLP)", "L3": "加权修正(动作头 chunk)",
         "L4": "度量张量(流形引擎)", "L5": "场景理解(VL 矢量)"}


def _layer_forces_mod():
    """tools/layer_forces.py 按模块加载 (真源只有一份, 不在这里抄公式)。"""
    import importlib.util as _ilu
    p = os.path.join(_REPO_ROOT, "tools", "layer_forces.py")
    s = _ilu.spec_from_file_location("zmax_layer_forces", p)
    m = _ilu.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _unit(v):
    import math
    n = math.sqrt(sum(float(x) * float(x) for x in v)) if v else 0.0
    return ([float(x) / n for x in v] if n > 1e-12 else None), n


def run(ctx):
    _brk("grav")          # ZMAX_DEBUG_BREAK=grav 时停在这里
    log = ctx.get("log")
    root = ctx.get("root") or _REPO_ROOT
    live = os.path.join(root, "zmax_data", "ss_live")
    try:
        import json as _json
        import numpy as _np
        from lerobot.manifold.state_space_energy import live_energy, StateSpaceHamiltonian

        # ── ① 能量层: H = K + U (真源 live_energy) ────────────────────────────
        out = live_energy(root, _HAM_CACHE)
        U, K, F = float(out["U"]), float(out["K"]), out["F"]
        hd = float(out["hdot"])
        xi_e, stage = out["xi_e"], out["stage"]
        src_vel = out["xi_src"]

        # ── ② 四层力 (真源 tools/layer_forces.py, 每层读自己的唯一依据) ────────
        lf, res, main = {}, None, None
        lf_err = ""
        try:
            _m = _layer_forces_mod()
            lf = _m.layer_forces() or {}
            res = _m.resultant(lf)
            main = _m.main_force(lf)
        except Exception as _e:                                              # noqa: BLE001
            lf_err = "%s: %s" % (type(_e).__name__, _e)

        ham = StateSpaceHamiltonian()
        layers = {}
        for L in _LAYERS:
            x = lf.get(L) or {}
            v = x.get("vec")
            # 层受控判据: 该层矢量与合力方向夹角 (与 L2 收口闸同口径 >60° 否决)
            pr = ham.layer_projection(v, xi_e) if v else {"cos": 0.0, "deg": 90.0, "allow": False}
            layers[L] = {
                "vec": v, "mag": (round(float(x["mag"]), 6) if x.get("mag") is not None else None),
                "w": x.get("w"), "k": x.get("k"), "role": _ROLE[L],
                "src": x.get("src") or ("缺 %s" % L),
                "fresh": x.get("fresh"), "age_s": x.get("age_s"),
                "allow": bool(pr["allow"]), "deg": round(float(pr["deg"]), 1),
                "main": (L == main),
            }
        # 恒等式: Σ_l F_l == 合力 (两条口径对齐的自证, 不通过就如实报)
        if res is not None:
            _sum = [sum((layers[L]["vec"] or [0.0, 0.0, 0.0])[i] for L in _LAYERS) for i in range(3)]
            resid = max(abs(_sum[i] - float(res[i])) for i in range(3))
        else:
            _sum, resid = None, None
        _dir, _mag = _unit(res) if res else (None, 0.0)
        n_ok = sum(1 for L in _LAYERS if layers[L]["vec"] is not None)

        # ── ③ 两侧实况是否同源同步 (势场侧 trace_live vs 模型侧 chunk_latest) ──
        #   不同阶段/不同时刻混着算, 会让「层矢量 vs 势场力」的夹角失真 (实测落 86~98° 全否决),
        #   所以把两边阶段与时间戳一起报出来, 谁不同步一眼可见 —— 不掩盖。
        _sync = {}
        try:
            import json as _j2
            _ck = _j2.load(open(os.path.join(live, "chunk_latest.json"), encoding="utf-8")) or {}
            _ct = float(_ck.get("ts") or 0.0)
            _tt = float(out["ts"] or 0.0)
            _sync = {"trace_stage": str(stage or ""), "chunk_stage": _ck.get("stage"),
                     "trace_ts": round(_tt, 2), "chunk_ts": (round(_ct, 2) if _ct else None),
                     "chunk_cycle": _ck.get("cycle"),
                     "dt_s": (round(abs(_ct - _tt), 2) if (_ct and _tt) else None),
                     "stage_same": (str(stage) == str(_ck.get("stage")) if _ck.get("stage") else None),
                     "note": "两侧阶段/时间不一致时, 层矢量与势场力的夹角不可当判据用"}
        except Exception as _se:                                             # noqa: BLE001
            _sync = {"err": "%s: %s" % (type(_se).__name__, _se)}

        # ── ④ 落盘 (独立文件: `hamiltonian.json` 由 ss_engine_loop 每周期原子写, 本节点再写同一份会互抢,
        #        实测出现「文件时有时无 layers」⇒ 分层力单独落 `gravity_layers.json`, 唯一写入者=本节点) ──
        _doc = dict(out)
        _doc.update({"layers": layers, "layer_resultant": res, "layer_main": main,
                     "layer_sum": _sum, "layer_residual": resid, "layer_n_ok": n_ok,
                     "layers_src": "tools/layer_forces.py (config/calib/layer_forces.json 的 w/k)",
                     "layer_err": lf_err, "sync": _sync,
                     "energy_snapshot": {"U": U, "K": K, "H": K + U, "hdot": hd, "passive": bool(hd <= 0)}})
        try:
            os.makedirs(live, exist_ok=True)
            _p = os.path.join(live, "gravity_layers.json")
            _t = _p + ".tmp"
            with open(_t, "w", encoding="utf-8") as fh:
                _json.dump(_doc, fh, ensure_ascii=False, indent=1, default=float)
            os.replace(_t, _p)                       # 原子替换, 读方永远看不到半个文件
        except Exception as _we:                                  # noqa: BLE001
            # 🔴 落盘异常**不许静默吞掉** (技能铁律): 文件不更新而日志看着像成功
            if log:
                log("⚠️ gravity_layers.json 落盘失败: %s: %s" % (type(_we).__name__, _we))

        if log:
            log("🌍 万有引力: ξ_e=[%.1f,%.1f,%.1f]mm · U=%.6fJ · K=%.6fJ · H=%.6fJ · Ḣ=%.2e %s"
                % (xi_e[0] * 1000, xi_e[1] * 1000, xi_e[2] * 1000, U, K, K + U, hd,
                   "(被动✅)" if hd <= 0 else "(主动⚠)"))
            log("   四层力 %d/4 有数 · 主力=%s · |F_合|=%.5f · 层和残差=%s"
                % (n_ok, main, _mag, ("%.2e" % resid) if resid is not None else "n/a"))
            for L in _LAYERS:
                d = layers[L]
                if d["vec"] is None:
                    log("   %s %-22s 缺: %s" % (L, d["role"], str(d["src"])[:64]))
                else:
                    log("   %s %-22s |F|=%.5f w=%.2f k=%.2f 夹角%.0f° %s · %s"
                        % (L, d["role"], d["mag"], d["w"], d["k"], d["deg"],
                           "放行" if d["allow"] else "否决", str(d["src"])[:48]))
            log("   数据源: %s · 阶段 %s · ξ 来自 %s" % (str(out["src"])[:40], stage, src_vel))

        # ── ⑤ 输出 ───────────────────────────────────────────────────────────
        out1 = {"kind": "force_corrected", "dir": _dir, "mag": round(_mag, 6),
                "fuse": "Σ_l w_l·k_l·v_l (L2 基础 + L3/L4/L5 加权)",
                "main": main, "n_ok": n_ok,
                "layers": {L: layers[L]["mag"] for L in _LAYERS},
                "allow": {L: layers[L]["allow"] for L in _LAYERS},
                "sync": _sync,
                "src": "tools/layer_forces.py", "t": float(out["ts"])}
        out2 = {"F": res, "M": [0.0, 0.0, 0.0],
                "M_src": "姿态力矩项未建模 ⇒ 如实写 0, 不拿位置力冒充",
                "unit": "m/s 速度当量 (与 tools/layer_forces.py 同口径)",
                "layers": layers, "residual": resid, "main": main,
                "euler_gate": "见 layers[*].allow (夹角>60° 否决)",
                "sync": _sync,
                "H": K + U, "U": U, "K": K, "hdot": hd}
        return _NodeOut({"out1": out1, "out2": out2,
                         "ok": True, "U": U, "K": K, "H": K + U, "hdot": hd,
                         "layers": layers, "layer_resultant": res})
    except Exception as e:                                                  # noqa: BLE001
        if log:
            log("⚠️ 万有引力节点: %s: %s (缺实况 ⇒ 不出数, 不造数)" % (type(e).__name__, e))
        return _NodeOut({"out1": None, "out2": None, "ok": False,
                         "err": "%s: %s" % (type(e).__name__, e)})
