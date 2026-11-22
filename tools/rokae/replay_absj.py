#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay_absj.py — 关节空间回放(MoveAbsJ), 用示教记下的关节角原样重现。

为什么用关节空间: 笛卡尔 MoveL/MoveJ 在手腕奇异区(第 53 帧 pitch −88.5°)会停住不动;
关节空间插补没有这个问题。

轨迹格式: {"frames":[{q:[6], p:[3], rpy:[3]}...]}   (q 弧度)
安全: 前置 on/automatic/idle; 每批 ≤BATCH 点; 批间等 idle; 每批核关节角误差 ≤1.5°; 失败即停。
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
SPEED = float(os.environ.get("ZMAX_SEG_SPEED") or 40)
TRAJ = os.environ.get("ZMAX_SEG_TRAJ") or "/sdk/real_traj_absj.json"
BATCH = int(os.environ.get("ZMAX_REPLAY_BATCH") or 50)


def main() -> int:
    fr = json.load(open(TRAJ))["frames"]
    qs = [f["q"] for f in fr]
    _f = int(os.environ.get("ZMAX_PTS_FROM") or 0)
    _t = int(os.environ.get("ZMAX_PTS_TO") or 0)
    if _t > 0:
        qs = qs[_f:_t]
        print("范围: 第 %d~%d 帧(%d 帧)" % (_f, _t, len(qs)), flush=True)
    print("关节回放: %d 帧 · 批量 %d · %.0f%%" % (len(qs), BATCH, SPEED), flush=True)

    r = x.xMateRobot()
    r.connectToRobot(IP)
    pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
    print("自检: %s %s %s" % (pw, md, op), flush=True)
    if "on" not in pw or "automatic" not in md or "idle" not in op:
        print("✗ 前置不满足, 不动")
        return 3

    def cur_q():
        jp = r.jointPos({})
        return list(jp.jointPosition)[:6] if hasattr(jp, "jointPosition") else list(jp)[:6]

    def wait_idle(tmo=30.0):
        t0 = time.time()
        while time.time() - t0 < tmo:
            if "idle" in str(r.operationState({})):
                return True
            time.sleep(0.2)
        return False

    # 断点续跑: 按关节角找最近的一帧(示教轨迹自交多, 用关节角比 TCP 更可靠)
    k0 = 0
    if os.environ.get("ZMAX_REPLAY_RESUME") == "1":
        cq = cur_q()
        k0 = min(range(len(qs)), key=lambda i: max(abs(a - b) for a, b in zip(qs[i], cq)))
        k0 = max(0, (k0 // BATCH) * BATCH)
        print("续跑: 最近第 %d 帧 ⇒ 从第 %d 批开始" % (k0, k0 // BATCH + 1), flush=True)

    r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
    for k in range(k0, len(qs), BATCH):
        chunk = qs[k:k + BATCH]
        if not wait_idle(25.0):
            print("✗ 未回 idle, 停")
            return 6
        r.moveReset({})
        bad = None
        for m, q in enumerate(chunk):
            ec = {}
            r.moveAppend(x.MoveAbsJCommand(x.JointPosition([float(v) for v in q]), SPEED, -1),
                         x.PyString("A%d" % m), ec)
            if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
                bad = (m, ec)
                break
        if bad:
            print("✗ append 第 %d 点被拒: %s" % bad)
            return 7
        ok = False
        for wait in (0.0, 0.5, 1.0, 2.0, 4.0):
            if wait:
                time.sleep(wait)
            ec = {}
            r.moveStart(ec)
            e = ec.get("ec", 0) if isinstance(ec, dict) else 0
            if e in (0, None):
                ok = True
                break
            print("  ⋯ start 拒发 %s, 退避 %.1fs" % (ec, wait), flush=True)
        if not ok:
            print("✗ 本批未发出, 停")
            return 4
        # ⚠️ start 回 {"message": ...} 而不带 ec 时会被当成成功但一动不动(实测停在 z≈998)。
        #    判据改成: 2 秒内关节角必须有变化, 否则算没启动。
        _q0 = cur_q()
        _moved = False
        for _ in range(20):
            time.sleep(0.1)
            if max(abs(a - b) for a, b in zip(cur_q(), _q0)) * 57.2958 > 0.05:
                _moved = True
                break
        if not _moved:
            print("✗ 本批 start 后 2s 关节无变化, 视为未启动, 停")
            return 8
        tgt = chunk[-1]
        t0 = time.time()
        while time.time() - t0 < 300.0:
            time.sleep(0.2)
            if max(abs(a - b) for a, b in zip(cur_q(), tgt)) * 57.2958 < 0.8:
                time.sleep(0.3)
                break
        dq = max(abs(a - b) for a, b in zip(cur_q(), tgt)) * 57.2958
        print("  %s 批 %2d/%d · 第 %d 帧 · 关节差 %.2f°"
              % ("✓" if dq < 1.5 else "✗", k // BATCH + 1,
                 (len(qs) + BATCH - 1) // BATCH, min(k + BATCH, len(qs)), dq), flush=True)
        if dq >= 1.5:
            print("✗ 本批未到位, 停(不硬顶)")
            return 5
    print("完成: 关节回放整圈结束", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
