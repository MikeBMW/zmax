#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_replay_continuous.py —— 真机「按录制真实速度连续回放 215 点」

老倪 2026-11-15: 「现在的轨迹回放, 非常慢, 不是真实的回放的速度」
  ⇒ 真实回放 = 录制真值 42.85s / 215 点 = 0.199 s/点 (frames[0].t=0 → frames[-1].t=42.849)

为什么 arm_step_traj.py 慢 (10.94 s/点, 慢 55 倍):
  它每点 moveAppend 一条 + moveStart + **等到位** + dwell, 且 zone=-1(精确停)
  ⇒ 每点必然「静止→加速→减速→静止」, 物理上不可能达到连续速度。

本脚本的做法(连续):
  ① moveReset 一次
  ② 批量 moveAppend 全部点, zone>0(转弯区, 到点前就开始转下一点 ⇒ 不停顿)
  ③ moveStart 一次, 控制器内部插补整条
  ④ 只在**整批结束**时判到位, 不在每点之间停

安全(与 arm_step_traj.py 同一套闸, 缺一不下发):
  ① 前置 power=on + operation=idle/automatic (非 drag/manual)
  ② 逐点关节跳变 > MAX_JUMP_DEG 拒发(全批先校验, 有一点超限就整条不发)
  ③ 起点归位: |当前→第0点| > MAX_JUMP_DEG 时按 ≤18°/段插中间点先归位
  ④ 整批超时 = n_pts * per_pt_budget(默认宽松) ⇒ 超时立即 moveStop
  ⑤ 任一点 append 被拒 ⇒ 立即 moveStop, 不重发不补偿
  ⑥ 结束时核对最终关节角误差, 超过 TOL_DEG 报失败

用法(容器内, 由 rokae_sdk_run.sh 挂载):
  bash tools/rokae_sdk_run.sh --script arm_replay_continuous.py --dry
  bash tools/rokae_sdk_run.sh --script arm_replay_continuous.py              # 真走整条
  ZMAX_REPLAY_N=10 ... --script arm_replay_continuous.py                    # 只走前 10 点

环境变量:
  ZMAX_REPLAY_N       只回放前 N 点(默认全部)
  ZMAX_REPLAY_SPEED   速度 %(默认 100 = 录制速度)
  ZMAX_REPLAY_ZONE    转弯区 mm(默认 2.0; -1 = 精确停, 会退化成逐点慢跑)
  ZMAX_REPLAY_CHUNK   每批追加点数(默认 0 = 全部一次追加)
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"
CMD = os.environ.get("ZMAX_REPLAY_CMD") or "/sdk/traj_step_cmd.json"
TRAJ = os.environ.get("ZMAX_REPLAY_TRAJ") or "/sdk/real_traj_joints.json"
MAX_JUMP_DEG = 40.0        # 单点关节跳变上限(与 arm_step_traj.py 同一口径; 本条轨迹相邻最大 31.1°)
TOL_DEG = 1.5              # 整批结束后的最终到位判据(连续模式不逐点判, 给宽一点)
PREP_SEG_DEG = 18.0        # 归位插值段每段最大角度


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
    return str(r.operationState({}))


def _as_j(f):
    """帧可能是 dict({t,p,j,q,...}) 或裸 6 元 list; 统一取关节角弧度。"""
    if isinstance(f, dict):
        for k in ("j", "joints", "joint", "q"):
            v = f.get(k)
            if isinstance(v, (list, tuple)) and len(v) >= 6:
                return [float(x) for x in v[:6]]
        raise ValueError("帧里找不到关节角字段(j/joints/q): keys=%s" % list(f.keys()))
    return [float(x) for x in list(f)[:6]]


def main() -> int:
    dry = "--dry" in sys.argv
    out = {"ok": False, "dry": dry, "mode": "continuous"}

    # ── 读帧 ────────────────────────────────────────────────
    src = TRAJ if os.path.isfile(TRAJ) else CMD
    try:
        d = json.load(open(src, encoding="utf-8"))
        frames = d.get("frames") or []
    except Exception as e:                                                    # noqa: BLE001
        out["why"] = "读不到轨迹 %s: %s: %s" % (src, type(e).__name__, e)
        print(json.dumps(out, ensure_ascii=False))
        return 2
    if not frames:
        out["why"] = "轨迹没有帧: %s" % src
        print(json.dumps(out, ensure_ascii=False))
        return 2

    n_env = int(os.environ.get("ZMAX_REPLAY_N") or 0)
    n = min(n_env or len(frames), len(frames))
    frames = frames[:n]
    speed = float(os.environ.get("ZMAX_REPLAY_SPEED") or 100.0)
    zone = float(os.environ.get("ZMAX_REPLAY_ZONE") or 2.0)
    chunk = int(os.environ.get("ZMAX_REPLAY_CHUNK") or 0) or n
    dur_src = d.get("dur_s")
    if dur_src and n == len(d.get("frames") or []):
        budget = float(dur_src) * float(os.environ.get("ZMAX_REPLAY_BUDGET_X") or 3.0)
    else:
        budget = n * 2.0        # 部分点: 每点 2s 预算

    out.update({"n_points": n, "speed_pct": speed, "zone_mm": zone, "chunk": chunk,
                "src": src, "budget_s": round(budget, 1)})

    r = x.xMateRobot()
    try:
        r.connectToRobot(IP)
    except Exception as e:                                                    # noqa: BLE001
        out["why"] = "连不上控制器 %s: %s: %s" % (IP, type(e).__name__, e)
        print(json.dumps(out, ensure_ascii=False))
        return 2

    def _disc():
        try:
            r.disconnectFromRobot({})
        except Exception:                                                     # noqa: BLE001
            pass

    st = {"power": str(r.powerState({})), "op": opstate(r)}
    out["state_before"] = st
    if not ("on" in st["power"].lower()
            and ("idle" in st["op"].lower() or "automatic" in st["op"].lower())):
        out["why"] = ("前置不满足: power=%s(要 on) · operation=%s(要 idle/automatic; "
                      "drag=关拖动, manual=切自动)" % (st["power"], st["op"]))
        print(json.dumps(out, ensure_ascii=False))
        _disc()
        return 2

    cur = joints(r)
    out["joints_before_deg"] = [round(math.degrees(v), 2) for v in cur]

    # ── 全批跳变预检(帧内跳变; 起点跳变由下面的归位段处理, 不算拒发) ──────────
    j0 = _as_j(frames[0])
    start_jump = max(abs(math.degrees(b - a)) for a, b in zip(cur, j0))
    out["start_jump_deg"] = round(start_jump, 2)

    prev = j0                      # 🔴 从第0点起算"帧内"跳变, 不用 cur
    worst = 0.0
    worst_i = -1
    bad = []
    for i, j in enumerate(frames):
        jt = _as_j(j)
        jump = max(abs(math.degrees(b - a)) for a, b in zip(prev, jt))
        if jump > worst:
            worst, worst_i = jump, i
        if jump > MAX_JUMP_DEG:
            bad.append({"i": i, "jump_deg": round(jump, 2)})
        prev = jt
    out["max_jump_deg"] = round(worst, 2)
    out["max_jump_at"] = worst_i
    if bad:
        out["why"] = ("有 %d 点关节跳变超过 %.0f°(最大 %.1f° @点%d), 整条拒发防瞬移"
                      % (len(bad), MAX_JUMP_DEG, worst, worst_i))
        out["bad"] = bad[:8]
        print(json.dumps(out, ensure_ascii=False))
        _disc()
        return 1

    # ── 起点归位(当前 → 第0点, 超限则插中间点) ──────────────
    jump0 = start_jump
    prep = []
    if jump0 > MAX_JUMP_DEG:
        k = int(math.ceil(jump0 / PREP_SEG_DEG))
        prep = [[cur[m] + (j0[m] - cur[m]) * (t / float(k)) for m in range(6)]
                for t in range(1, k)]
    out["prep"] = {"jump_deg": round(jump0, 1), "n_mid": len(prep),
                   "seg_deg": round(jump0 / float(len(prep) + 1), 1)}

    if dry:
        out["ok"] = True
        out["note"] = ("dry: 跳变预检通过(最大 %.1f° @点%d), 未下发。"
                       "若真走: %d 点 · speed=%d%% · zone=%.1fmm · 预算 %.1fs(+归位 %d 点)"
                       % (worst, worst_i, n, speed, zone, budget, len(prep)))
        print(json.dumps(out, ensure_ascii=False))
        _disc()
        return 0

    # ── 归位段(逐点, 精确停 —— 只为了安全到位, 不追求速度) ────
    if prep:
        print(json.dumps({"prep_start": True, "n_mid": len(prep),
                          "seg_deg": round(jump0 / float(len(prep) + 1), 1)},
                         ensure_ascii=False), flush=True)
        for pi, pj in enumerate(prep):
            r.moveReset({})
            ec = {}
            r.moveAppend([x.MoveAbsJCommand(x.JointPosition([float(v) for v in pj]), speed, -1)],
                         x.PyString("prep%d" % pi), ec)
            if ec.get("ec", 0) != 0:
                out["why"] = "归位第 %d/%d 点 moveAppend 被拒: %s" % (pi + 1, len(prep), ec)
                print(json.dumps(out, ensure_ascii=False))
                _disc()
                return 1
            r.moveStart({})
            t0 = time.time()
            while time.time() - t0 < 30.0:
                time.sleep(0.1)
                if "idle" in opstate(r).lower():
                    break
            print(json.dumps({"prep_progress": pi + 1, "n": len(prep),
                              "secs": round(time.time() - t0, 2)}, ensure_ascii=False), flush=True)

    # ── 连续回放: 分批 append(zone>0) → start → 只等批末 ──────
    print(json.dumps({"start": True, "n": n, "speed_pct": speed, "zone_mm": zone,
                      "chunk": chunk,
                      "joints_now_deg": [round(math.degrees(v), 2) for v in joints(r)]},
                     ensure_ascii=False), flush=True)
    t_all = time.time()
    sent = 0
    batches = []
    while sent < n:
        part = frames[sent:sent + chunk]
        r.moveReset({})
        ec = {}
        n_ok = 0
        err = None
        for k, j in enumerate(part):
            jt = _as_j(j)
            ec1 = {}
            r.moveAppend([x.MoveAbsJCommand(x.JointPosition(jt), speed, zone)],
                         x.PyString("c%d" % (sent + k)), ec1)
            if ec1.get("ec", 0) != 0:
                err = {"i": sent + k, "ec": ec1}
                break
            n_ok += 1
        if err:
            try:
                r.moveStop({})
            except Exception:                                                 # noqa: BLE001
                pass
            out["why"] = ("第 %d 点 moveAppend 被拒 %s ⇒ 已 moveStop, 不重发不补偿"
                          % (err["i"], err["ec"]))
            out["sent"] = sent + n_ok
            print(json.dumps(out, ensure_ascii=False))
            _disc()
            return 1
        try:
            r.moveStart({})
        except Exception as e:                                                # noqa: BLE001
            out["why"] = "moveStart 异常 %s: %s" % (type(e).__name__, e)
            out["sent"] = sent
            print(json.dumps(out, ensure_ascii=False))
            _disc()
            return 1
        # 🔴 2026-11-15 实测 bug: moveStart 之后立刻查 opstate 还是 idle(臂还没起转),
        #    旧逻辑 `if idle: break` 直接跳出 ⇒ 215 点在 0.15s 内"跑完", 臂根本没动。
        #    正确: 先等它真的进 moving(最多 5s), 再等回 idle。
        t_wait = time.time()
        went_moving = False
        while time.time() - t_wait < 5.0:
            s_now = opstate(r).lower()
            if "moving" in s_now:
                went_moving = True
                break
            # 已经开始下电/报警就别等了
            if "off" in str(r.powerState({})).lower():
                out["why"] = "moveStart 后控制器立刻掉电(power=off), 已中止 —— 臂未运动"
                out["sent"] = sent
                print(json.dumps(out, ensure_ascii=False))
                _disc()
                return 1
            time.sleep(0.1)
        if not went_moving:
            out["why"] = ("moveStart 后 5s 内没有进入 moving(当前 %s) ⇒ 指令没被执行, 已中止"
                          % opstate(r))
            out["sent"] = sent
            print(json.dumps(out, ensure_ascii=False))
            _disc()
            return 1
        # 等这一批跑完(不在点间停, 只在批末判)
        tb = time.time()
        b_budget = max(15.0, len(part) * (budget / float(max(1, n))) * 2.5)
        while time.time() - tb < b_budget:
            time.sleep(0.15)
            if "idle" in opstate(r).lower():
                break
        secs = time.time() - tb
        sent += n_ok
        batches.append({"n": n_ok, "secs": round(secs, 2)})
        print(json.dumps({"batch": len(batches), "sent": sent, "n": n,
                          "secs": round(secs, 2),
                          "s_per_pt": round(secs / float(max(1, n_ok)), 3),
                          "elapsed_s": round(time.time() - t_all, 1)},
                         ensure_ascii=False), flush=True)
        if "idle" not in opstate(r).lower():
            out["why"] = ("第 %d 批超时未停稳(operationState=%s), 已停"
                          % (len(batches), opstate(r)))
            try:
                r.moveStop({})
            except Exception:                                                 # noqa: BLE001
                pass
            out["sent"] = sent
            print(json.dumps(out, ensure_ascii=False))
            _disc()
            return 1

    tot = time.time() - t_all
    aj = joints(r)
    fin_err = max(abs(math.degrees(b - a)) for a, b in zip(_as_j(frames[-1]), aj))
    out.update({"sent": sent, "elapsed_s": round(tot, 2),
                "s_per_pt": round(tot / float(max(1, sent)), 3),
                "final_err_deg": round(fin_err, 2),
                "joints_after_deg": [round(math.degrees(v), 2) for v in aj],
                "batches": batches})
    if dur_src:
        out["vs_record_s"] = round(tot / float(dur_src), 2)     # 1.0 = 与录制同速
    out["state_after"] = {"power": str(r.powerState({})), "op": opstate(r)}
    out["ok"] = fin_err <= TOL_DEG
    out["why"] = ("连续回放完成: %d 点 / %.2fs (%.3fs每点%s), 最终误差 %.2f°"
                  % (sent, tot, tot / float(max(1, sent)),
                     (", 录制 %.2fs 的 %.2f 倍" % (dur_src, tot / float(dur_src))) if dur_src else "",
                     fin_err))
    print(json.dumps(out, ensure_ascii=False))
    _disc()
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
