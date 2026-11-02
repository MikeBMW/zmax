#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rot_precision_sweep.py — 姿态(相对旋转)精度实测: 解算器到底能不能解出夹持歪斜。

为什么单独测: 2026-09-18 的自检只打分了 3D 中心与框 IoU, 没打旋转; 而 11-03 把 quat
写进契约后, 能不能做"按姿态插拔"全看这个旋转准不准。

做法 (与 box3d_solver_selftest 同一套真代码, 只把真值旋转设成非零):
  · 真值: 模块相对工具系歪斜 R_rel_true = Rz(12°)Ry(-4°)Rx(6°)  (= [6,-4,12] 度),
    模块中心 OFF_TRUE = [0,-90,0] mm, 尺寸 40×16×12 mm。
  · 观测: 只给 (图像里抠出来的 AABB + 0.5px/2.0px 噪声, TCP, TCP 四元数); 真值只用于打分。
  · 变量: 帧数 40/80/160 · 框噪声 0.5/2.0 px · 姿态散布 12°/25° · 是否联合估计旋转。
  · 判据: 旋转误差 (度) ≤ 5° 才算能做朝向对齐; ≤ 2° 才算能精插。
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_REPO, "src", "lerobot", "policies", "yolo_3d"))

import real_probe_dryrun_selftest as RS                                   # noqa: E402
from mono23d_experiment import OFF_TRUE, SIZE, pose_set                   # noqa: E402
from box3d_solver import Box3DSolver                                     # noqa: E402

W, H = 640, 480
MOD_RGB = (218, 208, 196)
RREL_TRUE_DEG = (6.0, -4.0, 12.0)          # 与 2026-09-18 存盘同值 (roll, pitch, yaw)


def R_euler_deg(deg):
    a, b, c = [math.radians(float(v)) for v in deg]
    Rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    Ry = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    return Rz @ Ry @ Rx


def rot_err_deg(R1, R2):
    R = np.asarray(R1, float).T @ np.asarray(R2, float)
    c = max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))
    return math.degrees(math.acos(c))


def detect_box(img_rgb):
    m = (np.abs(img_rgb.astype(int) - np.array(MOD_RGB)).sum(2) < 60)
    ys, xs = np.nonzero(m)
    if len(xs) < 20:
        return None
    return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]


def build_samples(n, tilt_deg, noise_px, seed=2026):
    """渲染 n 帧: 模块相对工具系带 6/-4/12 度歪斜。真值不外传。"""
    R_rel = R_euler_deg(RREL_TRUE_DEG)
    poses, cam = pose_set(n, 0.125, tilt_deg, seed, "big")
    P_true, _axes = cam
    rng = np.random.default_rng(seed)
    base = RS.static_scene()
    out = []
    for tcp, R_tool in poses:
        Rs = R_tool @ R_rel
        c = np.asarray(tcp, float) + Rs @ OFF_TRUE
        q = RS.rot_to_quat(Rs)
        img = RS.render(base, P_true, c, q, SIZE, gripper_tcp=tcp)
        bx = detect_box(img)
        if bx is None:
            continue
        out.append(([v + rng.normal(0, noise_px) for v in bx],
                    [float(v) for v in tcp], q, Rs.tolist()))
    return out


def fit_and_score(samples, n_use, use_rrel, use_scale=False):
    slv = Box3DSolver(size_mm=[s * 1000 for s in SIZE], img_wh=(W, H))
    for bx, tcp, q, _ in samples[:n_use]:
        slv.add(bx, tcp, q)
    r = slv.fit(use_rrel=use_rrel, use_scale=use_scale)
    R_rel_true = R_euler_deg(RREL_TRUE_DEG)
    out = {"ok": bool(r.get("ok")), "rms_px": r.get("rms_px"), "holdout_px": r.get("holdout_rms_px")}
    if r.get("rrel_deg"):
        out["rrel_fit_deg"] = [round(float(v), 2) for v in r["rrel_deg"]]
        out["rot_err_deg"] = round(rot_err_deg(R_euler_deg(r["rrel_deg"]), R_rel_true), 2)
    else:
        out["rrel_fit_deg"] = None
        out["rot_err_deg"] = None
    if r.get("off_mm"):
        out["off_err_mm"] = round(float(np.linalg.norm(np.asarray(r["off_mm"]) - OFF_TRUE * 1000)), 1)
    if r.get("size_mm"):
        out["size_mm"] = [round(float(v), 1) for v in r["size_mm"]]
    # 中心误差: 用预测位姿 (TCP + R_tool·R_rel·off) 对真值中心
    errs = []
    for bx, tcp, q, Rs in samples[:n_use]:
        Rt = np.asarray(Rs, float)          # 真值: 模块在位姿下的实际朝向 (打分用)
        # 用解出的 off + 解出的 rrel 预测: c = tcp + Rt·off  (Rt 用的是该帧真实朝向)
        # 这里只用 off 判中心, 因为 R_rel 误差已单列
        if r.get("off_mm"):
            c_pred = np.asarray(tcp, float) + Rt @ (np.asarray(r["off_mm"], float) / 1000.0)
            errs.append(float(np.linalg.norm(c_pred - (np.asarray(tcp, float) + Rt @ OFF_TRUE))) * 1000)
    if errs:
        out["center_err_mm_median"] = round(float(np.median(errs)), 2)
    return out


def main():
    print("═══ 姿态(相对旋转)精度实测 · 真值歪斜 6/-4/12 度 ═══")
    print("变量: 帧数 × 框噪声 × 姿态散布 × 是否联合估计旋转")
    rows = []
    cache = {}
    for tilt in (12.0, 25.0):
        for noise in (0.5, 2.0):
            key = (tilt, noise)
            samples = build_samples(160, tilt, noise)
            cache[key] = samples
            print("\n— 姿态散布 %2.0f° · 框噪声 %.1f px → 可用 %d 帧" % (tilt, noise, len(samples)))
            for n_use in (40, 80, 160):
                for use_rrel in (False, True):
                    res = fit_and_score(samples, n_use, use_rrel)
                    tag = "%2.0f°·%.1fpx·%3d帧·%s" % (tilt, noise, n_use, "联合估旋转" if use_rrel else "不估旋转")
                    rows.append(dict(tilt=tilt, noise=noise, n=n_use, use_rrel=use_rrel, **res))
                    print("   %s → 旋转误差 %s · off误差 %s mm · rms %s px · size %s"
                          % (tag,
                             ("%5.2f°" % res["rot_err_deg"]) if res.get("rot_err_deg") is not None else "  n/a ",
                             res.get("off_err_mm"), res.get("rms_px"), res.get("size_mm")))
    # 结论
    best = [r for r in rows if r.get("rot_err_deg") is not None]
    ok5 = [r for r in best if r["rot_err_deg"] <= 5.0]
    ok2 = [r for r in best if r["rot_err_deg"] <= 2.0]
    print("\n═══ 结论 ═══")
    print("  能做到 ≤5° 的配置: %d/%d    ≤2° 的配置: %d/%d" % (len(ok5), len(rows), len(ok2), len(rows)))
    if best:
        b = min(best, key=lambda r: r["rot_err_deg"])
        print("  最好: %2.0f°·%.1fpx·%d帧·%s → %s° (off误差 %s mm)"
              % (b["tilt"], b["noise"], b["n"], "联合" if b["use_rrel"] else "不估",
                 b["rot_err_deg"], b.get("off_err_mm")))
    out = os.path.join(_REPO, "zmax_data", "rot_precision_sweep.json")
    json.dump({"truth": {"rrel_deg": list(RREL_TRUE_DEG), "off_mm": [0, -90, 0], "size_mm": [40, 16, 12]},
               "rows": rows}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("  明细: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
