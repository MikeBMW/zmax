#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_manifold10d.py — 十维流形引擎数学自证 (每项都是可算判据, 不打印象分)

用法:
    gui-venv311/bin/python tools/verify_manifold10d.py [--replay]

判据与阈值(全部实测输出, 失败即非 0 退出):
  1 度规对称/正定/Cholesky/块对角
  2 势能零点与标度 (10mm ⇒ V=0.5)
  3 θ 的 S¹ 环绕 (0.98→0.02 = 0.04)
  4 自然梯度在二次型上 = −ΔX (说明它不能直接当动作)
  5 各向异性 vs 各向同性: 径向动作被压得更狠
  6 硬投影: 越界一定拉回, 残差 = 越界量
  7 IHS 散热齿惩罚倍数 (>100×)
  8 沿 −G⁻¹∇V 的 V 单调下降且终值 <1e-12
  9 单步耗时 < 1ms (1kHz 预算)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.manifold.manifold10d import (  # noqa: E402
    DIM_HIDDEN, DIM_MACRO, build_metric, default_bounds, metric_report,
    pack_state, potential, project_hidden, selftest, sensitivity_from_gains,
    utilization, violation_error,
    to_action6, constrained_step,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", action="store_true", help="用真机位姿真值跑一段投影回放")
    a = ap.parse_args()

    r = selftest(verbose=False)
    m = r["metric"]
    rows = [
        ("① 度规 对称/正定", "sym_err=%.1e · eig_min=%.3e · chol=%s" % (m["sym_err"], m["eig_min"], m["cholesky_ok"]), m["cholesky_ok"]),
        ("② 势能标度 10mm", "V=%.6f (期望 0.5)" % r["potential_10mm"], abs(r["potential_10mm"] - 0.5) < 1e-9),
        ("③ θ 环绕 S¹", "|Δθ|=%.4f (0.98→0.02 期望 0.04)" % r["theta_wrap"], abs(r["theta_wrap"] - 0.04) < 1e-12),
        ("④ 自然梯度= −ΔX", "max_err=%.1e (证: 不能用它当动作)" % r["natural_grad_vs_delta"], r["natural_grad_vs_delta"] < 1e-12),
        ("⑤ 各向异性 径向/轴向", "径向 意图15mm⇒%.2fmm / %.1fN · 轴向⇒%.2fmm · 各向同性径向⇒%.2fmm/%.1fN"
         % (r["aniso_radial_mm"], r["aniso_radial_force_n"], r["aniso_axial_mm"],
            r["iso_radial_mm"], r["iso_radial_force_n"]),
         r["aniso_radial_mm"] < r["iso_radial_mm"] and r["aniso_radial_force_n"] < 18.0 < r["iso_radial_force_n"]),
        ("⑥ QP 硬约束", "越界=%.1e · 余量1N⇒%.3fmm/%.1fN" % (r["qp_worst_violation"], r["headroom_dx_mm"], r["headroom_fx_n"]),
         r["qp_worst_violation"] < 1e-9 and abs(r["headroom_dx_mm"] - 0.5) < 1e-6),
        ("⑦ 散热齿惩罚", "代价倍数=%.1f×" % r["teeth_ratio"], r["teeth_ratio"] > 100),
        ("⑧ 梯度流单调收敛", "final V=%.2e" % r["flow_v_final"], r["flow_monotone"] and r["flow_v_final"] < 1e-12),
        ("⑨ 利用率门控", "盒内放行63%%级 · 3N:%.0f%% / 17N:%.1f%% · 刚度×%.1f"
         % (r["gate_low_ratio"] * 100, r["gate_high_ratio"] * 100, r["gate_stiff_high"]),
         r["gate_high_ratio"] < 0.1 * r["gate_low_ratio"]),
        ("⑩ 节点入口 step10", "util_max=%.2f · 4mm轴向意图⇒%.2fmm" % (r["step10_util_max"], r["step10_action_z_mm"]),
         r["step10_ok"] and r["step10_action_z_mm"] > 3.5),
        ("⑪ 实时性", "单步 %.4f ms (预算 1.0000)" % r["step_ms"], r["step_ms"] < 1.0),
    ]
    print("== 十维流形引擎 (4D 宏观 ⊕ 6D 隐藏) 数学自证 ==")
    for name, detail, ok in rows:
        print("  %-22s %-58s %s" % (name, detail, "PASS" if ok else "FAIL"))
    n_pass = sum(1 for _, _, ok in rows if ok)
    print("  => %d/%d 通过" % (n_pass, len(rows)))

    if a.replay:
        _replay()

    return 0 if n_pass == len(rows) else 1


def _replay() -> None:
    """用真机位姿真值(tcp_out/latest.json) + 力(ft_out 若有) 跑一段投影, 看动作是否合理。"""
    import glob
    import time

    import numpy as np

    pose_f = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")
    if not os.path.exists(pose_f):
        print("  [replay] 没有位姿真值 %s, 跳过" % pose_f)
        return
    d = json.load(open(pose_f, encoding="utf-8"))
    xyz = [d["x"], d["y"], d["z"]]
    age = time.time() - os.path.getmtime(pose_f)
    ft = sorted(glob.glob(os.path.join(ROOT, "zmax_data/rokae_sdk/ft_out/*.jsonl")),
                key=os.path.getmtime)
    force = [0.0, 0.0, 0.0]
    fsrc, fmtime = "(none)", 0.0
    if ft:
        try:
            with open(ft[-1], encoding="utf-8") as fh:      # 只读最后一行, 不整文件载入(58MB+)
                fh.seek(max(0, os.path.getsize(ft[-1]) - 4000))
                last = fh.read().strip().splitlines()[-1]
            j = json.loads(last)
            force = [float(j.get("fx", 0)), float(j.get("fy", 0)), float(j.get("fz", 0))]
            fsrc = str(j.get("src", "?"))[:46]
            fmtime = time.time() - os.path.getmtime(ft[-1])
        except Exception:                                              # noqa: BLE001
            pass

    from lerobot.manifold.manifold10d import step10
    cases = ((0.42, [0.005, 0.0, 0.0, 0.0], "接近段·径向 5mm"),
             (0.42, [0.0, 0.0, 0.004, 0.02], "接近段·轴向 4mm"),
             (0.92, [0.006, 0.003, 0.004, 0.05], "插入段·横向6+3/轴向4mm"))
    print("  [replay] 真实现场: 力=(%.2f,%.2f,%.2f)N · 位姿=(%.4f,%.4f,%.4f)m"
          % (force[0], force[1], force[2], xyz[0], xyz[1], xyz[2]))
    for prog, intent, tag in cases:
        out = step10({"in1": {"value": {"xyz": xyz, "progress": prog}},
                      "in2": {"value": {"force": force, "tol_normal_mm": 0.05,
                                        "tol_tangent_mm": 0.20, "conf": 0.93}},
                      "in3": {"value": {"delta": intent}}})
        a = out["action6"]
        print("  [replay] %-18s 意图 dx=%5.1f dy=%5.1f dz=%5.1f mm ⇒ 实得 dx=%5.2f dy=%5.2f dz=%5.2f mm · "
              "util=%.2f 刚度×%.0f 越界=%.1e"
              % (tag, intent[0] * 1e3, intent[1] * 1e3, intent[2] * 1e3,
                 a[0] * 1e3, a[1] * 1e3, a[2] * 1e3,
                 out["gate"]["util_max"], out["stiffness_gain"], out["violation_after"]))
    print("  [replay] 位姿帧龄 %.1fs · 力源=%s (帧龄 %.1fs) · 起点=(%.4f,%.4f,%.4f)m"
          % (age, fsrc, fmtime, xyz[0], xyz[1], xyz[2]))
    if "Torque" in fsrc:
        print("  [口径] ⚠ 力分量当前取的是 getEndTorque(N·m), 当力(N)用只是量级代理;"
              " 要真力需乘力臂或换 6 维力传感器(卡点, 见报告)")


if __name__ == "__main__":
    raise SystemExit(main())
