# -*- coding: utf-8 -*-
"""sssk1 — 节点实现正文 (文件名 = 画布节点: sssk1)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_atomic   ·   registry key: sssk1
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _REPO_ROOT,
    _SS_DIR,
    _SS_STATE,
    _load_mod,
    os,
    time,
)

def node_ss_atomic(ctx):
    """🧩 原子技能层 (2026-09-07 老倪: 决策层与执行层之间加技能模板层)
    机制: 8 个原子技能 (SK01-08) = 固定轨迹模板; 决策层 (动作调制器状态机经安全边界)
    明确选定当前技能并**实时赋值** (阶段目标/速度), 技能模板被复制实例化 → 快速执行 →
    直接输出执行指令给 🤖执行器。
    模板权威源 = src/lerobot/.../state_space/skills/atomic_skills.py (SKILL_BY_CODE,
    右键本节点看真实源码); 数据真源 = module._ss_tr 当前帧 (stage=当前技能 / target=
    决策赋值目标 / u_exec_vec=实际下发速度)。"""
    log = ctx.get("log")
    try:
        import numpy as np
        # 🧩 模板真源: skills/atomic_skills.py (2026-09-08 集中到 src/lerobot)
        _p = os.path.join(_SS_DIR, "skills", "atomic_skills.py")
        _m = _load_mod("ss_atomic_skills", _p)              # 正常 import (断点可绑)
        name = ctx.get("name", "")
        p = ctx.get("params", {}) or {}
        sk = p.get("skill") or {}
        tpl = str(sk.get("template", "SK--"))
        stg = str(sk.get("stage", ""))
        _tpl = _m.SKILL_BY_CODE.get(tpl) or _m.SKILL_BY_STAGE.get(stg)
        mod = ctx.get("module")
        tr = getattr(mod, "_ss_tr", None) if mod is not None else None
        if tr is None or not tr.get("t"):
            if log:
                log(f"🧩 原子技能 {name} · {tpl}: 无引擎轨迹 — 先点 ▶ 运行状态空间")
            # 2026-11-01: 无轨迹也要给**带类型的帧** (active=False), 否则下游 in4 拿到 None
            #   ⇒ 运动规划看不出"技能没激活"和"技能没接线"的区别 (两种都是空)。
            _t0 = float(time.time())
            # 🧭 2026-11-01 老倪「技能必须真正执行」: 没有引擎轨迹 ≠ 不能算目标。
            #   技能模板的 next_target() 能从**真源点位库** (config/points/cell_points.json) 算本段目标,
            #   这是真算 (不是编造的形状); 引擎轨迹只影响 clamp/trace, 不影响目标点解析。
            _tgt, _src, _why = None, "", ""
            try:
                import json as _js2
                _d = os.path.dirname(os.path.abspath(__file__))
                while _d != os.path.dirname(_d) and not os.path.isdir(os.path.join(_d, ".git")):
                    _d = os.path.dirname(_d)
                _pp = os.path.join(_d, "config", "points", "cell_points.json")
                _raw = _js2.load(open(_pp, encoding="utf-8"))
                # 点位库 → next_target 要的 {name:{"pos":[3]}} + 几何 ctx
                _pts, _geo = {}, {}
                for _it in (_raw.get("slots") or []):
                    _pts[_it["name"]] = {"pos": _it["pos"]}
                for _it in (_raw.get("holes") or []):
                    _pts["%s_mouth" % _it["name"]] = {"pos": _it["mouth"]}
                    _pts["%s_insert" % _it["name"]] = {"pos": _it["insert"]}
                    _geo.setdefault("hole", _it["insert"])
                    _geo.setdefault("hole_mouth", _it["mouth"])
                for _it in (_raw.get("sides") or []) + (_raw.get("scrap") or []):
                    _pts[_it["name"]] = {"pos": _it["pos"]}
                if isinstance(_raw.get("golden"), list):
                    _pts["golden"] = {"pos": _raw["golden"]}
                    _geo.setdefault("table_z", float(_raw["golden"][2]))
                _peg = _SS_STATE.get("peg") or _SS_STATE.get("peg_xyz")
                if _peg is not None:
                    _geo["peg"] = list(np.asarray(_peg, dtype=float).ravel()[:3])
                    _geo.setdefault("head_off", [0.0, 0.0, 0.0])
                _cur = _SS_STATE.get("pos") or _SS_STATE.get("tcp") or None
                # 段→点位名 (技能语义 ↔ 点位库名): 抓取系看料位, 插入系看孔口/孔底
                _code = str(tpl)
                _MAP = {"SK01": "槽1", "SK02": "槽1", "SK03": "槽1", "SK04": "槽1", "SK05": "槽1",
                        "SK06": "孔1_mouth", "SK07": "孔1_insert", "SK08": "孔1_insert"}
                _spec = {"point": _MAP[_code]} if _code in _MAP else None
                if _spec and _spec["point"] not in _pts:
                    _spec = None
                _tn = _tpl.next_target(ctx=_geo or None, points=_pts, spec=_spec, cur=_cur)
                if _tn:
                    _tgt = [round(float(x), 3) for x in _tn["xyz"]]
                    _src = "next_target[%s] ref=%s" % (_tn.get("src") or "taught", _tn.get("ref"))
            except Exception as _e:                                       # noqa: BLE001
                _why = "%s: %s" % (type(_e).__name__, str(_e)[:60])
            return {"out1": {"kind": "skill_act", "skill": tpl, "stage": stg,
                             "active": _tgt is not None and bool(stg),
                             "target": _tgt, "target_src": _src,
                             "reason": ("target_only_no_trace" if _tgt else "no_engine_trace"),
                             "why": _why, "name": name, "t": _t0},
                    "out2": {"kind": "skill_gate", "skill": tpl, "stage": stg,
                             "f_need_N": None, "reason": "no_engine_trace", "t": _t0}}
        idx = int(min(getattr(mod, "_ss_round", 0) or 0, len(tr["t"]) - 1))
        stage_now = str(tr["stage"][idx]).replace("阶段 ", "").split("·")[0].strip()
        tgt = np.asarray(tr["target"][idx], dtype=float) if tr.get("target") else np.zeros(3)
        u = np.asarray(tr["u_exec_vec"][idx], dtype=float) if tr.get("u_exec_vec") else np.zeros(4)
        act = bool(stg and stage_now == stg)
        # 🧭 2026-10-31 老倪「按照连线, 强制保持数据功能与连线一致」:
        #   连线上这个节点被激活 ⇒ **真跑一次本段技能的 clamp** (以前只打日志 = 线连着但不执行,
        #   SK01 的 clamp 一拍都没进过, 断点当然不进)。结果带 why/err_norm, 沿 sssk → ssphys 的线往下走。
        _gate = None
        if act:
            try:
                import sys as _sys
                _tp = os.path.join(_REPO_ROOT, "tools")
                if _tp not in _sys.path:
                    _sys.path.insert(0, _tp)
                import dispatch_inproc as _dpi
                _gate = _dpi.step_stage(stg, np.asarray(u[:3], dtype=float))
            except Exception as _e:                                          # noqa: BLE001
                _gate = None
                if log:
                    log(f"⚠️ 原子技能 {name}: 调 clamp 失败 {type(_e).__name__}: {_e}")
        if log:
            if _tpl is not None:
                log(f"🧩 模板 {tpl} {_tpl.name}: {_tpl.desc}")
                log(f"   目标 {_tpl.goal} · 参数 {_tpl.params} · 推进 {_tpl.evidence}")
            if act:
                log(f"🧩 原子技能 ▶ {name} 激活 · 模板{tpl} (决策层选定「{stg}」→ 模板实例化快速执行) · "
                    f"决策实时赋值: 目标 {np.round(tgt[:3], 3)} · 执行速度 u={np.round(u[:3], 3)} m/s")
                if _gate:
                    log("   ⚖ 过闸 → |u|=%.3f m/s · 偏差 %.1f mm/s · 削因 %s · f_need=%.3f N" % (
                        float(np.linalg.norm(np.asarray(_gate.get("u") or [0, 0, 0], dtype=float))),
                        float(_gate.get("err_norm") or 0.0) * 1000.0,
                        _gate.get("why") or "", float(_gate.get("f_need_N") or 0.0)))
            else:
                log(f"🧩 原子技能 {name} 待命 · 模板{tpl} (当前阶段 {stage_now or '—'}, 未调用)")
        # 🧭 2026-11-01 老倪「plan 的上游是技能, 端口必须对正, 真执行」:
        #   原来本函数只 return True ⇒ 壳子拿到非 dict ⇒ out1/out2 恒空 ⇒
        #   连到 运动规划(in4) 的 8 根线传的全是空值 (线在, 值没有 = 假接线)。
        #   现按端口语义给出: out1 = 技能动作 (含 target[mm] 供规划用) / out2 = 过闸结果。
        _tgt_mm = [round(float(x) * 1000.0, 3) for x in np.asarray(tgt, dtype=float).ravel()[:3]]
        _u4 = [round(float(x), 6) for x in np.asarray(u, dtype=float).ravel()[:4]]
        # 🧠 2026-11-02 老倪「L2 记忆节点应该给技能赋能」: 每拍把**本段记忆**带在 out1 上
        #   (工艺点通道 key/r/L/节拍 + 标杆命中) —— in3 有记忆包就用它, 没有就现查 l2_store, 两边同一份真源。
        _mem = None
        try:
            _in3 = (ctx.get("in3") or {}).get("value") if isinstance(ctx.get("in3"), dict) else None
            if isinstance(_in3, dict) and _in3.get("key"):
                _mem = _in3
            else:
                from lerobot.memory import l2_store as _LS
                _tab = {"接近": ("槽", "槽"), "下降": ("槽", "槽"), "抓取": ("槽", "槽"), "抬起": ("槽", "槽"),
                        "转移": ("槽", "孔"), "对位": ("孔", "孔"), "插入": ("孔", "孔"), "完成": ("孔", "孔")}
                _ps, _pe = _tab.get(stg, ("槽", "槽"))
                _lst = [v for v in (_LS.corridors() or {}).values() if v.get("stage") == stg]
                _okv = lambda v: str(v.get("from") or "").startswith(_ps) and \
                    (str(v.get("to") or "").startswith(_pe) or v.get("to") == "-")
                _pool = [v for v in _lst if v.get("kind") == "real" and _okv(v)] or \
                        [v for v in _lst if _okv(v)] or _lst
                if _pool:
                    _b = max(_pool, key=lambda v: (v.get("kind") == "real", v.get("n_poly") or 0))
                    _ck = [k for k in (_LS.champs() or {}) if k.endswith("|" + stg)]
                    _mem = {"key": _b.get("key"), "kind": _b.get("kind"), "r_mm": _b.get("r_mm"),
                            "L_mm": _b.get("L_mm"), "s_tick_mm": _b.get("s_tick_mm"),
                            "v_along_cap": _b.get("v_along_cap"), "tact_s": _b.get("tact_s"),
                            "champ_n_ok": sum(int(((_LS.champs() or {}).get(k) or {}).get("n_ok") or 0) for k in _ck),
                            "src": "data/memory/l2_store/corridors.json"}
        except Exception:                                            # noqa: BLE001
            _mem = None
        out1 = {"kind": "skill_act", "skill": tpl, "stage": stg, "active": bool(act),
                "target": _tgt_mm, "target_unit": "mm(base_link)",
                "u": _u4, "u_unit": "m/s(与引擎 u_exec_vec 同口径)",
                "mem": _mem, "gate": _gate, "name": name, "t": float(time.time())}
        out2 = {"kind": "skill_gate", "skill": tpl, "stage": stg,
                "f_need_N": (_gate or {}).get("f_need_N"),
                "u_gate": (_gate or {}).get("u"), "why": (_gate or {}).get("why"),
                "err_mm": (round(float((_gate or {}).get("err_norm") or 0.0) * 1000.0, 3)
                           if _gate else None),
                "saturated": bool(_gate and (_gate.get("why") or "").strip() not in ("", "pass")),
                "t": float(time.time())}
        return {"out1": out1, "out2": out2}
    except Exception as e:
        if log:
            log(f"⚠️ 原子技能层执行失败: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_atomic
