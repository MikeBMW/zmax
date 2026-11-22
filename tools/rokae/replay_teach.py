#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay_teach.py — 把"示教学出来的整圈"批量下发回放(NRT · MoveL 队列)。

为什么要单独一支: 逐点 append+start 会在控制器"还没停稳"时收到 -20 robot state(moving),
每点要退避 4~8s, 一圈 200+ 点就慢到不可用(实测)。这里改成**一次 append 一批(默认 20 点)
再 start 一次**, 控制器内部按序插补, 既快又不丢点。

安全约定:
  · 只跑 NRT 模式; 前置必须 on/automatic/idle
  · 逐点过包络闸(BOX), 越界即停(不猜)
  · 每批结束后核到位(≤3mm), 失败立刻停, 不硬顶
  · 速度由 ZMAX_SEG_SPEED 控制(mm/s)

用法(宿主):
  ZMAX_TEACH_TRAJ=/sdk/real_traj_teach.json ZMAX_SEG_SPEED=50 bash tools/rokae_sdk_run.sh --script replay_teach.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x          # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
SPEED = float(os.environ.get("ZMAX_SEG_SPEED") or 50)
TRAJ = os.environ.get("ZMAX_SEG_TRAJ") or "/sdk/real_traj_teach.json"
BATCH = int(os.environ.get("ZMAX_REPLAY_BATCH") or 20)
# 包络按"示教实测范围"取(老倪这一圈 x 212~818 / y -508~454 / z 118~999), 留 20mm 余量
BOX = dict(x=(190, 900), y=(-560, 620),
           z=(95, float(os.environ.get("ZMAX_BOX_ZMAX") or 1005.0)))


def main() -> int:
    fr = json.load(open(TRAJ))["frames"]
    pts = [(f["p"], f["rpy"]) for f in fr]
    # 🔴 示教里手腕在个别点会一次转 40~50°(实测第 50→53 帧 yaw 0.83→2.61 rad/25mm),
    #    控制器到那里就停住不动(709.8,125.4,234.2 反复卡死)。按"每步 ≤4° / ≤10mm"插值补齐。
    _raw = len(pts)
    _out = [pts[0]]
    if os.environ.get("ZMAX_NO_EXPAND") == "1":
        _out = list(pts)
    for _i in (range(1, len(pts)) if os.environ.get("ZMAX_NO_EXPAND") != "1" else []):
        _p0, _r0 = pts[_i - 1]; _p1, _r1 = pts[_i]
        _dd = math.dist(_p0, _p1)
        _dr = [math.atan2(math.sin(b - a), math.cos(b - a)) for a, b in zip(_r0, _r1)]
        _n = max(1, int(math.ceil(max(max(abs(v) for v in _dr) * 57.2958 / 4.0, _dd / 10.0))))
        for _u in range(1, _n + 1):
            _t = _u / _n
            _out.append(([a + (b - a) * _t for a, b in zip(_p0, _p1)],
                         _r1 if _u == _n else [a + v * _t for a, v in zip(_r0, _dr)]))
    pts = _out if os.environ.get("ZMAX_NO_EXPAND") == "1" else _out
    _f = int(os.environ.get("ZMAX_PTS_FROM") or 0)
    _t = int(os.environ.get("ZMAX_PTS_TO") or 0)
    if _t > 0:
        pts = pts[_f:_t]
        print("范围: 第 %d~%d 点(%d 点)" % (_f, _t, len(pts)), flush=True)
    print("插值: %d → %d 点(每步 ≤4°/10mm)" % (_raw, len(pts)), flush=True)
    print("示教回放: %d 点 · 批量 %d · %.0fmm/s" % (len(pts), BATCH, SPEED), flush=True)
    for p, _ in pts:
        if not all(BOX[k][0] <= v <= BOX[k][1] for k, v in zip("xyz", p)):
            print("✗ 越界 %.1f,%.1f,%.1f —— 不动" % tuple(p))
            return 2

    r = x.xMateRobot()
    r.connectToRobot(IP)
    pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
    print("自检: %s %s %s" % (pw, md, op), flush=True)
    if "on" not in pw or "automatic" not in md or "idle" not in op:
        print("✗ 前置不满足(EStop/手动/运行中), 不动")
        return 3

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) * 1000.0 for v in cp.trans]

    def start_with_retry():
        for wait in (0.0, 0.5, 1.0, 2.0, 4.0, 6.0):
            if wait:
                time.sleep(wait)
                r.moveReset({})
                _flush()
            ec = {}
            r.moveStart(ec)
            e = ec.get("ec", 0) if isinstance(ec, dict) else 0
            if e in (0, None):
                return True
            if e == -3:
                print("✗ EStop: %s" % ec.get("message"), flush=True)
                return False
            print("  ⋯ moveStart 拒发 %s, 退避 %.1fs" % (ec, wait), flush=True)
        return False

    _cur = {"chunk": []}

    _fail = {"i": -1, "ec": None}

    def _flush():
        """逐点 append; ⚠️ 必须查 ec —— 之前用空 dict 不查, 有点被静默丢掉,
        队列提前结束⇒真机停在半路(实测 707,131,232 停住不动)。"""
        _fail["i"], _fail["ec"] = -1, None
        for m, (p, rpy) in enumerate(_cur["chunk"]):
            ec = {}
            _cp = x.CartesianPosition([v / 1000.0 for v in p], [float(v) for v in rpy])
            # MoveJ: 控制器自己做 IK + 关节插补 ⇒ 能过手腕奇异区(第 53 帧 pitch −88.5° 那类)
            _cmd = (x.MoveJCommand if os.environ.get("ZMAX_MOVE_TYPE") == "J" else x.MoveLCommand)(_cp, SPEED, -1)
            r.moveAppend(_cmd, x.PyString("T%d" % m), ec)
            if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
                _fail["i"], _fail["ec"] = m, ec
                print("  ✗ append 第 %d 点被拒: %s" % (m, ec), flush=True)
                return False
        return True

    p0 = pose()
    print("当前 %.1f,%.1f,%.1f · 目标起点 %.1f,%.1f,%.1f"
          % (*p0, *pts[0][0]), flush=True)

    def wait_idle(tmo=30.0):
        """等控制器真回到 idle —— 只看"到位 3mm"不够: 减速还没结束就 start 会一直 -20(实测)。"""
        t0 = time.time()
        while time.time() - t0 < tmo:
            if "idle" in str(r.operationState({})) and "idle" in str(r.robotState({}) if hasattr(r, "robotState") else "idle"):
                return True
            time.sleep(0.2)
        return False

    r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
    k0 = 0
    if os.environ.get("ZMAX_REPLAY_RESUME") == "1":
        _p = pose()
        k0 = min(range(len(pts)), key=lambda i: math.dist(pts[i][0], _p))
        k0 = max(0, (k0 // BATCH) * BATCH)
        print("续跑: 当前离第 %d 点最近 ⇒ 从第 %d 批开始" % (k0, k0 // BATCH + 1), flush=True)
    # ⚡ 快速模式: 整圈一次入队(控制器内部连续插补), 只在整圈走完后核一次末点。
    #    老倪 11-22: "太慢了, 快点走" —— 分批每批都要等 idle, 一圈要十几分钟。
    if os.environ.get("ZMAX_REPLAY_FAST") == "1":
        chunk = pts[k0:]
        _cur["chunk"] = chunk
        r.moveReset({})
        if not _flush():
            return 7
        if not start_with_retry():
            print("✗ 整圈没能下发")
            return 4
        tgt = chunk[-1][0]
        t0 = time.time()
        while time.time() - t0 < 900.0:
            time.sleep(0.3)
            if math.dist(pose(), tgt) < 3.0:
                break
        d = math.dist(pose(), tgt)
        print("%s 整圈 %d 点 · 用时 %.1fs · 末点差 %.1fmm"
              % ("✓" if d < 5.0 else "✗", len(chunk), time.time() - t0, d), flush=True)
        return 0 if d < 5.0 else 5

    done = 0
    for k in range(k0, len(pts), BATCH):
        chunk = pts[k:k + BATCH]
        _cur["chunk"] = chunk
        if not wait_idle(25.0):
            print("✗ 控制器 25s 未回 idle, 停(不硬顶)", flush=True)
            return 6
        r.moveReset({})
        if not _flush():
            print("✗ 本批下发失败(见上), 停", flush=True)
            return 7
        if not start_with_retry():
            print("✗ 第 %d 批没发出去, 停" % (k // BATCH + 1))
            return 4
        tgt = chunk[-1][0]
        t0 = time.time()
        # 到位判据只看"离末点 <3mm"; 超时给足(实测 500mm 一批要 40~90s, 原来的公式会提前判失败)
        tmo = 300.0
        while time.time() - t0 < tmo:
            time.sleep(0.2)
            if math.dist(pose(), tgt) < 3.0:
                time.sleep(0.3)
                break
        d = math.dist(pose(), tgt)
        done = k + len(chunk)
        print("  %s 批 %2d/%d · 第 %d 点 · 末点差 %.1fmm"
              % ("✓" if d < 3.0 else "✗", k // BATCH + 1,
                 (len(pts) + BATCH - 1) // BATCH, done, d), flush=True)
        if d >= 3.0:
            print("✗ 该批未到位, 停(不硬顶)")
            return 5

    p9 = pose()
    print("完成: 末点 %.1f,%.1f,%.1f · 与目标差 %.1fmm"
          % (*p9, math.dist(p9, pts[-1][0])), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
