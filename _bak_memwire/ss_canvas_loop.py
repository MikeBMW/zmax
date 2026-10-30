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
    while True:
        try:
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
            if n_tick % STATE_EVERY == 0:
                brief = [{"id": t.get("id"), "status": t.get("status"),
                          "out": {k: (v if not isinstance(v, (list, dict)) else "[%s]" % type(v).__name__)
                                  for k, v in (t.get("out") or {}).items()}}
                         for t in traces]
                write_state({"t": time.time(), "t_str": time.strftime("%H:%M:%S"),
                             "ok": True, "hz": HZ, "only": ONLY, "tick": n_tick,
                             "cost_ms": round(cost * 1000, 1),
                             "n_nodes": len(prj.nodes), "n_ran": len(traces),
                             "traces": brief, "err": ""})
            dt = 1.0 / HZ - cost
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
