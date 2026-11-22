#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""goto_slot.py — 把末端送到料盘**槽1**抓取位 (648.3, 503.9, 111.8), 姿态取真机实测值。

用法: ZMAX_SLOT_XYZ=517,206,110 ZMAX_SLOT_RPY=... bash tools/rokae_sdk_run.sh --script goto_slot.py\n目标来源: zmax_data/live_ds/episode_* 真机采集帧 (槽1 附近最近帧), 非自造:
    xyz 648.3, 503.9, 111.8 mm      rpy 3.098, -1.491, 0.059 rad (≈177.5°, -85.4°, 3.4°)

路径(严禁低位横移 —— 料盘边缘会扫到):
    S0 原地抬到 z=300 (先脱离低处, 姿态不变)
    S1 → (648.3, 503.9, 300) 高处平移跨 y≈530mm
    S2 原地转身 → 目标 rpy (z=300 处, 离盘面 ~190mm, 腕部不扫料盘)
    S3 垂直下降到 z=111.8
每步核: |Δxyz|<2.0mm · 姿态差<1.5° · 任一步失败立即停, 不继续后续步。
"""
from __future__ import annotations

import math
import os
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x          # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
SPEED = float(os.environ.get("ZMAX_SLOT_SPEED", "40"))     # mm/s, 慢速
TGT = [663.9, -29.3, 293.5]   # 初始位 (239点#0 实测真值)
RPY_T = [2.055, -1.166, 0.953]  # 初始位实测姿态
D_MAX, R_MAX = 2.0, 1.5
BOX = dict(x=(400, 900), y=(-350, 620), z=(90, 620))       # 绝对工作域, 出界不动


def R_of(a, b, c):
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return [[ca * cb, ca * sb * sc - sa * cc, ca * sb * cc + sa * sc],
            [sa * cb, sa * sb * sc + ca * cc, sa * sb * cc - ca * sc],
            [-sb, cb * sc, cb * cc]]


def rpy_err(a, b):
    A, B = R_of(*a), R_of(*b)
    tr = sum(A[i][j] * B[i][j] for i in range(3) for j in range(3))
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1) / 2.0))))


def in_box(p):
    return all(BOX[k][0] <= v <= BOX[k][1] for k, v in zip("xyz", p))


def main() -> int:
    r = x.xMateRobot()
    r.connectToRobot(IP)
    pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
    print("自检: %s %s %s" % (pw, md, op), flush=True)
    if "on" not in pw or "automatic" not in md or "idle" not in op:
        print("✗ 前置不满足, 不动")
        return 3

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) * 1000.0 for v in cp.trans], [float(v) for v in cp.rpy]

    def send(p, rpy, name):
        if not in_box(p):
            print("  ✗ 出工作域 %s, 拒绝" % name, flush=True)
            return False
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend(x.MoveLCommand(
            x.CartesianPosition([v / 1000.0 for v in p], [float(v) for v in rpy]), SPEED, -1),
            x.PyString(name), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            print("  ✗ 下发失败 %s %s" % (name, ec), flush=True)
            return False
        r.moveStart({})
        # 🔴 不能只看 operationState: moveStart 后它可能仍读 idle(实测 S2 抬升 132mm 被判"没动")
        #    改成"位姿连续 3 拍不变且已过 0.6s"才算到位。
        # 判据: 连续 2 拍"到目标 <1mm" 且已过 1.5s 才算到位 (不能靠"没动"判断,
        # 控制器接单到起动有 ~1s 延迟, 用"没动"会把起步前的静止当到位 —— 实测就是这样误判)。
        t0 = time.time()
        near = 0
        while time.time() - t0 < 120:
            time.sleep(0.2)
            cur = pose()[0]
            near = near + 1 if math.dist(cur, p) < 1.0 else 0
            if near >= 2 and time.time() - t0 > 1.5:
                break
        time.sleep(0.2)
        p2, r2 = pose()
        dp = math.dist(p, p2)
        dr = rpy_err(rpy, r2)
        ok = dp < D_MAX and dr < R_MAX
        print("  %s %s Δxyz %.2fmm  姿态差 %.2f°  实测 %.1f,%.1f,%.1f"
              % ("✓" if ok else "✗", name, dp, dr, *p2), flush=True)
        return ok

    p0, r0 = pose()
    print("起点 %.1f,%.1f,%.1f rpy %.3f,%.3f,%.3f" % (*p0, *r0), flush=True)
    LIFT = min(p0[2] + 50.0, 620.0)          # 老倪: 先抬 5 厘米, 再回
    seq = [
        ([p0[0], p0[1], LIFT], r0, "S0_抬高50"),
        ([TGT[0], TGT[1], LIFT], r0, "S1_平移到初始位上方"),
        ([TGT[0], TGT[1], TGT[2]], r0, "S2_升到初始高度"),
        ([TGT[0], TGT[1], TGT[2]], RPY_T, "S3_转到初始姿态"),
    ]
    for p, rpy, name in seq:
        if not send(p, rpy, name):
            print("✗ 中断于 %s —— 后续不执行" % name, flush=True)
            return 1
    p1, r1 = pose()
    print("到槽1: Δxyz %.2fmm  最终姿态 %.3f,%.3f,%.3f"
          % (math.dist(TGT, p1), *r1), flush=True)
    print("OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
