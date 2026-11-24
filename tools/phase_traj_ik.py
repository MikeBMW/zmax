#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""phase_traj_ik.py — 把 8815 的 251 点全流程相位轨迹(含 AOI 检测)解成关节帧,
写成 /api/orbit_frames 读的 port_orbit_joints.json, 供 ar3d 仿真右臂回放(真机不动)。

口径:
  · 输入 = http://192.168.23.50:8815/api/geo 的 frames (p=mm, q=四元数)
  · TCP → 法兰: flange = tcp - R[:,2] * TOOL_LEN (0.2587m, 见 port_orbit_sim.py)
  · IK 用 MuJoCo 数值解, seed=上一点 (连续轨迹用上一点做种子收敛快)
  · 只写文件, 不下发任何真机指令
"""
import json, math, os, sys, urllib.request
import numpy as np

REPO = '/home/ubuntu/zmax'
SCRATCH = '/home/ubuntu/.hermes/cache/scratch/xms5'
URDF_SRC = os.path.join(REPO, 'zmax_data/deliverables/20261107_preoff/state/config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf')
MESH_SRC = os.path.join(REPO, 'zmax_data/deliverables/20261107_preoff/state/config/moveit_xms5/urdf/meshes/xms5_r800_w4g3b4c_meshes')
TOOL_LEN = 0.2587
OUT = os.path.join(REPO, 'zmax_data/capture_plan/port_orbit_joints.json')


def quat_to_R(q):
    # 🔴 2026-11-24 实测: 8815 的 q 是 [w,x,y,z] 顺序 —— 按 [x,y,z,w] 解会让工具 z 轴差 140°,
    #    IK 33% 失败(见 phase_traj 首轮 84/251 点 ik_err>5mm)。按真机当前位姿反推验证:
    #    [w,x,y,z] 差 5.2° / [x,y,z,w] 差 140.5° ⇒ 以 w 开头为准。
    w, x, y, z = [float(v) for v in q]
    n = math.sqrt(x*x + y*y + z*z + w*w) or 1.0
    x, y, z, w = x/n, y/n, z/n, w/n
    return np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w),   2*(x*z+y*w)],
        [2*(x*y+z*w),   1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w),   2*(y*z+x*w),   1-2*(x*x+y*y)],
    ])


def prep_urdf():
    import shutil
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
    ast = 0.0
    geo = json.loads(urllib.request.urlopen('http://192.168.23.50:8815/api/geo', timeout=15).read().decode())
    frames_in = geo['frames']
    print('输入 %d 帧 · %.0fmm · set=%s' % (len(frames_in), geo['len_mm'], geo.get('set')))

    urdf = prep_urdf()
    spec = mujoco.MjSpec.from_file(urdf)
    m = spec.compile()
    d = mujoco.MjData(m)

    def fk_flange(q):
        for i in range(min(6, m.nq)):
            d.qpos[i] = q[i]
        mujoco.mj_forward(m, d)
        b = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, 'XMS5-R800-W4G3B4C_link6')
        return d.xpos[b].copy(), d.xmat[b].reshape(3, 3).copy()

    def ik(target_p, target_R, q0, iters=200):
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
            q = q + J.T @ np.linalg.solve(J @ J.T + 1e-4 * np.eye(6), e)
            q = np.clip(q, m.jnt_range[:6, 0], m.jnt_range[:6, 1])
        p, R = fk_flange(q)
        return q, float(np.linalg.norm(target_p - p))

    q = np.array([0.34, 0.25, -2.46, 0.57, 0.46, 0.22])
    out, errs = [], []
    for k, f in enumerate(frames_in):
        tcp = np.array(f['p'], dtype=float) / 1000.0
        R = quat_to_R(f['q'])
        flange_p = tcp - R[:, 2] * TOOL_LEN
        q, err = ik(flange_p, R, q)
        errs.append(err)
        out.append({'i': k, 'p': [round(v, 6) for v in tcp],
                    'q': [round(float(v), 6) for v in f['q']],
                    'j': [round(float(v), 6) for v in q],
                    'ik_err_mm': round(err * 1000, 2),
                    't': round(float(f.get('s') or 0), 6)})
        if k % 40 == 0:
            print('  %3d/%d  ik_err %.2fmm' % (k, len(frames_in), err * 1000))

    path_mm = sum(float(np.linalg.norm(np.array(out[i+1]['p']) - np.array(out[i]['p'])) * 1000)
                  for i in range(len(out) - 1))
    res = {
        'src': 'tools/phase_traj_ik.py (8815 /api/geo → MuJoCo IK)',
        'src_rec': '%d 点全流程相位轨迹(含AOI金手指1/2 + 侧面点1~4) · 仿真右臂回放 · 真机不动' % len(out),
        'n_frames': len(out),
        'dur_s': round(len(out) / 25.0, 2),
        'path_mm': round(path_mm, 1),
        'rot_total_deg': 0.0,
        'unit': 'p=m, j=rad',
        'note': 'IK 中位 %.2fmm / P95 %.2fmm / 最大 %.2fmm' % (
            float(np.median(errs)) * 1000, float(np.percentile(errs, 95)) * 1000, max(errs) * 1000),
        'states': geo.get('states') or [],
        'frames': out,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)
    print('IK 误差: 中位 %.2fmm  P95 %.2fmm  最大 %.2fmm' % (
        float(np.median(errs)) * 1000, float(np.percentile(errs, 95)) * 1000, max(errs) * 1000))
    print('路径 %.0fmm · %d 帧' % (path_mm, len(out)))


if __name__ == '__main__':
    main()
