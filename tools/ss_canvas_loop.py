#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态空间画布常驻循环 —— 每拍按拓扑序真跑画布节点 (engine of record = state_space_obs.json)

为什么需要它:
  控制台 GUI 里的 tick 只在窗口开着时跑; mw_project.py step 只能跑一拍。
  「由状态空间的节点实现」要成立, 必须有一个常驻进程按拍跑画布节点。本脚本就是它。

白名单 (重要):
  ZMAX_CANVAS_ONLY=ssuph         只跑这些节点(逗号分隔)。空 = 跑全部可执行节点。
  默认 **不跑全部** —— 画布里多数节点 PURE=True 会真调模型/硬件, 逐节点验过再把 id 加进白名单。

用法:
  ZMAX_CANVAS_ONLY=ssuph ./gui-venv311/bin/python tools/ss_canvas_loop.py
  ZMAX_CANVAS_ONLY=ssuph,ssllm ZMAX_CANVAS_HZ=10 ...

产物:
  zmax_data/ss_live/canvas_loop.json   每拍摘要(帧龄/节点状态/最后一拍 trace)
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lerobot.middleware import load_project          # noqa: E402

CANVAS = os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas",
                      "state_space_obs.json")
STATE = os.path.join(ROOT, "zmax_data", "ss_live", "canvas_loop.json")
ONLY = [x.strip() for x in (os.environ.get("ZMAX_CANVAS_ONLY") or "").split(",") if x.strip()]
HZ = max(0.5, float(os.environ.get("ZMAX_CANVAS_HZ") or "10"))
STATE_EVERY = max(1, int(HZ))                 # 约 1s 落一次状态


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


SW = os.path.join(ROOT, "zmax_data", "ss_live", "exec_switches.json")
SW_FRESH_S = 1800.0
_LAST_KA = [0.0]


def keepalive_switch():
    """🔄 AR 开关续期 (只续 ar_scene, real_auth 永不自动续 —— 安全红线)

    背景: exec_switches.json 由控制台「点开关」写盘, 有效期 AR_SW_FRESH_S=1800s。
    控制台长时间不开 ⇒ 过期 ⇒ /api/ar/mode 返回 ar_scene=false ⇒ AR 页回落自播
    ⇒ 用户看到「双臂不工作」。画布常驻循环本来每拍就在读这份唯一依据, 顺手续期最合适。
    ⛔ real_auth (真机授权) 绝不续期: 那是人点出来的, 机器不能替人授权。
    """
    now = time.time()
    if now - _LAST_KA[0] < 60:
        return
    _LAST_KA[0] = now
    try:
        d = json.load(open(SW, encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        return
    if not d.get("ar_scene") or d.get("real_auth"):
        return                                                 # 关着不续; 有真机授权更不续
    age = now - float(d.get("t") or 0)
    if age < SW_FRESH_S * 0.6:
        return
    d["t"] = now
    d["t_str"] = time.strftime("%Y-%m-%d %H:%M:%S")
    d["_kept_alive_by"] = "ss_canvas_loop (只续 ar_scene)"
    d["_prev_age_s"] = round(age, 1)
    tmp = SW + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, SW)
        log("🔄 AR 开关续期 (ar_scene=True · real_auth=False · 原龄 %.0fs)" % age)
    except Exception as e:                                     # noqa: BLE001
        log("AR 开关续期失败 %s: %s" % (type(e).__name__, e))


def write_state(d):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        os.replace(tmp, STATE)
    except Exception as e:                                     # noqa: BLE001
        log("写状态失败 %s: %s" % (type(e).__name__, e))


def main():
    log("画布常驻循环启动 · HZ=%.1f · 白名单=%s" % (HZ, ONLY or "全部(危险,不建议)"))
    prj, mtime, n_tick, last_err = None, 0.0, 0, ""
    _last_ev = [None]              # 上一行证据的 (段,件) —— 只在变化时打 (见 ✅ 行)
    while True:
        try:
            t_iter = time.monotonic()          # 本拍真正起点 (含 keepalive/心跳/写状态的杂项开销)
            mt = os.path.getmtime(CANVAS)
            if prj is None or mt != mtime:
                t0 = time.monotonic()
                prj = load_project()
                mtime = mt
                log("加载画布: %d 节点 / %d 连线 (%.2fs) 白名单生效=%s"
                    % (len(prj.nodes), len(prj.order), time.monotonic() - t0, bool(ONLY)))
            t0 = time.monotonic()
            traces = prj.step(only=ONLY or None)
            cost = time.monotonic() - t0
            n_tick += 1
            keepalive_switch()                 # 🔄 AR 开关续期(只续 ar_scene), 防 1800s 过期导致双臂不动
            # 💓 心跳: 终端每 ~5s 一行 (tick/耗时/节点数) —— 没有心跳时"安静"会被误读成"卡住"
            # 💓 2026-10-31 老倪「不允许再有 tick」: 心跳默认**关**。要开就设 ZMAX_LOOP_BEAT_S=5
            #   (单位秒); 设 0 或不设 = 一行 tick 都不打。加载/报错/跑满结束照常打。
            _beat_s = float(os.environ.get("ZMAX_LOOP_BEAT_S", "0") or 0)
            beats = int(HZ * _beat_s) if _beat_s > 0 else 0
            if beats > 0 and n_tick % beats == 0:
                _over = cost > 1.0 / HZ
                _top = ""
                if _over:
                    _tt = sorted(((t.get("ms") or 0), t.get("id")) for t in traces)[-2:]
                    _top = " ← " + " · ".join("%s %sms" % (i, round(m, 1)) for m, i in reversed(_tt))
                log("💓 tick=%d · %.0fms/%s · %d 节点%s"
                    % (n_tick, cost * 1000, ("%.0fms" % (1000.0 / HZ)),
                       len(traces), (" · ⚠️ 超节拍" + _top) if _over else ""))
            # ✅ 每秒一行"这一秒真算出了什么" —— 只有心跳时终端看着像空转, 老倪问"还是循环"就是这个
            if float(os.environ.get("ZMAX_LOOP_EVIDENCE", "1")) > 0 and n_tick % max(1, int(HZ)) == 0:
                _det = _frm = None; _u = None; _n_act = 0; _seq = _lab = _el = _mod = None
                for _t in traces:
                    _o = _t.get("out") or {}
                    if _t.get("id") == "ssyolo":
                        _p = _o.get("out1") or {}
                        if isinstance(_p, dict):
                            _det = len(_p.get("points") or {}) or 0
                            _frm = _p.get("frame")
                    elif _t.get("id") == "ssplan":
                        _g = _o.get("out1") or {}
                        if isinstance(_g, dict):
                            _seq, _lab, _el, _mod = (_g.get("seq"), _g.get("label"),
                                                     _g.get("elapsed_s"), _g.get("mod"))
                    elif _t.get("id") == "ssact":
                        _a = _o.get("out1") or {}
                        if isinstance(_a, dict):
                            _u = _a.get("u_sat") or _a.get("u_cmd")
                            _n_act += 1
                _us = ("[%s]" % ",".join("%.2f" % float(v) for v in _u)) if isinstance(_u, (list, tuple)) and _u else "—"
                # 🐛 2026-10-31 老倪「还在反复检测」: 每秒都打"检测 3 点"⇒ 看着像没完没了地检测。
                #   改成**只在段/件变化时**打一行 (进度真的走了才出声), 其余交给 5s 心跳。
                _key = (_mod,)          # 只在"件"变化时出声 (段每 0.2s 换一次, 按段会刷屏)
                if _key != _last_ev[0]:        # 和上一行比 (原来拿 tuple 跟 list 比 ⇒ 恒不相等, 每拍都打)
                    _last_ev[0] = _key
                    log("✅ 段%s %s · t=%ss · 件%s · 检测 %s 点 · u=%s"
                        % (_seq if _seq is not None else "—", _lab or "—",
                           _el if _el is not None else "—", _mod if _mod is not None else "—",
                           _det if _det is not None else "—", _us))
            _max_t = int(float(os.environ.get("ZMAX_LOOP_MAX_TICKS", "0") or 0))
            if _max_t and n_tick >= _max_t:
                log("🏁 已跑满 %d 拍 (ZMAX_LOOP_MAX_TICKS) → 正常结束, 不再检测" % _max_t)
                write_state({"t": time.time(), "t_str": time.strftime("%H:%M:%S"), "ok": True,
                             "hz": HZ, "only": ONLY, "tick": n_tick, "cost_ms": round(cost * 1000, 1),
                             "budget_ms": round(1000.0 / HZ, 1), "over_budget": False,
                             "n_nodes": len(prj.nodes), "n_ran": len(traces), "traces": [],
                             "err": "", "done": True})
                # 🔴 不能裸 return: 解释器正常退出会去析构 mujoco/EGL + 后台推理线程,
                #   实测报 "FATAL: exception not rethrown" 并 dumped core。这里直接 _exit。
                sys.stdout.flush()
                os._exit(0)
            if n_tick % STATE_EVERY == 0:
                brief = [{"id": t.get("id"), "status": t.get("status"), "ms": t.get("ms"),
                          "out": {k: (v if not isinstance(v, (list, dict)) else "[%s]" % type(v).__name__)
                                  for k, v in (t.get("out") or {}).items()}}
                         for t in traces]
                write_state({"t": time.time(), "t_str": time.strftime("%H:%M:%S"),
                             "ok": True, "hz": HZ, "only": ONLY, "tick": n_tick,
                             "cost_ms": round(cost * 1000, 1),
                             "budget_ms": round(1000.0 / HZ, 1),
                             "over_budget": bool(cost > 1.0 / HZ),
                             "n_nodes": len(prj.nodes), "n_ran": len(traces),
                             "traces": brief, "err": ""})
            # 🕒 2026-10-31: 原来 dt 只扣了 prj.step 的耗时, 没扣本拍杂项 (keepalive/心跳/写状态 ~7ms)
            #   ⇒ 实测只有 9.3Hz (每拍 107ms)。改成按**整拍墙钟**结算, 稳定 10Hz。
            dt = 1.0 / HZ - (time.monotonic() - t_iter)
            if dt > 0:
                time.sleep(dt)
        except Exception as e:                                 # noqa: BLE001
            msg = "%s: %s" % (type(e).__name__, e)
            if msg != last_err:
                log("循环异常 → 1s 后重建: " + msg)
                last_err = msg
            write_state({"t": time.time(), "t_str": time.strftime("%H:%M:%S"),
                         "ok": False, "hz": HZ, "only": ONLY, "tick": n_tick,
                         "err": msg})
            prj = None
            time.sleep(1.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("停止")
        sys.stdout.flush()
        os._exit(130)
