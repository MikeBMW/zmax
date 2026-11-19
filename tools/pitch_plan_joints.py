#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pitch_plan_joints.py — 在**关节空间**规划「同一 TCP 点 + 俯仰 −15/0/+15°」的姿态序列。

为什么必须走关节空间(2026-11-19 实测教训):
  控制器 cartPosture 的 rpy 在 ±π 附近**表示歧义**: 命令 -15° 后回读成 [0.0004,-1.4013,-3.1247],
  与原 rpy 逐个比差 180°(假差), 但旋转矩阵之间的夹角正好 15°(真差)。
  再按"度/弧度"去试, TCP 直接跑到 675/247/193 ⇒ 用 rpy 步进加俯仰不安全。
  所以: 真机 URDF 里做 FK→绕工具 Y 轴转→IK 回关节角, 用 MoveAbsJ 下发, 全程只认关节真值。

输出: {"base_joints","poses":[{"pitch","joints_deg","joints_rad","pos_err_mm","rot_err_deg","clear_mm"}]}

用法:
  python3 tools/pitch_plan_joints.py --pitches "-15,0,15" --out zmax_data/capture_plan/pitch_joints.json
"""
import argparse
import json
import math
import os
import shutil
import sys

import numpy as np

URDF_SRC = "zmax_data/deliverables/20261107_preoff/state/config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf"
SCRATCH = os.path.expanduser("~/.hermes/cache/scratch/xms5")
TOOL_LEN = 0.2587          # 法兰→TCP(实测 259.8 / 拟合 261.2, 取保守值)
# 对插口姿态的关节真值(2026-11-19 12:31 实测, 当时 TCP 653.0/256.0/171.9)
J_BASE = [0.342214, 0.246983, -2.459296, 0.566751, 0.460537, 0.48606]
PANEL_LO = np.array([0.690, 0.190, 0.150])
PANEL_HI = np.array([0.820, 0.270, 0.330])


def prep_urdf():
    os.makedirs(SCRATCH, exist_ok=True)
    src_dir = os.path.dirname(URDF_SRC)
    for root, _dirs, files in os.walk(src_dir):
        for f in files:
            if f.lower().endswith((".stl", ".STL", ".dae")):
                rel = os.path.relpath(os.path.join(root, f), src_dir)
                dst = os.path.join(SCRATCH, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if not os.path.exists(dst):
                    shutil.copy(os.path.join(root, f), dst)
    dst = os.path.join(SCRATCH, os.path.basename(URDF_SRC))
    shutil.copy(URDF_SRC, dst)
    return dst


def rot_tool_y(R, deg):
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    Ry = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    return R @ Ry


def geod_deg(Ra, Rb):
    tr = float(np.trace(Ra.T @ Rb))
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1.0) / 2.0))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pitches", default="-15,0,15")
    ap.add_argument("--out", default="zmax_data/capture_plan/pitch_joints.json")
    a = ap.parse_args()
    import mujoco

    spec = mujoco.MjSpec.from_file(prep_urdf())
    wb = spec.worldbody
    g = wb.add_geom(); g.name = "panel"; g.type = mujoco.mjtGeom.mjGEOM_BOX
    g.size = list((PANEL_HI - PANEL_LO) / 2); g.pos = list((PANEL_HI + PANEL_LO) / 2)
    m = spec.compile(); d = mujoco.MjData(m)
    link6 = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "XMS5-R800-W4G3B4C_link6")

    def fk(q):
        for i in range(6):
            d.qpos[i] = q[i]
        mujoco.mj_forward(m, d)
        return d.xpos[link6].copy(), d.xmat[link6].reshape(3, 3).copy()

    def ik(pt, Rt, q0, iters=300):
        q = q0.copy()
        for _ in range(iters):
            p, R = fk(q)
            ep = pt - p
            eR = 0.5 * sum(np.cross(R[:, i], Rt[:, i]) for i in range(3))
            if np.linalg.norm(ep) < 5e-4 and np.linalg.norm(eR) < 3e-3:
                break
            J = np.zeros((6, 6))
            for k in range(6):
                dq = q.copy(); dq[k] += 1e-5
                p2, R2 = fk(dq)
                J[:3, k] = (p2 - p) / 1e-5
                dR = R2 @ R.T
                J[3:, k] = np.array([dR[2, 1] - dR[1, 2], dR[0, 2] - dR[2, 0], dR[1, 0] - dR[0, 1]]) / 2 / 1e-5
            e = np.concatenate([ep, eR])
            q = np.clip(q + J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(6), e),
                        m.jnt_range[:6, 0], m.jnt_range[:6, 1])
        p, R = fk(q)
        return q, float(np.linalg.norm(pt - p)), geod_deg(R, Rt)

    def clear_mm(q):
        fk(q)
        dd = mujoco.mj_geomDistance(m, d, link6, mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "panel"), 1.0, None)
        return float(dd) * 1000.0

    q0 = np.array(J_BASE)
    p0, R0 = fk(q0)
    tcp0 = p0 + R0[:, 2] * TOOL_LEN
    print("FK 法兰 %s mm · TCP %s mm (控制器真值 653.0/256.0/171.9)"
          % ((p0 * 1000).round(1), (tcp0 * 1000).round(1)))

    out = {"base_joints": J_BASE, "tcp_mm": (tcp0 * 1000).round(1).tolist(), "poses": []}
    seed = q0
    for pd in [float(v) for v in a.pitches.split(",") if v.strip()]:
        Rt = rot_tool_y(R0, pd)
        # 🔴 2026-11-19 真机实测: 固定**法兰**位姿只转姿态 ⇒ 工具尖(TCP)画圆弧, 259mm×sin(12°)=54.1mm
        #    (脚本的 >25mm 保护把它拦下了, 没有碰撞)。要的是"绕 TCP 转"= 相机盯着插口不动 ⇒
        #    法兰必须跟着平移: p_flange_new = p_tcp - R_new·[0,0,TOOL_LEN]。
        p_new = tcp0 - Rt[:, 2] * TOOL_LEN
        q, perr, rerr = ik(p_new, Rt, seed)
        # 2π 折算: 关节 4/5/6 允许整圈, 取最接近基准的等价写法, 避免甩腕
        qq = q.copy()
        for k in range(6):
            while qq[k] - seed[k] > math.pi:
                qq[k] -= 2 * math.pi
            while qq[k] - seed[k] < -math.pi:
                qq[k] += 2 * math.pi
        q = np.clip(qq, m.jnt_range[:6, 0], m.jnt_range[:6, 1])
        cl = clear_mm(q)
        rec = {"pitch": pd, "joints_rad": [round(float(v), 6) for v in q],
               "joints_deg": [round(math.degrees(float(v)), 2) for v in q],
               "pos_err_mm": round(perr * 1000, 2), "rot_err_deg": round(rerr, 3),
               "clear_mm": round(cl, 1),
               "max_dj_deg": round(float(np.max(np.abs(np.degrees(q - seed)))), 1)}
        out["poses"].append(rec)
        print("俯仰 %+3.0f° · 关节 %s · 位姿误差 %.2fmm/%.3f° · 面板间隙 %.0fmm · 相对基准最大关节变化 %.1f°"
              % (pd, rec["joints_deg"], rec["pos_err_mm"], rec["rot_err_deg"], cl, rec["max_dj_deg"]))
        seed = q

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→ %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
