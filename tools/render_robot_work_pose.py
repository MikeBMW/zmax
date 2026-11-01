#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_robot_work_pose.py — 真机作业姿态渲染（架在基座上，对着工作台干活）。

为什么必须加基座：这台 XMS5-R800 肩部只有 328mm 高。台面若放 300mm，工具要朝下
就只能把肘部翘到 700mm+（v1 被否的「胳膊举高」）。真实机器人工作站一律把机器人
装在立柱上，肩膀接近台面，才是自然的伸手作业姿态。

做法：复用 render_robot_views 的 URDF 正运动学 + numpy z-buffer 光栅化
      (本机 headless GL 不可用，pyrender/trimesh 的 save_image 会失败)

用法: ./gui-venv311/bin/python tools/render_robot_work_pose.py --outdir DIR
"""
from __future__ import annotations
import os, sys, json, math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_robot_views import (SPEC, LINK_ORDER, fk, load_meshes, world_tris,
                                render, rot_cam, save)

# ── 工位尺寸 (m) ──────────────────────────────────────────────────────
PEDESTAL_Z = 1.07      # 基座立柱高度：肩部 (base+0.328) 抬到 1.40m
TABLE_Z = 0.75         # 工作台面高度（腰高，工业常态）
GRASP_H = 0.110        # TCP 距台面高度（留出夹爪长度）
TARGET_X = 0.70        # 台面推远：肘部才能压到肩下 195mm（放 0.52 时只低 54mm，看着像举手）

SHOULDER_Z = PEDESTAL_Z + 0.328
TCP_Z = TABLE_Z + GRASP_H
WRIST_Y = 0.136       # link4→link5 的 Y 偏置：工具朝下时腕恒在此处


def tcp_of(spec, q):
    T = fk(spec, q)
    M = T[LINK_ORDER[-1]]
    return M[:3, 3], M[:3, :3]


def solve_work_pose(spec, target, seed=3):
    """解作业姿态 —— 解析降维枚举。

    关键几何事实（实测枚举得出，不是猜）：
      · 工具朝下 ⇒ 三个俯仰角之和必须是 π，即 q5 = q2 - q3 - π
        → 自由度从 3 维降到 2 维，直接枚举 q2/q3 即可
      · 工具朝下时腕部 y 恒在 +0.136m（link4→link5 的 Y 偏置决定，q4 无法消掉）
      · 台面 750mm / 抓取高 825mm 时，x 可达区间 [0.47, 0.81]
        → 台面中心必须放在 x≈0.6 一带；放 0.42 是物理上够不到的（v2 误差 349mm 的真因）

    在满足位置的点里，挑**肘部最低**的那个 —— 肘低 = 姿态自然 = 不是"举手"。
    """
    Down = np.array([0.0, 0.0, -1.0])
    tgt = np.array(target, float)
    cands = []
    for q2 in np.arange(0.5, 1.96, 0.01):
        for q3 in np.arange(-2.9, 2.9, 0.01):
            q5 = q2 - q3 - math.pi
            if not (-2.4 <= q5 <= 2.4):
                continue
            q = np.array([0.0, q2, q3, 0.0, q5, 0.0])
            T = fk(spec, q)
            M = T[LINK_ORDER[-1]]
            if M[:3, 2] @ Down < 0.995:
                continue
            p = M[:3, 3] + np.array([0.0, 0.0, PEDESTAL_Z])
            d = float(np.linalg.norm(p - tgt))
            elbow_z = T[LINK_ORDER[3]][2, 3] + PEDESTAL_Z
            cands.append((d, elbow_z, q))

    if not cands:
        raise RuntimeError("工具朝下的可达解为空，检查 PEDESTAL_Z / TABLE_Z")

    # 自然姿态判据：前臂朝下 => 肘高于腕；肘低于肩。先满足这两条，再挑离目标最近的。
    natural = [c for c in cands if c[1] >= c[2][0] * 0 + c[1]]  # placeholder
    def tcp_z_of(q):
        return (fk(spec, q)[LINK_ORDER[-1]][2, 3]) + PEDESTAL_Z
    nat = [c for c in cands
           if c[1] >= tcp_z_of(c[2]) + 0.12 and c[1] <= SHOULDER_Z - 0.05]
    pool = nat if nat else cands
    pool.sort(key=lambda t: (t[0], t[1]))
    d, elbow_z, q = pool[0]
    return q, d


def _unused_numerical(spec, target, seed=3):
    """保留参考：数值优化版本（会陷局部解，v2 误差 349mm）。"""
    tgt = np.array(target, float)
    Down = np.array([0.0, 0.0, -1.0])
    elbow_cap = SHOULDER_Z + 0.02
    lo = np.array([-2.9, -1.9, -2.9, -2.9, -2.4, -2.9])
    hi = np.array([2.9, 1.9, 2.9, 2.9, 2.4, 2.9])

    def cost(q):
        T = fk(spec, q)
        M = T[LINK_ORDER[-1]]
        p = M[:3, 3] + np.array([0.0, 0.0, PEDESTAL_Z])
        c = 12.0 * float(np.sum((p - tgt) ** 2))
        c += 16.0 * float(1.0 + M[:3, 2] @ Down) ** 2
        elbow_z = T[LINK_ORDER[3]][2, 3] + PEDESTAL_Z
        c += 400.0 * max(0.0, elbow_z - elbow_cap) ** 2
        return c

    g2 = np.arange(-0.2, 2.0, 0.06)
    g3 = np.arange(-2.9, 2.4, 0.06)
    g5 = np.arange(-2.3, 2.3, 0.06)
    seeds = []
    for a in g2:
        for b in g3:
            for c5 in g5:
                q = np.array([0.0, a, b, 0.0, c5, 0.0])
                seeds.append((cost(q), q))
    seeds.sort(key=lambda t: t[0])

    from scipy.optimize import minimize
    cands = []
    for _, q0 in seeds[:10]:
        r = minimize(cost, q0, method="Nelder-Mead",
                     options=dict(maxiter=20000, xatol=1e-9, fatol=1e-12))
        qr = np.clip(r.x, lo, hi)
        cands.append((cost(qr), qr))
    cands.sort(key=lambda t: t[0])
    return cands[0][1], math.sqrt(max(0.0, cands[0][0] / 12.0))


# ── 几何：盒子的三角形 ────────────────────────────────────────────────
def box_tris(center, size):
    cx, cy, cz = center
    sx, sy, sz = (s / 2.0 for s in size)
    v = np.array([
        [cx - sx, cy - sy, cz - sz], [cx + sx, cy - sy, cz - sz],
        [cx + sx, cy + sy, cz - sz], [cx - sx, cy + sy, cz - sz],
        [cx - sx, cy - sy, cz + sz], [cx + sx, cy - sy, cz + sz],
        [cx + sx, cy + sy, cz + sz], [cx - sx, cy + sy, cz + sz],
    ])
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return np.array([[v[a], v[b], v[c]] for a, b, c in f])


def build_scene(tcp):
    """基座立柱 + 工作台 + 料盘 + 工件 + 地面。返回 (tris, colors)。"""
    tx, ty, tz = tcp[0], tcp[1], TABLE_Z
    parts = []

    # 机器人基座立柱 + 底板
    parts.append((box_tris((0.0, 0.0, PEDESTAL_Z / 2), (0.22, 0.22, PEDESTAL_Z)), (0.34, 0.36, 0.40)))
    parts.append((box_tris((0.0, 0.0, 0.015), (0.40, 0.40, 0.03)), (0.30, 0.31, 0.34)))

    # 工作台：台面板 + 四腿 + 横梁
    tw, td = 0.72, 0.92
    parts.append((box_tris((tx, ty, tz - 0.022), (tw, td, 0.044)), (0.58, 0.60, 0.64)))
    for dx in (-tw / 2 + 0.05, tw / 2 - 0.05):
        for dy in (-td / 2 + 0.05, td / 2 - 0.05):
            parts.append((box_tris((tx + dx, ty + dy, (tz - 0.044) / 2),
                                   (0.05, 0.05, tz - 0.044)), (0.30, 0.31, 0.34)))
    for yy in (ty - td / 2 + 0.05, ty + td / 2 - 0.05):
        parts.append((box_tris((tx, yy, 0.18), (tw - 0.10, 0.035, 0.035)), (0.30, 0.31, 0.34)))
    for xx in (tx - tw / 2 + 0.05, tx + tw / 2 - 0.05):
        parts.append((box_tris((xx, ty, 0.18), (0.035, td - 0.10, 0.035)), (0.30, 0.31, 0.34)))

    # 料盘（黑色，实测造型简化）：底面 + 四壁
    parts.append((box_tris((tx, ty, tz + 0.008), (0.20, 0.30, 0.016)), (0.13, 0.13, 0.15)))
    for dx in (-0.098, 0.098):
        parts.append((box_tris((tx + dx, ty, tz + 0.032), (0.008, 0.30, 0.032)), (0.13, 0.13, 0.15)))
    for dy in (-0.148, 0.148):
        parts.append((box_tris((tx, ty + dy, tz + 0.032), (0.20, 0.008, 0.032)), (0.13, 0.13, 0.15)))
    # 槽内工件（绿色光模块）
    for dy in (-0.10, -0.035, 0.035, 0.10):
        parts.append((box_tris((tx - 0.045, ty + dy, tz + 0.030), (0.07, 0.042, 0.024)), (0.10, 0.62, 0.36)))
    # 爪子正下方这个：正在被夹住（离爪指最近）
    parts.append((box_tris((tx, ty, tz + 0.032), (0.072, 0.044, 0.026)), (0.13, 0.70, 0.42)))

    # 地面
    parts.append((box_tris((tx * 0.5, ty, -0.01), (2.6, 2.6, 0.02)), (0.82, 0.83, 0.85)))
    # 假接触阴影（扁平暗色四边形，压在地面上，让物体不"浮"着）
    for cx, cy, sx, sy in ((0.0, 0.0, 0.52, 0.52), (tx, ty, tw + 0.18, td + 0.18)):
        parts.append((box_tris((cx, cy, 0.004), (sx, sy, 0.002)), (0.68, 0.69, 0.71)))

    tris = np.concatenate([p[0] for p in parts], axis=0)
    cols = np.concatenate([np.tile(np.array(p[1], float), (len(p[0]), 1)) for p in parts], axis=0)
    return tris, cols


def main():
    outdir = None
    for i, a in enumerate(sys.argv):
        if a == "--outdir" and i + 1 < len(sys.argv):
            outdir = sys.argv[i + 1]
    outdir = outdir or "/tmp/robot_work"
    os.makedirs(outdir, exist_ok=True)

    spec = json.load(open(SPEC))
    meshes = load_meshes()

    # 腕部 Y 偏置固定 +0.136，目标点也带上它，误差才反映真实的 x/z 偏差
    target = (TARGET_X, WRIST_Y, TCP_Z)
    q, err = solve_work_pose(spec, target)
    T = fk(spec, q)
    p, Rz = tcp_of(spec, q)
    p_world = p + np.array([0.0, 0.0, PEDESTAL_Z])

    print("肩高 %.0f mm | 台面 %.0f mm | TCP 目标 (%.2f, 0, %.2f)" %
          (SHOULDER_Z * 1000, TABLE_Z * 1000, TARGET_X, TCP_Z))
    print("姿态 q =", [round(float(x), 3) for x in q])
    print("TCP = (%.3f, %.3f, %.3f)  位置误差 %.0f mm" %
          (p_world[0], p_world[1], p_world[2], err * 1000))
    print("工具轴 = (%.2f, %.2f, %.2f)  理想 (0,0,-1)" % tuple(Rz[:, 2]))
    print("肘部 %.0f mm  (肩 %.0f mm)" %
          ((T[LINK_ORDER[3]][2, 3] + PEDESTAL_Z) * 1000, SHOULDER_Z * 1000))

    robot = world_tris(T, meshes) + np.array([0.0, 0.0, PEDESTAL_Z])
    machine_cols = np.tile(np.array([0.76, 0.78, 0.82]), (len(robot), 1))

    # 夹爪（URDF 只到法兰，厂家没给爪；补一个两指平行夹爪，才看得出"在抓件"）
    gx, gy, gz = p_world
    grip = []
    grip.append((box_tris((gx, gy, gz - 0.025), (0.085, 0.055, 0.050)), (0.24, 0.25, 0.28)))   # 爪体
    for dx in (-0.044, 0.044):
        grip.append((box_tris((gx + dx, gy, gz - 0.072), (0.014, 0.046, 0.048)), (0.30, 0.31, 0.34)))  # 指
    gtris = np.concatenate([g[0] for g in grip], axis=0)
    gcols = np.concatenate([np.tile(np.array(g[1], float), (len(g[0]), 1)) for g in grip], axis=0)

    scene_tris, scene_cols = build_scene(p_world)
    robot = np.concatenate([robot, gtris], axis=0)
    machine_cols = np.concatenate([machine_cols, gcols], axis=0)
    tris = np.concatenate([robot, scene_tris], axis=0)
    cols = np.concatenate([machine_cols, scene_cols], axis=0)

    for name, (az, el) in {"work": (34, 12), "work2": (62, 18)}.items():
        img, meta = render(tris, rot_cam(az, el), size=(1600, 1200), ss=2, colors=cols)
        path = os.path.join(outdir, f"robot_{name}.png")
        save(img, path, dpi=150)
        print("saved", path, img.shape)

    json.dump(dict(q=[round(float(x), 4) for x in q],
                   tcp_m=[round(float(v), 4) for v in p_world],
                   tool_axis=[round(float(v), 3) for v in Rz[:, 2]],
                   target=list(target), table_z=TABLE_Z,
                   pedestal_z=PEDESTAL_Z, shoulder_z=round(SHOULDER_Z, 4)),
              open(os.path.join(outdir, "work_meta.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
