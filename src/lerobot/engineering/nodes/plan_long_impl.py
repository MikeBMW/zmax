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
    LAST_STATUS = "元任务配置已展开: %d 元任务 / %d 段 (与段表逐段一致)" % (mt_i, len(segs))
    return segs, cum


def reset():
    _S.update(i=0, t0=None)


def _pub_ar(o1, u, seg_t, el):
    if not _AR_PUB:
        return
    try:
        d = {"t": time.time(), "t_str": time.strftime("%H:%M:%S"), "src": "ss_plan_long",
             "task_id": o1.get("task_id"), "seq": o1.get("seq"), "mod": o1.get("mod"),
             "kind": o1.get("kind"), "label": o1.get("label"), "a": o1.get("a"), "b": o1.get("b"),
             "u": round(min(1.0, max(0.0, u)), 4), "t_seg": seg_t, "t_left": o1.get("t_left"),
             "elapsed_s": round(el, 2), "mt_id": o1.get("mt_id"), "mt_name": o1.get("mt_name"),
             "mt_i": o1.get("mt_i"), "mt_n": o1.get("mt_n"), "batch": o1.get("batch"),
             # 🔴 2026-10-29: 视觉观测点同拍带给页面/执行器 (接口对齐; 误差/gaps 原样透出, 不美化)
             "vision": o1.get("vision")}
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
    segs, cum = _load()
    if not segs:
        return {"out1": None, "out2": None, "out3": {"vision": _vis}}

    now = time.monotonic()
    if _S["t0"] is None:
        _S["t0"] = now
    el = (now - _S["t0"]) * _SPEED
    while _S["i"] < len(segs) and el >= cum[_S["i"]]:
        _S["i"] += 1
    if _S["i"] >= len(segs):                       # 一轮走完 → 循环(流水线不停)
        _S["i"] = 0
        _S["t0"] = now
        _S["round"] += 1
        el = 0.0

    seg = segs[_S["i"]]
    seg_t = float(seg.get("t") or 0.0)
    seg_t0 = cum[_S["i"]] - seg_t
    left = max(0.0, cum[_S["i"]] - el)
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
    _pub_ar(o1, el - seg_t0, seg_t, el)
    return {
        "out1": o1,
        "out2": {"mt_id": seg.get("mt_id"), "mt_name": seg.get("mt_name"),
                 "mt_i": seg.get("mt_i"), "mt_total": _S["n_mt"],
                 "batch": seg.get("batch"), "mod": cur_mod, "done": done, "total": _S["n_mods"],
                 "uph_live": (round(uph, 1) if uph else None)},
        "out3": {"elapsed_s": round(el, 2), "round": _S["round"], "tact_s": round(_S["tact"], 2),
                 "uph_target": _S["uph_target"],
                 "uph_capability": round(3600.0 / max(_S["tact"], 0.1), 1),
                 "speed_factor": _SPEED, "seg_index": _S["i"], "n_segs": len(segs),
                 "task_id": _S["task_id"], "verified": _S["verified"],
                 "vision": _vis},
    }
