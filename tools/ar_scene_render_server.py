#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ar_scene_render_server.py — AR 工位场景渲染帧服务 (L2 感知输入 + 双臂控制/真值)

老倪 2026-10-29:
  「要用 AR 场景的渲染后的视频作为数据源, 再有 L2 的感知节点检测」
  「再做一个 render 页面… L2 接渲染后的图像感知 → 给 plan 模块规划 → 驱动 AR 场景左右臂」

## 为什么不能复用 8801 (fw_render_server)
8801 是 `RealStateSpaceSim` + metaworld peg-insert-side 的帧 (机位 corner2 照不到工位料盘),
在役 AR 权重 `models/yolo_ar_peg.pt` 在它上面 **0 框**。真正的 AR 场景是
`tools/ar_mujoco_env.ArMujocoEnv` (双臂 + 料盘 + 金色光模块 + freejoint 可抓)。

## 本服务
  · 加载 ArMujocoEnv, 专用工作区机位, 960×720, 与训练集同口径
  · **可达可动**: 双臂 12 个 position actuator 可下指令 (deg), 仿真真跑 (mj_step)
  · **真值直出** /state.json: 双腕 TCP 世界坐标、光模块 xyz、孔口、关节角 —— 取 model.data, 不手推
  · **平面单应标定** (启动时 3×3 网格自标): 物料台面 (x,y) ↔ 像素, 残差自报 ⇒ 2D→3D 有据
  · **IK 端点**: 阻尼最小二乘 (mujoco 雅可比) 解 6 轴到指定位姿, 失败如实报 err_mm
  · label.json 金色像素连通域外接框 = 像素级真值 (非模型预测), 供核对

接口:
    GET  /frame.png | /frame.jpg    最新渲染帧 (960×720)
    GET  /status.json               帧号/帧龄/均值/金色像素/耗时/错误
    GET  /label.json                像素级真值框
    GET  /state.json                双臂/光模块/孔口真值 + 关节角 + 标定残差
    GET  /ik?side=R&x=&y=&z=        6 轴 IK (m) → deg + err_mm
    GET  /proj?x=&y=&z=             世界点 → 像素 (用标定单应, 仅台面同高有效)
    GET  /unproj?u=&v=              像素 → 台面 3D (m)
    POST /control                   {"mode":"sim","L":[6deg],"R":[6deg],"gripL":0/1,"gripR":0/1}
    POST /reset                     回到双臂 home 姿态 + 光模块落位
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

W, H = 960, 720
# 🎥 两个机位 (同一仿真状态, 同一拍出图 ⇒ 天生同步):
#   close = 特写 (料盘+模块, AR 权重训练口径, L2 只认这个视角)
#   ar3d  = 全景 (与 AR 页 3D 视图同视角参数: VR yaw=-0.9rad pitch=0.55rad dist=1.6m tgt=[0.70,0.22,0.14])
VIEWS = {
    # 特写: 从 +y 侧看料盘 (两臂在 y=0 / y=0.5, 不挡视线); 实测 AR 权重 conf 0.914, 框与真值差 1px
    "close": {"lookat": [0.52, 0.35, 0.12], "distance": 0.34, "elevation": -40.0,
              "azimuth": 90.0, "fovy": 55.0, "note": "特写: 料盘+模块 (L2 视觉域)"},
    # 全景: 位置/朝向/视距/目标点/焦距 全部照 tools/web/tcp-ar.html 的 VR 默认值
    #   yaw=-0.9rad pitch=0.55rad dist=1.6 tgt=[0.70,0.22,0.14] F=520px@960x720
    #   ⇒ azimuth=-51.6 elevation=-31.5 fovy=2*atan(360/520)=69.4 (同一套针孔模型, 画面才"一模一样")
    "ar3d": {"lookat": [0.70, 0.22, 0.14], "distance": 1.60, "elevation": -31.5,
             "azimuth": -51.6, "fovy": 69.4, "note": "全景: 与 AR 页 3D 同视角 (yaw-0.9 pitch0.55 d1.6 F520)"},
}
STATE = {"png": b"", "n": 0, "ts": 0.0, "mean": None, "gold_px": 0, "box": None,
         "ms": None, "shape": None, "err": None, "mode": "idle",
         "truth": {}, "calib": {}, "cmd": {}, "steps": 0,
         "views": {}}
LOCK = threading.Lock()
CMD = {"mode": "idle", "L": None, "R": None, "gripL": None, "gripR": None, "ts": 0.0}
ENV = {"env": None}          # render_loop 建好后放进来, 供 /ik 用


def gold_mask(img):
    """金色模块像素 (sRGB: R 高、B 低) —— 与 tools/ar_mujoco_dataset.py 同一判据。"""
    import numpy as np
    a = np.asarray(img).astype(int)
    if a.ndim == 3 and a.shape[2] == 4:
        a = a[:, :, :3]
    return ((a[:, :, 0] > 120) & (a[:, :, 1] > 85) &
            (a[:, :, 0] - a[:, :, 2] > 40) & (a[:, :, 1] - a[:, :, 2] > 20))


def gold_box(mask, min_px=40, sigma_px=90):
    """最大连通域外接框 (中位数±σ 剔飞点)。返回 ([x1,y1,x2,y2] | None, 像素数)。"""
    import numpy as np
    ys, xs = np.where(mask)
    if len(ys) < min_px:
        return None, int(len(ys))
    mx, my = float(np.median(xs)), float(np.median(ys))
    keep = (np.abs(xs - mx) < sigma_px) & (np.abs(ys - my) < sigma_px)
    if keep.sum() < min_px:
        return None, int(keep.sum())
    xs, ys = xs[keep], ys[keep]
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], int(keep.sum())


# ───────────── 平面单应标定 (像素 ↔ 台面 xy) ─────────────
def _solve_homography(src, dst):
    """DLT 解 3×3 单应 (src=平面 xy, dst=像素 uv)。"""
    import numpy as np
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    A = np.asarray(A, float)
    _, _, vt = np.linalg.svd(A)
    Hm = vt[-1].reshape(3, 3)
    return Hm / Hm[2, 2]


def _apply_h(Hm, x, y):
    import numpy as np
    p = Hm @ np.array([x, y, 1.0])
    return float(p[0] / p[2]), float(p[1] / p[2])


def _apply_h_inv(Hm, u, v):
    import numpy as np
    Hi = np.linalg.inv(Hm)
    p = Hi @ np.array([u, v, 1.0])
    return float(p[0] / p[2]), float(p[1] / p[2])


def _dlt_P(world, pixels):
    """3D 点 → 像素 的 3×4 相机矩阵 (DLT)。world: N×3, pixels: N×2。非共面点才有唯一解。"""
    import numpy as np
    A = []
    for (X, Y, Z), (u, v) in zip(world, pixels):
        A.append([X, Y, Z, 1, 0, 0, 0, 0, -u * X, -u * Y, -u * Z, -u])
        A.append([0, 0, 0, 0, X, Y, Z, 1, -v * X, -v * Y, -v * Z, -v])
    A = np.asarray(A, float)
    _, _, vt = np.linalg.svd(A)
    return vt[-1].reshape(3, 4)


def _proj_P(P, xyz):
    import numpy as np
    p = np.asarray(P, float) @ np.array([float(xyz[0]), float(xyz[1]), float(xyz[2]), 1.0])
    if abs(p[2]) < 1e-12:
        return None
    return float(p[0] / p[2]), float(p[1] / p[2])


def _unproj_P(P, u, v, z):
    """像素 → 射线 → 与 z 平面求交。P 用实拍标定, 不手推内参。"""
    import numpy as np
    P = np.asarray(P, float)
    M = P[:, :3]
    try:
        C = -np.linalg.solve(M, P[:, 3])          # 相机中心
        d = np.linalg.solve(M, np.array([u, v, 1.0]))  # 射线方向
    except Exception:                                                  # noqa: BLE001
        return None
    if abs(d[2]) < 1e-12:
        return None
    t = (float(z) - C[2]) / d[2]
    if t <= 0:
        return None
    p = C + t * d
    return float(p[0]), float(p[1])


def calibrate_camera(mujoco, model, data, renderer, gold_qadr, plane_z, cx, cy, cam, tag="", fovy=None):
    """把光模块摆到 3 层 z × 3×3 网格 (共 27 点) 逐点渲染 → 金色像素中心 → DLT 解 P。

    这是在仿真里**真做的标定**: 27 个已知 3D 点对应 27 个实测像素点, 回代残差自报 (px/mm)。
    只标平面单应的话, 高于台面的点 (双腕 TCP) 投不准。
    """
    import numpy as np
    # 🔴 标定必须用**与出图同一个 fovy**: 原来标定走默认 45°, 出图用 55°/69.4° ⇒
    #    标出来的 P 跟画面不是一个针孔模型, 叠加/反解全偏 (实测与 AR 页同口径点差 214px)。
    if fovy:
        model.vis.global_.fovy = float(fovy)
    world, pixels = [], []
    qsave = data.qpos[gold_qadr:gold_qadr + 3].copy()
    qvsave = data.qvel[gold_qadr:gold_qadr + 3].copy() if data.qvel.size else None
    try:
        for dz in (0.008, 0.060, 0.120):
            for dx in (-0.05, 0.0, 0.05):
                for dy in (-0.05, 0.0, 0.05):
                    P3 = [cx + dx, cy + dy, plane_z + dz]
                    data.qpos[gold_qadr:gold_qadr + 3] = P3
                    data.qpos[gold_qadr + 3:gold_qadr + 7] = [1, 0, 0, 0]
                    if qvsave is not None:
                        data.qvel[gold_qadr:gold_qadr + 3] = 0
                    mujoco.mj_forward(model, data)
                    renderer.update_scene(data, cam)
                    img = np.asarray(renderer.render())
                    ys, xs = np.where(gold_mask(img))
                    if len(xs) < 40:
                        continue
                    mx, my = float(np.median(xs)), float(np.median(ys))
                    keep = (np.abs(xs - mx) < 90) & (np.abs(ys - my) < 90)
                    world.append(P3)
                    pixels.append((float(xs[keep].mean()), float(ys[keep].mean())))
    finally:
        data.qpos[gold_qadr:gold_qadr + 3] = qsave
        if qvsave is not None:
            data.qvel[gold_qadr:gold_qadr + 3] = qvsave
        mujoco.mj_forward(model, data)
    if len(world) < 6:
        return {"ok": False, "n": len(world), "err": "标定点不足 6 个 (%s)" % tag}
    Pm = _dlt_P(world, pixels)
    # 平面单应 (只用 dz 最小的那 9 点): 2D→3D 定位用 H 更准 (实测 0.8px vs 全 P 3.9px,
    # 因为高处的模块遮出的是顶面, 质心 ≠ 体心, 会把全 P 的拟合带偏)
    pl = [(w, p) for w, p in zip(world, pixels) if abs(w[2] - (plane_z + 0.008)) < 1e-9]
    Hm = None
    resH = None
    if len(pl) >= 4:
        Hm = _solve_homography([w[:2] for w, _ in pl], [p for _, p in pl])
        resH = []
        for w, (u, v) in pl:
            pu, pv = _apply_h(Hm, w[0], w[1])
            resH.append(((pu - u) ** 2 + (pv - v) ** 2) ** 0.5)
    res = []
    for W3, (u, v) in zip(world, pixels):
        pr = _proj_P(Pm, W3)
        if pr:
            res.append(((pr[0] - u) ** 2 + (pr[1] - v) ** 2) ** 0.5)
    return {"ok": True, "P": Pm.tolist(), "H": (Hm.tolist() if Hm is not None else None),
            "n": len(world), "n_plane": len(pl),
            "res_plane_px_med": round(float(np.median(resH)), 2) if resH else None,
            "res_px_med": round(float(np.median(res)), 2) if res else None,
            "res_px_max": round(float(np.max(res)), 2) if res else None,
            "plane_z": round(float(plane_z), 5), "tray_center": [round(cx, 4), round(cy, 4)],
            "view": tag}


def _truth(mj, model, data, mujoco, plane_z):
    def gp(nm):
        i = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, nm)
        return [round(float(v), 5) for v in data.geom_xpos[i]] if i >= 0 else None

    def sp(nm):
        i = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, nm)
        return [round(float(v), 5) for v in data.site_xpos[i]] if i >= 0 else None

    def jq(side):
        out = []
        for k in range(6):
            j = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "%s_j%d" % (side, k))
            out.append(round(float(data.qpos[model.jnt_qposadr[j]]), 4) if j >= 0 else None)
        return out

    def jv(side):
        out = []
        for k in range(6):
            j = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "%s_j%d" % (side, k))
            out.append(round(float(data.qvel[model.jnt_dofadr[j]]), 4) if j >= 0 else 0.0)
        return out

    def sm(side):
        """TCP site 旋转 (展平 9) — obs[24:33] 同口径。"""
        i = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "%s_tcp" % side)
        return [round(float(v), 5) for v in data.site_xmat[i]] if i >= 0 else [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]

    def fq(side):
        """两指开度 (slide qpos, 0..0.02) — obs[10:12] 同口径。"""
        out = []
        for f in ("fa", "fb"):
            j = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "%s_%s" % (side, f))
            out.append(round(float(data.qpos[model.jnt_qposadr[j]]), 5) if j >= 0 else 0.0)
        return out

    return {"gold": gp("gold_geom"), "hole": sp("hole"), "goal": sp("goal"),
            "tcpL": gp("L_tcp"), "tcpR": gp("R_tcp"),
            "qL": jq("L"), "qR": jq("R"), "plane_z": round(float(plane_z), 5),
            # 🔴 2026-10-29: 补齐 obs43 需要的真值通道 (dq/旋转/夹爪开度), 全部 mujoco 真值,
            #   不给下游留"用 0 填"的借口 (触觉 4 维另说: 场景无触觉传感器, 明确标 0)。
            "dqL": jv("L"), "dqR": jv("R"),
            "rotL": sm("L"), "rotR": sm("R"),
            "gripL": fq("L"), "gripR": fq("R"),
            "sim_time": round(float(data.time), 3)}


# ───────────── IK (阻尼最小二乘, mujoco 雅可比真解) ─────────────
def ik_solve(mj, model, data, mujoco, side, target, iters=240, tol=0.002, limit_deg=165.0,
             seed_deg=None, rate_deg=None):
    """6 轴 IK: 阻尼最小二乘 + 多初值重试 + 关节限位规避。

    🔴 单初值会卡在 170° 关节限位上 (实测 L 臂给出 deg=170 的解, 执行端 PD 永远到不了,
       8s 超时) ⇒ 这里多初值取最优, 且把"贴限位"的解判为不可达, 让调用方如实报 err。
    """
    import numpy as np
    jids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "%s_j%d" % (side, k))
            for k in range(6)]
    qadr = [int(model.jnt_qposadr[j]) for j in jids]
    dadr = [int(model.jnt_dofadr[j]) for j in jids]
    gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "%s_tcp" % side)
    bid = int(model.geom_bodyid[gid]) if gid >= 0 else -1
    if gid < 0 or bid < 0:
        return {"ok": False, "err": "找不到 %s_tcp" % side}
    tgt = np.asarray(target, float)
    lim = np.radians(limit_deg)
    q_now = np.array([float(data.qpos[a]) for a in qadr], float)
    rng = np.random.default_rng(7)
    seeds = [q_now, np.zeros(6), np.array([0.5, 1.6, -2.6, -0.45, 0.0, 0.0])]
    seeds += [q_now + rng.uniform(-0.6, 0.6, 6) for _ in range(4)]
    best = None
    cands = []
    jacp = np.zeros((3, model.nv))
    jacr = np.zeros((3, model.nv))
    for q0 in seeds:
        d = mujoco.MjData(model)
        d.qpos[:] = data.qpos
        for k, a in enumerate(qadr):
            d.qpos[a] = float(np.clip(q0[k], -lim, lim))
        mujoco.mj_forward(model, d)
        err = 1e9
        for it in range(iters):
            mujoco.mj_forward(model, d)
            p = np.array(d.geom_xpos[gid], float)
            e = tgt - p
            err = float(np.linalg.norm(e))
            if err < tol:
                break
            mujoco.mj_jac(model, d, jacp, jacr, p, bid)
            J = jacp[:, dadr]
            lam = 0.03
            dq = J.T @ np.linalg.solve(J @ J.T + lam * np.eye(3), e)
            dq = np.clip(dq, -0.15, 0.15)
            for k, a in enumerate(qadr):
                d.qpos[a] = float(np.clip(d.qpos[a] + dq[k], -lim, lim))
        mujoco.mj_forward(model, d)
        p = np.array(d.geom_xpos[gid], float)
        err = float(np.linalg.norm(tgt - p))
        q = np.array([float(d.qpos[a]) for a in qadr], float)
        at_lim = bool(np.any(np.abs(q) > lim - 1e-3))
        score = err + (0.05 if at_lim else 0.0) + 0.001 * float(np.linalg.norm(q - q_now))
        cands.append({"score": score, "err": err, "q": q, "at_lim": at_lim, "tcp": p})
        if best is None or score < best["score"]:
            best = {"score": score, "err": err, "q": q, "at_lim": at_lim, "tcp": p}
        if err < tol and not at_lim:
            break
    # 🔴 2026-10-29 连续控制用: 给 seed_deg 时, 在"同样能到"的解里挑**离上一条指令最近**的,
    #   否则逐拍重新 IK 会跳分支 (实测 L 臂在一拍之内从 z=0.55 折到 z=0.25, 80 拍都追不回来)。
    #   rate_deg 再做关节限速, 保证一条指令不会让 PD 走大步。
    if seed_deg is not None and cands:
        sd = np.radians(np.asarray(seed_deg, float))
        ok = [c for c in cands if c["err"] < 0.02 and not c["at_lim"]]
        pick = min(ok or cands, key=lambda c: float(np.linalg.norm(c["q"] - sd)))
        best, q = dict(pick), np.array(pick["q"], float)
        if rate_deg:
            r = np.radians(float(rate_deg))
            q = np.clip(q, sd - r, sd + r)
            best["q"] = q
            best["rate_clipped"] = True
        best["seed_gap_deg"] = round(float(np.degrees(np.linalg.norm(best["q"] - sd))), 2)
    q, err = best["q"], best["err"]
    return {"ok": bool(err < 0.02 and not best["at_lim"]), "side": side,
            "deg": [round(np.degrees(v), 2) for v in q],
            "q_rad": [round(float(v), 5) for v in q], "err_mm": round(err * 1000, 2),
            "at_limit": best["at_lim"], "reachable": bool(not best["at_lim"]),
            "tcp": [round(float(v), 5) for v in best["tcp"]],
            "seed_gap_deg": best.get("seed_gap_deg"), "rate_clipped": best.get("rate_clipped"),
            "target": [round(float(v), 5) for v in tgt]}


def _apply_ctrl(mj, env, model, data, mujoco, cmd):
    """把 deg 指令写进 position actuator; 夹爪 0..1 → 0.002..0.018 m。"""
    import numpy as np
    for side in ("L", "R"):
        ang = cmd.get(side)
        if not ang:
            continue
        for k in range(6):
            aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, "%s_act%d" % (side, k))
            if aid < 0:
                continue
            v = float(np.radians(float(ang[k])))
            v = float(np.clip(v, -np.radians(170), np.radians(170)))
            data.ctrl[aid] = v
    for side in ("L", "R"):
        g = cmd.get("grip" + side)
        if g is None:
            continue
        g = float(np.clip(float(g), 0.0, 1.0))
        for f in ("a", "b"):
            aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, "%s_act_f%s" % (side, f))
            if aid >= 0:
                data.ctrl[aid] = 0.002 + 0.016 * g


def render_loop(hz: float, jitter: bool, seed: int, phys_hz: float = 0.0, render_hz: float = 0.0):
    import cv2
    import mujoco
    import numpy as np
    from ar_mujoco_env import ArMujocoEnv

    # 🔴 2026-10-29: 构造必须在 try 里 + 自愈重试。
    #   原来 env/renderer 建在 try 之外 ⇒ 开机时 X/GL 还没就绪就抛异常, **线程直接死**,
    #   主线程照样监听端口 ⇒ 表面"服务 active"、实际 n=0 且 err=None(假活, 实测 74 分钟零帧)。
    while True:
        try:
            env = ArMujocoEnv(render_mode="rgb_array", camera_name="corner2")
            model, data = env.model, env.data
            env.reset()                                   # 双臂 home, 不留 0 位姿
            renderer = mujoco.Renderer(model, H, W)
            cams, cam0 = {}, {}
            for name, v in VIEWS.items():
                c = mujoco.MjvCamera()
                c.lookat[:] = v["lookat"]
                c.distance = v["distance"]
                c.elevation = v["elevation"]
                c.azimuth = v["azimuth"]
                cams[name] = c
                cam0[name] = (v["elevation"], v["azimuth"])
            gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "gold_module")
            jid = int(model.body_jntadr[gid]) if gid >= 0 else -1
            qadr = int(model.jnt_qposadr[jid]) if jid >= 0 else -1
            mujoco.mj_forward(model, data)
            base = np.array(data.qpos[qadr:qadr + 3]) if qadr >= 0 else None
            tid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "table")
            plane_z = float(data.geom_xpos[tid][2] + model.geom_size[tid][2]) if tid >= 0 else 0.10
            cx, cy = (float(base[0]), float(base[1])) if base is not None else (0.52, 0.35)
            calibs = {}
            for name, c in cams.items():
                calibs[name] = calibrate_camera(mujoco, model, data, renderer, qadr,
                                                plane_z, cx, cy, c, name,
                                                fovy=VIEWS[name].get("fovy", 45.0))
                cl = calibs[name]
                print("📐 标定[%s]: n=%s 残差中位 %s px" % (name, cl.get("n"), cl.get("res_px_med")),
                      flush=True)
            with LOCK:
                STATE.update({"err": None, "calib": calibs.get("close") or {},
                              "calibs": calibs, "plane_z": plane_z})
            ENV["env"] = env
            break
        except Exception as e:                                               # noqa: BLE001
            with LOCK:
                STATE["err"] = "构造失败(3s 后重试): %s: %s" % (type(e).__name__, e)
            time.sleep(3.0)

    n = 0
    _phz = float(phys_hz or hz)
    _rhz = float(render_hz or hz)
    period = 1.0 / max(0.5, _phz)              # 每拍 = 物理/真值一拍
    _rperiod = 1.0 / max(0.5, _rhz)            # 出图间隔
    _last_render = 0.0
    _views_cache = {}
    while True:
        t0 = time.time()
        with LOCK:
            cmd = dict(CMD)
        mode = cmd.get("mode") or "idle"
        try:
            if mode == "sim":
                # 控制模式: 下指令 → 真跑物理 → 渲染 (臂真的动)
                _apply_ctrl(mujoco, env, model, data, mujoco, cmd)
                _nstep = max(1, int(round(period / 0.002)))
                for _ in range(_nstep):                 # period/2ms 拍 (物理与真值同频)
                    mujoco.mj_step(model, data)
            elif jitter and base is not None and qadr >= 0:
                ph = n / 12.0
                # 幅值 3mm (原 12/10mm): 画面"活"靠机位微抖就够了; 模块大幅漂移会让
                # 感知误差核对变成"帧与真值时序差"(实测出现 16mm 假误差)
                data.qpos[qadr + 0] = base[0] + 0.003 * np.sin(ph)
                data.qpos[qadr + 1] = base[1] + 0.0025 * np.cos(ph * 0.8)
                mujoco.mj_forward(model, data)
            else:
                mujoco.mj_forward(model, data)
            # 同一拍出两路图 (特写 + 全景) ⇒ 两个视角天生同步
            # 🔎 2026-10-29: 渲染(4 路 render+PNG) ~60ms ⇒ 逼得整个循环只能跑 8~9Hz,
            #   真值因此 125ms 才更新一帧, 末端 350mm/s 就成 44mm 的台阶 (采样看像 1.2m/s 猛冲)。
            #   这里把"出图"和"物理/真值"解耦: 真值每拍更新, 图按 render_hz 出, 中间复用上一帧。
            _do_render = (time.time() - _last_render) >= _rperiod
            if _do_render:
                _last_render = time.time()
                views_out = dict(_views_cache or {})
                # 只渲特写 (close) 每拍出图; 全景 (ar3d) 每 3 拍一次 —— 两路一起渲 ~60ms,
                # 是出图帧率上不去的根因; 特写单路 ~20ms ⇒ 出图能到 25~30Hz。
                _names = list(cams.keys())
                if len(_names) > 1:
                    _names = [_names[0]] + ([_names[1]] if (n % 3 == 0) else [])
                for name in _names:
                    c = cams[name]
                    if jitter and mode != "sim":
                        c.elevation = cam0[name][0] + 1.5 * np.cos(n / 7.0)
                        c.azimuth = cam0[name][1] + 2.0 * np.sin(n / 24.0)
                    else:
                        c.elevation, c.azimuth = cam0[name]
                    model.vis.global_.fovy = float(VIEWS[name].get("fovy", 45.0))
                    renderer.update_scene(data, c)
                    img = np.asarray(renderer.render())
                    box, px = gold_box(gold_mask(img))
                    ok, buf = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR),
                                           [cv2.IMWRITE_PNG_COMPRESSION, 3])
                    if not ok:
                        raise RuntimeError("png encode failed")
                    views_out[name] = {"png": buf.tobytes(), "mean": round(float(img.mean()), 2),
                                       "gold_px": px, "box": box, "shape": list(img.shape),
                                       "ts": time.time()}
                _views_cache = views_out
            else:
                views_out = _views_cache or {}
            n += 1
            cl = views_out.get("close") or {}
            with LOCK:
                STATE.update({"n": n, "ts": time.time(), "mode": mode,
                              "truth": _truth(mujoco, model, data, mujoco, plane_z),
                              "cmd": {k: cmd.get(k) for k in ("L", "R", "gripL", "gripR")},
                              "ctl": dict(CMD.get("stats") or {}),
                              "steps": int(data.time / 0.002), "views": views_out,
                              "png": cl.get("png", b""), "mean": cl.get("mean"),
                              "gold_px": cl.get("gold_px"), "box": cl.get("box"),
                              "shape": cl.get("shape"),
                              "ms": round((time.time() - t0) * 1000, 1), "err": None})
        except Exception as e:                                               # noqa: BLE001
            with LOCK:
                STATE["err"] = "%s: %s" % (type(e).__name__, e)
        dt = period - (time.time() - t0)
        if dt > 0:
            time.sleep(dt)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):                                              # noqa: D401
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:                                                    # noqa: BLE001
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):                                                        # noqa: N802
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        p, qs = u.path, parse_qs(u.query)
        with LOCK:
            st = dict(STATE)
        views = st.get("views") or {}
        cam_name = (qs.get("cam") or ["close"])[0]
        if cam_name not in VIEWS:
            cam_name = "close"
        if p in ("/", "/frame.png", "/frame.jpg"):
            b = (views.get(cam_name) or {}).get("png") or (st["png"] if cam_name == "close" else b"")
            if not b:
                self._send(503, b"no frame yet", "text/plain")
                return
            self._send(200, b, "image/png")
            return
        if p == "/status.json":
            age = (time.time() - st["ts"]) if st["ts"] else None
            cal = st.get("calibs") or {}
            self._json({"ok": st["err"] is None, "n": st["n"], "mode": st["mode"],
                        "age_s": round(age, 2) if age is not None else None,
                        "shape": st.get("shape"), "mean": st.get("mean"),
                        "gold_px": st.get("gold_px"), "box": st.get("box"), "ms": st.get("ms"),
                        "err": st["err"],
                        "calib": st.get("calib"),
                        "views": {k: {"mean": v.get("mean"), "gold_px": v.get("gold_px"),
                                      "box": v.get("box"), "shape": v.get("shape"),
                                      "n": st["n"], "ts": st["ts"]} for k, v in views.items()},
                        "calibs": {k: {"res_px_med": (c or {}).get("res_px_med"),
                                       "n": (c or {}).get("n"), "ok": (c or {}).get("ok"),
                                       "view_note": VIEWS[k]["note"]} for k, c in cal.items()},
                        "src": "ArMujocoEnv(AR工位) · 双视角 close/ar3d · 960x720"})
            return
        if p == "/label.json":
            vb = (views.get(cam_name) or {})
            self._json({"ok": vb.get("box") is not None, "n": st["n"], "ts": st["ts"],
                        "cam": cam_name, "box": vb.get("box"), "gold_px": vb.get("gold_px"),
                        "note": "金色像素连通域外接框 = 像素级真值 (非模型预测)"})
            return
        if p == "/state.json":
            self._json({"ok": True, "n": st["n"], "ts": st["ts"], "mode": st["mode"],
                        "age_s": round(time.time() - st["ts"], 2) if st["ts"] else None,
                        "truth": st.get("truth"), "cmd": st.get("cmd"),
                        "calib": st.get("calib"), "calibs": st.get("calibs"),
                        "steps": st.get("steps"), "err": st["err"], "views": list(views),
                        "ctl": st.get("ctl")})
            return
        if p == "/calib.json":
            self._json({"ok": True, "calibs": st.get("calibs") or {},
                        "views": {k: {"note": v["note"], "lookat": v["lookat"],
                                      "distance": v["distance"], "elevation": v["elevation"],
                                      "azimuth": v["azimuth"]} for k, v in VIEWS.items()}})
            return
        if p in ("/ik", "/proj", "/unproj"):
            env = ENV.get("env")
            if env is None:
                self._json({"ok": False, "err": "场景未就绪"}, 503)
                return
            import mujoco
            try:
                if p == "/ik":
                    side = (qs.get("side") or ["R"])[0].upper()
                    tgt = [float(qs["x"][0]), float(qs["y"][0]), float(qs["z"][0])]
                    # seed: 上一条指令的关节角 (逐拍连续控制必须给, 否则跳分支)
                    _sd = None
                    if qs.get("seed"):
                        try:
                            _sd = [float(v) for v in str(qs["seed"][0]).split(",")][:6]
                        except Exception:                                    # noqa: BLE001
                            _sd = None
                    _rate = float(qs["rate"][0]) if qs.get("rate") else None
                    self._json(ik_solve(mujoco, env.model, env.data, mujoco, side, tgt,
                                        seed_deg=_sd, rate_deg=_rate))
                    return
                cal = (st.get("calibs") or {}).get(cam_name) or {}
                if not cal.get("ok"):
                    self._json({"ok": False, "err": "视角 %s 标定未完成: %s" % (cam_name, cal.get("err"))})
                    return
                Pm = cal["P"]
                if p == "/unproj":
                    if cal.get("H"):
                        xx, yy = _apply_h_inv(cal["H"], float(qs["u"][0]), float(qs["v"][0]))
                        self._json({"ok": True, "cam": cam_name, "x": round(xx, 5), "y": round(yy, 5),
                                    "z": round(float(cal["plane_z"]), 5),
                                    "src": "平面单应 H 反解 (残差 %s px)" % cal.get("res_plane_px_med"),
                                    "note": "像素→台面; 高度按台面, 不是模块顶面"})
                        return
                    r = _unproj_P(Pm, float(qs["u"][0]), float(qs["v"][0]), cal["plane_z"])
                    if not r:
                        self._json({"ok": False, "err": "射线与台面无交"})
                        return
                    self._json({"ok": True, "cam": cam_name, "x": round(r[0], 5), "y": round(r[1], 5),
                                "z": round(float(cal["plane_z"]), 5),
                                "note": "像素→台面 (标定 P 反解); 高度按台面, 不是模块顶面"})
                    return
                q = _proj_P(Pm, [float(qs["x"][0]), float(qs["y"][0]), float(qs["z"][0])])
                if not q:
                    self._json({"ok": False, "err": "投影失败"})
                    return
                self._json({"ok": True, "cam": cam_name, "u": round(q[0], 1), "v": round(q[1], 1)})
                return
            except Exception as e:                                           # noqa: BLE001
                self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, e)}, 400)
                return
        self._send(404, b"not found", "text/plain")

    def do_POST(self):                                                       # noqa: N802
        from urllib.parse import urlparse
        p = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:                                                    # noqa: BLE001
            self._json({"ok": False, "err": "body 不是 JSON"}, 400)
            return
        if p == "/control":
            _now = time.time()
            with LOCK:
                # 🔎 指令流取证 (2026-10-29): 实测"末端 1.2m/s 猛冲"但看不懂指令从哪来 ⇒
                #   这里把每一次下发与上一次的**关节最大变化**、以及下发频率记下来, 由 /state.json 暴露。
                _st = CMD.setdefault("stats", {"n": 0, "t0": _now, "dmax": 0.0, "nfast": 0,
                                               "last": {}, "gapmax": 0.0, "tlast": 0.0})
                for _sd in ("L", "R"):
                    _v = body.get(_sd)
                    _p = (_st["last"] or {}).get(_sd)
                    if _v and _p:
                        try:
                            _d = max(abs(float(a) - float(b)) for a, b in zip(_v, _p))
                            _st["dmax"] = max(_st["dmax"], _d)
                            if _d > 1.2:
                                _st["nfast"] += 1
                        except Exception:                                        # noqa: BLE001
                            pass
                    if _v:
                        _st["last"][_sd] = list(_v)
                if _st["tlast"]:
                    _st["gapmax"] = max(_st["gapmax"], _now - _st["tlast"])
                _st["tlast"] = _now
                _st["n"] += 1
                _st["hz"] = round(_st["n"] / max(1e-6, _now - _st["t0"]), 1)
                CMD.update({"mode": str(body.get("mode") or "sim"),
                            "L": body.get("L"), "R": body.get("R"),
                            "gripL": body.get("gripL"), "gripR": body.get("gripR"),
                            "ts": _now})
            self._json({"ok": True, "cmd": {k: CMD.get(k) for k in ("mode", "L", "R", "gripL", "gripR")}})
            return
        if p == "/reset":
            env = ENV.get("env")
            if env is None:
                self._json({"ok": False, "err": "场景未就绪"}, 503)
                return
            with LOCK:
                CMD.update({"mode": "idle", "L": None, "R": None, "gripL": None, "gripR": None})
            env.reset()
            self._json({"ok": True, "note": "已回 home 姿态 (渲染线程下一拍生效)"})
            return
        self._send(404, b"not found", "text/plain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8802)
    ap.add_argument("--hz", type=float, default=8.0)                 # 兼容旧参数 = 渲染频率
    ap.add_argument("--phys-hz", type=float, default=0.0)             # 物理/真值频率 (0=跟 --hz 同频)
    ap.add_argument("--render-hz", type=float, default=0.0)           # 渲染频率 (0=跟 --hz 同频)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--no-jitter", action="store_true")
    a = ap.parse_args()
    threading.Thread(target=render_loop, args=(a.hz, not a.no_jitter, a.seed,
                                               a.phys_hz, a.render_hz),
                     daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    print("🎬 AR 工位渲染帧服务 :%d · %.1fHz · 960x720 · /frame.png /state.json /label.json "
          "/control /ik /unproj" % (a.port, a.hz), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
