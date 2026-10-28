# -*- coding: utf-8 -*-
"""🏭 UPH 节拍循环器 · 真实实现 (registry key = ss_uph)

为什么要独立成文件:
  画布每次 save_canvas 都会按 node_names.json 重新生成 n_*.py 外壳 (PURE=False 直通),
  手写在外壳里的算法会被覆盖。工程约定 = 外壳只做绑定, 真实现住在这里并由 registry 注册。

实现口径:
  输入  无强依赖 (ctx 可有可无)。段表真源 = zmax_data/runtime/traj/sim_insert.json (只读, 不改)。
  输出  out1 当前动作 {seq,kind,label,a,b,t,t_in_seg,t_left,mod,hole}
        out2 进度/产出 {mod,done,total,mods_per_cycle,uph_live}
        out3 节拍/UPH {elapsed_s,total_elapsed_s,round,tact_s,uph_target,uph_capability,speed_factor,seg_index,n_segs}
  副作用 只有一件: ZMAX_UPH_AR_PUB=1 时把当前段写成 AR 虚拟臂渲染指令 (zmax_data/ss_live/ar_cmd.json)。
        它不碰 ctl_auth / l2_daemon / 任何硬件句柄 —— 真机零指令。

件数口径 (踩过的坑):
  段表 plan[].k 是**搬运批次**(1..8), 不是件号。件数真源 = cycles_data (14 条), 按 t_work 累加成
  "第几件在何时完成" 的时间轴。用 k 当件号会把 UPH 算成 208 (真值 316)。
"""
from __future__ import annotations

import json
import os
import time

_ROOT = os.path.expanduser("~/zmax/zmax_data/runtime/traj")
_PLAN = os.path.join(_ROOT, "sim_insert.json")
_AR_CMD = os.path.abspath(os.path.join(_ROOT, "..", "..", "ss_live", "ar_cmd.json"))
_SPEED = float(os.environ.get("ZMAX_UPH_SPEED", "1.0"))     # 时间倍速(调试用), 默认实时
_AR_PUB = os.environ.get("ZMAX_UPH_AR_PUB", "0") == "1"     # 1 = 每拍发 AR 渲染指令

_S = {"plan": None, "cum": None, "i": 0, "t0": None, "done": 0, "total": 0,
      "tact_s": 12.0, "uph_target": 300, "mods": 1, "mtime": 0.0,
      "round": 0, "t_all0": None, "mod_cum": None, "n_mods": 0}
LAST_STATUS = ""


def _load():
    """读段表(带 mtime 热重载) → (plan, cum 累积时间, 件数)"""
    global LAST_STATUS
    try:
        mt = os.path.getmtime(_PLAN)
    except OSError as e:
        LAST_STATUS = "段表不可读 (%s)" % e
        return None, None, 0
    if _S["plan"] is not None and mt == _S["mtime"]:
        return _S["plan"], _S["cum"], _S["n_mods"]

    with open(_PLAN, encoding="utf-8") as fh:
        d = json.load(fh)
    plan = d.get("plan") or []
    cum, acc = [], 0.0
    for s in plan:
        acc += float(s.get("t") or 0.0)
        cum.append(acc)
    cyc = d.get("cycles_data") or []
    tact = float(d.get("tact_steady_s") or 12.0)
    mod_cum, macc = [], 0.0
    for c in cyc:
        macc += float(c.get("t_work") or tact)
        mod_cum.append(macc)
    _S.update(plan=plan, cum=cum, i=0, t0=None, done=0, mtime=mt,
              total=len(cyc), mod_cum=mod_cum, n_mods=len(cyc), tact_s=tact,
              uph_target=int(d.get("uph_target") or 300),
              mods=int(d.get("mods_per_cycle") or 1))
    return plan, cum, len(cyc)


def reset():
    _S.update(i=0, t0=None, done=0)


def _pub_ar(o1, t_in_seg, seg_t, el):
    """当前段 → AR 虚拟臂渲染指令。只渲染, 不下发真机。"""
    if not _AR_PUB:
        return
    try:
        u = (t_in_seg / seg_t) if seg_t > 0 else 1.0
        d = {"t": time.time(), "t_str": time.strftime("%H:%M:%S"), "src": "ss_uph_tact",
             "seq": o1.get("seq"), "mod": o1.get("mod"), "kind": o1.get("kind"),
             "label": o1.get("label"), "a": o1.get("a"), "b": o1.get("b"),
             "u": round(min(1.0, max(0.0, u)), 4), "t_seg": seg_t,
             "t_left": o1.get("t_left"), "elapsed_s": round(el, 2)}
        os.makedirs(os.path.dirname(_AR_CMD), exist_ok=True)
        tmp = _AR_CMD + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        os.replace(tmp, _AR_CMD)
    except Exception:                                           # noqa: BLE001
        pass


def run(ctx=None):
    """一拍: 按累积时间定位当前段 → 返回三个输出端口。"""
    global LAST_STATUS
    plan, cum, _total = _load()
    if not plan or not cum:
        return {"out1": None, "out2": None, "out3": None}

    now = time.monotonic()
    if _S["t0"] is None:
        _S["t0"] = now
    if _S["t_all0"] is None:
        _S["t_all0"] = now
    el = (now - _S["t0"]) * _SPEED
    el_all = (now - _S["t_all0"]) * _SPEED

    while _S["i"] < len(plan) and el >= cum[_S["i"]]:
        _S["i"] += 1
    if _S["i"] >= len(plan):                    # 一轮走完 → 从头再来(流水线不停)
        _S["done"] = _S["n_mods"]
        _S["i"] = 0
        _S["t0"] = now
        _S["round"] += 1
        el = 0.0

    seg = plan[_S["i"]]
    seg_t = float(seg.get("t") or 0.0)
    seg_t0 = cum[_S["i"]] - seg_t
    left = max(0.0, cum[_S["i"]] - el)

    mod = seg.get("mod") or 0
    if mod and mod != _S["mods"]:
        _S["mods"] = mod

    done = 0
    for th in (_S["mod_cum"] or []):
        if el >= th:
            done += 1
        else:
            break
    cur_mod = min(done + 1, _S["n_mods"] or done)

    # 实时 UPH: 样本足够才报(否则头 0.5s 能算出四位数假值)
    uph = (done / el * 3600.0) if (el >= max(30.0, 3.0 * _S["tact_s"]) and done >= 2) else None

    LAST_STATUS = "第%s段 %s · 第%d/%d件 · 累计%.1fs" % (
        seg.get("seq"), seg.get("kind"), cur_mod, _S["n_mods"], el)

    o1 = {"seq": seg.get("seq"), "kind": seg.get("kind"), "label": seg.get("label"),
          "a": seg.get("a"), "b": seg.get("b"), "t": seg_t,
          "t_in_seg": round(el - seg_t0, 3), "t_left": round(left, 3),
          "mod": cur_mod, "hole": seg.get("hole")}
    _pub_ar(o1, el - seg_t0, seg_t, el)
    return {
        "out1": o1,
        "out2": {"mod": cur_mod, "done": done, "total": _S["n_mods"],
                 "mods_per_cycle": _S["mods"],
                 "uph_live": (round(uph, 1) if uph else None)},
        "out3": {"elapsed_s": round(el, 2), "total_elapsed_s": round(el_all, 2),
                 "round": _S["round"], "tact_s": round(_S["tact_s"], 2),
                 "uph_target": _S["uph_target"],
                 "uph_capability": round(3600.0 / max(_S["tact_s"], 0.1), 1),
                 "speed_factor": _SPEED, "seg_index": _S["i"], "n_segs": len(plan)},
    }
