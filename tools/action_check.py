#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔍 action 三方对账: 工程输出(action.json) ⇄ 215点目标(real_traj_joints.json) ⇄ 机器人真值(latest.json)

口径(2026-11-14 老倪): action 是工程唯一输出; 调试期 src=traj215 时它必须**逐字等于**215点目标;
真机执行后, 机器人真值必须收敛到同一目标。三份对不上, 就说明"看着对、实际没执行到"。

用法: python3 tools/action_check.py [--i N]
"""
import json
import math
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACT = os.path.join(REPO, "zmax_data", "ss_live", "action.json")
TRUTH = os.path.join(REPO, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
TRAJ = os.path.join(REPO, "tools", "web", "real_traj_joints.json")


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                       # noqa: BLE001
        return None


def _abc(q):
    """四元数 → ZYX 欧拉(度), 与 tools/pt_pose.py:abc_deg 同口径"""
    x, y, z, w = q
    rx = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    ry = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    rz = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return [math.degrees(rx), math.degrees(ry), math.degrees(rz)]


def main():
    idx = None
    if "--i" in sys.argv:
        idx = int(sys.argv[sys.argv.index("--i") + 1])

    act = _load(ACT) or {}
    truth = _load(TRUTH) or {}
    traj = _load(TRAJ) or {}
    frames = traj.get("frames") or []
    i = idx if idx is not None else int(act.get("i") or 0)
    fr = frames[i] if 0 <= i < len(frames) else {}

    print("=" * 62)
    print("① 工程输出 action.json")
    if act:
        print("   src=%s  i=%d/215  帧龄 %.1fs" % (act.get("src"), act.get("i") or -1, time.time() - float(act.get("ts") or 0)))
        print("   位姿 x=%.2f y=%.2f z=%.2f mm   a=%.2f b=%.2f c=%.2f deg" % (
            act.get("x", float("nan")), act.get("y", float("nan")), act.get("z", float("nan")),
            act.get("a", float("nan")), act.get("b", float("nan")), act.get("c", float("nan"))))
        print("   关节 %s" % ["%.2f" % float(act.get(k) or 0) for k in ("j1", "j2", "j3", "j4", "j5", "j6")])
        print("   夹爪 %s mm (%s / %s)" % (act.get("grip_mm"), act.get("grip_act"), act.get("grip_state")))
    else:
        print("   ❌ 读不到(action 总线还没写过)")

    print("② 215 点目标 frames[%d]" % i)
    if fr:
        p = fr.get("p") or []
        q = fr.get("q") or []
        e = _abc(q) if len(q) == 4 else [float("nan")] * 3
        print("   位姿 x=%.2f y=%.2f z=%.2f mm   a=%.2f b=%.2f c=%.2f deg" % (
            p[0] * 1000, p[1] * 1000, p[2] * 1000, e[0], e[1], e[2]))
        print("   关节 %s (deg)" % ["%.2f" % math.degrees(v) for v in (fr.get("j") or [])[:6]])
    else:
        print("   ❌ 无该点")

    print("③ 机器人真值 latest.json")
    if truth:
        print("   帧龄 %.2fs  x=%.2f y=%.2f z=%.2f mm  rx=%.2f ry=%.2f rz=%.2f deg" % (
            time.time() - float(truth.get("ts") or 0),
            float(truth.get("x", 0)) * 1000, float(truth.get("y", 0)) * 1000, float(truth.get("z", 0)) * 1000,
            math.degrees(float(truth.get("rx", 0))), math.degrees(float(truth.get("ry", 0))),
            math.degrees(float(truth.get("rz", 0)))))
        print("   关节 %s (deg)" % ["%.2f" % math.degrees(v) for v in (truth.get("joint") or [])[:6]])
    else:
        print("   ❌ 读不到")

    print("=" * 62)
    if fr and act:
        dp = [abs(float(act.get(k, 0)) - fr["p"][n] * 1000) for n, k in enumerate(("x", "y", "z"))]
        dj = [abs(float(act.get("j%d" % (n + 1)) or 0) - math.degrees(fr["j"][n])) for n in range(min(6, len(fr.get("j") or [])))]
        print("action ⇄ 215点: |Δxyz|max=%.2f mm   |Δ关节|max=%.3f deg  %s" % (
            max(dp), max(dj) if dj else float("nan"), "✅ 一致" if max(dp) < 0.5 and (dj and max(dj) < 0.05) else "⚠️ 不一致"))
    if fr and truth:
        dpt = [abs(fr["p"][n] * 1000 - float(truth.get(k, 0)) * 1000) for n, k in enumerate(("x", "y", "z"))]
        djt = [abs(math.degrees(fr["j"][n]) - math.degrees(v)) for n, v in enumerate((truth.get("joint") or [])[:6])]
        print("215点 ⇄ 真机: |Δxyz|max=%.2f mm   |Δ关节|max=%.3f deg  %s" % (
            max(dpt), max(djt) if djt else float("nan"),
            "✅ 已到位" if max(dpt) < 2.0 else "⏳ 尚未执行到该点(游标领先/未跑)"))
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
