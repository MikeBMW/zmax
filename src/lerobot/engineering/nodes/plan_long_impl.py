# -*- coding: utf-8 -*-
"""🧩 长程元任务编排器 (Plan 节点) · 真实实现 (registry key = ss_plan_long)

与 🏭 UPH 节拍循环器的分工:
  UPH 节拍循环器 (ss_uph)   : 直接读段表 sim_insert.json 的成品 plan, 按节拍推进 —— 只关心"第几段"
  长程元任务编排器 (本节点) : 读**配置中心的 TASK-07-AOI 元任务组合**(ar_meta_tasks.json),
                              按轮模板把元任务展开成段序列, 让每一段都带上"属于哪个元任务"的归属,
                              再按节拍推进 —— 关心"正在执行哪个元任务、第几段"

数据真源 (只读):
  data/database/zmax/sources/config/tasks/ar_meta_tasks.json   元任务库 + 轮模板 (由 tools/ss_meta_task_ar.py 生成)
  zmax_data/runtime/traj/sim_insert.json                       段几何 (a/b/t), 不重复造数
  两者不一致 ⇒ 拒跑并如实报 (不许拿旧配置硬跑)

输出:
  out1 当前动作 {seq,kind,label,a,b,t,t_in_seg,t_left,mod,hole, mt_id,mt_name,mt_i,mt_n,batch}
  out2 元任务进度 {mt_id,mt_name,mt_done,mt_total,batch,batch_n,mod,done,total,uph_live}
  out3 长程任务 {elapsed_s,round,tact_s,uph_target,uph_capability,seg_index,n_segs,task_id,verified}
副作用: ZMAX_UPH_AR_PUB=1 时写 zmax_data/ss_live/ar_cmd.json (AR 渲染指令, 真机零指令)
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

_ROOT = os.path.expanduser("~/zmax")
_META = os.path.join(_ROOT, "data", "database", "zmax", "sources", "config", "tasks", "ar_meta_tasks.json")
_PLAN = os.path.join(_ROOT, "zmax_data", "runtime", "traj", "sim_insert.json")
_AR_CMD = os.path.join(_ROOT, "zmax_data", "ss_live", "ar_cmd.json")

# 🧱 2026-11-01 老倪「要接上 动手」: 把「运动学通道(r_mm) + 动力学(v/a/jerk) + 拐角限速」
#   真压进 plan 的段时长。闸后表由 tools/plan_gate_corridor.py 算 (可复算可对拍),
#   真源 = skill_corridors.json(8 阶段 r/v_cap/a_max) + config/calib/zmax_skill_physics.json(jerk)。
#   plan 只吃「闸后 t + 逐段闸参数」, 几何仍用自算/磁盘段表 ⇒ 不影响 _self_plan 对拍。
_GATED = os.path.join(_ROOT, "zmax_data", "runtime", "traj", "sim_insert_gated.json")
_GATE_ON = os.environ.get("ZMAX_PLAN_GATE", "1") == "1"
_GATE = {"rows": None, "mtime": 0.0, "n": 0, "src": "未接"}

# 🚀 规划速度档位 (2026-11-01 老倪「必须上300」): 过渡阶段提速 + 空载跨件飞行速度
_SPEED_JSON = os.path.join(_ROOT, "config", "calib", "zmax_plan_speed.json")
_SPD = {"mtime": 0.0, "d": {}}


def _speed_profile():
    """读 config/calib/zmax_plan_speed.json (改档位免重启: 按 mtime 热读)"""
    try:
        if not os.path.isfile(_SPEED_JSON):
            return _SPD["d"]
        mt = os.path.getmtime(_SPEED_JSON)
        if mt != _SPD["mtime"]:
            _SPD["d"] = json.load(open(_SPEED_JSON, encoding="utf-8")) or {}
            _SPD["mtime"] = mt
        return _SPD["d"]
    except Exception:                                                  # noqa: BLE001
        return _SPD["d"]


# 🧱 2026-11-01 老倪「状态空间 技能约束通道 要真有效 接入 plan 节点」:
#   之前 plan 只吃到 r_mm 这个**数字**(算段时长), 几何通道本身没进发布路径 ⇒ 通道=画了条线。
#   现在发布前把**段端点 + 每拍点**夹进该技能真实通道 (切外+回中到管壁); 越界量/回中量/技能码
#   写进 ar_cmd.gate.cor。页面按 d.a/d.b 动画 ⇒ 画出来的就是通道内的轨迹, 且有取证可查。
#   真源 = zmax_data/ss_live/skill_corridors.json (tools/ss_corridor_build.py 建/改半径重跑)。
_COR_ON = os.environ.get("ZMAX_PLAN_CORRIDOR", "1") == "1"
_COR_PATH = os.path.join(_ROOT, "zmax_data", "ss_live", "skill_corridors.json")
_COR = {"mtime": 0.0, "d": {}, "mod": None, "src": "未接"}
_FIT = {}                     # (seq, stage) → 段端点贴合结果 (同一段只算一次)
_TICK = {"dev_max": 0.0, "cut": 0, "n": 0, "seq": None}


def _corridor_mod():
    """按路径加载 corridor.py (固定模块名 ⇒ 与技能侧同一份算法, 不写第二套)。"""
    if _COR["mod"] is not None:
        return _COR["mod"] or None
    try:
        import importlib.util as ilu
        p = os.path.join(_ROOT, "src", "lerobot", "policies", "left_right",
                         "state_space", "corridor.py")
        m = sys.modules.get("zmax_skill_corridor")
        if m is None:
            spec = ilu.spec_from_file_location("zmax_skill_corridor", p)
            m = ilu.module_from_spec(spec)
            sys.modules["zmax_skill_corridor"] = m
            spec.loader.exec_module(m)
        _COR["mod"] = m
    except Exception as e:                                             # noqa: BLE001
        _COR["mod"] = False
        _COR["src"] = "通道模块加载失败: %s: %s" % (type(e).__name__, e)
    return _COR["mod"] or None


def _cor(stage):
    """stage → 该技能的通道 (按 mtime 热读); 没有该技能通道 ⇒ None。"""
    if not _COR_ON:
        return None
    m = _corridor_mod()
    if m is None:
        return None
    try:
        if not os.path.isfile(_COR_PATH):
            _COR["src"] = "无通道真源(先跑 tools/ss_corridor_build.py)"
            return None
        mt = os.path.getmtime(_COR_PATH)
        if mt != _COR["mtime"]:
            _COR["d"] = m.load_corridors(_COR_PATH) or {}
            _COR["mtime"] = mt
            _COR["src"] = "通道真源 %s (%d 技能)" % (
                time.strftime("%m-%d %H:%M", time.localtime(mt)), len(_COR["d"]))
        return (_COR["d"] or {}).get(str(stage or ""))
    except Exception as e:                                             # noqa: BLE001
        _COR["src"] = "通道读失败: %s: %s" % (type(e).__name__, e)
        return None


def _skill_stage(kind, label):
    """段 (kind,label) → 原子技能段名 —— 与 tools/ss_corridor_build.group_polys 同一规则。"""
    kind = str(kind or "")
    label = str(label or "")
    if kind == "move":
        return "转移" if "行进高度" in label else ("对位" if "孔口" in label else "接近")
    return {"down": "下降", "grip": "抓取", "up": "抬起", "insert": "插入",
            "pull": "插入", "release": "完成"}.get(kind)


def _cor_fit(o1):
    """段端点夹进通道 (每段一次, 按 seq 缓存): 返回 (a, b, info, corr) 或 None。"""
    if not _COR_ON:
        return None
    stage = _skill_stage(o1.get("kind"), o1.get("label"))
    a = list(o1.get("a") or [])
    b = list(o1.get("b") or [])
    if len(a) != 3 or len(b) != 3:
        return None
    if not stage:
        # 📷 零位移的检测/保持段 (AOI 金手指/侧面): 没有技能通道, 但也不许飘 ——
        #   用「保持点通道」(轴 1mm, 半径取本段闸 r): 实际点偏离保持点 > r 就会被夹回。
        if math.dist([float(x) for x in a], [float(x) for x in b]) > 1e-6:
            return None
        r_g = float((_gate_info(_S.get("i")) or {}).get("r_mm") or 0.0)
        if r_g <= 0.0:
            return None
        stage = "保持"
        corr = {"polys": [[a, [a[0], a[1], a[2] - 1.0]]], "r_mm": r_g, "L_mm": 1.0,
                "stage": "保持", "dt": 0.1}
    else:
        corr = _cor(stage)
    if not corr:
        return None
    key = (o1.get("seq"), stage, tuple(round(float(x), 3) for x in a + b))
    hit = _FIT.get(key)
    if hit is not None:
        return hit
    m = _corridor_mod()
    a2, ia = m.clamp_into(corr, a)
    b2, ib = m.clamp_into(corr, b)
    why = []
    if not ia["in_channel"]:
        why.append("起点" + str(ia["why"]))
    if not ib["in_channel"]:
        why.append("终点" + str(ib["why"]))
    info = {"stage": stage, "skill": _skill_code(stage), "r_mm": corr.get("r_mm"),
            "a_in": ia["in_channel"], "b_in": ib["in_channel"],
            "dev_a": ia["dev_mm"], "dev_b": ib["dev_mm"],
            "moved_mm": round(float(ia["moved_mm"]) + float(ib["moved_mm"]), 3),
            "why": "+".join(why) or "通道内", "cut": bool(why)}
    if len(_FIT) > 4000:
        _FIT.clear()
    _FIT[key] = (a2, b2, info, corr)
    return _FIT[key]


def _cor_pub(o1, corr, a_fit, b_fit, u):
    """每拍: 发布点必须落在通道内 —— 越界则把 u 二分收回到管内最大进度。"""
    m = _corridor_mod()
    seq = o1.get("seq")
    if _TICK["seq"] != seq:
        _TICK.update(seq=seq, dev_max=0.0, cut=0, n=0)
    p = [a_fit[i] + (b_fit[i] - a_fit[i]) * u for i in range(3)]
    _p2, info = m.clamp_into(corr, p)
    _TICK["n"] += 1
    if info["dev_mm"] > _TICK["dev_max"]:
        _TICK["dev_max"] = info["dev_mm"]
    if info["in_channel"]:
        return u, {"dev_mm": info["dev_mm"], "in": True, "cut": False,
                   "n": _TICK["n"], "dev_max": round(_TICK["dev_max"], 3)}
    lo, hi = 0.0, u
    for _ in range(7):
        mid = 0.5 * (lo + hi)
        q = [a_fit[i] + (b_fit[i] - a_fit[i]) * mid for i in range(3)]
        if m.clamp_into(corr, q)[1]["in_channel"]:
            lo = mid
        else:
            hi = mid
    _TICK["cut"] += 1
    return lo, {"dev_mm": info["dev_mm"], "in": False, "cut": True,
                "u_nom": round(u, 4), "u_fit": round(lo, 4),
                "n": _TICK["n"], "dev_max": round(_TICK["dev_max"], 3)}


def _gate_rows(n_seg):
    """读闸后段表 → 逐段 {t, r_mm, v_cap, a_cap, j_cap, stage, bound_by}; 段数不符 ⇒ None"""
    if not _GATE_ON:
        _GATE.update(rows=None, src="闸关闭(ZMAX_PLAN_GATE=0)")
        return None
    if not os.path.isfile(_GATED):
        _GATE.update(rows=None, src="无闸后表(先跑 tools/plan_gate_corridor.py --write)")
        return None
    try:
        mt = os.path.getmtime(_GATED)
        if _GATE["rows"] is None or mt != _GATE["mtime"]:
            d = json.load(open(_GATED, encoding="utf-8"))
            pl = d.get("plan") or []
            rows = []
            for s in pl:
                g = s.get("gate") or {}
                rows.append({"t": float(s.get("t") or 0.0), "t_in": float(s.get("t_in") or 0.0),
                             "stage": g.get("stage"), "r_mm": g.get("r_mm"),
                             "v_cap": g.get("v_cap"), "a_cap": g.get("a_cap"),
                             "j_cap": g.get("j_cap"), "bound_by": g.get("bound_by"),
                             "corner_s": g.get("corner_s")})
            _GATE.update(rows=rows, mtime=mt, n=len(rows),
                         src="闸后表 %s (%d 段)" % (time.strftime("%m-%d %H:%M", time.localtime(mt)), len(rows)))
        if _GATE["n"] != int(n_seg):
            _GATE["src"] = "闸后表段数不符 %d≠%d ⇒ 本圈不用" % (_GATE["n"], int(n_seg))
            return None
        return _GATE["rows"]
    except Exception as e:                                            # noqa: BLE001
        _GATE.update(rows=None, src="闸后表读失败: %s: %s" % (type(e).__name__, e))
        return None


def _gate_info(i):
    """当前段(i)的闸参数 —— 透给 ar_cmd, 页面/执行器同一口径"""
    r = _GATE.get("rows")
    if not r or i is None:
        return None
    try:
        return r[int(i)]
    except Exception:                                                 # noqa: BLE001
        return None
_SPEED = float(os.environ.get("ZMAX_UPH_SPEED", "1.0"))
_AR_PUB = os.environ.get("ZMAX_UPH_AR_PUB", "0") == "1"
# 🧠 记忆层接入 (2026-10-30): L2 肌肉 / L3 流程工艺 / L4 安全 → 本节点的动作输出
_MEM_ON = os.environ.get("ZMAX_PLAN_MEM", "1") == "1"
_TACT_TARGET = float(os.environ.get("ZMAX_UPH_TACT_TARGET", "11.9"))   # 300UPH = 12.0s/件, 留 0.1s 余量
# ❗段间连续只兜「小缝」: 段表里 400~900mm 的跳是换件/重新定位, 线性插值会变成超速扫掠 (实测 905mm 一跳)
_BLEND_MAX_MM = float(os.environ.get("ZMAX_MEM_BLEND_MAX_MM", "60"))
# 🧠 2026-10-30 实测: 一段到下一段「跨件/换位」有 10 处缺口 (最大 564mm), 段表没给过渡时间。
#   开 ZMAX_MEM_TRAVEL=1 就把缺口按 travel 速度补进后一段的时长 ⇒ 视觉/真机都连续, 不超速。
#   代价: 每圈多 ~7.7s ⇒ UPH 307→~293 (物理下限, 不许为了达标超速)
_TRAVEL_ON = os.environ.get("ZMAX_MEM_TRAVEL", "1") == "1"
_MEM_S = {"ok": False, "kl2": {}, "l4": {}, "l3": {}, "t_eff": None, "cum2": None,
          "scale": 1.0, "prev_b": None, "seg_t_switch": None, "n_jump": 0,
          "jump_mm": [], "big_jump_mm": [], "cyc0": None, "err": ""}


def _mf():
    """记忆桥 (缺席则 None ⇒ 全程标称, 零回退)"""
    if not _MEM_ON:
        return None
    try:
        from lerobot.memory import mem_feed                                  # noqa: PLC0415
        return mem_feed
    except Exception as e:                                                   # noqa: BLE001
        _MEM_S["err"] = "%s: %s" % (type(e).__name__, e)
        return None


def _smooth(u):
    """五次 S 曲线 (C2, 首末速 0): u∈[0,1] ⇒ 钟形速度包络"""
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
    return u * u * u * (u * (u * 6.0 - 15.0) + 10.0)


def _mem_timing(segs):
    """L2 肌肉记忆(实测比例) + L4 安全(限速) ⇒ 每段有效时长 t_eff 与累计 cum2

    · 每段 t_eff = t × kl2[kind] (固化标杆: 实测比段表慢就多给时间, 快就少给)
    · 再按 L4 v_cap 兜底: t_eff ≥ 段长/v_cap (不许超速)
    · 整圈时间归一到 tact 目标 (300UPH = 12.0s/件, 目标取 11.9s 留余量)
    """
    mf = _mf()
    _MEM_S.update(ok=False, kl2={}, l4={}, l3={}, err="")
    if mf is None:
        gated0 = _gate_rows(len(segs))
        te0, ng0 = [], 0
        for i, s in enumerate(segs):
            t = float(s.get("t") or 0.0)
            if gated0 is not None and i < len(gated0):
                tg = float(gated0[i].get("t") or 0.0)
                if tg > t:
                    t = tg
                    ng0 += 1
            te0.append(max(1e-3, t))
        _MEM_S["t_eff"] = te0
        _MEM_S["cum2"] = None
        _MEM_S["gate"] = {"on": gated0 is not None, "src": _GATE.get("src"),
                          "n_stretched": ng0, "n_seg": len(segs), "note": "记忆未接, 仍走闸"}
        return
    try:
        f = mf.feed() if hasattr(mf, "feed") else {}
        l4 = dict(mf.safety() or {})
        if isinstance((f or {}).get("l4"), dict):
            l4.update({k: v for k, v in f["l4"].items() if v is not None})
        v_cap = float(l4.get("v_cap_mm_s") or 700.0)
        kinds = sorted({str(s.get("kind")) for s in segs})
        kl2 = {}
        for k in kinds:
            tt = [float(s.get("t") or 0) for s in segs if str(s.get("kind")) == k]
            kl2[k] = mf.bench_kind(k, sum(tt) / max(len(tt), 1)) if hasattr(mf, "bench_kind") else {"k": 1.0}
        cont = float(l4.get("continuity_mm") or 1.0)
        gaps = [0.0]
        for i in range(1, len(segs)):
            pb, ca = segs[i - 1].get("b"), segs[i].get("a")
            if not pb or not ca:
                gaps.append(0.0)
                continue
            g = sum((float(x) - float(y)) ** 2 for x, y in zip(pb, ca)) ** 0.5
            gaps.append(g if g > cont else 0.0)
        v_travel = float(os.environ.get("ZMAX_MEM_TRAVEL_MM_S")
                         or (_speed_profile().get("travel_mm_s") or 0)
                         or v_cap)
        # 🔴 2026-10-30 实测坑: 段被 tick 量化 (6Hz ⇒ 每段都比标称多 ~半拍 83ms) ⇒ kl2 系统性 >1
        #   (move 实测 0.51s vs 标称 0.40s ⇒ kl2=1.27)。用中位数归一去掉公共偏置, 只留 kind 之间的相对快慢。
        if kl2:
            _ks = sorted(float((v or {}).get("k") or 1.0) for v in kl2.values())
            _med = _ks[len(_ks) // 2] or 1.0
            if _med > 0:
                for k, v in list(kl2.items()):
                    v = dict(v or {})
                    v["k_raw"] = v.get("k")
                    v["k"] = round(float(v.get("k") or 1.0) / _med, 4)
                    kl2[k] = v
            # L2 只负责「段之间怎么分配时间」, 不负责「一圈总共多长」(那是 L3 节拍的事):
            # 再把比例整体缩放到 Σt·k = Σt ⇒ 记忆成熟度不会把整圈撑长 (550C 曾因此 294 vs 550A 302)
            _tot = sum(float(s.get("t") or 0.0) for s in segs) or 1.0
            _totk = sum(float(s.get("t") or 0.0) * float((kl2.get(str(s.get("kind"))) or {}).get("k") or 1.0)
                        for s in segs) or 1.0
            _r = _tot / _totk
            for k, v in list(kl2.items()):
                v = dict(v or {})
                v["k"] = round(max(0.85, min(1.25, float(v.get("k") or 1.0) * _r)), 4)
                kl2[k] = v
        t_eff = []
        gated = _gate_rows(len(segs))
        n_gate = 0
        for i, s in enumerate(segs):
            t0 = float(s.get("t") or 0.0)
            kk = float((kl2.get(str(s.get("kind"))) or {}).get("k") or 1.0)
            te = t0 * kk
            a, b = s.get("a") or [0, 0, 0], s.get("b") or [0, 0, 0]
            dist = sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)) ** 0.5
            if dist > 1e-6:
                te = max(te, dist / v_cap)          # 限速兜底 (速度 ≤ v_cap)
            if _TRAVEL_ON and gaps[i] > 0.0:
                te += gaps[i] / max(v_travel, 1.0)  # 跨件过渡时间 (连续化的物理预算)
            # 🧱 运动学通道 + 动力学 + 拐角限速 (老倪 2026-11-01「要接上」)
            if gated is not None and i < len(gated):
                tg = float(gated[i].get("t") or 0.0)
                if tg > te:
                    te = tg
                    n_gate += 1
            t_eff.append(max(1e-3, te))
        _MEM_S["gate"] = {"on": gated is not None, "src": _GATE.get("src"),
                          "n_stretched": n_gate, "n_seg": len(segs)}
        _MEM_S["gap_mm"] = gaps
        _MEM_S["travel_s"] = round(sum(g / max(v_travel, 1.0) for g in gaps), 3)
        _MEM_S.update(ok=True, kl2=kl2, l4=l4, t_eff=t_eff, cum2=None)
        _MEM_S["scale"] = 1.0
        _MEM_S["l3"] = dict((f or {}).get("l3") or {})
    except Exception as e:                                                   # noqa: BLE001
        _MEM_S.update(ok=False, err="%s: %s" % (type(e).__name__, e))
        _MEM_S["t_eff"] = [float(s.get("t") or 0.0) for s in segs]


def _t_axis(segs, n_mods):
    """时间轴: 段表 t (或 L2 修正后的 t_eff) → 累计; 整圈归一 to tact 目标"""
    t = _MEM_S.get("t_eff") or [float(s.get("t") or 0.0) for s in segs]
    cum, acc = [], 0.0
    for x in t:
        acc += float(x)
        cum.append(acc)
    _MEM_S["cum2"] = cum
    # 整圈 wall 目标 = tact × 件数; el 用 scale 缩放 ⇒ 实际件节拍 = 目标
    tt = _TACT_TARGET * max(1, int(n_mods or 1))
    # 🔴 只有 acc < 目标节拍 时才放慢 (scale<1); acc 已超目标 ⇒ scale=1 跑物理下限,
    #    绝不为凑 300UPH 把 el 拉快 (那会让每段速度超过 v_cap = 假节拍)
    _MEM_S["scale"] = max(0.05, min(1.0, acc / max(tt, 0.1))) if acc > 0 else 1.0
    _MEM_S["acc_s"] = round(acc, 3)
    return cum

_S = {"segs": None, "cum": None, "i": 0, "t0": None, "round": 0,
      "mtime": (0.0, 0.0), "tact": 12.0, "uph_target": 300, "n_mods": 0,
      "mod_cum": None, "task_id": "TASK-07-AOI", "verified": False, "n_mt": 0}
LAST_STATUS = ""


def _self_plan():
    """🆕 段表由 **本节点自己算** (L2 Plan 节点真执行)。磁盘 sim_insert.json 只作对拍基准与回退。

    · 自算成功且与磁盘表逐段一致 (段数/kind/t/端点 ≤0.01mm) ⇒ 用自算的 (真执行);
    · 自算失败 / 不一致 ⇒ **回退**用磁盘表, 并把差异写进 LAST_STATUS (老实说回退过);
    · 两边都拿不到 ⇒ (None, None) 让调用方拒跑。
    """
    global LAST_STATUS
    disk = None
    if os.path.isfile(_PLAN):
        try:
            disk = json.load(open(_PLAN, encoding="utf-8"))
        except Exception as e:                                               # noqa: BLE001
            LAST_STATUS = "磁盘段表读不出: %s: %s" % (type(e).__name__, e)
    if os.environ.get("ZMAX_PLAN_SELF", "1") != "1":
        return disk, "disk(自算关闭)"
    try:
        from . import cycle_plan as _CP                                       # noqa: PLC0415
        out = _CP.build()
    except Exception as e:                                                    # noqa: BLE001
        LAST_STATUS = "节点自算失败 (%s: %s) ⇒ 回退磁盘段表" % (type(e).__name__, e)
        return disk, "disk(自算失败)"
    if disk is None:
        return out, "self"
    if disk.get("cfg_sha") != out.get("cfg_sha"):
        LAST_STATUS = ("段表 = 节点自算 %d 段 (磁盘表来自旧配置 %s ≠ 当前 %s ⇒ 以自算为准)"
                       % (len(out.get("plan") or []), disk.get("cfg_sha"), out.get("cfg_sha")))
        return out, "self(配置已变)"
    a, b = out.get("plan") or [], disk.get("plan") or []
    if len(a) != len(b):
        LAST_STATUS = "自算 %d 段 ≠ 磁盘 %d 段 ⇒ 回退磁盘段表" % (len(a), len(b))
        return disk, "disk(段数不一致)"
    worst, bad_i = 0.0, -1
    for i, (x, y) in enumerate(zip(a, b)):
        if (x.get("kind"), round(float(x.get("t") or 0), 4)) != (y.get("kind"), round(float(y.get("t") or 0), 4)):
            bad_i = i
            break
        for j in range(min(len(x.get("a") or []), len(y.get("a") or []))):
            worst = max(worst, abs(float(x["a"][j]) - float(y["a"][j])), abs(float(x["b"][j]) - float(y["b"][j])))
    if bad_i >= 0 or worst > 0.01:
        LAST_STATUS = ("自算与磁盘段表不一致 (第 %d 段 kind/t 异 · 端点最大差 %.2fmm) ⇒ 回退磁盘段表"
                       % (bad_i, worst))
        return disk, "disk(不一致)"
    LAST_STATUS = "段表 = 节点自算 %d 段 (与磁盘表逐段一致 · 端点差 ≤%.3fmm)" % (len(a), worst)
    return out, "self"


def _load():
    """元任务组合 + 段几何 → 逐段带元任务归属的段序列 (双向校验)"""
    global LAST_STATUS
    try:
        m1 = os.path.getmtime(_META)
        m2 = os.path.getmtime(_PLAN)
    except OSError as e:
        LAST_STATUS = "配置/段表不可读 (%s)" % e
        return None, None
    try:
        _mcp0 = os.path.getmtime(os.path.join(_ROOT, "config", "points", "cell_points.json"))
    except OSError:
        _mcp0 = 0.0
    if _S["segs"] is not None and (m1, m2, _mcp0) == _S["mtime"]:
        return _S["segs"], _S["cum"]

    # 🔴 新鲜度闸: 只有**回退用磁盘表**时才需要 (自算每次 build() 直接吃最新配置, 不需要闸)
    meta = json.load(open(_META, encoding="utf-8"))
    seg_doc, _src = _self_plan()
    if seg_doc is None:
        LAST_STATUS = LAST_STATUS or "段表取不到 (自算+磁盘都失败)"
        return None, None
    _S["plan_src"] = _src
    if str(_src).startswith("disk"):
        _cp = os.path.join(_ROOT, "config", "points", "cell_points.json")
        try:
            if os.path.getmtime(_cp) > m2 + 1.0:
                LAST_STATUS = ("回退用磁盘段表, 但点位配置比它新 (%s) ⇒ 拒跑, 先跑 "
                               "./gui-venv311/bin/python tools/sim_insert_plan.py" % os.path.basename(_cp))
                _S["verified"] = False
                return None, None
        except OSError:
            pass
    plan = seg_doc.get("plan") or []
    rounds = (meta.get("long_horizon") or {}).get("rounds") or []
    mt_lib = {m["id"]: m for m in (meta.get("meta_tasks") or [])}
    if not rounds or not plan:
        LAST_STATUS = "元任务配置为空 (rounds=%d plan=%d)" % (len(rounds), len(plan))
        return None, None

    # 按 rounds 的批次顺序展开: 每批按 meta_seq 的段数切段表
    order = []
    for r in rounds:
        for _ in range(int(r.get("count") or 0)):
            order.append(list(r.get("meta_seq") or []))
    segs, idx, mt_i, batch = [], 0, 0, 0
    for seq in order:
        batch += 1
        for mid in seq:
            ln = int((mt_lib.get(mid) or {}).get("segments") or 0)
            chunk = plan[idx:idx + ln]
            if len(chunk) != ln:
                LAST_STATUS = "展开越界: 段表只剩 %d 段, 元任务 %s 需要 %d" % (len(plan) - idx, mid, ln)
                return None, None
            for s in chunk:
                d = dict(s)
                d["mt_id"] = mid
                d["mt_name"] = (mt_lib.get(mid) or {}).get("name", mid)
                d["mt_i"] = mt_i + 1
                d["batch"] = batch
                segs.append(d)
            idx += ln
            mt_i += 1

    # 双向校验: 展开段数必须等于段表, 且逐段 kind/label/t 一致 (顺序不能错)
    bad = [i for i, (a, b) in enumerate(zip(plan, segs))
           if (a.get("kind"), a.get("label"), a.get("t")) != (b.get("kind"), b.get("label"), b.get("t"))]
    if idx != len(plan) or bad:
        LAST_STATUS = ("展开与段表不一致 (展开 %d 段 / 段表 %d 段%s)"
                       % (idx, len(plan), "" if not bad else ", 首个差异第 %d 段" % bad[0]))
        _S["verified"] = False
        return None, None

    cum, acc = [], 0.0
    for s in segs:
        acc += float(s.get("t") or 0.0)
        cum.append(acc)
    cyc = seg_doc.get("cycles_data") or []
    mod_cum, macc = [], 0.0
    tact = float(seg_doc.get("tact_steady_s") or 12.0)
    for c in cyc:
        macc += float(c.get("t_work") or tact)
        mod_cum.append(macc)

    try:
        _mcp = os.path.getmtime(os.path.join(_ROOT, "config", "points", "cell_points.json"))
    except OSError:
        _mcp = 0.0
    _S.update(segs=segs, cum=cum, i=0, t0=None, mtime=(m1, m2, _mcp), tact=tact,
              uph_target=int(seg_doc.get("uph_target") or 300), n_mods=len(cyc),
              mod_cum=mod_cum, task_id=meta.get("task_id") or "TASK-07-AOI",
              verified=bool(meta.get("verified")), n_mt=mt_i)
    # 🧠 记忆层接入: L2 实测比例 + L4 限速 → t_eff; 整圈归一 to 300UPH 目标节拍
    _mem_timing(segs)
    _S["cum_eff"] = _t_axis(segs, len(cyc))
    _MEM_S.update(prev_b=None, seg_t_switch=None, n_jump=0, jump_mm=[], big_jump_mm=[])
    _k0 = " · 记忆 L2 k=%s · L4 v_cap=%.0f" % (
        {k: round(float((v or {}).get("k") or 1.0), 3) for k, v in (_MEM_S.get("kl2") or {}).items()},
        float(_MEM_S.get("l4", {}).get("v_cap_mm_s") or 0.0)) if _MEM_S.get("ok") else " · 记忆未接(标称)"
    LAST_STATUS = ("元任务配置已展开: %d 元任务 / %d 段 (与段表逐段一致)%s"
                   % (mt_i, len(segs), _k0))
    return segs, cum


def reset():
    _S.update(i=0, t0=None)


# 🧱 2026-11-01 老倪「按你的建议执行」: 八道技能 clamp 里**每拍**那一半 (单拍位移/限速)
#   原来只在执行侧 dispatch→skill_phys 跑, AR 链只有「一圈一次」的段时长闸 (慢变化)。
#   这里把每拍闸接进 plan 的发布路径: 发布前按本段 v_cap 限住 u 的增量 ⇒ 页面上真的被技能约束管住。
_CLAMP = {"t": 0.0, "u": 0.0, "seq": None, "u_nom": 0.0, "clip": 0, "n": 0, "v_cap": 0.0,
          "L": 0.0, "v_nom": 0.0, "lag": 0.0}
# 🧱 动力学二阶限幅 (a/jerk) 开关 + 状态: 关 ZMAX_PLAN_DYN=0 回到只限速的老口径
_DYN_ON = os.environ.get("ZMAX_PLAN_DYN", "1") == "1"
_DYN = {"v": 0.0, "aa": 0.0, "seq": None, "clip_a": 0, "clip_j": 0, "n": 0}
_SK_CODE = {}


def _skill_code(stage):
    """stage → 技能码 (SK01..SK08), 取自 zmax_skill_physics.json 的 skills 表。"""
    if not _SK_CODE:
        try:
            with open(os.path.join(_ROOT, "config", "calib", "zmax_skill_physics.json"),
                      encoding="utf-8") as fh:
                for it in (json.load(fh).get("skills") or []):
                    if isinstance(it, dict) and it.get("stage"):
                        _SK_CODE[str(it["stage"])] = it.get("code")
        except Exception:                                          # noqa: BLE001
            pass
    return _SK_CODE.get(str(stage or ""), None)


def _skill_clamp(u, o1, a_pub=None):
    """按当前段 gate 的 v_cap / a_cap / j_cap 逐拍限速限加加速度, 返回允许发布的 u。

    · v_cap: 单拍位移 ≤ v_cap·dt (老口径, 保留)
    · a_cap / j_cap: 2026-11-01 老倪「动力学约束有效么」—— 之前这两个只在 plan_gate_corridor
      里定**段时长**, 发布信号本身是线性/S 曲线插值 ⇒ 段首 0→v_cap 一步到位, 实测 a 峰 6.4×、
      jerk 峰 4~5× 上限。这里改成对**发布信号**本身做二阶限幅 (v→a→jerk)，关闸 ZMAX_PLAN_DYN=0。
    单调向前, 换段/超时重锚。
    """
    g = _gate_info(_S.get("i")) or {}
    v_cap = float(g.get("v_cap") or 0.0) / 1000.0            # mm/s → m/s
    a_cap = float(g.get("a_cap") or 0.0) / 1000.0            # mm/s² → m/s²
    j_cap = float(g.get("j_cap") or 0.0) / 1000.0            # mm/s³ → m/s³
    a = a_pub if isinstance(a_pub, (list, tuple)) and len(a_pub) == 3 else (o1.get("a") or [])
    b = o1.get("b") or []
    if v_cap <= 0.0 or len(a) != 3 or len(b) != 3:
        return u
    try:
        L = math.dist([float(x) for x in a], [float(x) for x in b])
    except Exception:                                              # noqa: BLE001
        return u
    if L <= 1e-6:
        return u
    now = time.time()
    seq = o1.get("seq")
    dt = now - float(_CLAMP["t"] or now)
    _CLAMP["n"] += 1
    _CLAMP["v_cap"], _CLAMP["L"] = v_cap * 1000.0, L
    if 0.0 < dt < 0.01:
        # 同一拍内重复调用 (发布路径+预览路径挨着来): 不重锚, 也**不能原样放行** ——
        # 放行会让这一笔绕开限速 (实测一次就冲出去 3.4 倍上限)。冻结在上次发布的 u。
        return float(_CLAMP["u"])
    if seq != _CLAMP["seq"] or dt <= 0.0 or dt > 0.5:
        _CLAMP.update({"t": now, "u": u, "seq": seq})
        _DYN.update(seq=seq, v=0.0, aa=0.0)
        return u
    # ① 速度: 名义速度 (m/s)
    v_nom = (u - float(_CLAMP["u"])) * L / 1000.0 / max(dt, 1e-6)
    v_new = min(v_nom, v_cap)
    _CLAMP["v_nom"] = round(v_nom, 4)
    if _DYN_ON and L > 1.0:
        v_prev, a_prev = (float(_DYN["v"]), float(_DYN["aa"])) if _DYN["seq"] == seq else (0.0, 0.0)
        # ② 加速度: |Δv| ≤ a_cap·dt (起步从 0 爬, 不许一步到巡航)
        if a_cap > 0.0:
            v_new = max(v_prev - a_cap * dt, min(v_prev + a_cap * dt, v_new))
        a_new = (v_new - v_prev) / max(dt, 1e-6)
        # ③ 加加速度: |Δa| ≤ j_cap·dt ⇒ 加速度本身也要爬, 再回代速度
        if j_cap > 0.0:
            a_new = max(a_prev - j_cap * dt, min(a_prev + j_cap * dt, a_new))
            v_new = v_prev + a_new * dt
            _DYN["clip_j"] += int(abs(a_new) < abs((v_new - v_prev) / max(dt, 1e-6)) - 1e-9)
        if a_cap > 0.0 and abs(a_new) > a_cap + 1e-9:
            _DYN["clip_a"] += 1
        v_new = max(0.0, min(v_cap, v_new))
        _DYN.update(seq=seq, v=v_new, aa=a_new, n=_DYN.get("n", 0) + 1)
    u_max = float(_CLAMP["u"]) + (v_new * dt * 1000.0) / L
    if u > u_max + 1e-9:
        _CLAMP["clip"] += 1
        _CLAMP["u_nom"] = round(u, 4)
        u = max(float(_CLAMP["u"]), min(1.0, u_max))
        _CLAMP["lag"] = round(float(u_max) - float(u), 5)        # 被动力闸拖住的量 (给 hold 用)
    _CLAMP.update({"t": now, "u": u})
    return u


def _pub_ar(o1, u_ratio, seg_t, el, a_eff=None, sm=False, mem=None):
    if not _AR_PUB:
        return
    # 唯一写者闸 (2026-11-01): 与 uph_tact_impl 抢写同一 ar_cmd.json 会让手臂来回跳
    if os.environ.get("ZMAX_AR_OWNER", "plan") != "plan":
        return
    # 🔴 2026-10-29 老倪「走了几成是什么」: 原写法直接把 `el - seg_t0`(本段已过**秒数**)
    #   当 0~1 比例透出去, 只是被 min/max 砍到 [0,1] —— 段时长中位数 0.3s, 页面按
    #   `a+(b-a)*u` 拿到 0.15 就画 15%, 实际已走一半 ⇒ 虚拟臂每段只走 30% 就跳下一段,
    #   看着一顿一顿。这里补归一化, 与 uph_tact_impl._pub_ar 同口径。
    # 🧠 2026-10-30 L4 安全记忆: 段内按五次 S 曲线给 u (首末速 0 ⇒ 速度钟形, 无阶跃)
    u = (u_ratio if u_ratio is not None else 1.0)
    u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
    if sm:
        u = _smooth(u)
    # 🧠 L4 段间连续: 上一段终点 ≠ 本段起点时, 起点改用当前实际位置 (a_raw 保真, 页面按 a_raw 认段)
    a_pub = list(o1.get("a") or [])
    a_raw = None
    if a_eff is not None:
        a_raw = list(o1.get("a") or [])
        a_pub = list(a_eff)
    b_pub = list(o1.get("b") or [])
    # 🧱 每拍技能约束 (单拍位移 ≤ v_cap·dt + a/jerk 升降幅) — 发布前收口。
    #   🔴 必须用**发布出去的起点** (a_eff 混合后) 算段长: 用原始 a 会把实际行程算短,
    #   实测 blend 段 L_eff/L_raw≈1.4 ⇒ 真实速度超上限 40% (v 951 vs cap 724mm/s)。
    _u_nom = u
    try:
        u = _skill_clamp(u, o1, a_pub)
    except Exception:                                              # noqa: BLE001
        pass
    # 🧱 几何通道 (真有效): 段端点夹进技能通道 (每段一次) + 每拍发布点核在内 (关闸/无通道 ⇒ 原样)
    _cor_info = None
    try:
        _fit = _cor_fit(o1)
        if _fit:
            _a_fit, _b_fit, _seg, _corr = _fit
            if a_eff is not None:                       # 实际起点也必须在管内
                _a_fit = _corridor_mod().clamp_into(_corr, a_pub)[0]
            a_pub, b_pub = list(_a_fit), list(_b_fit)
            u, _u_tick = _cor_pub(o1, _corr, a_pub, b_pub, u)
            _cor_info = dict(_seg)
            if _u_tick:
                _cor_info["tick"] = _u_tick
            _cor_info["u_pub"] = round(float(u), 4)
    except Exception:                                              # noqa: BLE001
        _cor_info = None
    try:
        d = {"t": time.time(), "t_str": time.strftime("%H:%M:%S"), "src": "ss_plan_long",
             "task_id": o1.get("task_id"), "seq": o1.get("seq"), "mod": o1.get("mod"),
             "kind": o1.get("kind"), "label": o1.get("label"), "a": a_pub, "b": b_pub,
             "u": round(u, 4), "t_seg": seg_t, "t_left": o1.get("t_left"),
             "elapsed_s": round(el, 2), "mt_id": o1.get("mt_id"), "mt_name": o1.get("mt_name"),
             "mt_i": o1.get("mt_i"), "mt_n": o1.get("mt_n"), "batch": o1.get("batch"),
             # 🔴 2026-10-29: 视觉观测点同拍带给页面/执行器 (接口对齐; 误差/gaps 原样透出, 不美化)
             "vision": o1.get("vision")}
        _b_org = o1.get("b")
        if isinstance(_b_org, (list, tuple)) and len(_b_org) == 3 and \
                any(abs(float(_b_org[i]) - float(b_pub[i])) > 1e-6 for i in range(3)):
            d["b_raw"] = list(_b_org)       # 被通道夹回来的原始目标 (取证用, 不覆盖)
        if a_raw is not None:
            d["a_raw"] = a_raw
        if mem:
            d["mem"] = mem
        if _cor_info and "gate" not in d:
            d["cor"] = _cor_info          # 无闸后表时也要能看到通道取证
        # 🧱 本段的闸参数 (通道半径/限速/加速度/加加速度/受限原因) —— 页面与执行器同一口径
        _g = _gate_info(_S.get("i"))
        if _g:
            d["gate"] = {"stage": _g.get("stage"), "r_mm": _g.get("r_mm"),
                         "v_cap": _g.get("v_cap"), "a_cap": _g.get("a_cap"),
                         "j_cap": _g.get("j_cap"), "bound_by": _g.get("bound_by"),
                         "t_gate": round(float(_g.get("t") or 0.0), 4),
                         "t_in": round(float(_g.get("t_in") or 0.0), 4)}
            d["cor_r_mm"] = _g.get("r_mm")
            # 🧱 几何通道取证: 技能码 / 半径 / 段端点偏差 / 是否被夹回 / 每拍偏差与削次数
            if _cor_info:
                d["gate"]["cor"] = _cor_info
                d["gate"]["cor"]["src"] = _COR.get("src")
            # 每拍技能闸取证: 技能码 / 限速 / 段长 / 已削次数 / 本拍名义 vs 实发
            try:
                d["gate"]["skill"] = {
                    "code": _skill_code(_g.get("stage")), "v_cap": _CLAMP["v_cap"],
                    "L_mm": round(float(_CLAMP["L"]), 1), "clip": int(_CLAMP["clip"]),
                    "n": int(_CLAMP["n"]), "u_nom": round(float(_u_nom), 4),
                    "u_pub": round(float(u), 4),
                    "cut": bool(abs(float(_u_nom) - float(u)) > 1e-6),
                    # 🧱 动力学: 本拍发出的速度/加速度 (m/s, m/s²) + 累计被 a/jerk 削的次数
                    "dyn": {"on": _DYN_ON, "v": round(float(_DYN["v"]), 4),
                            "a": round(float(_DYN["aa"]), 3), "v_nom": _CLAMP.get("v_nom"),
                            "a_cap": _g.get("a_cap"), "j_cap": _g.get("j_cap"),
                            "clip_a": int(_DYN["clip_a"]), "clip_j": int(_DYN["clip_j"])}}
            except Exception:                                      # noqa: BLE001
                pass
        os.makedirs(os.path.dirname(_AR_CMD), exist_ok=True)
        tmp = _AR_CMD + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        os.replace(tmp, _AR_CMD)
    except Exception:                                              # noqa: BLE001
        pass


def run(ctx=None):
    global LAST_STATUS
    # 🔴 2026-10-29 老倪: 「L2 节点输出必须能被 plan 接管, 接口必须对齐, 可以带误差」——
    #   in2 ← 🎯 YOLO 目标检测 (ssyolo.out1, 画布闭环反馈线)。本节点把它**原样透传**到 out1/out3.vision,
    #   不因 verified=false / conf 低就丢字段: 谁要用谁自己判(下游/页面能看到 gaps 与 conf)。
    _visv = ((ctx or {}).get("in2") or {}).get("value")
    _vis = None
    if isinstance(_visv, dict):
        _pts = _visv.get("points") if isinstance(_visv.get("points"), dict) else {}
        _confs = [p.get("conf") for p in _pts.values() if isinstance(p, dict) and p.get("conf") is not None]
        _vis = {
            "frame": _visv.get("frame"),
            "verified": bool(_visv.get("verified")),
            "n_points": len(_pts),
            "conf_max": (round(max(_confs), 3) if _confs else None),
            "gaps": list(_visv.get("gaps") or (_visv.get("source") or {}).get("gaps") or []),
            "src_kind": _visv.get("src_kind"),
            "age_s": (round(max(0.0, time.time() - float(_visv["t"])), 3) if _visv.get("t") else None),
            "cached_ago_s": _visv.get("cached_ago_s"),
            "points": {k: {"pos_mm": v.get("pos_mm"), "conf": v.get("conf")}
                       for k, v in _pts.items() if isinstance(v, dict)},
        }
    # 🔴 2026-10-31 老倪: 「技能节点的信号必须传入 plan 节点」——
    #   in3 = 🛠 L3 技能序列编排 · in4..in11 = ①..⑧ 原子技能 (sssk1..8) 的动作/物理结果。
    #   口径: **只收下 + 原样透传到 out1/out3.skills, 不参与控制** (当前段表仍由元任务组合驱动);
    #   以后标定好了直接把这批信号当目标用, 不需要重接线。
    #   环境开关 ZMAX_PLAN_USE_SKILL=1 才让 plan 真按技能动作走 (默认关 ⇒ 现有行为一字不变)。
    _skills = {}
    for _pk, _pn in (("in4", "①接近"), ("in5", "②对位"), ("in6", "③下降"), ("in7", "④抓取"),
                     ("in8", "⑤抬起"), ("in9", "⑥转移"), ("in10", "⑦插入"), ("in11", "⑧完成")):
        _d = (((ctx or {}).get(_pk) or {}).get("value"))
        if not isinstance(_d, dict):
            continue
        _skills[_pn] = {
            "stage": _d.get("stage"), "active": _d.get("active"),
            "u": _d.get("u"), "v_req": _d.get("v_req"),
            "err_norm": _d.get("err_norm"), "why": _d.get("why"),
            "f_need_N": _d.get("f_need_N"), "over_travel": _d.get("over_travel"),
        }
    _seq = (((ctx or {}).get("in3") or {}).get("value"))
    _skill_use = (os.environ.get("ZMAX_PLAN_USE_SKILL", "0") == "1")
    _skill_blk = {"n_in": len(_skills), "from": "sssk1..sssk8.out2 + ssskill.out1",
                  "used_for_control": bool(_skill_use), "skills": _skills,
                  "seq_type": (type(_seq).__name__ if _seq is not None else None)}

    segs, cum = _load()
    if not segs:
        return {"out1": {"skills": _skill_blk}, "out2": None, "out3": {"vision": _vis, "skills": _skill_blk}}

    now = time.monotonic()
    if _S["t0"] is None:
        _S["t0"] = now
        _MEM_S["cyc0"] = now
    cum_t = _S.get("cum_eff") or cum
    mem_on = bool(_MEM_S.get("ok"))
    scale = float(_MEM_S.get("scale") or 1.0) if mem_on else 1.0
    # 🧠 L3 流程工艺记忆: 整圈时间归一 (scale) ⇒ 件节拍 = tact 目标 (300UPH ≤12.0s)
    el = (now - _S["t0"]) * _SPEED * scale
    while _S["i"] < len(segs) and el >= cum_t[_S["i"]]:
        _S["i"] += 1
    if _S["i"] >= len(segs):                       # 一轮走完 → 循环(流水线不停)
        # ── 🧠 L3 流程工艺记忆: 这一圈的真实墙钟节拍入库 (下一圈按它校正) ──
        wall = now - float(_MEM_S.get("cyc0") or now)
        n_mods = int(_S["n_mods"] or 1)
        tact_live = wall / max(n_mods, 1)
        _mf_obj = _mf()
        jm = _MEM_S.get("jump_mm") or []
        bj = _MEM_S.get("big_jump_mm") or []
        if _mf_obj is not None:
            try:
                _mf_obj.record_cycle({
                    "t": time.strftime("%Y-%m-%d %H:%M:%S"), "round": int(_S["round"]) + 1,
                    "task_id": _S["task_id"], "wall_s": round(wall, 2), "n_mods": n_mods,
                    "tact_s": round(tact_live, 3), "uph": round(3600.0 / max(tact_live, 1e-3), 1),
                    "uph_target": _S["uph_target"], "tact_target": _TACT_TARGET,
                    "segs": len(segs), "scale": round(scale, 4),
                    "acc_s": _MEM_S.get("acc_s"), "travel_s": _MEM_S.get("travel_s"),
                    "travel_jumps": sum(1 for g in (_MEM_S.get("gap_mm") or []) if (g or 0) > 0),
                    "kl2": {k: round(float((v or {}).get("k") or 1.0), 3)
                            for k, v in (_MEM_S.get("kl2") or {}).items()},
                    "jumps": len(jm), "jump_max_mm": (round(max(jm), 1) if jm else 0.0),
                    "big_jumps": len(bj), "big_jump_max_mm": (round(max(bj), 1) if bj else 0.0),
                    # 判据对 300UPH 口径 (tact ≤ 3600/uph_target), 不对内部目标 _TACT_TARGET 判:
                    #   travel 补时间后物理下限就是 11.98s/件 (300.5UPH), 拿 11.7 判会永远 False
                    "ok": tact_live <= (3600.0 / max(int(_S["uph_target"] or 300), 1)) + 1e-6,
                    "src": "ss_plan_long.run (真实圈墙钟, 非名义)"})
                if jm and max(jm) > 1.0:      # 🧠 L4 安全记忆: 已兜住的小缝硬跳
                    _mf_obj.record_violation(
                        "jump", max(jm), cap=float((_MEM_S.get("l4") or {}).get("dv_cap_mm_s") or 0),
                        note="段间小缝硬跳 → 已用 a:=上一段终点 连续化")
                if bj:                          # 大跳只记账 (不插值, 交给段表换位语义)
                    _mf_obj.record_violation(
                        "jump", max(bj), cap=float((_MEM_S.get("l4") or {}).get("dv_cap_mm_s") or 0),
                        note="段间大跳(换位) → 不连续化, 记录供 L4 学习上限")
            except Exception:                                              # noqa: BLE001
                pass
        _S["i"] = 0
        _S["t0"] = now
        _S["round"] += 1
        el = 0.0
        # 🧠 L2 肌肉记忆: 上一圈已固化新样本 ⇒ 重算标杆比例/时间轴 (下一圈按固化后的标杆跑)
        try:
            _mem_timing(segs)
            _S["cum_eff"] = _t_axis(segs, n_mods)
            cum_t = _S.get("cum_eff") or cum
            scale = float(_MEM_S.get("scale") or 1.0) if _MEM_S.get("ok") else 1.0
            mem_on = bool(_MEM_S.get("ok"))
        except Exception:                                                  # noqa: BLE001
            pass
        _MEM_S.update(cyc0=now, jump_mm=[], big_jump_mm=[], seg_t_switch=None, i_seg=None, prev_b=None)

    seg = segs[_S["i"]]
    i_now = _S["i"]
    seg_t = float(seg.get("t") or 0.0)
    te = float(cum_t[i_now] - (cum_t[i_now - 1] if i_now > 0 else 0.0)) or seg_t
    seg_t0 = cum_t[i_now] - te
    left = max(0.0, cum_t[i_now] - el)
    # ── 🧠 L2 肌肉记忆: 段切换 ⇒ 上一段的**真实墙钟时长**入固化库 (换算回段表时间基) ──
    if _MEM_S.get("i_seg") != i_now:
        prev_i = _MEM_S.get("i_seg")
        t_sw = _MEM_S.get("seg_t_switch")
        if prev_i is not None and 0 <= prev_i < len(segs) and t_sw:
            _mf_obj = _mf()
            if _mf_obj is not None:
                ps = segs[prev_i]
                try:
                    _mf_obj.record_segment(
                        ps.get("kind"), (now - t_sw) * _SPEED * scale,
                        float(ps.get("t") or 0.0), label=str(ps.get("label") or ""),
                        flush=True)
                except Exception:                                          # noqa: BLE001
                    pass
        _MEM_S["i_seg"] = i_now
        _MEM_S["seg_t_switch"] = now
        # ── 🧠 L4 安全记忆: 段间连续 —— 起点改成上一段终点 (差 > continuity_mm 才算硬跳) ──
        prev_b = _MEM_S.get("prev_b")
        a_blend, dj = None, 0.0
        if prev_b and seg.get("a"):
            dj = sum((float(x) - float(y)) ** 2 for x, y in zip(prev_b, seg["a"])) ** 0.5
            _l4 = _MEM_S.get("l4") or {}
            _vcap = float(_l4.get("v_cap_mm_s") or 700.0)
            _gaps = _MEM_S.get("gap_mm") or []
            _budgeted = bool(_TRAVEL_ON and i_now < len(_gaps) and (_gaps[i_now] or 0) > 0)
            if dj > float(_l4.get("continuity_mm") or 1.0):
                if _budgeted or (dj <= _BLEND_MAX_MM and (dj / max(te, 1e-3)) <= _vcap):
                    a_blend = list(prev_b)                       # 小缝: 连续化 (不超速)
                    _MEM_S.setdefault("jump_mm", []).append(dj)
                else:
                    # 大跳 = 段表本来就要换位 ⇒ 不插值 (否则 905mm/0.4s = 2260mm/s 超速扫掠)
                    _MEM_S.setdefault("big_jump_mm", []).append(dj)
        _MEM_S["a_blend"] = a_blend
        _MEM_S["blend_mm"] = round(dj, 1)
    a_blend = _MEM_S.get("a_blend")
    if seg.get("b"):
        _MEM_S["prev_b"] = list(seg["b"])
    done = 0
    for th in (_S["mod_cum"] or []):
        if el >= th:
            done += 1
        else:
            break
    cur_mod = min(done + 1, _S["n_mods"] or done)
    uph = (done / el * 3600.0) if (el >= max(30.0, 3.0 * _S["tact"]) and done >= 2) else None

    o1 = {"task_id": _S["task_id"], "seq": seg.get("seq"), "kind": seg.get("kind"),
          "label": seg.get("label"), "a": seg.get("a"), "b": seg.get("b"), "t": seg_t,
          # 🔴 2026-10-29: 段内累计时间也进 out1 —— 执行器(ssact)转发给页面时, 页面要用它
          #   区分"同一段动作在第几件"(14 件里 a/b 端点会撞), 缺了会取错件的手里/孔状态。
          "elapsed_s": round(el, 2),
          "t_in_seg": round(el - seg_t0, 3), "t_left": round(left, 3),
          "mod": cur_mod, "hole": seg.get("hole"),
          "mt_id": seg.get("mt_id"), "mt_name": seg.get("mt_name"),
          "mt_i": seg.get("mt_i"), "mt_n": _S["n_mt"], "batch": seg.get("batch")}
    LAST_STATUS = ("元任务 %s %s (%d/%d) · 第%s段 %s"
                   % (seg.get("mt_id"), seg.get("mt_name"), seg.get("mt_i"), _S["n_mt"],
                      seg.get("seq"), seg.get("kind")))
    _vis_use = _vis          # 段 + 同拍视觉状态一起给执行器/页面 (接口对齐, 误差如实带)
    o1["vision"] = _vis_use
    o1["skills"] = _skill_blk
    # 🔴 2026-10-29 可选开关: 让 plan 真**用**视觉点 (默认关 ⇒ 300UPH 的配置槽位路径一字不变)
    #   开启后 out1 带 goal/goal_src/goal_conf/goal_frame, 下游可直接拿视觉点当目标;
    #   允许 verified=false / conf 低 —— 误差如实带出去, 由消费方按自己的闸判定。
    if os.environ.get("ZMAX_PLAN_USE_VISION", "0") == "1" and _vis and _vis.get("n_points"):
        _pv = (_vis.get("points") or {}).get("光模块·当前") or {}
        if _pv.get("pos_mm"):
            o1["goal"] = [round(float(x), 2) for x in _pv["pos_mm"]]
            o1["goal_src"] = "vision_points:光模块·当前"
            o1["goal_conf"] = _pv.get("conf")
            o1["goal_frame"] = _vis.get("frame")
    # 🧠 记忆层取证块: 每拍随 ar_cmd 发出 (L2 标杆比例 / L3 节拍 / L4 安全包络 + 本段生效值)
    mem_block = None
    if mem_on:
        try:
            _l4 = _MEM_S.get("l4") or {}
            _last = (_mf().last_cycle() if _mf() is not None else {}) or {}
            mem_block = {
                "ok": True,
                "l2": {"src": "data/memory/ar_muscle.json",
                       "kl2": {k: round(float((v or {}).get("k") or 1.0), 3)
                               for k, v in (_MEM_S.get("kl2") or {}).items()},
                       "kind_n": {k: int((v or {}).get("n") or 0) for k, v in (_MEM_S.get("kl2") or {}).items()}},
                "l3": {"src": "data/memory/ar_cycles.jsonl",
                       "scale": round(scale, 4), "tact_target": _TACT_TARGET,
                       "tact_last": _last.get("tact_s"), "uph_last": _last.get("uph"),
                       "cycle_ok": _last.get("ok"), "n_cycles": _last.get("round")},
                "l4": {"src": "data/memory/ar_safety.json",
                       "v_cap_mm_s": float(_l4.get("v_cap_mm_s") or 0),
                       "dv_cap_mm_s": float(_l4.get("dv_cap_mm_s") or 0),
                       "smooth": int(_l4.get("smooth") or 0),
                       "jumps_this_cycle": len(_MEM_S.get("jump_mm") or [])},
                "seg_t_raw": round(seg_t, 3), "seg_t_eff": round(te, 3),
                "acc_s": _MEM_S.get("acc_s"), "travel_s": _MEM_S.get("travel_s"),
                "blend_mm": float(_MEM_S.get("blend_mm") or 0.0),
                "u_ratio": round(max(0.0, min(1.0, (el - seg_t0) / max(te, 1e-9))), 4),
            }
        except Exception:                                                  # noqa: BLE001
            mem_block = {"ok": False, "err": _MEM_S.get("err")}
    # 🧱 剖面口径 (2026-11-01 动力学实测): 闸是**连续梯形**剖面 (v_lim ≤ v_cap, 段间不停) 定时间,
    #   但发布用的是**每段启停的五次 S 曲线** (峰值 1.875×平均) ⇒ 实测 v 峰 1.8×、a 1.5×、jerk 4~5× 超限。
    #   默认 linear (与闸同一剖面: 恒速 = L/T ≤ v_lim), 要老的 S 曲线动效设 ZMAX_PLAN_PROFILE=scurve。
    _prof = os.environ.get("ZMAX_PLAN_PROFILE", "linear").lower()
    _sm = bool((_MEM_S.get("l4") or {}).get("smooth") or 0)
    if _prof in ("scurve", "smooth", "s"):
        _sm = True
    elif _prof in ("linear", "lin", "trap", "trapezoid"):
        _sm = False
    _pub_ar(o1, (el - seg_t0) / max(te, 1e-9), te, el, a_eff=a_blend,
            sm=_sm, mem=mem_block)
    _last_c = {}
    try:
        _last_c = (_mf().last_cycle() if _mf() is not None else {}) or {}
    except Exception:                                                      # noqa: BLE001
        pass
    return {
        "out1": o1,
        "out2": {"mt_id": seg.get("mt_id"), "mt_name": seg.get("mt_name"),
                 "mt_i": seg.get("mt_i"), "mt_total": _S["n_mt"],
                 "batch": seg.get("batch"), "mod": cur_mod, "done": done, "total": _S["n_mods"],
                 "uph_live": (round(uph, 1) if uph else None)},
        "out3": {"elapsed_s": round(el, 2), "skills": _skill_blk, "round": _S["round"], "tact_s": round(_S["tact"], 2),
                 "uph_target": _S["uph_target"],
                 "uph_capability": round(3600.0 / max(_S["tact"], 0.1), 1),
                 "speed_factor": _SPEED, "seg_index": _S["i"], "n_segs": len(segs),
                 "task_id": _S["task_id"], "verified": _S["verified"],
                 # 🧠 记忆层真实生效值 (逐层可对账)
                 "mem": mem_block,
                 "mem_l2_kl2": mem_block["l2"]["kl2"] if mem_block else None,
                 "mem_l3_tact_last": _last_c.get("tact_s"),
                 "mem_l3_uph_last": _last_c.get("uph"),
                 "mem_l4": (mem_block or {}).get("l4"),
                 "vision": _vis},
    }
