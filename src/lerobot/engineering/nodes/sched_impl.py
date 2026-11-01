# -*- coding: utf-8 -*-
"""🧭 工艺规划引擎 (被「测地线规划引导」n_geoplan 调用; 不是独立画布节点)

老倪 2026-11-01:
  「推进器为什么在 tools/ss_canvas_loop.py？应该是状态空间工程的调度模块。以后迁移到 550C 怎么办？
    这些是数据迁移的核心策略，不能放在这。应该放在规划节点。你设计调度节点，接入 L2 层。」

归属 (老倪 2026-11-01):
  「应该是测地线规划引导这个节点负责工艺规划」
  ⇒ 本模块是**工艺引擎** (纯逻辑, 无副作用地算"该做哪一步"), 由 n_geoplan 每拍调用,
    工艺步骤随引导位姿一起输出给下游 (安全边界 sslimit → 动作调制器 sssched)。
    画布上只有一个规划入口 = 测地线规划引导; 不再另设调度节点。

分工 (三件事必须分开, 以前混在 ss_plan_long 里):
  ① **调度** (本节点): 决定"现在该做哪个元任务的哪一步、什么时候算做完、下一步做什么"
     · 输入 = 配置真源 (config/tasks/ar_meta_tasks.json) + L2 执行反馈 (n_exec)
     · 输出 = 一步指令 (out1) + 进度 (out2) + 调度事件 (out3)
  ② 规划 (n_moveit): 把一步目标变成段表 (起点真值 + 闸 + 势场), 只规划不下发
  ③ 执行 (n_exec/l2_daemon): 下发 + 到位判决, 唯一能碰真机的一层
  本节点**不写 ar_cmd、不碰硬件、不认段几何** —— 只产"意图 + 推进判决"。

L2 接入 (推进条件来自执行层, 不再靠墙钟):
  in2 ← n_exec:  phase/seg/n_seg/residual_mm/blocked_by/age_s
  推进 (advance) 需要同时满足:
    · age_s ≤ STALE_S            (L2 状态新鲜; 旧状态一律不推进)
    · 无 blocked_by              (被授权/位姿/安全闸拦住 ⇒ 卡住不动, 报原因)
    · phase ∈ DONE_PHASES 或 (seg ≥ n_seg 且 residual_mm ≤ tol_mm)   (真到位才算这一步做完)
  否则 hold (报 why), 绝不"按时间猜着往下走"。

550C 迁移 (本节点为迁移策略的一部分, 所以路径全部可换):
  · 仓库根: ZMAX_REPO → 否则从本文件向上找含 zmax_data/ 的目录 (不写死 ~/zmax)
  · 配置:   ZMAX_META_TASKS → 否则 <repo>/config/tasks/ar_meta_tasks.json
            → 再否则 <repo>/data/database/zmax/sources/config/tasks/ar_meta_tasks.json
  · 运行态: ZMAX_SCHED_STATE → 否则 <repo>/zmax_data/ss_live/sched_state.json
  ⇒ 配置随仓库走 (进 git 的 data/database/.../config), 运行态随数据盘走 (zmax_data, 可丢弃可重建);
    换机器只需改两个环境变量或保持同样的相对布局, 节点代码零改动。
"""
from __future__ import annotations

import json
import os
import time

NODE = "n_geoplan.craft"   # 工艺引擎 (挂在引导节点下)
STALE_S = float(os.environ.get("ZMAX_SCHED_STALE_S") or 2.0)     # L2 状态超过它就算过期
STEP_TIMEOUT_S = float(os.environ.get("ZMAX_SCHED_STEP_TIMEOUT_S") or 8.0)  # 一步等这么久没到位就报超时(仍不推进)
ARRIVE_TOL_MM = float(os.environ.get("ZMAX_SCHED_TOL_MM") or 1.0)  # 到位残差阈值
# ⚠️ idle 不算"这一步做完了": 它只表示执行层手上没活。若把 idle 当完成,
#   每拍都会推进一次 (实测: 首拍就从 MT-01 step0 跳到 step1, 一步没动就跑到下一条)。
DONE_PHASES = {"done", "arrived", "完成", "到位"}


# ── 路径解析 (迁移友好: 全部可用环境变量覆盖) ─────────────────────────────────────
def _repo() -> str:
    env = (os.environ.get("ZMAX_REPO") or "").strip()
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    # 先认 .git (仓库根唯一判据); 再看 zmax_data —— 只认**两者之一都不在 src/ 里的**那层,
    # 否则 src/zmax_data 这类残留会把仓库根算成 src/ (元任务配置就找不到了)。
    p = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isdir(os.path.join(p, ".git")):
            return p
        p = os.path.dirname(p)
    p = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isdir(os.path.join(p, "zmax_data")) and not p.rstrip("/").endswith("/src"):
            return p
        p = os.path.dirname(p)
    return "/home/ubuntu/zmax"


def _meta_path() -> str:
    env = (os.environ.get("ZMAX_META_TASKS") or "").strip()
    if env:
        return env                                   # 给了就用它; 不存在由 _cfg() 明确报错
    r = _repo()
    for rel in (("config", "tasks", "ar_meta_tasks.json"),
                ("data", "database", "zmax", "sources", "config", "tasks", "ar_meta_tasks.json")):
        p = os.path.join(r, *rel)
        if os.path.isfile(p):
            return p
    return ""


def _state_path() -> str:
    env = (os.environ.get("ZMAX_SCHED_STATE") or "").strip()
    if env:
        return env
    return os.path.join(_repo(), "zmax_data", "ss_live", "sched_state.json")


# ── 配置真源 (热读: 改表不用重启) ──────────────────────────────────────────────────
_CFG = {"mtime": 0.0, "path": "", "mts": {}, "order": {}, "err": ""}


def _cfg() -> dict:
    p = _meta_path()
    if not p:
        _CFG["err"] = "元任务配置找不到 (ZMAX_META_TASKS / config/tasks/ar_meta_tasks.json)"
        return _CFG
    try:
        mt = os.path.getmtime(p)
    except OSError as e:
        _CFG["err"] = "配置读不到 (%s): %s" % (p, e)
        _CFG["mts"], _CFG["order"] = {}, {}
        return _CFG
    if mt == _CFG["mtime"] and _CFG["path"] == p:
        return _CFG
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:                                              # noqa: BLE001
        _CFG["err"] = "配置解析失败: %s" % e
        return _CFG
    mts = {}
    for m in d.get("meta_tasks") or []:
        if isinstance(m, dict) and m.get("id"):
            mts[str(m["id"])] = m
    hands = ((d.get("long_horizon") or {}).get("hands") or {})
    order = {}
    for hand, ids in hands.items():
        for i in ids:
            if i in mts:
                order.setdefault(str(hand), []).append(i)
    _CFG.update({"mtime": mt, "path": p, "mts": mts, "order": order, "err": "",
                 "task_id": d.get("task_id"), "task": d})
    return _CFG


# ── 运行态 (推进到哪一步) ────────────────────────────────────────────────────────
def _load_state() -> dict:
    p = _state_path()
    try:
        d = json.load(open(p, encoding="utf-8"))
        if isinstance(d, dict):
            return d
    except Exception:                                                   # noqa: BLE001
        pass
    return {"task_id": None, "hand": "R", "mt_i": 0, "step_i": 0, "batch": 0,
            "mt_done": 0, "step_done": 0, "t0": time.time(), "events": []}


def _save_state(st: dict) -> None:
    p = _state_path()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:                                                   # noqa: BLE001
        pass


# ── L2 执行状态 (推进判决的全部依据) ───────────────────────────────────────────────
def _l2(ctx) -> dict:
    v = (ctx or {}).get("in2")
    if isinstance(v, dict) and (v.get("phase") is not None or v.get("seg") is not None
                                or v.get("blocked_by") is not None):
        return v
    # 没有连线时读执行器自己发布的真值 (同一个文件, 与 n_exec 同源)
    p = os.path.join(_repo(), "zmax_data", "ss_live", "exec_state.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        if "age_s" not in d:
            t = float(d.get("t_pub") or d.get("t") or 0.0)
            d["age_s"] = round(time.time() - t, 2) if t else None
        return d
    except Exception:                                                   # noqa: BLE001
        return {}


def _arrived(l2: dict) -> tuple:
    """L2 是否已把这一步做完 ⇒ (bool, why)"""
    if not l2:
        return False, "无 L2 执行状态"
    age = l2.get("age_s")
    if age is None:
        t = float(l2.get("t_pub") or l2.get("t") or 0.0)
        age = (time.time() - t) if t else None
    if age is not None and float(age) > STALE_S:
        return False, "L2 状态过期 %.1fs > %.1fs" % (float(age), STALE_S)
    b = str(l2.get("blocked_by") or "").strip()
    if b:
        return False, "L2 被拦: %s" % b
    ph = str(l2.get("phase") or "").strip().lower()
    if ph in DONE_PHASES:
        return True, "phase=%s" % ph
    seg, n_seg = l2.get("seg"), l2.get("n_seg")
    res = l2.get("residual_mm")
    if seg is not None and n_seg is not None and float(n_seg) > 0 and float(seg) >= float(n_seg):
        if res is None or float(res) <= ARRIVE_TOL_MM:
            return True, "段走完 seg=%s/%s 残差=%s" % (seg, n_seg, res)
        return False, "段走完但残差 %s mm > %.1f" % (res, ARRIVE_TOL_MM)
    return False, "执行中 seg=%s/%s 残差=%s" % (seg, n_seg, res)


def _gate_ok(ctx) -> tuple:
    g = (ctx or {}).get("in3")
    if isinstance(g, dict):
        if g.get("ok") is False or g.get("veto"):
            return False, "安全闸否决: %s" % (g.get("why") or g.get("reason") or "veto")
    return True, ""


def reset(reason: str = "manual") -> dict:
    st = _load_state()
    st.update({"mt_i": 0, "step_i": 0, "mt_done": 0, "step_done": 0, "t0": time.time(),
               "events": [{"at": round(time.time(), 3), "event": "reset", "why": reason}]})
    _save_state(st)
    return st


def run(ctx=None):
    """一个周期: (配置, L2 状态, 安全闸) → 一步指令 + 进度 + 调度事件。"""
    ctx = ctx or {}
    c = _cfg()
    out = {"node": NODE, "impl": "nodes/sched_impl.py:run"}
    if c["err"]:
        return {"out1": None, "out2": {"ok": False}, "out3": {"event": "hold", "why": c["err"]}}

    # ① 任务/批次切换 (in1 优先, 否则沿用状态文件) —— 也支持 in1={"reset":true}
    st = _load_state()
    req = ctx.get("in1") if isinstance(ctx.get("in1"), dict) else {}
    if req.get("reset"):
        st = reset(str(req.get("why") or "in1.reset"))
    hand = str(req.get("hand") or st.get("hand") or "R").upper()
    task_id = str(req.get("task_id") or st.get("task_id") or c.get("task_id") or "")
    batch = int(req.get("batch") if req.get("batch") is not None else (st.get("batch") or 0))
    if task_id != st.get("task_id"):
        st.update({"task_id": task_id, "mt_i": 0, "step_i": 0, "hand": hand, "t0": time.time()})

    order = list((c["order"].get(hand) or c["order"].get("R") or []) or [])
    if not order:
        return {"out1": None, "out2": {"ok": False},
                "out3": {"event": "hold", "why": "配置里没有手=%s 的元任务顺序 (long_horizon.hands)" % hand}}

    mt_i = int(st.get("mt_i") or 0) % len(order)
    mt = c["mts"].get(order[mt_i]) or {}
    actions = [str(a) for a in (mt.get("actions") or [])]
    n_step = max(1, len(actions))
    step_i = int(st.get("step_i") or 0) % n_step

    # ② L2 判决: 上一拍/上一步是否真做完
    l2 = _l2(ctx)
    ok_arrive, why_arr = _arrived(l2)
    ok_gate, why_gate = _gate_ok(ctx)
    ev = {"at": round(time.time(), 3), "event": "hold", "why": why_arr or why_gate}

    seq_i = int(st.get("step_done") or 0)
    _pend = st.get("pending")
    _pt0 = float(st.get("pending_t0") or 0.0)
    _key = "%s|%d|%d" % (order[mt_i] if order else "-", mt_i, step_i)
    if _pend != _key:                      # 新的一步: 记 pending, 等 L2 回执
        st["pending"] = _key
        st["pending_t0"] = time.time()
        _pt0 = st["pending_t0"]
    _waited = time.time() - _pt0 if _pt0 else 0.0
    if (not ok_arrive) and _waited > STEP_TIMEOUT_S:
        why_arr = "%s (等到位已 %.1fs > %.0fs ⇒ 不推进, 派发链需查)" % (why_arr, _waited, STEP_TIMEOUT_S)
    if ok_arrive and ok_gate:
        # 只有"真到位"才推进: 本步完成 → 下一步; 末步完成 → 下一个元任务
        step_i += 1
        st["pending"] = None
        st["pending_t0"] = 0.0
        st["step_done"] = int(st.get("step_done") or 0) + 1
        if step_i >= n_step:
            step_i = 0
            mt_i = (mt_i + 1) % len(order)
            st["mt_done"] = int(st.get("mt_done") or 0) + 1
            if mt_i == 0:
                st["batch"] = batch + 1
                batch = st["batch"]
            ev = {"at": round(time.time(), 3), "event": "advance_mt",
                  "why": "元任务完成: %s (%s)" % (mt.get("id"), mt.get("name", "")[:40]),
                  "mt_i": mt_i, "mt_done": st["mt_done"]}
        else:
            ev = {"at": round(time.time(), 3), "event": "advance_step",
                  "why": "到位: %s" % why_arr, "mt_i": mt_i, "step_i": step_i}
    else:
        ev["why"] = why_gate or why_arr

    st.update({"task_id": task_id, "hand": hand, "mt_i": mt_i, "step_i": step_i, "batch": batch,
               "updated": round(time.time(), 3)})
    evs = (st.get("events") or [])[-49:] + [ev]
    st["events"] = evs
    _save_state(st)

    mt = c["mts"].get(order[mt_i]) or {}
    actions = [str(a) for a in (mt.get("actions") or [])]
    n_step = max(1, len(actions))
    step_i = int(step_i) % n_step
    t0 = float(st.get("t0") or time.time())
    elapsed = max(1e-3, time.time() - t0)
    uph = 3600.0 * max(1, int(st.get("mt_done") or 0)) / elapsed

    out1 = {
        "seq": seq_i, "task_id": task_id, "batch": batch, "hand": hand,
        "mt_id": mt.get("id"), "mt_name": mt.get("name"), "mt_i": mt_i, "mt_n": len(order),
        "step": actions[step_i] if actions else None, "step_i": step_i, "n_step": n_step,
        "label": "%s · %s [%d/%d]" % (mt.get("id"), (actions[step_i] if actions else "—"), step_i + 1, n_step),
        "tol_mm": ARRIVE_TOL_MM, "src": "n_sched(调度节点)",
    }
    out2 = {"ok": True, "batch": batch, "hand": hand, "mt_done": int(st.get("mt_done") or 0),
            "mt_total": len(order), "step_done": int(st.get("step_done") or 0),
            "elapsed_s": round(elapsed, 2), "uph_live": round(uph, 1),
            "l2_phase": l2.get("phase"), "l2_seg": l2.get("seg"), "l2_n_seg": l2.get("n_seg"),
            "l2_age_s": l2.get("age_s"), "l2_blocked_by": l2.get("blocked_by") or "",
            "cfg": c["path"], "state": _state_path()}
    out3 = dict(ev, advance_ok=bool(ok_arrive and ok_gate), cfg_task=c.get("task_id"),
                recent=[e.get("event") for e in evs[-5:]])
    return {"out1": out1, "out2": out2, "out3": out3}
