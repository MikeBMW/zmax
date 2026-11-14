#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 action ↔ 真机位姿 对齐探针 (2026-11-14 老倪: 「按实际位姿对齐 action, 模型输出也要跟 action 对齐」)

两种跑法:
  --selftest   离线自证: 拿真机录制位姿序列当"真机真值时流", 逐拍算 action, 核
               ① action.pose 逐轴 == 真值 + u·dt (差 <0.01mm, 即每拍都锚在真值上, 无漂移)
               ② 夹爪 action 跟着 u[3] 走
               ③ 单拍幅度/帧龄闸生效
  --live N     读 zmax_data/ss_live/action.json + tcp_out/latest.json N 秒, 报:
               src 分布 / align.truth_fresh 比例 / step_ok 比例 / pose 与"真值+u·dt"的偏差

判据(过闸才算对齐):
  pose 偏差 ≤0.05mm · 逐轴增益 1.00±0.02 · 真值新鲜率 ≥95% · 单拍超限 0 次
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.policies.left_right.state_space import action_bus as AB            # noqa: E402

REC = os.path.join(ROOT, "zmax_data", "pose_records", "rec_20261111_181020", "poses.jsonl")
ACT = os.path.join(ROOT, "zmax_data", "ss_live", "action.json")
TCP = os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")


def _truth_seq(n=60):
    """真机录制位姿序列 (mm + 四元数), 当"真机真值时流"用。"""
    out = []
    try:
        for line in open(REC, encoding="utf-8"):
            r = json.loads(line)
            if r.get("x") is None:                       # 真源字段是 x/y/z (米)
                continue
            p = [float(r["x"]) * 1000.0, float(r["y"]) * 1000.0, float(r["z"]) * 1000.0]
            q = r.get("quat") or [r.get("qx"), r.get("qy"), r.get("qz"), r.get("qw")]
            if any(v is None for v in q):
                continue
            out.append({"x": float(p[0]), "y": float(p[1]), "z": float(p[2]),
                        "qx": float(q[0]), "qy": float(q[1]), "qz": float(q[2]), "qw": float(q[3]),
                        "age_s": 0.02})
            if len(out) >= n:
                break
    except Exception as e:                                                 # noqa: BLE001
        print("  ⚠ 读录制失败:", e)
    return out


def selftest():
    seq = _truth_seq(60)
    if len(seq) < 10:
        print("❌ 录制位姿不够, 不能自证")
        return 2
    worst = 0.0
    bad_grip = 0
    bad_gate = 0
    rows = []
    for k, t in enumerate(seq):
        ang = 0.02 * k
        u = [0.12 * math.cos(ang), 0.12 * math.sin(ang), -0.05, (1.0 if (k // 10) % 2 == 0 else 0.0)]
        a = AB.from_ss(u, dt=0.1, pose_now=t, joints_now=None, why="selftest")
        if not a:
            print("❌ 第 %d 拍没出 action" % k)
            return 2
        exp = [t["x"] + u[0] * 100, t["y"] + u[1] * 100, t["z"] + u[2] * 100]
        got = [a["x"], a["y"], a["z"]]
        d = max(abs(got[i] - exp[i]) for i in range(3))
        worst = max(worst, d)
        want = "close" if u[3] >= 0.5 else "open"
        if a.get("grip_act") != want:
            bad_grip += 1
        if not a["align"]["step_ok"]:
            bad_gate += 1
        if k < 3 or k % 20 == 0:
            rows.append((k, got, exp, d, a.get("grip_act"), a["align"]["step_mm"]))
    print("  拍数 %d · pose 与(真值+u·dt)最大偏差 %.4f mm" % (len(seq), worst))
    for r in rows:
        print("   i=%2d action=%s 期望=%s 偏差=%.4f 夹爪=%s 单拍=%.2fmm"
              % (r[0], [round(v, 2) for v in r[1]], [round(v, 2) for v in r[2]], r[3], r[4], r[5]))
    print("  夹爪跟随 u[3] 错 %d 次 · 单拍超限 %d 次" % (bad_grip, bad_gate))
    ok = worst <= 0.05 and bad_grip == 0 and bad_gate == 0
    print("  判据(偏差≤0.05mm · 夹爪全跟随 · 无超限) ⇒", "✅ 对齐" if ok else "❌ 不对齐")
    return 0 if ok else 1


def live(sec=20.0):
    t0 = time.time()
    n = 0
    fresh = 0
    step_ok = 0
    srcs = {}
    dev = []
    last = 0.0
    while time.time() - t0 < sec:
        try:
            a = json.load(open(ACT, encoding="utf-8"))
            m = os.path.getmtime(ACT)
        except Exception:                                                  # noqa: BLE001
            time.sleep(0.2)
            continue
        if m != last:
            last = m
            n += 1
            srcs[a.get("src")] = srcs.get(a.get("src"), 0) + 1
            al = a.get("align") or {}
            if al.get("truth_fresh"):
                fresh += 1
            if al.get("step_ok"):
                step_ok += 1
            pz = a.get("pose") or {}
            tr = al.get("pose_truth")
            um = al.get("u_mm")
            if pz.get("x") is not None and tr and um:
                e = max(abs(pz["x"] - (tr[0] + um[0])), abs(pz["y"] - (tr[1] + um[1])),
                        abs(pz["z"] - (tr[2] + um[2])))
                dev.append(e)
        time.sleep(0.05)
    if not n:
        print("  ⚠ %ss 内 action.json 没有更新(引擎没在跑?)" % int(sec))
        return 3
    worst = max(dev) if dev else None
    print("  %ss 内 %d 拍 · src=%s" % (int(sec), n, srcs))
    print("  真值新鲜 %d/%d (%.0f%%) · 单拍未超限 %d/%d" % (fresh, n, 100.0 * fresh / n, step_ok, n))
    if worst is not None:
        print("  pose 与(pose_truth+u_mm) 最大偏差 %.4f mm" % worst)
    ok = (fresh / n >= 0.95) and (step_ok == n) and (worst is not None and worst <= 0.05)
    print("  判据 ⇒", "✅ 对齐" if ok else "❌ 不对齐/证据不足")
    return 0 if ok else 1


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return selftest()
    sec = 20.0
    if "--live" in argv:
        k = argv.index("--live")
        if k + 1 < len(argv):
            try:
                sec = float(argv[k + 1])
            except ValueError:
                pass
        return live(sec)
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
