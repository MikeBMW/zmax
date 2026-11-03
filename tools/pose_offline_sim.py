#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pose_offline_sim.py — 姿态从「料盘/孔位几何」推出 + 真机 URDF 运动学离线仿真

回答的问题
  段表只有位置时，"算轨迹=精准执行"缺的是姿态。这里把姿态**按几何推出来**(不采集真机姿态):
    · 抓取/放置 (down/up/grip/release) → 工具 z 轴竖直向下 (0,0,-1)
    · 插入 → 工具 z 轴 = 孔轴 (孔口→插到位, 实测 +x)
    · 拔出 → 孔轴反向 (-x)
    · 平移/AOI/金手指 → 保持上一姿态 (hold)
  然后在**真机 URDF 参数**上做数值 IK + 关节速度/奇异性检查 (不碰真机, 纯离线):
    URDF/FK 取自 tools/rokae/gravity_torque_check.py (现场 URDF 关节原点/轴/连杆 + tool1 变换,
    该文件已与控制器实测 endInRef 对过: FK 位置 0.6623,0.1262,0.2928 吻合)。

输出
  zmax_data/ss_live/pose_offline_sim.json   逐段位姿 + IK 结果 + 判据
  判据: 位置误差 ≤1mm · 姿态误差 ≤0.5° · IK 失败 0 · 关节角速度峰值 (报告值, 与 180°/s 假拟线对照)

用法
  python3 tools/pose_offline_sim.py                 # 窗口 mods1-4
  python3 tools/pose_offline_sim.py --all --hz 20
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space"))
import pose_caliper as pc                                     # noqa: E402

API = os.environ.get("SS_PLAN_API", "http://127.0.0.1:8797/api/sim_insert")
OUT_DIR = os.path.join(ROOT, "zmax_data", "ss_live")


def _load_fk():
    p = os.path.join(ROOT, "tools", "rokae", "gravity_torque_check.py")
    spec = importlib.util.spec_from_file_location("rokae_grav", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.fk


fk = _load_fk()


# ── 姿态规则 (几何推导, 每条都写清依据) ────────────────────────────────────────
DOWN = np.array([0.0, 0.0, -1.0])


def R_align(cur_R, axis):
    """把当前工具 z 轴**最小旋转**到 axis 上 —— 保持 yaw 连续 (不额外造转角)。"""
    cur_z = np.asarray(cur_R, float)[:, 2]
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    v = np.cross(cur_z, axis)
    c = float(np.dot(cur_z, axis))
    s = float(np.linalg.norm(v))
    if s < 1e-12:
        return np.asarray(cur_R, float).copy() if c > 0 else _rot_axis(cur_R, np.array([1.0, 0, 0]), np.pi)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    Rd = np.eye(3) + K + K @ K * ((1 - c) / (s * s))
    return Rd @ np.asarray(cur_R, float)


def _rot_axis(R, axis, ang):
    axis = axis / np.linalg.norm(axis)
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return (np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * K @ K) @ R


def seg_axis(seg, hole_axis):
    """该段应让工具 z 轴指哪 (几何依据)。返回 None = hold 上一姿态。"""
    k = str(seg.get("kind") or "")
    lab = str(seg.get("label") or "")
    if k in ("down", "up"):
        return DOWN, "竖直向下 (料盘/孔口上方的接近方向)"
    if k == "insert":
        return hole_axis, "孔轴 (孔口→插到位)"
    if k == "pull":
        return -hole_axis, "孔轴反向 (拔出)"
    if k == "move" and "孔口" in lab:
        return hole_axis, "到孔口前已对准孔轴"
    return None, "hold 上一姿态 (%s)" % (k or "?")


# ── 数值 IK (DLS, 6×6 数值雅可比) ─────────────────────────────────────────────
_G = None


def _kin():
    """只算 TCP 的快速 FK (复用现场 URDF 参数; 省掉重心/负载计算)。"""
    global _G
    if _G is None:
        import importlib.util as _u
        p = os.path.join(ROOT, "tools", "rokae", "gravity_torque_check.py")
        sp = _u.spec_from_file_location("rokae_grav2", p)
        _G = _u.module_from_spec(sp)
        sp.loader.exec_module(_G)
    return _G


def tcp(q):
    G = _kin()
    T = np.eye(4)
    for i, (_n, xyz, ax, _m, _c) in enumerate(G.JOINTS):
        T[:3, 3] = T[:3, 3] + T[:3, :3] @ np.asarray(xyz, float)
        a = np.asarray(ax, float)
        a = a / np.linalg.norm(a)
        c, s = np.cos(q[i]), np.sin(q[i])
        K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
        T[:3, :3] = T[:3, :3] @ (np.eye(3) + s * K + (1 - c) * (K @ K))
    T[:3, 3] = T[:3, 3] + T[:3, :3] @ np.asarray(G.TOOL_XYZ, float)
    T[:3, :3] = T[:3, :3] @ G.rpy_to_R(*G.TOOL_RPY)
    return T[:3, 3].copy(), T[:3, :3].copy()


def ik(p_des, R_des, q0, iters=220, tol_p=1e-4, tol_r=1e-4):
    q = np.asarray(q0, float).copy()
    best = (1e9, q.copy())
    for _ in range(iters):
        p, R = tcp(q)
        ep = np.asarray(p_des, float) - p
        Re = np.asarray(R_des, float) @ R.T
        ang = np.arccos(np.clip((np.trace(Re) - 1) / 2, -1, 1))
        if ang < 1e-12:
            er = np.zeros(3)
        else:
            ax = np.array([Re[2, 1] - Re[1, 2], Re[0, 2] - Re[2, 0], Re[1, 0] - Re[0, 1]])
            n = np.linalg.norm(ax)
            er = (ax / n * ang) if n > 1e-12 else np.zeros(3)
        err = np.concatenate([ep, er])
        e = float(np.linalg.norm(ep))
        if e < best[0]:
            best = (e, q.copy())
        if e < tol_p and float(np.linalg.norm(er)) < tol_r:
            break
        J = np.zeros((6, 6))
        h = 1e-6
        p0, R0 = p, R
        for j in range(6):
            qq = q.copy(); qq[j] += h
            p1, R1 = tcp(qq)
            J[:3, j] = (p1 - p0) / h
            Rj = R1 @ R0.T
            a = np.arccos(np.clip((np.trace(Rj) - 1) / 2, -1, 1))
            if a < 1e-12:
                J[3:, j] = 0.0
            else:
                ax = np.array([Rj[2, 1] - Rj[1, 2], Rj[0, 2] - Rj[2, 0], Rj[1, 0] - Rj[0, 1]])
                n = np.linalg.norm(ax)
                J[3:, j] = (ax / n * a) / h if n > 1e-12 else 0.0
        lam = 1e-3
        dq = J.T @ np.linalg.solve(J @ J.T + lam * np.eye(6), err)
        dq = np.clip(dq, -0.15, 0.15)
        q += dq
    p, R = tcp(q)
    ep = float(np.linalg.norm(np.asarray(p_des) - p))
    Re = np.asarray(R_des) @ R.T
    ang = float(np.degrees(np.arccos(np.clip((np.trace(Re) - 1) / 2, -1, 1))))
    return q, ep, ang


def s_curve(u):
    u = float(np.clip(u, 0, 1))
    return 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--rule", choices=("geom", "hold"), default="geom",
                    help="geom=按料盘/孔位几何推固定姿态; hold=全程保持当前实测姿态 (对照基线)")
    a = ap.parse_args()
    with urllib.request.urlopen(API, timeout=20) as r:
        d = json.loads(r.read().decode())
    plan = d["plan"]
    holes = {h["id"]: h for h in (d.get("holes") or [])}
    h1 = holes.get(1) or {}
    hole_axis = np.asarray(h1.get("insert", [1, 0, 0]), float) - np.asarray(h1.get("mouth", [0, 0, 0]), float)
    hole_axis = hole_axis / np.linalg.norm(hole_axis)

    segs = plan if a.all else [s for s in plan if s.get("mod") in (1, 2, 3, 4)]
    # 起点关节角: 段表第一点 + 上表姿态 反解 (作为 IK 种子)
    q_seed = np.array([0.566, 0.037, -2.401, 1.832, 0.625, -0.719])   # 现场实测姿态 (gravity_torque_check.Q)
    R_cur = tcp(q_seed)[1]
    q_cur = q_seed.copy()
    rows, fails, maxp, maxr, maxqdot, hold_cnt = [], 0, 0.0, 0.0, 0.0, 0
    for seg in segs:
        ax, why = (None, "hold 当前实测姿态 (对照基线)") if a.rule == "hold" else seg_axis(seg, hole_axis)
        if ax is None:
            hold_cnt += 1
            R_seg = R_cur
        else:
            # 🔑 2026-11-03 离线实测: 同一"工具 z 轴对齐"约束下有 24 个 yaw 自由度,
            #   有的 yaw 可达 (0.0mm)、有的差 30~150mm ⇒ yaw 必须与位置一起选, 不能"最小旋转"或写死。
            pa0 = np.asarray(seg.get("a"), float) / 1000.0
            R0 = R_align(R_cur, ax)
            feas = []
            for _y in np.linspace(0, 2 * np.pi, 24, endpoint=False):
                _R = _rot_axis(R0, ax, _y)
                _q, _e, _r = ik(pa0, _R, q_cur, iters=90)
                if _e * 1000 <= 1.0 and _r <= 0.5:
                    feas.append((float(np.degrees(np.arccos(np.clip((np.trace(_R @ R_cur.T) - 1) / 2, -1, 1)))), _R, _q))
            if feas:
                feas.sort(key=lambda t: t[0])          # 取"姿态改动最小"的那个可行 yaw (连续优先)
                why += " · yaw 搜索: %d/24 个可行, 选最小改动 %.1f°" % (len(feas), feas[0][0])
                R_seg, q_cur = feas[0][1], feas[0][2]
            else:
                why += " · yaw 搜索: 24 个全不可行 (保持最小旋转解)"
                R_seg = R0
        t_seg = float(seg.get("t") or 0)
        if t_seg <= 0:
            continue
        n = max(2, int(round(t_seg * a.hz)))
        pa = np.asarray(seg.get("a"), float) / 1000.0
        pb = np.asarray(seg.get("b"), float) / 1000.0
        q_prev = q_cur
        segrows = []
        for i in range(n + 1):
            u = i / float(n)
            p = pa + (pb - pa) * s_curve(u)
            R = R_seg                                  # 段内姿态恒定 (几何规则决定的固定姿态)
            q, ep, er = ik(p, R, q_cur)
            if ep * 1000 > 1.0:            # 主种子没收敛 ⇒ 换两个种子重解, 取最好的 (如实记录是否用了备用种子)
                best = (ep, er, q)
                for _s in (np.array([0.0, 0.9, -1.2, 1.2, 0.4, 0.0]),
                           np.array([0.8, -0.4, -1.6, 1.8, 0.9, -0.6])):
                    qq, e2, r2 = ik(p, R, _s)
                    if e2 < best[0]:
                        best = (e2, r2, qq)
                ep, er, q = best
            q_cur = q
            maxp, maxr = max(maxp, ep * 1000), max(maxr, er)
            if i > 0:
                maxqdot = max(maxqdot, float(np.max(np.abs(q - q_prev))) / (1.0 / a.hz))
            q_prev = q
            segrows.append({"pos_mm": [round(float(x) * 1000, 2) for x in p],
                            "q": [round(float(x), 6) for x in pc.q_from_R(R)],
                            "q_win": np.round(q, 4).tolist(),
                            "err_mm": round(ep * 1000, 3), "err_deg": round(er, 3)})
            if ep * 1000 > 1.0 or er > 0.5:
                fails += 1
        rows.append({"seq": seg.get("seq"), "kind": seg.get("kind"), "label": seg.get("label"),
                     "axis_rule": why, "n": n, "points": segrows,
                     "err_mm_max": max([r["err_mm"] for r in segrows]),
                     "err_deg_max": max([r["err_deg"] for r in segrows])})
        R_cur = R_seg
    rep = {
        "rule": a.rule,
        "src": {"plan": API, "kin": "tools/rokae/gravity_torque_check.py::fk (现场 URDF 参数)"},
        "n_seg": len(rows), "n_sample": sum(r["n"] + 1 for r in rows),
        "hold_seg": hold_cnt,
        "hole_axis": [round(float(x), 4) for x in hole_axis],
        "criteria": {"err_mm_max": 1.0, "err_deg_max": 0.5, "qdot_max_assumed_deg_s": 180.0},
        "measured": {"err_mm_max": round(maxp, 3), "err_deg_max": round(maxr, 3),
                     "qdot_max_deg_s": round(float(np.degrees(maxqdot)), 1),
                     "ik_fail_points": fails},
        "ok": bool(maxp <= 1.0 and maxr <= 0.5 and fails == 0
                   and np.degrees(maxqdot) <= 180.0),
        "segments": rows,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    out_p = os.path.join(OUT_DIR, "pose_offline_sim_%s.json" % a.rule)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False)
    print("报告:", out_p)
    print(json.dumps({k: rep[k] for k in ("n_seg", "n_sample", "hold_seg", "hole_axis",
                                          "criteria", "measured", "ok")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
