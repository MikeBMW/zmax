#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""close_loop_to_point.py — 小步闭环到示教点 (专治奇异区/50113/50120)

现场实测(2026-10-13):
  · 单步姿态变化 >阈值 ⇒ 控制器 `50113 [奇异规避]路径中改变的姿态最大值超过阈值` / `50120 沿路径无法到达终点`,
    而执行器那条腿只比**位置**残差 ⇒ **假报"到位"**(姿态一字未转)。⇒ 姿态必须小步(≤5°)且**逐步核真值**。
  · 奇异区附近"下降 / 绕工具Z自转"可能被拒, 而"上升 / 后退 / 绕工具X"能走 ⇒ 每步核真值, 不通就换轴。

策略: 每轮只发**一条**相对指令(姿态误差优先, 每步 ≤5°; 位置每步 ≤50mm), 发完核真值;
      该步真值没动 ⇒ 记该轴受阻, 换下一条; 全部受阻或超轮次 ⇒ 停(绝不重发)。
用法: gui-venv311/bin/python tools/close_loop_to_point.py --to 侧面点1 [--tol-mm 2 --tol-deg 2 --max-iters 80]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSE = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")
API = "http://127.0.0.1:8793/ctl/move"


def log(*a):
    print(*a, flush=True)


def pose():
    with open(POSE, encoding="utf-8") as fh:
        d = json.load(fh)
    return (np.array([float(d["x"]), float(d["y"]), float(d["z"])]),
            np.array([float(d["qx"]), float(d["qy"]), float(d["qz"]), float(d["qw"])]), float(d["ts"]))


def ang(a, b):
    return math.degrees(2 * math.acos(min(1.0, abs(float(np.dot(a, b))))))


def Rq(v):
    x, y, z, w = [float(a) for a in v]
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def euler_xyz(Rm):
    sy = -Rm[2, 0]
    y = math.asin(max(-1.0, min(1.0, sy)))
    if abs(sy) < 0.9999:
        x = math.atan2(Rm[2, 1], Rm[2, 2])
        z = math.atan2(Rm[1, 0], Rm[0, 0])
    else:
        x = math.atan2(-Rm[1, 2], Rm[1, 1])
        z = 0.0
    return [math.degrees(v) for v in (x, y, z)]


def send(skill, key, val, speed):
    body = {"skill": skill, key: float(val), "speed": float(speed), "arm": 1}
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            o = json.loads(r.read().decode())
        o["_sent"] = skill
        return o
    except Exception as e:                                                        # noqa: BLE001
        return {"ok": False, "err": repr(e)[:140], "_sent": skill}


def blocked_axes_check():
    """快速探测: 哪些方向在当前姿态放行 (每步 5mm/5°, 只探不发大动作)。"""
    res = {}
    for skill, key, val, axis in (("L2.lift", "d_mm", 5.0, "+Z"), ("L2.backward", "d_mm", 5.0, "-X"),
                                  ("L2.forward", "d_mm", 5.0, "+X"), ("L2.left", "d_mm", 5.0, "+Y"),
                                  ("L2.right", "d_mm", 5.0, "-Y"), ("L2.lower", "d_mm", 5.0, "-Z"),
                                  ("L2.rot_a_pos", "deg", 4.0, "A+"), ("L2.rot_b_pos", "deg", 4.0, "B+")):
        p0, q0, _ = pose()
        send(skill, key, val, 1000)
        time.sleep(4.5)
        p1, q1, _ = pose()
        moved = bool(float(np.linalg.norm(p1 - p0)) * 1000 > 0.5 or ang(q0, q1) > 0.5)
        res[axis] = moved
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default="侧面点1")
    ap.add_argument("--tol-mm", type=float, default=2.0)
    ap.add_argument("--tol-deg", type=float, default=2.0)
    ap.add_argument("--rot-chunk", type=float, default=5.0)
    ap.add_argument("--lin-chunk", type=float, default=50.0)
    ap.add_argument("--speed", type=float, default=1000.0)
    ap.add_argument("--max-iters", type=int, default=80)
    ap.add_argument("--no-probe", action="store_true")
    a = ap.parse_args()

    with open(os.path.join(ROOT, "reports/aoi_points/%s.json" % a.to), encoding="utf-8") as fh:
        tgt = json.load(fh)
    tp = np.array([float(x) for x in tgt["pos"][:3]])
    tq = np.array([float(x) for x in tgt["quat"]])

    if not a.no_probe:
        log("── 放行探测 (每轴 5mm/4°, 逐步核真值) ──")
        bl = blocked_axes_check()
        log("   " + "  ".join("%s:%s" % (k, "✅" if v else "❌") for k, v in bl.items()))
    else:
        bl = {}

    hist = []
    t0 = time.time()
    for it in range(1, a.max_iters + 1):
        p, q, ts = pose()
        dp = (tp - p) * 1000.0
        dist = float(np.linalg.norm(dp))
        datt = ang(q, tq)
        if dist <= a.tol_mm and datt <= a.tol_deg:
            log("✅ 到位: 位置差 %.2fmm · 姿态差 %.2f° (第 %d 轮, %.0fs)" % (dist, datt, it, time.time() - t0))
            break
        e = euler_xyz(Rq(q).T @ Rq(tq))
        # 先修姿态(小步, 步长 ∝ 未放行概率低的轴优先 A→B→C), 再修位置
        order = []
        for name, val, key in (("a", e[0], "L2.rot_a_pos" if e[0] > 0 else "L2.rot_a_neg"),
                               ("b", e[1], "L2.rot_b_pos" if e[1] > 0 else "L2.rot_b_neg"),
                               ("c", e[2], "L2.rot_c_pos" if e[2] > 0 else "L2.rot_c_neg")):
            if abs(val) > a.tol_deg:
                order.append((key, "deg", max(-a.rot_chunk, min(a.rot_chunk, val)), "姿态%s %+.1f°" % (name.upper(), val)))
        for axis, val in (("x", dp[0]), ("y", dp[1])):
            if abs(val) > max(a.tol_mm, 1.0):
                if axis == "x":
                    k = "L2.forward" if val > 0 else "L2.backward"
                else:
                    k = "L2.left" if val > 0 else "L2.right"
                order.append((k, "d_mm", max(-a.lin_chunk, min(a.lin_chunk, val)), "位置%s %+.1fmm" % (axis, val)))
        if abs(dp[2]) > max(a.tol_mm, 1.0):
            k = "L2.lift" if dp[2] > 0 else "L2.lower"
            order.append((k, "d_mm", max(-a.lin_chunk, min(a.lin_chunk, dp[2])), "位置Z %+.1fmm" % dp[2]))
        if not order:
            log("ℹ️ 无可用小步 (误差已在容差内或分解为 0)")
            break
        did = False
        for skill, key, val, lab in order:
            if val == 0:
                continue
            p0, q0, _ = pose()
            out = send(skill, key, abs(val), a.speed)
            time.sleep(5.0)
            p1, q1, _ = pose()
            moved = float(np.linalg.norm(p1 - p0)) * 1000
            rotd = ang(q0, q1)
            ok = bool(rotd > 0.4 * abs(val)) if key == "deg" else bool(moved > 0.4 * abs(val))
            log("  [%2d] %-16s %+7.2f  ⇒ %s (位移%.1fmm 姿态%.2f°)" % (
                it, skill, val, "✅" if ok else "❌不动", moved, rotd))
            hist.append({"it": int(it), "skill": str(skill), "val": float(abs(val)), "ok": bool(ok),
                         "moved_mm": float(round(moved, 2)), "rot_deg": float(round(rotd, 2)),
                         "lines": [str(x) for x in (out.get("lines") or [])[-2:]]})
            did = did or ok
            if ok:
                break
        if not did:
            log("⛔ 本轮所有候选轴都被拒 ⇒ 停 (位置差 %.1fmm · 姿态差 %.1f°)" % (dist, datt))
            break
    p, q, ts = pose()
    dp = (tp - p) * 1000.0
    log("── 终态 [%.5f, %.5f, %.5f] · 位置差 %.2fmm · 姿态差 %.2f° · 用时 %.0fs ──" % (
        p[0], p[1], p[2], float(np.linalg.norm(dp)), ang(q, tq), time.time() - t0))
    rep = os.path.join(ROOT, "reports", "close_loop_%s_%s.json" % (a.to, time.strftime("%Y%m%d_%H%M%S")))
    with open(rep, "w", encoding="utf-8") as fh:
        json.dump({"ts": time.time(), "to": a.to, "blocked": bl, "hist": hist,
                   "final": {"p": [round(float(v), 5) for v in p], "pos_err_mm": round(float(np.linalg.norm(dp)), 2),
                             "att_err_deg": round(ang(q, tq), 2)}}, fh, ensure_ascii=False, indent=1)
    log("  报告: %s" % rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
