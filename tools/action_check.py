#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔍 action 三方对账: 工程输出(action.json) ⇄ 215点目标(real_traj_joints.json) ⇄ 机器人真值(latest.json)

口径(2026-11-14 老倪): action 是工程唯一输出; 调试期 src=traj215 时它必须**逐字等于**215点目标;
真机执行后, 机器人真值必须收敛到同一目标。三份对不上, 就说明"看着对、实际没执行到"。

⚠️ 一个必须知道的坑: `action.json` 只在**画布 tick 时**才写。
   VSCode 停在断点上 / 画布暂停时, 它就是**上一拍**的旧值(常见 20s+ 甚至几分钟),
   拿它跟正在动的机器人比, 必然"对不上"。所以本脚本:
     · 帧龄 > 3s  ⇒ 判定为陈旧, 直接用 action_bus 现算一份对照(并明确标注)
     · 同时打印 action 自带的 pose_now / delta_mm / i_nearest(新字段)

用法: python3 tools/action_check.py [--i N] [--live]
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
STALE_S = 3.0


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


def _live_action():
    """用 action_bus 现算一份 traj215 口径的 action(与工程里跑的同一份代码)。"""
    try:
        sys.path.insert(0, os.path.join(REPO, "src"))
        from lerobot.policies.left_right.state_space import action_bus as AB   # noqa: PLC0415
        return AB.from_traj215()
    except Exception as e:                                                  # noqa: BLE001
        print("   ⚠️ 现算失败: %s" % e)
        return None


def _nearest(frames, xyz):
    best, bd = None, 1e9
    for i, f in enumerate(frames):
        q = f.get("p") or []
        if len(q) != 3:
            continue
        dd = math.dist([q[0] * 1000, q[1] * 1000, q[2] * 1000], xyz)
        if dd < bd:
            best, bd = i, dd
    return best, bd


def main():
    idx = None
    if "--i" in sys.argv:
        idx = int(sys.argv[sys.argv.index("--i") + 1])

    act = _load(ACT) or {}
    truth = _load(TRUTH) or {}
    traj = _load(TRAJ) or {}
    frames = traj.get("frames") or []
    age = time.time() - float(act.get("ts") or 0) if act else 1e9
    stale = (not act) or age > STALE_S or "--live" in sys.argv

    print("=" * 62)
    if stale:
        print("① 工程输出 action.json —— ⚠️ 陈旧 %.1fs(画布没 tick: 断点/暂停), 下面用现算值对照" % age)
        live = _live_action()
        if live:
            print("   现算 src=%s  i=%s/215  i_plan=%s" % (live.get("src"), live.get("i"), live.get("i_plan")))
            print("   位姿 x=%.2f y=%.2f z=%.2f mm   a=%.2f b=%.2f c=%.2f deg" % (
                live.get("x", float("nan")), live.get("y", float("nan")), live.get("z", float("nan")),
                live.get("a", float("nan")), live.get("b", float("nan")), live.get("c", float("nan"))))
            print("   关节 %s" % ["%.2f" % float(live.get(k) or 0) for k in ("j1", "j2", "j3", "j4", "j5", "j6")])
            print("   夹爪 %s mm (%s / %s)" % (live.get("grip_mm"), live.get("grip_act"), live.get("grip_state")))
            if idx is None:
                idx = int(live.get("i") or 0)
            act_for_cmp = live
            print("   落盘旧值 i=%s 位姿 %.2f/%.2f/%.2f(= 上一拍, 别拿它对正在动的臂)" % (
                act.get("i"), act.get("x", 0), act.get("y", 0), act.get("z", 0)))
        else:
            act_for_cmp = act
    else:
        print("① 工程输出 action.json   帧龄 %.1fs" % age)
        print("   src=%s  i=%s/215  i_plan=%s  i_nearest=%s" % (
            act.get("src"), act.get("i"), act.get("i_plan"), act.get("i_nearest")))
        print("   位姿 x=%.2f y=%.2f z=%.2f mm   a=%.2f b=%.2f c=%.2f deg" % (
            act.get("x", float("nan")), act.get("y", float("nan")), act.get("z", float("nan")),
            act.get("a", float("nan")), act.get("b", float("nan")), act.get("c", float("nan"))))
        print("   关节 %s" % ["%.2f" % float(act.get(k) or 0) for k in ("j1", "j2", "j3", "j4", "j5", "j6")])
        print("   夹爪 %s mm (%s / %s)" % (act.get("grip_mm"), act.get("grip_act"), act.get("grip_state")))
        act_for_cmp = act

    i = idx if idx is not None else int(act_for_cmp.get("i") or 0)
    fr = frames[i] if 0 <= i < len(frames) else {}

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
        if frames:
            txyz = [float(truth.get("x", 0)) * 1000, float(truth.get("y", 0)) * 1000, float(truth.get("z", 0)) * 1000]
            nb, nd = _nearest(frames, txyz)
            print("   ⇒ 实测最近 215 点: 第 %d 点 (距 %.1f mm)" % (nb, nd))
    else:
        print("   ❌ 读不到")

    print("=" * 62)
    if fr and act_for_cmp:
        dp = [abs(float(act_for_cmp.get(k, 0)) - fr["p"][n] * 1000) for n, k in enumerate(("x", "y", "z"))]
        dj = [abs(float(act_for_cmp.get("j%d" % (n + 1)) or 0) - math.degrees(fr["j"][n]))
              for n in range(min(6, len(fr.get("j") or [])))]
        print("action ⇄ 215点: |Δxyz|max=%.2f mm   |Δ关节|max=%.3f deg  %s" % (
            max(dp), max(dj) if dj else float("nan"),
            "✅ 一致" if max(dp) < 0.5 and (dj and max(dj) < 0.05) else "⚠️ 不一致"))
    if truth and act_for_cmp:
        dpt = [abs(float(act_for_cmp.get(k, 0)) - float(truth.get(k, 0)) * 1000) for k in ("x", "y", "z")]
        print("action ⇄ 真机 : |Δxyz|max=%.2f mm  %s" % (
            max(dpt), "✅ 已到位" if max(dpt) < 2.0 else "⏳ 未到位(目标还没执行完 / 该拍已过期)"))
    if fr and truth:
        dpt = [abs(fr["p"][n] * 1000 - float(truth.get(k, 0)) * 1000) for n, k in enumerate(("x", "y", "z"))]
        djt = [abs(math.degrees(fr["j"][n]) - math.degrees(v)) for n, v in enumerate((truth.get("joint") or [])[:6])]
        print("215点 ⇄ 真机: |Δxyz|max=%.2f mm   |Δ关节|max=%.3f deg  %s" % (
            max(dpt), max(djt) if djt else float("nan"),
            "✅ 已到位" if max(dpt) < 2.0 else "⏳ 尚未执行到该点"))
    if act.get("delta_mm"):
        _d = act["delta_mm"]
        _pn = act.get("pose_now") or {}
        print("落盘自带对账: 实测 %.2f/%.2f/%.2f (age %ss) · Δ=(%s, %s, %s) mm · i_nearest=%s · dispatch=%s" % (
            _pn.get("x") or 0, _pn.get("y") or 0, _pn.get("z") or 0, _pn.get("age_s"),
            _d[0], _d[1], _d[2], act.get("i_nearest"), act.get("dispatch")))
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
