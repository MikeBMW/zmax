#!/usr/bin/env python3
"""port_sweep_plan.py — 从**当前位姿**出发, 沿 y 走一条 ±20cm 的横线(建图补采)。

老倪 2026-11-19: 「当前位置你看到了么？你就从当前位置，左右20厘米，走横线，可以么？」
  要求: 起点=当前 TCP(真值), 只动 y, x/z 与姿态保持不变, 横向 ±200mm。

自洽性(关键):
  控制器 rpy 的欧拉约定与我们不一致 ⇒ 不拿 rpy 反推姿态。
  做法: 读**当前关节角** j0 → 用真机 URDF 做 FK 得法兰位姿 (p0,R0) ⇒ 这是仿真模型里
        唯一自洽的姿态; 之后固定 R0, 只平移 y 解 IK。仿真臂的起点与真机当前姿态一致。

输出:
  zmax_data/capture_plan/port_sweep.json          (航点 + 检查结果)
  zmax_data/capture_plan/port_sweep_joints.json   (22/11 帧关节, 给 /ar3d 仿真右臂回放)
"""
import argparse
import json
import math
import os

import numpy as np

SCRATCH = "/home/ubuntu/.hermes/cache/scratch/xms5"
URDF_SRC = "zmax_data/deliverables/20261107_preoff/state/config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf"
MESH_SRC = "zmax_data/deliverables/20261107_preoff/state/config/moveit_xms5/urdf/meshes/xms5_r800_w4g3b4c_meshes"
TOOL_LEN = 0.2587
PANEL_LO = np.array([0.758, 0.140, 0.095])
PANEL_HI = np.array([0.835, 0.300, 0.285])
# 现场实时读数 (2026-11-19 11:5x, power=on idle manual)
TCP_NOW = np.array([0.6531, 0.2560, 0.1720])
J_NOW = np.array([0.34221, 0.24698, -2.4593, 0.56675, 0.46054, 0.48606])


def prep_urdf():
    os.makedirs(SCRATCH, exist_ok=True)
    dst = os.path.join(SCRATCH, os.path.basename(URDF_SRC))
    if not os.path.exists(dst):
        import shutil
        shutil.copy(URDF_SRC, dst)
    for f in os.listdir(MESH_SRC):
        p = os.path.join(SCRATCH, f)
        if not os.path.exists(p):
            import shutil
            shutil.copy(os.path.join(MESH_SRC, f), p)
    return dst


def R2q(R):
    w = math.sqrt(max(0.0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    if w < 1e-6:
        return [0.0, 0.0, 0.0, 1.0]
    return [round((R[2, 1] - R[1, 2]) / (4 * w), 6), round((R[0, 2] - R[2, 0]) / (4 * w), 6),
            round((R[1, 0] - R[0, 1]) / (4 * w), 6), round(w, 6)]


def main() -> int:
    ap = argparse.ArgumentParser()
    # 🔴 实测: 当前位置(x0.653)固定姿态走 ±200mm 时, 腕关节到限位 ⇒ IK 在第 9 点跳构型(122°/215°);
    #    ±120mm 才全程连续(最大单步 8.8°)。所以默认给 ±120mm(总 240mm) 的**连续**横线。
    ap.add_argument("--half", type=float, default=0.120, help="左右半幅 m (实测连续上限 ~120mm)")
    ap.add_argument("--step", type=float, default=0.024, help="步长 m")
    ap.add_argument("--out", default="zmax_data/capture_plan/port_sweep.json")
    a = ap.parse_args()
    import mujoco

    spec = mujoco.MjSpec.from_file(prep_urdf())
    wb = spec.worldbody
    g = wb.add_geom(); g.name = "table"; g.type = mujoco.mjtGeom.mjGEOM_BOX
    g.size = [0.58, 0.55, 0.005]; g.pos = [0.62, 0.22, -0.005]
    g2 = wb.add_geom(); g2.name = "panel"; g2.type = mujoco.mjtGeom.mjGEOM_BOX
    g2.size = list((PANEL_HI - PANEL_LO) / 2); g2.pos = list((PANEL_HI + PANEL_LO) / 2)
    m = spec.compile(); d = mujoco.MjData(m)
    link6 = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "XMS5-R800-W4G3B4C_link6")
    panel_id = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, "panel")

    def fk(q):
        for i in range(6):
            d.qpos[i] = q[i]
        mujoco.mj_forward(m, d)
        return d.xpos[link6].copy(), d.xmat[link6].reshape(3, 3).copy()

    def ik(pt, Rt, q0, iters=260):
        q = q0.copy()
        for _ in range(iters):
            p, R = fk(q)
            ep, eR = pt - p, 0.5 * sum(np.cross(R[:, i], Rt[:, i]) for i in range(3))
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
        p, _ = fk(q)
        return q, float(np.linalg.norm(pt - p))

    p0, R0 = fk(J_NOW)
    tcp0 = p0 + R0[:, 2] * TOOL_LEN
    print("URDF FK: 法兰 %s mm · 由法兰+工具轴推出的 TCP %s mm · 控制器读 %s mm"
          % ((p0 * 1000).round(1), (tcp0 * 1000).round(1), (TCP_NOW * 1000).round(1)))
    # 用**模型自洽**的起点: 法兰 p0, 只沿 y 平移
    n = int(round(a.half / a.step))
    ys = [i * a.step for i in range(-n, n + 1)]
    rows, frames, ok, worst = [], [], True, 9.9
    # 🔴 连续性优先: 从当前位姿(w=0)**向两侧**逐点解, 每点以上一点为种子 ⇒ 不会中途跳到另一个构型分支。
    #    (实测: 从左端一次扫到右端, 第 1 点就跳了 30°/89°, 那是换臂型, 真机上等于甩臂)
    order = sorted(range(len(ys)), key=lambda i: abs(ys[i]))
    solved = {}
    q_seed = J_NOW.copy()
    for i in order:
        pt = p0 + np.array([0.0, ys[i], 0.0])
        q_i, err_i = ik(pt, R0, q_seed)
        # 解出来可能是"同一个姿态的 ±2π 写法"(关节 4/5/6 允许整圈) ⇒ 按最接近上一点折算,
        # 否则回放/下发时会看到 360° 甩腕。2π 折算不改变末端位姿, 只换等价表示。
        for k in range(6):
            while q_i[k] - q_seed[k] > math.pi and q_i[k] - 2 * math.pi >= m.jnt_range[k, 0]:
                q_i[k] -= 2 * math.pi
            while q_seed[k] - q_i[k] > math.pi and q_i[k] + 2 * math.pi <= m.jnt_range[k, 1]:
                q_i[k] += 2 * math.pi
        solved[i] = (q_i, err_i)
        q_seed = q_i
    for i, dy in enumerate(ys):
        pt = p0 + np.array([0.0, dy, 0.0])
        q, err = solved[i]
        pf, Rf = fk(q)
        tcpp = pf + Rf[:, 2] * TOOL_LEN
        clear = min(float(mujoco.mj_geomDistance(m, d, gi, panel_id, 0.8, None))
                    for gi in range(m.ngeom)
                    if m.geom_bodyid[gi] == link6 or "link" in (mujoco.mj_id2name(
                        m, mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[gi]) or ""))
        worst = min(worst, clear)
        good = err < 1e-3 and clear > 0.05
        ok = ok and good
        rows.append({"i": i, "dy_mm": round(dy * 1000, 1), "tcp_mm": [round(v * 1000, 1) for v in tcpp],
                     "ik_err_mm": round(err * 1000, 2), "clear_mm": round(clear * 1000, 1), "pass": bool(good)})
        frames.append({"p": [round(float(v), 6) for v in tcpp], "q": R2q(Rf),
                       "j": [round(float(v), 6) for v in q], "t": round(i * 0.7, 3)})
    total = sum(math.dist(rows[i]["tcp_mm"], rows[i + 1]["tcp_mm"]) for i in range(len(rows) - 1)) / 1000
    plan = {"ok": bool(ok), "n": len(rows), "half_mm": a.half * 1000, "step_mm": a.step * 1000,
            "total_mm": round(total * 1000, 1), "worst_clear_mm": round(worst * 1000, 1),
            "rule": "起点=当前位姿(URDF FK 自洽) · 只动 y · IK<1mm · 到工装 ≥50mm",
            "start_tcp_mm": [round(v * 1000, 1) for v in tcp0],
            "waypoints": rows}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(plan, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    jf = a.out.replace(".json", "_joints.json")
    rot = max(max(abs(x - y) for x, y in zip(f["j"], frames[0]["j"])) for f in frames) * 57.2958
    json.dump({"src": "tools/port_sweep_plan.py (URDF IK · 当前位姿起)",
               "n_frames": len(frames), "dur_s": frames[-1]["t"],
               "path_mm": round(total * 1000, 1), "rot_total_deg": round(rot, 1),
               "src_rec": "当前位置横线扫掠 ±%.0fmm %d点 (仿真, 真机不动)" % (a.half * 1000, len(frames)),
               "note": "从当前 TCP 出发 · 只动 y · 建图补采", "unit": {"p": "m", "j": "rad", "t": "s"},
               "frames": frames}, open(jf, "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps({"ok": plan["ok"], "n": plan["n"], "total_mm": plan["total_mm"],
                      "worst_clear_mm": plan["worst_clear_mm"], "start_tcp_mm": plan["start_tcp_mm"],
                      "out": a.out, "joints": jf}, ensure_ascii=False))
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
