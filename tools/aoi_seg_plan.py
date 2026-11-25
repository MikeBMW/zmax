#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 251 点相位轨迹裁出 AOI 检测段 (i=166~224), 做逆解 + 预检, 产出可下发轨迹。

为什么只跑这一段:
  251 点里 40 点落在 F668833「检测设备」盒内 (x712~844 / y-91~302 / z0~340),
  集中在 i=1~78 (抓取/扫码/插入/钩拉环) —— 那正是 11-24 20:32 撞机的位置,
  而该围栏至今 enabled=False, precheck 拦不住。
  AOI 段 i=166~224 的 59 点与该盒交集为 0, 且全部 y<-200 (AOI 相机视野区),
  所以这一段既能真跑又不撞, 还能触发检测。

产出:
  zmax_data/capture_plan/aoi_seg_joints.json   真机下发用 (关节, deg)
  zmax_data/capture_plan/aoi_seg_meta.json     相位映射 + 检测触发窗口

用法:
  ./gui-venv311/bin/python tools/aoi_seg_plan.py [--check]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

SRC = os.path.join(REPO, "zmax_data/traj_phase/phase251_20261124/geo_raw.json")
OUT_J = os.path.join(REPO, "zmax_data/capture_plan/aoi_seg_joints.json")
OUT_M = os.path.join(REPO, "zmax_data/capture_plan/aoi_seg_meta.json")

SEG = (166, 224)          # 含首尾
FENCE_BOX = ((712., -91., 0.), (844., 302., 340.))   # F668833, mm


def quat_to_R(q):
    """q = [w, x, y, z] (引擎/8815 口径)。"""
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def load_ik():
    """复用 phase_traj_ik2 的 IK 口径 (避免两套解算)。"""
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import importlib
    m = importlib.import_module("phase_traj_ik2")
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只预检, 不写产物")
    a = ap.parse_args()

    d = json.load(open(SRC, encoding="utf-8"))
    frames, states = d["frames"], d["states"]
    print("源轨迹 %d 点, %d 相位" % (len(frames), len(states)))

    lo, hi = SEG
    seg = [f for f in frames if lo <= f["i"] <= hi]
    P = np.array([f["p"] for f in seg], float)
    print("AOI 段 i=%d~%d, %d 点" % (lo, hi, len(seg)))
    print("  范围 X %.0f~%.0f  Y %.0f~%.0f  Z %.0f~%.0f mm"
          % (P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(),
             P[:, 2].min(), P[:, 2].max()))
    step = np.linalg.norm(np.diff(P, axis=0), axis=1)
    print("  相邻步距 max %.1f mm · 中位 %.1f mm" % (step.max(), np.median(step)))

    # 碰撞盒复核
    blo, bhi = [np.array(v) for v in FENCE_BOX]
    inb = ((P >= blo) & (P <= bhi)).all(1)
    print("  F668833 盒内点数: %d (必须为 0)" % inb.sum())
    if inb.sum():
        print("  ❌ 有碰撞风险, 中止")
        return 2
    # AOI 视野判据
    if not (P[:, 1] < -200).all():
        bad = int((P[:, 1] >= -200).sum())
        print("  ⚠️ 有 %d 点 y>=-200 (不在 AOI 视野), 仍可跑但检测可能空" % bad)
    else:
        print("  ✅ 全部 y<-200 (AOI 视野区)")

    # 相位 -> 段内 cursor 映射 (给触发窗口用)
    meta_phases = []
    for s in states:
        i0, i1 = max(s["i0"], lo), min(s["i1"], hi)
        if i0 > i1:
            continue
        meta_phases.append({
            "name": s["name"], "i0": s["i0"], "i1": s["i1"],
            "cursor0": s["i0"] - lo, "cursor1": s["i1"] - lo,
        })
    print("\n段内相位 (%d 个):" % len(meta_phases))
    for p in meta_phases:
        print("  %-22s i=%3d~%3d → cursor %2d~%2d"
              % (p["name"], p["i0"], p["i1"], p["cursor0"], p["cursor1"]))

    # 检测触发窗口: 静止的"侧面点"相位 (名字含"侧面点"且不含"移动")
    win = [(p["cursor0"], p["cursor1"]) for p in meta_phases
           if "侧面点" in p["name"] and "移动" not in p["name"]]
    print("\nAOI 触发窗口 (段内 cursor): %s" % win)

    meta = {
        "src": os.path.relpath(SRC, REPO),
        "seg": list(SEG),
        "n": len(seg),
        "phases": meta_phases,
        "aoi_windows": win,
        "note": "F668833 检测设备围栏 enabled=False, 但本段与该盒交集为 0; "
                "跑前请复核 /api/fence 未被改动",
    }

    if a.check:
        print("\n(--check) 未写产物")
        return 0

    # ---- IK ----
    ik = load_ik()
    joints, skipped = [], []
    solver = None
    for name in ("solve_ik", "ik_point", "make_solver"):
        if hasattr(ik, name):
            solver = getattr(ik, name)
            break
    if solver is None:
        print("\n⚠️ phase_traj_ik2 未暴露可直接调用的 IK 入口, 改用它产出的 372 帧做映射")
        j372 = os.path.join(REPO, "zmax_data/traj_phase/phase251_20261124/joints_372f.json")
        if not os.path.isfile(j372):
            print("❌ 缺 %s" % j372)
            return 3
        jd = json.load(open(j372, encoding="utf-8"))
        jl = jd["frames"] if isinstance(jd, dict) else jd
        # 372 帧是 251 点的插值扩展: 用 i 索引折算
        n251 = len(frames)
        n372 = len(jl)
        idx = [int(round(p["i"] / max(1, n251 - 1) * (n372 - 1))) for p in seg]
        joints = [jp["j"] for jp in (jl[k] for k in idx)]
        print("从 372 帧取 %d 个关节样本" % len(joints))
    else:
        print("\n用 phase_traj_ik2 的 IK 入口求解…")
        for f in seg:
            R = quat_to_R(f["q"])
            try:
                j = solver(np.array(f["p"], float), R)
                if j is None:
                    skipped.append(f["i"])
                else:
                    joints.append(list(np.asarray(j, float)))
            except Exception as e:                                   # noqa: BLE001
                skipped.append(f["i"])
                print("  #%d 解算异常 %s" % (f["i"], type(e).__name__))
        print("解出 %d 点, 跳过 %d" % (len(joints), len(skipped)))

    out = {"ok": True, "seg": list(SEG), "n": len(joints),
           "frames": [{"i": seg[k]["i"], "j": joints[k]} for k in range(len(joints))],
           "meta": meta}
    os.makedirs(os.path.dirname(OUT_J), exist_ok=True)
    with open(OUT_J, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    with open(OUT_M, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("\n已写 %s (%d 点)" % (os.path.relpath(OUT_J, REPO), len(joints)))
    print("已写 %s" % os.path.relpath(OUT_M, REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
