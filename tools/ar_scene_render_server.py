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
import hashlib
import os
import queue
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
    # 🔴 2026-11-09: 换真 URDF 臂后臂高 1.23m (旧缩尺链只 0.6m), 目标点还压在台面 0.14 会把腕部顶出画面。
    #   目标点抬到臂身中部 0.50、距离放到 2.0 ⇒ 底座到腕都进画; 方向仍与 AR 页同一套 (yaw-0.9 pitch0.55)。
    #   🔴 2026-11-09 二修: 两臂基座在 y=0 / y=0.5, 方位角 -51.6 正好与基线重合 ⇒ 近臂把远臂整个遮死;
    #      目标点抬到 0.50 又让上方 30% 死黑。改方位 -72°(侧看, 两臂错开)、目标点落回臂身中部 0.36、距离 1.85。
    #   🔴 2026-11-09 三修: 两臂基座在 y=0/0.5, 只有沿 x 轴看才能把两台分开 (方位 -51.6/-72 都沿 y ⇒ 叠一起)。
    #      改方位 0° (正面), 俯角 -22°, 目标点 z0.30, 距离 1.75 ⇒ 两台底座各自可见。
    #   🔴 2026-11-09 四修: 距离 1.75 时左臂腕/夹爪出画 (两臂不对称)。后拉到 2.25, 目标点抬到 0.42。
    "ar3d": {"lookat": [0.55, 0.25, 0.42], "distance": 2.25, "elevation": -20.0,
             "azimuth": 0.0, "fovy": 69.4, "note": "全景: 正面 (方位0) 两臂分开且腕部入画, 目标点 z0.42 d2.25"},
}
STATE = {"png": b"", "n": 0, "ts": 0.0, "mean": None, "gold_px": 0, "box": None,
         "ms": None, "shape": None, "err": None, "mode": "idle",
         "truth": {}, "calib": {}, "cmd": {}, "steps": 0,
         "views": {}}
LOCK = threading.Lock()
GL = threading.Lock()
FREE_Q = queue.Queue(maxsize=8)   # 🎥 任意视角请求 (必须由渲染线程消费: EGL 上下文线程绑定)          # 🎥 按需任意视角渲染 与 主循环 共用 renderer ⇒ 必须串行
_STREAMS = {"n": 0, "max": 3}     # 🎬 /video MJPEG 同时观看数上限(每条流都会持续拉渲染/重发帧, 不设上限会把渲染线程吃满)
_STREAMS_LOCK = threading.Lock()
# 🎥 2026-11-09 老倪: 「/video 没有跟 8797/ar3d 同步」⇒ ar3d 页面每 500ms 把它的相机
#   (az/el/dist/tgt/fovy) POST 到 /cam 落到这个文件; /video 每帧读它, 用**同一机位**渲染 ⇒
#   窗口里看到的就是页面上那个视角。页面不动相机时参数不变 ⇒ 复用上一帧, 零额外渲染开销
#   (自由机位单帧约 70ms, 12fps 空转会白烧 CPU 并拖慢 L2 取帧)。
_CAM_SYNC = {"path": os.path.expanduser(os.environ.get("ZMAX_AR3D_CAM")
                                        or "~/zmax/zmax_data/ss_live/ar3d_cam.json")}
_CAM_SYNC_LOCK = threading.Lock()


def _cam_sync_read(max_age=6.0):
    """读 ar3d 页面推来的相机; 过期/缺失 → None(退回预设机位, 不假装同步)。"""
    try:
        with open(_CAM_SYNC["path"], encoding="utf-8") as _f:
            d = json.load(_f)
        if (time.time() - float(d.get("ts") or 0)) > max_age:
            return None
        out = {}
        for k in ("az", "el", "dist", "tx", "ty", "tz", "fovy"):
            if k in d:
                out[k] = [str(d[k])]      # render_free 吃的是 query dict(list)
        return out if len(out) >= 6 else None
    except Exception:                                                    # noqa: BLE001
        return None


def _cam_sync_write(payload, src=""):
    d = {k: payload[k] for k in ("az", "el", "dist", "tx", "ty", "tz", "fovy") if k in payload}
    d["ts"] = time.time()
    d["src"] = src
    with _CAM_SYNC_LOCK:
        _p = _CAM_SYNC["path"]
        os.makedirs(os.path.dirname(_p), exist_ok=True)
        _tmp = _p + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as _f:
            json.dump(d, _f)
        os.replace(_tmp, _p)
    return d
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



# ═════ 🔁 AR 场景同步 (老倪 2026-11-09: 「http://127.0.0.1:8802/video 不同步」) ═════
#   8802 在 idle 时双臂是死的, 而 AR 页在按 ss_live/ar_cmd.json 走 (抓/插/拔/检测) ⇒ 两边画面自然对不上。
#   这里让渲染循环在 idle 时读 ar_cmd(新鲜 ≤2.5s), 把右臂目标 a→b 按 u 插值, 用本服务的 IK 解成 6 个关节角,
#   按 position actuator 下发 ⇒ 画面里的右臂和 AR 页同一个动作。解不出来就跳过(不假装同步, 页面上臂不动)。
_AC_LAST = {"t": 0.0, "deg": None, "err": None, "n": 0}


def _ar_cmd_read(max_age=2.5):
    try:
        with open(os.path.join(ROOT, "zmax_data", "ss_live", "ar_cmd.json"), encoding="utf-8") as _f:
            d = json.load(_f)
        if (time.time() - float(d.get("t") or 0)) > max_age:
            return None
        return d
    except Exception:                                                    # noqa: BLE001
        return None


def _ar_cmd_ctrl(mujoco, env, model, data, d):
    a, b = d.get("a"), d.get("b")
    if not a or not b:
        return None
    try:
        u = float(d.get("u") or 0.0)
        tgt = [(float(a[i]) + u * (float(b[i]) - float(a[i]))) / 1000.0 for i in range(3)]
    except Exception:                                                    # noqa: BLE001
        return None
    now = time.time()
    deg = _AC_LAST.get("deg")
    if not deg or (now - _AC_LAST["t"]) >= 0.12:
        r = ik_solve(mujoco, model, data, mujoco, "R", tgt, iters=60, seed_deg=deg)
        if not r.get("ok"):
            _AC_LAST["err"] = r.get("err") or "ik bad"
            return None
        deg = r["deg"]
        _AC_LAST.update({"t": now, "deg": deg, "err": None, "n": _AC_LAST.get("n", 0) + 1})
    out = {"mode": "sim", "R": deg, "_src": "ar_cmd", "_label": d.get("label"),
           "_tgt_mm": [round(v * 1000, 1) for v in tgt]}
    g = d.get("grip")
    if isinstance(g, (int, float)):
        out["gripR"] = float(g)
    return out


# ═════ 🎯 关节角直传 (老倪 2026-11-09: 「AR 场景的动作和 MuJoCo 的动作不一致」) ═════
#   根因: AR 页用**它自己的 IK** 解关节角画臂, 8802 用 Python 的 ik_solve 再解一遍 ⇒ 两个求解器
#   落不同分支(肘上/肘下), 同一个 TCP 目标画出两种姿态。外形换真 URDF 后几何一致了, 但解不唯一。
#   解法: 页面把它算出来的 6 个关节角直接推过来 (POST /armq), 8802 只做执行, 不再解 IK ⇒ 构造上一致。
_MJQ_FILE = os.path.join(ROOT, "zmax_data", "ss_live", "ar_mj_q.json")


def _apply_kin(mujoco, model, data, cmd):
    """把页面推来的关节角**直接写进 qpos** (运动学跟随), 不靠 PD 伺服。

    为什么不用 position actuator 跟: 真 URDF 链在 kp=300/1500 下都有 15° 级静差
    (实测 j0/j1 各差 15.9°, 末端差 57~217mm), 画面上看就是"手臂没到画布那个姿态"。
    AR 叠加要的是**同一组角 = 同一姿态**, 不是伺服精度; 光模块/工件的物理照常步进。
    """
    import numpy as np
    n = 0
    for side in ("L", "R"):
        deg = cmd.get(side)
        if not deg or len(deg) < 6:
            continue
        for k in range(6):
            j = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "%s_j%d" % (side, k))
            if j < 0:
                continue
            a = int(model.jnt_qposadr[j])
            data.qpos[a] = float(np.radians(float(deg[k])))
            v = int(model.jnt_dofadr[j])
            data.qvel[v] = 0.0
            aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, "%s_act%d" % (side, k))
            if aid >= 0:
                data.ctrl[aid] = float(np.radians(float(deg[k])))
            n += 1
    return n


def _armq_write(payload):
    d = {"t": time.time(), "R": payload.get("R"), "L": payload.get("L"),
         "gripL": payload.get("gripL"), "gripR": payload.get("gripR"),
         "seq": payload.get("seq"), "src": payload.get("src") or "ar3d"}
    os.makedirs(os.path.dirname(_MJQ_FILE), exist_ok=True)
    tmp = _MJQ_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, _MJQ_FILE)
    return d


def _armq_read(max_age=1.5):
    try:
        with open(_MJQ_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if (time.time() - float(d.get("t") or 0)) > max_age:
            return None
        return d
    except Exception:                                                    # noqa: BLE001
        return None


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
            # 🪟 2026-11-09 小静静实测: Windows 会话0/无桌面时 mujoco.Renderer 建不出来(WGL 无上下文,
            #   'Renderer' object has no attribute '_mjr_context')。原来这里一抛 ⇒ 整个构造轮重试 ⇒
            #   ENV 永不就位 ⇒ /bones.json 永远「未生成」 ⇒ AR3D 页面里**没有机器人**。
            #   降级: 没有 GL 就只跑物理 + 骨骼真值(不出渲染帧), 页面照样能画双臂并跟 ar_cmd 走。
            try:
                renderer = mujoco.Renderer(model, H, W)
            except Exception as _ge:                                     # noqa: BLE001
                renderer = None
                print("⚠ 无 GL 上下文 ⇒ 降级为「只出真值/骨骼」模式: %s: %s"
                      % (type(_ge).__name__, _ge), flush=True)
            ENV.update({"model": model, "data": data, "renderer": renderer})
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
            if renderer is not None:                 # 无 GL 没法标定(要渲染靶点) ⇒ 跳过, 不拦循环
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
        # 🎯 关节角直传优先于一切外部 /control: 页面推来的角就是画布上那台臂的角,
        #   8802 只执行 ⇒ 两边姿态逐帧一致 (两套 IK 各解一次必然有分支差)。
        _mq0 = _armq_read()
        if _mq0 and (_mq0.get("R") or _mq0.get("L")):
            mode = "sim"
            cmd = {"mode": "sim", "R": _mq0.get("R"), "L": _mq0.get("L"),
                   "gripL": _mq0.get("gripL"), "gripR": _mq0.get("gripR"), "_kin": True}
            with LOCK:
                STATE["sync"] = {"src": "armq", "seq": _mq0.get("seq"),
                                 "age_s": round(time.time() - float(_mq0.get("t") or 0), 2),
                                 "hasL": bool(_mq0.get("L")), "hasR": bool(_mq0.get("R"))}
        if mode == "idle":
            # 🎯 最优: 页面直推关节角 (两臂, 与画布同一组角) ⇒ 不解 IK, 姿态与画布逐帧一致
            _mq = _armq_read()
            if _mq and (_mq.get("R") or _mq.get("L")):
                mode = "sim"
                cmd = {"mode": "sim", "R": _mq.get("R"), "L": _mq.get("L"),
                       "gripL": _mq.get("gripL"), "gripR": _mq.get("gripR")}
                with LOCK:
                    STATE["sync"] = {"src": "armq", "seq": _mq.get("seq"),
                                     "age_s": round(time.time() - float(_mq.get("t") or 0), 2),
                                     "hasL": bool(_mq.get("L")), "hasR": bool(_mq.get("R"))}
                _ac = None
            else:
                _ac = _ar_cmd_read() if mode == "idle" else None
            if _ac is not None:
                _c2 = _ar_cmd_ctrl(mujoco, env, model, data, _ac)
                if _c2:
                    mode, cmd = "sim", _c2
                    with LOCK:
                        STATE["sync"] = {"src": "ar_cmd", "label": _c2.get("_label"),
                                         "tgt_mm": _c2.get("_tgt_mm"), "n": _AC_LAST.get("n")}
        try:
            if mode == "sim":
                # 控制模式: 下指令 → 真跑物理 → 渲染 (臂真的动)
                _apply_ctrl(mujoco, env, model, data, mujoco, cmd)
                _nstep = max(1, int(round(period / 0.002)))
                for _ in range(_nstep):                 # period/2ms 拍 (物理与真值同频)
                    mujoco.mj_step(model, data)
                if cmd.get("_kin"):
                    # 🎯 页面推角就是真值: 步进后再写一次 qpos 并清速度, 保证渲染姿态==画布姿态
                    _apply_kin(mujoco, model, data, cmd)
                    mujoco.mj_forward(model, data)
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
            with GL:                      # 🔒 出图与按需自由视角串行 (renderer 非线程安全)
                if _do_render and renderer is not None:
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
            # 🦾 仿真骨骼快照 (2026-11-08 老倪: AR 页要跟渲染同一份位姿数据)
            _bones = {"ok": True, "ts": time.time(), "n": n, "L": [], "R": []}
            for _side in ("L", "R"):
                _sg = []
                for _bi in range(model.nbody):
                    _nm = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, _bi) or ""
                    if not _nm.startswith(_side + "_"):
                        continue
                    _pa = int(model.body_parentid[_bi])
                    if _pa <= 0:                       # link0 挂世界系, 当起点用
                        continue
                    _sg.append([[round(float(v), 4) for v in data.xpos[_pa]],
                                [round(float(v), 4) for v in data.xpos[_bi]]])
                _bones[_side] = _sg
            with LOCK:
                STATE["bones"] = _bones
            # 🎥 任意视角请求: 必须在本线程渲染 (EGL 上下文线程绑定)
            while True:
                try:
                    _rq = FREE_Q.get_nowait()
                except Exception:                                          # noqa: BLE001
                    break
                try:
                    _cc = mujoco.MjvCamera()
                    _cc.lookat[:] = _rq["cam"]["lookat"]
                    _cc.distance = _rq["cam"]["distance"]
                    _cc.elevation = _rq["cam"]["elevation"]
                    _cc.azimuth = _rq["cam"]["azimuth"]
                    model.vis.global_.fovy = float(_rq["fovy"])
                    renderer.update_scene(data, _cc)
                    _im = np.asarray(renderer.render())
                    _ok, _buf = cv2.imencode(".png", cv2.cvtColor(_im, cv2.COLOR_RGB2BGR),
                                             [cv2.IMWRITE_PNG_COMPRESSION, 3])
                    _rq["png"] = _buf.tobytes() if _ok else None
                    _rq["err"] = None if _ok else "png encode failed"
                except Exception as _e:                                    # noqa: BLE001
                    _rq["err"] = "%s: %s" % (type(_e).__name__, _e)
                finally:
                    try:
                        model.vis.global_.fovy = float(VIEWS["close"].get("fovy", 45.0))
                    except Exception:                                      # noqa: BLE001
                        pass
                    _rq["ev"].set()
        except Exception as e:                                               # noqa: BLE001
            with LOCK:
                STATE["err"] = "%s: %s" % (type(e).__name__, e)
        dt = period - (time.time() - t0)
        if dt > 0:
            time.sleep(dt)


def render_free(qs, timeout=3.5):
    """🎥 任意视角: GET /frame.png?az=&el=&dist=&tx=&ty=&tz=&fovy=

    🔴 关键(实测): mujoco 的 EGL 上下文**绑定在渲染线程**, 在 HTTP 线程直接 render 会
    `EGLError(EGL_BAD_ACCESS, eglMakeCurrent)` → 所以这里只投递请求, 由 render_loop 线程渲染,
    结果经 Event 回传。默认值 = ar3d 全景机位; 只影响这一张图, 不动 STATE/标定/L2 那条链。
    """
    if ENV.get("renderer") is None or ENV.get("data") is None:
        raise RuntimeError("渲染器未就绪 (env/renderer 未建)")

    def _f(k, dv):
        try:
            return float((qs.get(k) or [dv])[0])
        except Exception:                                                  # noqa: BLE001
            return float(dv)

    cam = {"lookat": [_f("tx", 0.70), _f("ty", 0.22), _f("tz", 0.14)],
           "distance": max(0.05, _f("dist", 1.60)),
           "elevation": max(-90.0, min(90.0, _f("el", -31.5))),
           "azimuth": _f("az", -51.6)}
    req = {"cam": cam, "fovy": max(5.0, min(120.0, _f("fovy", VIEWS["ar3d"]["fovy"]))),
           "ev": threading.Event(), "png": None, "err": None}
    try:
        FREE_Q.put_nowait(req)
    except queue.Full:              # 丢最老的, 保证最新视角能出
        try:
            FREE_Q.get_nowait()
        except Exception:                                                  # noqa: BLE001
            pass
        FREE_Q.put_nowait(req)
    if not req["ev"].wait(timeout):
        raise RuntimeError("渲染线程忙/未出图 (超时 %.1fs)" % timeout)
    if req["err"]:
        raise RuntimeError(req["err"])
    if not req["png"]:
        raise RuntimeError("空帧")
    return req["png"]


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
        # 🎬 直播窗口默认看全景(ar3d) —— 「这个窗口」= AR 场景那个画面; 要料盘特写就 ?cam=close
        if p in ("/video", "/video.mjpg", "/stream", "/stream.mjpg") and not (qs.get("cam") or qs.get("c")):
            cam_name = "ar3d"
        if p in ("/", "/frame.png", "/frame.jpg") and any(
                k in qs for k in ("az", "el", "dist", "tx", "ty", "tz", "fovy")):
            try:
                self._send(200, render_free(qs), "image/png")
            except Exception as e:                                          # noqa: BLE001
                self._send(503, ("free-cam: %s: %s" % (type(e).__name__, e)).encode(), "text/plain")
            return
        if p in ("/", "/frame.png", "/frame.jpg"):
            b = b""
            if qs.get("live"):
                # 👁 live=1: 直播窗口要的是「和 AR 页同一个机位」⇒ 有新鲜推来的相机就现场按它渲染。
                #   不能拿 views[] 里的缓存帧 —— 那是预设机位, 老倪看到的就是「/video 与 AR 场景不同步」。
                try:
                    _cq = _cam_sync_read()
                    if _cq:
                        # 🎯 只信页面的**方向**(az/el), 目标点/距离换成 8802 自己的口径:
                        #   页面 autoZoom 的 tgt/dist 是它自绘场景的尺度(实测 tgt z=-186mm 落在台面下、
                        #   dist 2.1m 把工位拍成一小块), 照搬 ⇒ 画面又暗又空, 老倪看着就是「不同步」。
                        #   实测: dist×0.5 + 预设 lookat ⇒ 内容占比 5%→18%, 均值 13→24。
                        _cq = dict(_cq)
                        # 目标点钉在工位中心偏上(双臂工作高度): 页面 autoZoom 的 tgt 会掉到台面下,
                        #   pop 掉后用 render_free 的默认 tgt(0.70,0.22,0.14) 又会把上半屏留空
                        #   —— 实测 tgt z 0.14→0.32, 亮像素占比 5.1%→6.7%。
                        _cq["tx"], _cq["ty"], _cq["tz"] = ["0.52"], ["0.35"], ["0.32"]
                        _pd = float((_cq.get("dist") or ["1.6"])[0])
                        # 远近照页面(这才是"同焦"), 只做安全限幅; 目标点用预设(页面 autoZoom 的 tgt 会掉到台面下)
                        _cq["dist"] = [str(round(min(2.6, max(0.6, _pd * 0.65)), 3))]   # 0.65: 8802 场景比画布小, 同焦会显得空(实测占比 2%→16%)
                        b = render_free(_cq)
                except Exception:                                        # noqa: BLE001
                    b = b""
            if not b:
                b = (views.get(cam_name) or {}).get("png") or (st["png"] if cam_name == "close" else b"")
            if not b and cam_name != "close":
                # pull-frame-v1b: 直播窗口要的是"当前跟随机位的一张图" ⇒ 与 /video 同口径现场渲染,
                #   否则页面没在推视角时这里只有 503 (老倪右键新标签打开就一片空白)
                try:
                    _cq = _cam_sync_read()
                    b = render_free(_cq or {})
                except Exception:                                        # noqa: BLE001
                    b = b""
            if not b:
                self._send(503, b"no frame yet", "text/plain")
                return
            self._send(200, b, "image/png")
            return
        if p in ("/video", "/video.mjpg", "/stream", "/stream.mjpg") and \
                "text/html" in (self.headers.get("Accept") or "") and \
                (self.headers.get("Sec-Fetch-Dest") or "").lower() in ("document", ""):
            # 🖱 浏览器地址栏直接开 /video 时给 HTML 外壳 —— raw multipart 的顶栏导航永远"加载中"
            #   (实测浏览器一直转圈 ⇒ 老倪说的「video 网页打不开」)。<img src="/video"> 取流不受影响
            #   (那种请求 Sec-Fetch-Dest=image)。
            p = "/live"
        if p in ("/video", "/video.mjpg", "/stream", "/stream.mjpg"):
            # 🎬 2026-11-09 老倪: 「ar 场景渲染帧, 8802 输入还是跟原来一样 —— 把这个窗口直接做成
            #   http://10.163.146.76:8802/video 可以么?」⇒ 服务端直接推 MJPEG, 浏览器打开这个地址就是
            #   活的渲染画面(不再靠页面自己一帧帧拼, 也没跨源 taint 问题)。
            #   参数: cam=close|ar3d (默认 ar3d 全景) · fps=1..15 (默认 12)
            #        带 az/el/dist/tx/ty/tz/fovy ⇒ 自由机位(逐帧经渲染线程, 用独立 MjvCamera, 不动机位相机)
            _free = any(k in qs for k in ("az", "el", "dist", "tx", "ty", "tz", "fovy"))
            try:
                _fps = float((qs.get("fps") or ["12"])[0])
            except Exception:                                              # noqa: BLE001
                _fps = 12.0
            _fps = max(1.0, min(15.0, _fps))
            _dt = 1.0 / _fps
            with _STREAMS_LOCK:
                if _STREAMS["n"] >= _STREAMS["max"]:
                    self._send(503, b"too many streams (max %d)" % _STREAMS["max"], "text/plain")
                    return
                _STREAMS["n"] += 1
            try:
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                _last_n = -1
                _last_md5 = None
                _last_sent = 0.0
                _fkey = None
                _fpng = None
                _follow = (qs.get("follow") or ["1"])[0].lower() not in ("0", "false", "no", "off")
                while True:
                    _t0 = time.time()
                    _png = None
                    # 🎥 跟随 ar3d 页面的相机(默认开): 页面在推就同机位, 没在推就退回预设机位
                    if _follow:
                        _cq = _cam_sync_read()
                        if _cq:
                            try:
                                _k = tuple(round(float(_cq[_k2][0]), 5) for _k2 in
                                           ("az", "el", "dist", "tx", "ty", "tz", "fovy"))
                            except Exception:                              # noqa: BLE001
                                _k = None
                            if _k is not None and _k != _fkey:
                                try:
                                    _fpng = render_free(_cq)
                                    _fkey = _k
                                except Exception:                          # noqa: BLE001
                                    pass
                            _png = _fpng          # 相机没动 ⇒ 复用上一帧, 不重复渲染
                    if _png is None and _free:
                        try:
                            _png = render_free(qs)
                        except Exception:                                  # noqa: BLE001
                            _png = None
                    if _png is None and not (_follow and _fkey is not None):
                        with LOCK:
                            _st3 = dict(STATE)
                            _v3 = (_st3.get("views") or {}).get(cam_name) or {}
                        _n3 = _v3.get("n", _st3.get("n"))
                        if _n3 != _last_n:               # 同帧不重发(站点相机 → 零额外渲染开销)
                            _png = _v3.get("png") or (_st3.get("png") if cam_name == "close" else b"")
                            _last_n = _n3
                    # 🧮 场景静止时相机每帧都"变"(n 在涨)但像素不变 ⇒ 画面逐字节相同。
                    #   比对 md5: 没变就只按 1fps 发心跳帧, 否则 12fps 白白吃掉 ~9Mbps 带宽(实测 8 帧 md5 全同)。
                    if _png:
                        _md5 = hashlib.md5(_png).digest()
                        if _md5 == _last_md5 and (time.time() - _last_sent) < 1.0:
                            _png = None
                        else:
                            _last_md5, _last_sent = _md5, time.time()
                    if _png:
                        self.wfile.write(b"--frame\r\nContent-Type: image/png\r\nContent-Length: "
                                         + str(len(_png)).encode() + b"\r\n\r\n")
                        self.wfile.write(_png)
                        self.wfile.write(b"\r\n")
                        self.wfile.flush()
                    _gap = _dt - (time.time() - _t0)
                    time.sleep(_gap if _gap > 0 else 0.005)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass                                     # 客户端关窗/断网: 正常退出
            finally:
                with _STREAMS_LOCK:
                    _STREAMS["n"] = max(0, _STREAMS["n"] - 1)
            return
        if p in ("/live", "/live.html", "/video.html"):
            # 📺 /video 的 HTML 外壳: 一屏只有渲染画面 + 帧龄/尺寸角标, 手机/大屏直接全屏看
            _html = ("""<!doctype html><meta charset="utf-8">
<title>Z-MAX 8802 · 渲染帧</title>
<style>html,body{margin:0;height:100%;background:#05070a;overflow:hidden}
#w{position:fixed;inset:0;display:flex;align-items:center;justify-content:center}
#v{max-width:100%;max-height:100%}
#h{position:fixed;left:10px;top:8px;color:#79c0ff;font:bold 12px monospace;text-shadow:0 0 6px #000}
</style><div id="h"></div><div id="w"><img id="v" src="/frame.png?cam=ar3d&live=1" alt="8802 render stream"></div>
<script>
var t0=Date.now(),v=document.getElementById('v'),h=document.getElementById('h'),cam='预设机位';
// pull-frame-v1: 每 100ms 拉一张 /frame.png?cam=ar3d ⇒ 右键=当前帧真图
// 🔴 2026-11-09「8802/video 没有了」根因: 每拍改 <img>.src ⇒ 元素先进入 loading 态(0×0/透明),
//   6fps × 每张 ~200ms 加载 ⇒ 几乎全程是 loading, 看着就是"没有画面"。
//   改成 fetch 取 PNG → blob URL 换图 (已解码, 不会再走 loading), 旧 blob 立刻 revoke。
var FPS=6, busy=false;   // ⚠ FPS 必须定义: 下面 setInterval 用 Math.round(1000/FPS), 少了它=每帧连发, 会把渲染线程打满
function tick8802(){
  if(busy) return; busy=true;
  var u='/frame.png?cam=ar3d&live=1&_='+Date.now();
  fetch(u,{cache:'no-store'}).then(function(r){ return r.blob(); }).then(function(b){
    var url=URL.createObjectURL(b), old=v.getAttribute('data-u');
    v.src=url; v.setAttribute('data-u',url);
    if(old){ try{ URL.revokeObjectURL(old); }catch(e){} }
  }).catch(function(){}).then(function(){ busy=false; });
}
setInterval(tick8802,Math.round(1000/FPS));
setInterval(function(){h.textContent='Z-MAX AR 8802 · PNG 6fps · '+(v.naturalWidth||0)+'×'+(v.naturalHeight||0)
 +' · 视角:'+cam+' · 已看 '+Math.round((Date.now()-t0)/1000)+'s · '+location.host+'/video';},500);
setInterval(function(){fetch('/cam',{cache:'no-store'}).then(function(r){return r.json();}).then(function(j){
  cam = j.follow ? ('跟随 ar3d 页面 '+(j.age_s)+'s前') : '预设机位(页面没在推)';}).catch(function(){});},1500);
v.onerror=function(){h.textContent='流断了(8802 未起? 或通道数已满 3) · 10s 后自动重连';
 setTimeout(function(){v.src='/frame.png?cam=ar3d&live=1&_='+Date.now();},10000);};
</script>""").encode("utf-8")
            self._send(200, _html, "text/html; charset=utf-8")
            return
        if p == "/bones.json":
            self._json(st.get("bones") or {"ok": False, "why": "骨骼快照未生成 (渲染循环未跑)"})
            return
        if p == "/cam":
            # 🎥 当前跟随的相机(ar3d 页面推上来的那份) + 新鲜度; 页面没推 ⇒ age 很大/无文件 ⇒ 看的是预设机位
            try:
                with open(_CAM_SYNC["path"], encoding="utf-8") as _f:
                    _d = json.load(_f)
                _d["age_s"] = round(time.time() - float(_d.get("ts") or 0), 2)
                _d["follow"] = _d["age_s"] <= 6.0
                _d["path"] = _CAM_SYNC["path"]
                self._json(_d)
            except Exception:                                                # noqa: BLE001
                self._json({"follow": False, "why": "还没有页面推过相机(看的是预设机位)",
                            "path": _CAM_SYNC["path"]})
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
        if p == "/cam":
            # 🎥 2026-11-09 老倪: 「/video 没有跟 8797/ar3d 同步」
            #   ar3d 页面每 500ms 把它的相机推过来(跨源 no-cors POST, body 是 JSON 文本);
            #   /video 读同一份参数渲染 ⇒ 窗口与页面同机位。只存参数, 不动仿真/不下发关节。
            try:
                _d = _cam_sync_write(body or {}, src=str(self.headers.get("Origin") or ""))
                self._json({"ok": True, "ts": round(_d.get("ts", 0), 3),
                            "cam": {k: _d.get(k) for k in ("az", "el", "dist", "tx", "ty", "tz", "fovy")}})
            except Exception as e:                                           # noqa: BLE001
                self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, e)}, 400)
            return
        if p == "/armq":
            # 🎯 AR 页直推 6 轴关节角(度) ⇒ 8802 只执行, 不再自己解 IK (两套 IK 会落不同分支)
            try:
                _d = _armq_write(body or {})
                self._json({"ok": True, "ts": round(_d["t"], 3),
                            "nR": len(_d.get("R") or []), "nL": len(_d.get("L") or [])})
            except Exception as e:                                           # noqa: BLE001
                self._json({"ok": False, "err": "%s: %s" % (type(e).__name__, e)}, 400)
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
