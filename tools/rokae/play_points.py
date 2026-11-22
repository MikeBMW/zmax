#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""play_points.py —— 215 点「回放模式」(MoveAbsJ 逐点/分块), 停点停下 1 秒

老倪口径(2026-11-21): 不用 RT 流式控制, 回到原来的 215 点回放;
   每个点在页面上有「停」勾选 —— 勾了就停 1 秒, 没勾就快速通过。

跟 arm_rt_stream2.py 的区别:
  - 走 NRT 的 MoveAbsJ, 由控制器自己做关节插补(不需要 1kHz 指令流, 不会有 RT 跟丢/力矩墙)
  - 天然"点到点到位", 到点判据是实测关节误差 ≤ TOL_DEG 且 op=idle
  - 速度用控制器的 speed 百分比(实测 100 ≈ 上限), 所以"快速通过"= speed 100 分块连发

用法(docker 内):
    ZMAX_PP_I0=0 ZMAX_PP_I1=215 ZMAX_PP_SPEED=100 ZMAX_PP_DWELL=1000 \
    ZMAX_PP_CHUNK=8 python3 play_points.py

输出: 每个块一行 JSON, 便于 grep/取证。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
SDK = os.environ.get("ZMAX_SDK_DIR", "/sdk")
TRAJ = os.environ.get("ZMAX_PP_TRAJ") or os.path.join(SDK, "real_traj_joints.json")
STOPS = os.environ.get("ZMAX_PP_STOPS") or os.path.join(SDK, "point_stops.json")
I0 = int(os.environ.get("ZMAX_PP_I0") or 0)
I1 = int(os.environ.get("ZMAX_PP_I1") or 215)
SPEED = float(os.environ.get("ZMAX_PP_SPEED") or 100.0)
DWELL_MS = int(os.environ.get("ZMAX_PP_DWELL") or 1000)
CHUNK = int(os.environ.get("ZMAX_PP_CHUNK") or 8)
CHUNK_TMO = float(os.environ.get("ZMAX_PP_TMO") or 25.0)
TOL_DEG = float(os.environ.get("ZMAX_PP_TOL") or 0.6)
ABORT_DEG = float(os.environ.get("ZMAX_PP_ABORT") or 25.0)   # 指令 vs 实测差超此值就停(防假到位)
# 🔴 接触段必须低速: 纯位置回放没有力反馈, 硬顶就是撞机(INC-20261121-03)
#   格式 "21-35:15,93-108:15" —— 该区间每点单独成块, speed 用给定值
SLOW = os.environ.get("ZMAX_PP_SLOW") or "21-35:15,93-108:15"


def _slow_zones(spec):
    zs = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        rng, sp = part.split(":", 1)
        try:
            a, b = rng.split("-")
            zs.append((int(a), int(b), float(sp)))
        except Exception:                                                # noqa: BLE001
            continue
    return zs


def speed_at(i, zones, base):
    for a, b, sp in zones:
        if a <= i <= b:
            return sp, True
    return base, False


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def joints(r):
    v = r.jointPos({})
    if isinstance(v, dict):
        for k in ("jointPos", "joint", "values", "data"):
            if k in v:
                v = v[k]
                break
        else:
            v = list(v.values())[0]
    return [float(t) for t in list(v)[:6]]


def opstate(r):
    try:
        s = r.operationState({})
        if isinstance(s, dict):
            s = s.get("operationState") or s.get("state") or s
        return str(s)
    except Exception:                                                    # noqa: BLE001
        return "?"


def load_frames():
    d = json.load(open(TRAJ, encoding="utf-8"))
    fr = d.get("frames") or []
    return [[float(v) for v in (f.get("j") or [])[:6]] for f in fr]


def load_stops():
    try:
        c = json.load(open(STOPS, encoding="utf-8"))
    except Exception:                                                    # noqa: BLE001
        return set(), {}
    s = {int(k) for k, v in c.items() if (v or {}).get("stop")}
    nm = {int(k): (v or {}).get("name") for k, v in c.items() if (v or {}).get("name")}
    return s, nm


def send_chunk(r, jts, speed, tmo):
    t0 = time.time()
    try:
        r.moveReset({})
        ec = {}
        cmds = [x.MoveAbsJCommand(x.JointPosition([float(v) for v in jt]), speed, -1) for jt in jts]
        r.moveAppend(cmds, x.PyString("pp%d" % (int(t0 * 1000) % 100000)), ec)
        if ec.get("ec", 0) != 0:
            return False, 999.0, 0.0, "moveAppend 被拒: %s" % (ec,)
        r.moveStart({})
    except Exception as e:                                               # noqa: BLE001
        return False, 999.0, 0.0, "%s: %s" % (type(e).__name__, e)
    tgt = jts[-1]
    err = 999.0
    while time.time() - t0 < tmo:
        time.sleep(0.1)
        aj = joints(r)
        err = max(abs(math.degrees(b - a)) for a, b in zip(tgt, aj))
        if err <= TOL_DEG and "idle" in opstate(r).lower():
            return True, err, time.time() - t0, ""
    aj = joints(r)
    err = max(abs(math.degrees(b - a)) for a, b in zip(tgt, aj))
    return (err <= ABORT_DEG), err, time.time() - t0, ("超时(%.0fs) 停在中途" % tmo) if err > TOL_DEG else ""


def main() -> int:
    fr = load_frames()
    stops, names = load_stops()
    n = len(fr)
    i0, i1 = max(0, I0), min(n, I1)
    if i1 <= i0:
        out(ok=False, why="区间为空 %s..%s (共 %d 帧)" % (i0, i1, n))
        return 2

    r = x.xMateRobot()
    try:
        r.connectToRobot(IP)
    except Exception as e:                                               # noqa: BLE001
        out(ok=False, why="连不上 %s: %s" % (IP, e))
        return 2

    st_p, st_o = str(r.powerState({})), opstate(r)
    out(step="pre", power=st_p, op=st_o, i0=i0, i1=i1, speed=SPEED,
        dwell_ms=DWELL_MS, chunk=CHUNK, stops=[i for i in sorted(stops) if i0 <= i < i1])
    if "on" not in st_p.lower():
        out(ok=False, why="未上电(power=%s) 先跑 arm_power.py on" % st_p)
        return 2
    if not ("idle" in st_o.lower() or "automatic" in st_o.lower()):
        out(ok=False, why="operation=%s 不是 idle(示教器要切自动/关拖动)" % st_o)
        return 2

    cur = joints(r)
    jump0 = max(abs(math.degrees(b - a)) for a, b in zip(fr[i0], cur))
    out(step="start", cur_deg=[round(math.degrees(v), 2) for v in cur],
        jump_to_i0_deg=round(jump0, 2))

    zones = _slow_zones(SLOW)
    out(step="slow_zones", zones=zones if zones else "none")
    t_all = time.time()
    n_chunk = 0
    n_hold = 0
    bad = None
    i = i0
    while i < i1:
        # 组块: 最多 CHUNK 点; 遇到停点就把它作为块尾(保证停在点上)
        jts = []
        j = i
        while j < i1 and len(jts) < CHUNK:
            jts.append(fr[j])
            j += 1
            if (j - 1) in stops:
                break
            _sp, _in_slow = speed_at(j, zones, SPEED)
            if _in_slow:                      # 接触段: 一次只走 1 点, 不许连发
                break
        end_i = j - 1
        _spd, _slow = speed_at(end_i, zones, SPEED)
        ok, err, secs, why = send_chunk(r, jts, _spd, CHUNK_TMO * max(1.0, len(jts) / 4.0))
        n_chunk += 1
        rec = {"step": "chunk", "i0": i, "i1": end_i, "n": len(jts), "ok": ok, "speed": _spd,
               "err_deg": round(err, 3), "secs": round(secs, 2)}
        if end_i in stops:
            rec["stop"] = True
            rec["name"] = names.get(end_i)
        out(**rec)
        if not ok:
            bad = "块 %d..%d 失败: %s (err %.2f°)" % (i, end_i, why or "跟丢", err)
            break
        if end_i in stops and DWELL_MS > 0:
            t_hold = time.time()
            time.sleep(DWELL_MS / 1000.0)
            n_hold += 1
            out(step="dwell", i=end_i, ms=DWELL_MS, name=names.get(end_i),
                real_s=round(time.time() - t_hold, 2))
        i = end_i + 1

    out(step="done", ok=bad is None, why=bad or "", n_chunk=n_chunk, n_hold=n_hold,
        elapsed_s=round(time.time() - t_all, 2),
        end_i=i - 1 if bad is None else None,
        joints_deg=[round(math.degrees(v), 2) for v in joints(r)])
    return 0 if bad is None else 1


if __name__ == "__main__":
    sys.exit(main())
