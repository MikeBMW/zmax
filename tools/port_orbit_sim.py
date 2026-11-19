#!/usr/bin/env python3
"""port_orbit_sim.py — 用真实 URDF(XMS5-R800) 在 MuJoCo 里核验"插口特写补采"航路是否碰撞。

关键实测(2026-11-19):
  URDF 的 tool0 = **法兰**, 而控制器 endInRef 的 TCP 在法兰前 258.7mm (工具长度)。
  证据: 用现场实时关节角做 FK, 法兰 441.5/252.9/325.1, 控制器 TCP 653.1/256.0/172.0,
        差值 (211.6, 3.1, -153.1) 模长 261mm ≈ 工具 258.7mm。
  ⇒ 航点(TCP)必须先换算成法兰位姿  flange = TCP - 0.2587 * R[:,2] 才能解 IK。

判据:
  ① IK 收敛 (法兰位姿误差 < 1mm / 0.2°)
  ② MuJoCo 接触: 除"工具"外任何臂连杆与工装面板/台面有接触 ⇒ 失败
  ③ 连杆到面板的最小间隙 ≥ 20mm
"""
import argparse
import json
import math
import os
import shutil

import numpy as np

SCRATCH = "/home/ubuntu/.hermes/cache/scratch/xms5"
URDF_SRC = "zmax_data/deliverables/20261107_preoff/state/config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf"
MESH_SRC = "zmax_data/deliverables/20261107_preoff/state/config/moveit_xms5/urdf/meshes/xms5_r800_w4g3b4c_meshes"
TOOL_LEN = 0.2587
PANEL_LO = np.array([0.758, 0.140, 0.095])
PANEL_HI = np.array([0.835, 0.300, 0.285])


def prep_urdf():
    os.makedirs(SCRATCH, exist_ok=True)
    dst = os.path.join(SCRATCH, os.path.basename(URDF_SRC))
    if not os.path.exists(dst):
        shutil.copy(URDF_SRC, dst)
    for f in os.listdir(MESH_SRC):
        p = os.path.join(SCRATCH, f)
        if not os.path.exists(p):
            shutil.copy(os.path.join(MESH_SRC, f), p)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="zmax_data/capture_plan/port_orbit.json")
    ap.add_argument("--min-clear", type=float, default=0.020)
    a = ap.parse_args()
    import mujoco

    plan = json.load(open(a.plan, encoding="utf-8"))
    src = plan.get("pts_mm") or [w["tcp_mm"] for w in plan.get("waypoints") or [] if w.get("tcp_mm")]
    tcp_pts = [np.array(p, dtype=float) / 1000.0 for p in src]
    rpy0 = np.array(plan.get("rpy0") or [-2.9484, -1.5163, -0.1782])

    def rpy_to_R(r, p, y):
        cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
        return (np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]]) @
                np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]]) @
                np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]]))
    R0 = rpy_to_R(*rpy0)

    urdf = prep_urdf()
    spec = mujoco.MjSpec.from_file(urdf)
    wb = spec.worldbody
    # 台面
    g = wb.add_geom()
    g.name = "table"
    g.type = mujoco.mjtGeom.mjGEOM_BOX
    g.size = [0.58, 0.55, 0.005]
    g.pos = [0.62, 0.22, -0.005]   # 台面避开机器人基座(x<0.05 是基座)
    # 插口工装面板 (口沿平面 x=0.758 之后是实体)
    g2 = wb.add_geom()
    g2.name = "panel"
    g2.type = mujoco.mjtGeom.mjGEOM_BOX
    g2.size = list((PANEL_HI - PANEL_LO) / 2)
    g2.pos = list((PANEL_HI + PANEL_LO) / 2)
    m = spec.compile()
    d = mujoco.MjData(m)

    tool_geoms = set()
    for i in range(m.ngeom):
        bn = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[i]) or ""
        if "link6" in bn or "tool" in bn:
            tool_geoms.add(i)
    panel_id = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "panel")
    table_id = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "table")

    def fk_flange(q):
        for i in range(min(6, m.nq)):
            d.qpos[i] = q[i]
        mujoco.mj_forward(m, d)
        b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "XMS5-R800-W4G3B4C_link6")
        return d.xpos[b].copy(), d.xmat[b].reshape(3, 3).copy()

    def ik(target_p, target_R, q0, iters=300):
        q = q0.copy()
        for _ in range(iters):
            p, R = fk_flange(q)
            ep = target_p - p
            eR = 0.5 * (np.cross(R[:, 0], target_R[:, 0]) + np.cross(R[:, 1], target_R[:, 1]) +
                        np.cross(R[:, 2], target_R[:, 2]))
            if np.linalg.norm(ep) < 5e-4 and np.linalg.norm(eR) < 3e-3:
                break
            J = np.zeros((6, 6))
            for k in range(6):
                dq = q.copy()
                dq[k] += 1e-5
                p2, R2 = fk_flange(dq)
                J[:3, k] = (p2 - p) / 1e-5
                dR = R2 @ R.T
                J[3:, k] = np.array([dR[2, 1] - dR[1, 2], dR[0, 2] - dR[2, 0], dR[1, 0] - dR[0, 1]]) / 2 / 1e-5
            e = np.concatenate([ep, eR])
            q = q + J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(6), e)
            q = np.clip(q, m.jnt_range[:6, 0], m.jnt_range[:6, 1])
        p, R = fk_flange(q)
        return q, float(np.linalg.norm(target_p - p))

    rows, ok, worst = [], True, 9.9
    q = np.array([0.34, 0.25, -2.46, 0.57, 0.46, 0.49])
    for i, t in enumerate(tcp_pts):
        flange_p = t - R0[:, 2] * TOOL_LEN
        q, err = ik(flange_p, R0, q)
        # 接触检查
        d.ncon and None
        mujoco.mj_forward(m, d)
        bad = []
        # 只看"臂 vs 工装/台面"的接触; 基座网格与 link1 的重叠是建模固有, 不算碰撞
        for c in d.contact[:d.ncon]:
            g1, g2 = int(c.geom1), int(c.geom2)
            if g1 in tool_geoms or g2 in tool_geoms:
                continue
            if {g1, g2} & {panel_id, table_id} == set():
                continue
            bad.append((mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g1) or ("body:" +
                        (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[g1]) or "?")),
                        mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g2) or ("body:" +
                        (mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[g2]) or "?"))))
        # 连杆到面板的**真实**几何最近距离: MuJoCo 自带 geom 间距 (不是原点近似)
        mind = 9.9
        for gi in range(m.ngeom):
            if gi in tool_geoms or gi == panel_id:
                continue
            try:
                dd = mujoco.mj_geomDistance(m, d, gi, panel_id, 0.8, None)
            except Exception:                                                 # noqa: BLE001
                dd = 0.8
            mind = min(mind, float(dd))
        worst = min(worst, mind)
        good = (err < 1e-3) and not bad and mind >= a.min_clear
        ok = ok and good
        rows.append({"i": i, "tcp_mm": [round(v * 1000, 1) for v in t], "ik_err_mm": round(err * 1000, 2),
                     "_q": [float(v) for v in q],
                     "contacts": bad[:3], "link_panel_mm": round(mind * 1000, 1), "pass": bool(good)})
    # 📤 给 /ar3d 的仿真右臂用: 每点的 p(m)/q(quat)/j(rad)/t(s), 与页面 rtrajData 同格式
    def R2q(R):
        w = math.sqrt(max(0.0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
        if w < 1e-6:
            return [0.0, 0.0, 0.0, 1.0]
        return [round((R[2, 1] - R[1, 2]) / (4 * w), 6), round((R[0, 2] - R[2, 0]) / (4 * w), 6),
                round((R[1, 0] - R[0, 1]) / (4 * w), 6), round(w, 6)]
    qq = R2q(R0)
    frames = []
    for i, (t, r) in enumerate(zip(tcp_pts, rows)):
        frames.append({"p": [round(float(v), 6) for v in t], "q": qq,
                       "j": [round(float(v), 6) for v in r.get("_q", [0] * 6)],
                       "t": round(i * 0.6, 3)})
    if all(f["j"] != [0] * 6 for f in frames):
        json.dump({"src": "tools/port_orbit_sim.py (URDF IK)", "n_frames": len(frames),
                   "dur_s": round(frames[-1]["t"], 3), "port_mm": plan.get("port_mm"),
                   "note": "插口特写补采航路 44 点 · 仿真右臂回放用",
                   "unit": {"p": "m", "j": "rad", "t": "s"}, "frames": frames},
                  open("zmax_data/capture_plan/port_orbit_joints.json", "w", encoding="utf-8"), ensure_ascii=False)
    res = {"ok": bool(ok), "n": len(rows), "worst_link_panel_mm": round(worst * 1000, 1),
           "rule": "IK<1mm + 无(工具以外的)接触 + 连杆到面板 ≥ %.0fmm" % (a.min_clear * 1000),
           "fails": [r for r in rows if not r["pass"]][:5]}
    json.dump(res, open(a.plan.replace(".json", "_sim.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False)[:600])
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
