#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""se3_pose_path.py — 段表 → SE(3) 位姿轨迹 (位置 + 姿态四元数), 给执行端逐拍跟踪

存在的理由 (老倪: 「四元数是数学游标卡尺, 算这条轨迹=精准执行那个动作」)
  要让这句话成立, 计划里**必须有姿态流**。当前 AR 段表 (8797 /api/sim_insert, 392 段) 只有
  a/b 位置 + t, **0/392 段带 quat** —— 所以"算轨迹"只对位置有信息, 对姿态没有信息, 不能称执行尺子。
  本工具把缺的那一层显式化并可验收:
    · 位置: 段内直线插值 + S曲线时间归一 (与段表 t 对齐, 不额外加时)
    · 姿态: 有 quat 就 slerp (S³ 测地线, 最短弧, 双覆盖已商); 没有就 hold 上一姿态并如实标 quat_src
    · 判据: 到位 = 位置≤tol AND 姿态≤deg_tol (连续两次), 缺姿态 ⇒ 报 unverified (fail-closed)

用法
  python3 tools/se3_pose_path.py                      # 真段表 → 轨迹 + 缺口报告
  python3 tools/se3_pose_path.py --quat 0,0,0,1       # 指定常量姿态 (演示; 标 quat_src=arg)
  python3 tools/se3_pose_path.py --tol-mm 0.5 --tol-deg 0.5 --hz 10
输出
  zmax_data/ss_live/se3_pose_trace.json   逐拍位姿 (q/R/pos/t/seg/quat_src)
  reports/se3_pose_path.json              汇总 + 判据 (ok / blocked / 缺口原因)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space"))

import numpy as np                                            # noqa: E402

import pose_caliper as pc                                     # noqa: E402

API = os.environ.get("SS_PLAN_API", "http://127.0.0.1:8797/api/sim_insert")
OUT_TRACE = os.path.join(ROOT, "zmax_data", "ss_live", "se3_pose_trace.json")
OUT_REPORT = os.path.join(ROOT, "reports", "se3_pose_path.json")


def load_plan():
    with urllib.request.urlopen(API, timeout=20) as r:
        d = json.loads(r.read().decode("utf-8"))
    return d.get("plan") or [], d


def s_curve(u: float) -> float:
    """5 次最小加加速度 (0→1, 端点速度/加速度为 0) —— 与段表 t 同段内, 不加总时长。"""
    u = float(np.clip(u, 0.0, 1.0))
    return 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5


def seg_quat(seg, fallback_q, default_src):
    """段姿态: 段里带 quat 就用 (标 quat_src=段表); 否则 hold fallback (标来源)。"""
    q = seg.get("quat")
    if q and len(q) == 4:
        return pc.canonical(q), (seg.get("quat_src") or "段表")
    return fallback_q, default_src


def build(plan, const_quat=None, hz=10.0):
    """段表 → 逐拍 SE(3) 位姿。返回 (trace, stats)"""
    if const_quat is not None:
        q_hold = pc.canonical(const_quat)
        hold_src = "arg(常量姿态, 非计划姿态)"
    else:
        q_hold = np.array([1.0, 0.0, 0.0, 0.0])      # 单位姿态 = 无旋转 (如实标注)
        hold_src = "none(无姿态源→单位/hold)"
    trace, n_seg_with_quat, n_seg = [], 0, 0
    max_step_deg, max_step_mm = 0.0, 0.0
    pos_prev = None
    for seg in plan:
        a = np.asarray(seg.get("a") or [0, 0, 0], float) / 1000.0
        b = np.asarray(seg.get("b") or a.tolist(), float) / 1000.0
        t_seg = float(seg.get("t") or 0.0)
        if t_seg <= 0:
            continue
        qa, src_a = seg_quat(seg, q_hold, hold_src)
        qb, src_b = seg_quat(seg, q_hold, hold_src)
        if src_a != hold_src:
            n_seg_with_quat += 1
        n_seg += 1
        n = max(2, int(round(t_seg * hz)))
        for i in range(n + 1):
            u = i / float(n)
            p = a + (b - a) * s_curve(u)
            q = pc.slerp(qa, qb, s_curve(u)) if not np.allclose(qa, qb) else qa
            if pos_prev is not None:
                max_step_mm = max(max_step_mm, float(np.linalg.norm(p - pos_prev)) * 1000.0)
            if trace:
                max_step_deg = max(max_step_deg, float(np.degrees(pc.s3_angle(trace[-1]["q"], q))) * 2.0)
            pos_prev = p
            trace.append({"pos_mm": [round(float(x) * 1000.0, 3) for x in p],
                          "q": [round(float(x), 9) for x in q],
                          "theta_so3_deg": round(np.degrees(pc.theta_so3(q)), 6),
                          "seg": seg.get("seq"), "kind": seg.get("kind"),
                          "label": seg.get("label"), "quat_src": src_a,
                          "t": round(float(i) / hz, 4)})
        q_hold = qb
    # 姿态总弧长 (S³) 与物理转角
    arc = 0.0
    for i in range(1, len(trace)):
        arc += pc.s3_angle(trace[i - 1]["q"], trace[i]["q"])
    stats = {
        "n_seg": n_seg, "n_seg_with_quat": n_seg_with_quat,
        "quat_coverage": round(n_seg_with_quat / max(1, n_seg), 4),
        "n_sample": len(trace), "hz": hz,
        "max_step_pos_mm": round(max_step_mm, 4),
        "max_step_rot_deg": round(max_step_deg, 6),
        "rot_arc_deg_total": round(np.degrees(2.0 * arc), 6),
        "hold_src": hold_src,
        "dur_s": round(len(trace) / hz, 3),
    }
    return trace, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quat", default=None, help="x,y,z,w 常量姿态 (演示)")
    ap.add_argument("--tol-mm", type=float, default=0.5)
    ap.add_argument("--tol-deg", type=float, default=0.5)
    ap.add_argument("--hz", type=float, default=10.0)
    a = ap.parse_args()
    plan, d = load_plan()
    cq = [float(x) for x in a.quat.split(",")] if a.quat else None
    trace, st = build(plan, const_quat=cq, hz=a.hz)
    if trace:
        last = trace[-1]
        goal = np.asarray(plan[-1].get("b") or [0, 0, 0], float)
        err_mm = float(np.linalg.norm(np.asarray(last["pos_mm"], float) - goal))
    else:
        err_mm = None
    blocked = []
    if st["n_seg_with_quat"] == 0:
        blocked.append("段表 0/%d 段带 quat ⇒ 姿态流不存在 (只能 hold/单位), "
                       "「算轨迹=执行动作」对**姿态**不成立" % st["n_seg"])
    if st["rot_arc_deg_total"] == 0.0:
        blocked.append("姿态弧长 0.000° ⇒ 这条轨迹里没有姿态变化, 不能当执行尺子")
    rep = {"plan_src": API, "n_plan_seg": len(plan), "stats": st,
           "end_pos_err_mm": None if err_mm is None else round(err_mm, 6),
           "criteria": {"tol_mm": a.tol_mm, "tol_deg": a.tol_deg, "hz": a.hz},
           "blocked": blocked,
           "ok": bool(not blocked and err_mm is not None and err_mm <= a.tol_mm)}
    os.makedirs(os.path.dirname(OUT_TRACE), exist_ok=True)
    os.makedirs(os.path.dirname(OUT_REPORT), exist_ok=True)
    with open(OUT_TRACE, "w", encoding="utf-8") as f:
        json.dump({"meta": st, "trace": trace}, f, ensure_ascii=False)
    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
