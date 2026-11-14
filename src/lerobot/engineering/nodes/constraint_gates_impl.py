# -*- coding: utf-8 -*-
"""🧭 运动学约束 / ⚖ 动力学约束 画布节点真实现 (老倪 2026-10-31)

「后面的 接近、对位 这些技能, 要符合运动学约束; 物理约束这个要改成动力学约束; 都要真正调用」

本节点 (画布 id=ssphys, 名字「⚖ 动力学约束 · 惯性/质量率闸 (SK01-08)」) **每拍真跑两条闸**,
顺序与技能链完全一致 (与 tools/ss_skill_dispatch.py 同一批类, 不另写一套):

    u_req → 🧭 KinematicLimiter (①速度 ②加速度 ③加加速度 ⑤位移/行程)
          → ⚖ DynamicLimiter  (④动量/质量变化率 |m·Δv+v·Δm| ≤ F_max·dt)
          → 可行动作 + 削出偏差

数据真源: zmax_data/ss_live/chunk_latest.json (常驻回路写的块: u[H,4] + stage_idx),
和 60Hz 派发链读的是**同一份块**, 所以画布这一拍的 u 与技能侧认领的 u 同源 (不是另造的)。

输出三条线 (与画布连线语义一致):
    out1 可行动作 → 🛡 安全执行边界 (再限幅)
    out2 小偏差   → 🧪 状态校正器
    out3 大偏差   → 📡 融合定位建图

留证: zmax_data/ss_live/constraint_gate.json —— 每拍原子覆盖, 含两条闸各自的拍数与削因
      (老倪「都要真正调用」的判据: 运动学闸_拍 == 动力学闸_拍 == 节点_拍)。

铁律: 只算不下发 (不碰 FIFO / 不查授权 / 不写指令文件); 真机下发仍是 tools/l2_daemon.py + 8793 授权。
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

from .library import _SS_STATE, _ss_import

# 与 tools/ss_skill_dispatch.py:41 同一份阶段序 (块内第 i 拍 → stage_idx+i)
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
DT = 0.1                     # 秒 — 标定口径 (config/calib/zmax_skill_physics.json 的 dt), 不用引擎 dt


def _live_dir():
    """真源目录: 仓库根下 zmax_data/ss_live。
    ⚠️ 不能只"向上第 N 层"(src/zmax_data/ss_live 这种假目录会先命中, 实测 2026-10-29 就有), 必须按仓库根标记找。"""
    root = os.environ.get("ZMAX_ROOT")
    if root and os.path.isdir(os.path.join(root, "zmax_data", "ss_live")):
        return os.path.join(root, "zmax_data", "ss_live")
    p = os.path.abspath(__file__)
    for _ in range(8):
        p = os.path.dirname(p)
        if (os.path.isdir(os.path.join(p, "tools")) and os.path.isdir(os.path.join(p, "config"))
                and os.path.isdir(os.path.join(p, "zmax_data", "ss_live"))):
            return os.path.join(p, "zmax_data", "ss_live")
    return os.path.join(os.getcwd(), "zmax_data", "ss_live")


LIVE = _live_dir()
OUT = os.path.join(LIVE, "constraint_gate.json")

_PC = None


def _pc():
    """取 physics_constraints 模块 (与 safety/atomic_skills 同一加载口径: 经 _ss_import 走包内真身)。"""
    global _PC
    if _PC is None:
        _PC = _ss_import("physics_constraints")
    return _PC


# ── 两条闸的真身实例 (跨拍保留: 段行程/上拍速度/削因计数) ────────────────────────
_G = {"kin": None, "dyn": None, "n": 0, "n_kin": 0, "n_dyn": 0,
      "last_v": None, "last_a": None, "last_key": None}


def _gates():
    pc = _pc()
    if _G["kin"] is None:
        _G["kin"] = pc.KinematicLimiter(dt=DT)
    if _G["dyn"] is None:
        _G["dyn"] = pc.DynamicLimiter(dt=DT)
    return _G["kin"], _G["dyn"]


def _atomic_json(path, obj):
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, default=float)
    os.replace(tmp, path)


def _current():
    """当前块动作 (唯一依据): → (stage, u[4], age_s, src, block_ts) 或 (None, None, ...)。"""
    p = os.path.join(LIVE, "chunk_latest.json")
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as e:                                                  # noqa: BLE001
        return None, None, None, "chunk_latest.json 读不到: %s" % type(e).__name__, None
    ts = float(d.get("ts") or 0.0)
    age = round(time.time() - ts, 3) if ts else None
    u = d.get("u") or []
    if not d.get("ok") or not u:
        return None, None, age, "块无动作 (ok=%s, u=%d 拍)" % (d.get("ok"), len(u)), ts
    si = int(d.get("stage_idx") or 0)
    stage = STAGES[min(len(STAGES) - 1, max(0, si))]
    return stage, np.asarray(u[0], dtype=float).ravel()[:4], age, "chunk_latest.json", ts


def run(ctx):
    """画布节点真跑: 🧭 运动学 → ⚖ 动力学。返回 {out1, out2, out3} (壳只收 dict)。"""
    log = ctx.get("log")
    name = ctx.get("name", "")
    stage, u, age, src, block_ts = _current()
    if u is None:
        if log:
            log("⚖ 约束闸: 无当前块动作 ⇒ 本拍不裁 (如实报, 不造数): %s" % src)
        return {"out1": {"kind": "constraint_gate", "ok": False, "why": src,
                         "stage": None, "u_in": None, "u_out": None,
                         "src": "chunk_latest.json (无块)", "block_age_s": age}}

    pc = _pc()
    kin, dyn = _gates()
    p = pc.limits_for(stage, dt=DT)
    u_in = [float(x) for x in u]
    # ① ② ③ —— 🧭 运动学约束
    v, why_k, p, v0 = kin.limit(stage, u[:3], v_prev=_G["last_v"], a_prev=_G["last_a"], p=p)
    _G["n_kin"] += 1
    # ④ —— ⚖ 动力学约束
    v, why_d, f_need = dyn.limit(stage, v, v0, p)
    _G["n_dyn"] += 1
    # ⑤ —— 🧭 运动学约束 (位移是速度的积分)
    v, why_s, over, s_travel = kin.displace(stage, v, p)
    why = why_k + why_s
    _G["last_a"] = (v - (v0 if v0 is not None else np.zeros(3))) / DT
    _G["last_v"] = v.copy()
    _G["n"] += 1

    err = np.asarray(u_in, float)[:3] - v
    e_norm = float(np.linalg.norm(err))
    big = int(e_norm > float(os.environ.get("ZMAX_SKILL_BIG_ERR", "0.05")))
    out1 = {"kind": "constraint_gate", "ok": True, "stage": stage,
            # 🧭 运动学
            "kin_why": "+".join(why) or "可行",
            "kin_cut": dict(kin.n_cut),
            # ⚖ 动力学
            "dyn_why": "+".join(why_d) or "可行",
            "dyn_cut": dict(dyn.n_cut), "f_need_N": round(float(f_need), 6), "F_max_N": float(p["F"]),
            # 数值
            "u_in": [round(x, 6) for x in u_in],
            "u_kin": [round(float(x), 6) for x in v],
            "u_out": [round(float(x), 6) for x in v] + [round(float(u_in[3]), 6)],
            "why": "+".join(why + why_d) or "可行",
            "err": [round(float(x), 6) for x in err], "err_norm": round(e_norm, 6), "big": big,
            "s_travel_m": round(float(s_travel), 6), "over_travel": int(over),
            "limits": {"v_cap": float(p["v"]), "a_max": round(float(p["a_max"]), 4),
                       "jerk_max": round(float(p["jerk_max"]), 3),
                       "s_step": float(p.get("s_step") or 0.0), "s_max": float(p.get("s_max") or 0.0),
                       "m_kg": float(p["m"]), "dmdt_kg_s": float(p.get("dmdt") or 0.0), "dt": DT,
                       "calib": p.get("calib_src_kind")},
            "gate_n": {"node": _G["n"], "kin": _G["n_kin"], "dyn": _G["n_dyn"], "kin_obj": kin.n, "dyn_obj": dyn.n},
            "src": "physics_constraints.KinematicLimiter/DynamicLimiter ← %s" % src,
            "block_age_s": age, "t": time.time()}

    rec = {"ts": time.time(), "t_str": time.strftime("%H:%M:%S"), "node": "ssphys",
           "name": name or "⚖ 动力学约束 · 惯性/质量率闸 (SK01-08)",
           "stage": stage, "block_ts": block_ts, "block_age_s": age,
           "gate": out1,
           "真值口径": "u 来自 chunk_latest.json (与 60Hz 派发链同一份块); 两条闸各自拍数必须等于 node 拍数"}
    try:
        _atomic_json(OUT, rec)
    except Exception as e:                                                  # noqa: BLE001
        if log:
            log("⚠️ constraint_gate.json 落盘失败: %s: %s" % (type(e).__name__, e))

    if log:
        log("⚖ 约束闸(真实): 段[%s] u=%s → 🧭运动学[%s] → ⚖动力学[%s 力需求%.3fN/限%.1fN] → u_kin=%s · "
            "拍数 node%d/kin%d/dyn%d · 块龄%s"
            % (stage, [round(x, 3) for x in u_in],
               "+".join(why) or "可行", "+".join(why_d) or "可行",
               float(f_need), float(p["F"]), [round(float(x), 3) for x in v],
               _G["n"], _G["n_kin"], _G["n_dyn"], age))
    # 输出分流: 大偏差 → 融合定位; 小偏差 → 状态校正器; 可行动作 → 安全边界
    err_rec = {"kind": "constraint_err", "stage": stage, "err": out1["err"],
               "err_norm": out1["err_norm"], "big": big,
               "kin_why": out1["kin_why"], "dyn_why": out1["dyn_why"],
               "src": "⚖ 约束闸 (运动学+动力学) 削出偏差", "t": time.time()}
    return {"out1": out1, "out2": err_rec, "out3": err_rec}


def status():
    """给判据/面板: 两条闸各自的拍数与削因 (进程内真值)。"""
    kin, dyn = _gates()
    return {"node_n": _G["n"], "n_kin": _G["n_kin"], "n_dyn": _G["n_dyn"],
            "kin": kin.stats(), "dyn": dyn.stats(), "dt": DT, "live": OUT}
