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
import os
import time

_ROOT = os.path.expanduser("~/zmax")
_META = os.path.join(_ROOT, "data", "database", "zmax", "sources", "config", "tasks", "ar_meta_tasks.json")
_PLAN = os.path.join(_ROOT, "zmax_data", "runtime", "traj", "sim_insert.json")
_AR_CMD = os.path.join(_ROOT, "zmax_data", "ss_live", "ar_cmd.json")
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
        _MEM_S["t_eff"] = [float(s.get("t") or 0.0) for s in segs]
        _MEM_S["cum2"] = None
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
        v_travel = float(os.environ.get("ZMAX_MEM_TRAVEL_MM_S") or v_cap)
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
            t_eff.append(max(1e-3, te))
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


def _pub_ar(o1, u_ratio, seg_t, el, a_eff=None, sm=False, mem=None):
    if not _AR_PUB:
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
    try:
        d = {"t": time.time(), "t_str": time.strftime("%H:%M:%S"), "src": "ss_plan_long",
             "task_id": o1.get("task_id"), "seq": o1.get("seq"), "mod": o1.get("mod"),
             "kind": o1.get("kind"), "label": o1.get("label"), "a": a_pub, "b": o1.get("b"),
             "u": round(u, 4), "t_seg": seg_t, "t_left": o1.get("t_left"),
             "elapsed_s": round(el, 2), "mt_id": o1.get("mt_id"), "mt_name": o1.get("mt_name"),
             "mt_i": o1.get("mt_i"), "mt_n": o1.get("mt_n"), "batch": o1.get("batch"),
             # 🔴 2026-10-29: 视觉观测点同拍带给页面/执行器 (接口对齐; 误差/gaps 原样透出, 不美化)
             "vision": o1.get("vision")}
        if a_raw is not None:
            d["a_raw"] = a_raw
        if mem:
            d["mem"] = mem
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
    _pub_ar(o1, (el - seg_t0) / max(te, 1e-9), te, el, a_eff=a_blend,
            sm=bool((_MEM_S.get("l4") or {}).get("smooth") or 0), mem=mem_block)
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
