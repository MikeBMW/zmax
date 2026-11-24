#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase_traj_ik2.py — 8815 的 251 点全流程相位轨迹 → 连续关节帧（给 ar3d 只仿真回放用）

为什么重写第一版:
  第一版逐点 IK 用上一帧做 seed 但**不限关节步长**, 求得的解会在解支之间跳
  (实测插值后关节角冲到 445°、单帧跳 180°), 播出来手臂乱翻。
本版口径:
  · IK 每步限幅 max_step(rad) ⇒ 不会跨解支, 结果天然连续
  · 某帧不收敛 ⇒ **沿用上一帧关节角**(画面停一下), 不插值到未来解
  · 收尾再做 ±2π unwrap, 并报最大单帧步进
只写文件, 不下发任何真机指令。
"""
import json, math, os, shutil
import numpy as np

REPO = '/home/ubuntu/zmax'
SCRATCH = '/home/ubuntu/.hermes/cache/scratch/xms5'
URDF_SRC = os.path.join(REPO, 'zmax_data/deliverables/20261107_preoff/state/config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf')
MESH_SRC = os.path.join(REPO, 'zmax_data/deliverables/20261107_preoff/state/config/moveit_xms5/urdf/meshes/xms5_r800_w4g3b4c_meshes')
TOOL_LEN = 0.2587
OUT = os.path.join(REPO, 'zmax_data/capture_plan/port_orbit_joints.json')
GEO = os.path.join(REPO, 'zmax_data/capture_plan/phase251_geo.json')


def quat_to_R(q):
    # 8815 的 q 是 [w,x,y,z] —— 按 [x,y,z,w] 解会让工具 z 轴差 140°
    w, x, y, z = [float(v) for v in q]
    n = math.sqrt(x*x + y*y + z*z + w*w) or 1.0
    x, y, z, w = x/n, y/n, z/n, w/n
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w),   2*(x*z+y*w)],
        [2*(x*y+z*w),   1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w),   2*(y*z+x*w),   1-2*(x*x+y*y)],
    ])


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


def main():
    import mujoco
    geo = json.load(open(GEO, encoding='utf-8'))
    frames_in = geo['frames']
    print('输入 %d 帧 · %.0fmm' % (len(frames_in), geo.get('len_mm', 0)))

    spec = mujoco.MjSpec.from_file(prep_urdf())
    m = spec.compile()
    d = mujoco.MjData(m)
    lo = m.jnt_range[:6, 0].copy()
    hi = m.jnt_range[:6, 1].copy()

    def fk_flange(q):
        for i in range(min(6, m.nq)):
            d.qpos[i] = q[i]
        mujoco.mj_forward(m, d)
        b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'XMS5-R800-W4G3B4C_link6')
        return d.xpos[b].copy(), d.xmat[b].reshape(3, 3).copy()

    def ik(target_p, target_R, q0, iters=400, max_step=0.06):
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
                dq = q.copy(); dq[k] += 1e-5
                p2, R2 = fk_flange(dq)
                J[:3, k] = (p2 - p) / 1e-5
                dR = R2 @ R.T
                J[3:, k] = np.array([dR[2, 1]-dR[1, 2], dR[0, 2]-dR[2, 0], dR[1, 0]-dR[0, 1]]) / 2 / 1e-5
            e = np.concatenate([ep, eR])
            dq = J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(6), e)
            nrm = float(np.linalg.norm(dq))
            if nrm > max_step:                       # 🔑 限幅: 不许一步跨解支
                dq *= max_step / nrm
            q = np.clip(q + dq, lo, hi)
        p, R = fk_flange(q)
        return q, float(np.linalg.norm(target_p - p))

    q = np.array([0.34, 0.25, -2.46, 0.57, 0.46, 0.22])
    out, errs, held = [], [], 0
    for k, f in enumerate(frames_in):
        tcp = np.array(f['p'], dtype=float) / 1000.0
        R = quat_to_R(f['q'])
        flange_p = tcp - R[:, 2] * TOOL_LEN
        q_new, err = ik(flange_p, R, q)
        if err > 0.005:                              # 不收敛 ⇒ 沿用上一帧, 不插值到未来解
            q_new, held = q.copy(), held + 1
        else:
            q = q_new
        errs.append(err)
        out.append({'i': k, 'p': [round(v, 6) for v in tcp],
                    'q': [round(float(v), 6) for v in f['q']],
                    'j': [round(float(v), 6) for v in q_new],
                    'ik_err_mm': round(err * 1000, 2),
                    'held': bool(err > 0.005),
                    't': round(float(f.get('s') or 0), 6)})

    A = np.array([f['j'] for f in out])
    for i in range(1, len(A)):                       # ±2π unwrap
        for k in range(6):
            dk = A[i, k] - A[i-1, k]
            if dk > math.pi:  A[i, k] -= 2*math.pi
            elif dk < -math.pi: A[i, k] += 2*math.pi
    for i, f in enumerate(out):
        f['j'] = [round(float(v), 6) for v in A[i]]

    steps = np.degrees(np.abs(np.diff(A, axis=0))).max(axis=1)
    path_mm = sum(float(np.linalg.norm(np.array(out[i+1]['p']) - np.array(out[i]['p'])) * 1000)
                  for i in range(len(out) - 1))
    res = {
        'src': 'tools/phase_traj_ik2.py (8815 /api/geo → MuJoCo IK, 步长限幅)',
        'src_rec': '251 点全流程相位轨迹 (含AOI金手指1/2 + 侧面点1~4) · 仿真右臂回放 · 真机不动',
        'n_frames': len(out),
        'dur_s': round(len(out) / 25.0, 2),
        'path_mm': round(path_mm, 1),
        'rot_total_deg': round(float(np.degrees(np.abs(A[-1] - A[0])).sum()), 1),
        'unit': 'p=m, j=rad',
        'ik_ok': len(out) - held,
        'ik_held': held,
        'max_joint_step_deg': round(float(steps.max()), 2),
        'note': ('IK 收敛 %d/%d 帧 (中位 %.2fmm / P95 %.2fmm) · 未收敛 %d 帧沿用上一帧关节角(画面停住, 不跨解支) · 最大单帧步进 %.1f°'
                 % (len(out) - held, len(out), float(np.median(errs)) * 1000,
                    float(np.percentile(errs, 95)) * 1000, held, steps.max())),
        'states': geo.get('states') or [],
        'frames': out,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)
    print('IK 收敛 %d/%d · 未收敛沿用 %d 帧' % (len(out) - held, len(out), held))
    print('关节角最大单帧步进 %.2f° · >10° 帧数 %d' % (steps.max(), int((steps > 10).sum())))
    print('关节范围(deg) min %s' % np.round(np.degrees(A.min(axis=0)), 0))
    print('关节范围(deg) max %s' % np.round(np.degrees(A.max(axis=0)), 0))


if __name__ == '__main__':
    main()
