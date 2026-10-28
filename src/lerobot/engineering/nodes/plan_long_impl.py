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


def _load():
    """元任务组合 + 段几何 → 逐段带元任务归属的段序列 (双向校验)"""
    global LAST_STATUS
    try:
        m1 = os.path.getmtime(_META)
        m2 = os.path.getmtime(_PLAN)
    except OSError as e:
        LAST_STATUS = "配置/段表不可读 (%s)" % e
        return None, None
    if _S["segs"] is not None and (m1, m2) == _S["mtime"]:
        return _S["segs"], _S["cum"]

    meta = json.load(open(_META, encoding="utf-8"))
    seg_doc = json.load(open(_PLAN, encoding="utf-8"))
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

    _S.update(segs=segs, cum=cum, i=0, t0=None, mtime=(m1, m2), tact=tact,
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
             "mt_i": o1.get("mt_i"), "mt_n": o1.get("mt_n"), "batch": o1.get("batch")}
        os.makedirs(os.path.dirname(_AR_CMD), exist_ok=True)
        tmp = _AR_CMD + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        os.replace(tmp, _AR_CMD)
    except Exception:                                              # noqa: BLE001
        pass


def run(ctx=None):
    global LAST_STATUS
    segs, cum = _load()
    if not segs:
        return {"out1": None, "out2": None, "out3": None}

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
          "t_in_seg": round(el - seg_t0, 3), "t_left": round(left, 3),
          "mod": cur_mod, "hole": seg.get("hole"),
          "mt_id": seg.get("mt_id"), "mt_name": seg.get("mt_name"),
          "mt_i": seg.get("mt_i"), "mt_n": _S["n_mt"], "batch": seg.get("batch")}
    LAST_STATUS = ("元任务 %s %s (%d/%d) · 第%s段 %s"
                   % (seg.get("mt_id"), seg.get("mt_name"), seg.get("mt_i"), _S["n_mt"],
                      seg.get("seq"), seg.get("kind")))
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
                 "task_id": _S["task_id"], "verified": _S["verified"]},
    }
