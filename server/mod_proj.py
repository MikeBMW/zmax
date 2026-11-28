#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mod_proj.py —— 虚拟光模块 → 臂相机图像的 3D 长方体投影/渲染

老倪 2026-11-15:
  「http://10.163.146.76:8797/ar3d 这里，有 tool1 的光模块的位姿，是个虚拟的但是光模块的位姿
    是正确的，你能把这个光模块长方体，在手臂相机的图像里，渲染出来么？这样，当手臂出现在
    金手指检测和表面检测的相机视野中时，我就可以看到一个光模块了」

为什么这么做(而不是等真夹住工件):
  现在臂**没夹住**光模块(夹爪空着), 但 tool1 位姿是控制器真值(endInRef, toolset=tool1),
  tool1 原点按 8797 的定叉就是「光模块头部中心」。所以只要:
      光模块长方体(tool1 系) --T_base_tool1--> base --T_cam2tool⁻¹--> 相机系 --K--> 像素
  就能在任何一路相机里画出「本该在那里」的光模块, 让 AOI 相机在他走到检测位时看到工件。

链路(全部复用已有真源, 不新造):
  · TCP/tool1 位姿 : zmax_data/rokae_sdk/tcp_out/latest.json (新鲜≤8s) → 否则 Orin 桥 39061 /status
  · 手眼外参      : zmax_data/calib/handeye_state.json  T_cam2tool (12组, 0.32mm/0.029°)
  · 相机内参      : zmax_data/calib/real_cam_calib.json  K/dist (arm 640x480)
  · 尺寸          : opt_box3d 的 MOD_H_MM=56.5 / MOD_W_MM=13.4 / MOD_T_MM=8.5

⚠️ 这条链路只做**可视化叠加**, 不下发任何动作、不改任何真值。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TCP_JSON = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")
# 与 tools/opt_box3d.py 同源同路径(那边是 models/, 不是 zmax_data/calib/)
HAND_EYE = os.path.join(ROOT, "models", "handeye_state.json")
REAL_CAL = os.path.join(ROOT, "models", "real_cam_calib.json")
ORIN_BRIDGE = os.environ.get("ZMAX_ORIN_BRIDGE", "http://192.168.23.66:39061")
AR_BASE = os.environ.get("ZMAX_AR_BASE", "http://127.0.0.1:8797")       # 8797 ar3d (toolframe/module_spec)
ARM_SNAP = os.environ.get("ZMAX_ARM_SNAP", "http://127.0.0.1:8791/snapshot/arm.jpg")

# 光模块尺寸(mm) —— 与 tools/opt_box3d.py 同源, 不另立口径
MOD_H_MM = float(os.environ.get("ZMAX_MOD_H_MM", "56.5"))   # 长轴
MOD_W_MM = float(os.environ.get("ZMAX_MOD_W_MM", "13.4"))   # 短轴
MOD_T_MM = float(os.environ.get("ZMAX_MOD_T_MM", "8.5"))    # 厚度

STALE_S = 8.0   # latest.json 超过这么多秒 ⇒ 判陈旧, 走桥


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _get_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _quat_R(qx, qy, qz, qw):
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]])


def read_tool1(stale_s: float = STALE_S):
    """读 tool1 位姿。返回 (T_base_tool1 毫米, src 描述, age_s)。

    优先级(与 8797 同口径): latest.json 新鲜 → 用它; 陈旧/缺失 → Orin 桥 39061 直读。
    ⚠️ latest.json 全 0 是已知故障态(内存里有记录), 全 0 一律当无效, 不能当"臂在原点"用。
    """
    errs = []
    age = None
    # ① latest.json
    try:
        d = _load(TCP_JSON)
        age = time.time() - os.path.getmtime(TCP_JSON)
        p6 = d.get("endInRef") or d.get("pose") or d
        xyz = [float(p6["x"]), float(p6["y"]), float(p6["z"])]
        quat = p6.get("quat")
        if quat:
            R = _quat_R(*[float(v) for v in quat])
        else:
            a, b, c = [float(v) for v in (p6.get("a") or p6.get("rx"), p6.get("b") or p6.get("ry"),
                                          p6.get("c") or p6.get("rz"))]
            # RPY(rad) → R, 与 opt_box3d._R_from_abc 同序
            ca, sa = np.cos(a), np.sin(a)
            cb, sb = np.cos(b), np.sin(b)
            cc, sc = np.cos(c), np.sin(c)
            R = np.array([[cb * cc, cc * sa * sb - ca * sc, ca * cc * sb + sa * sc],
                          [cb * sc, ca * cc + sa * sb * sc, -cc * sa + ca * sb * sc],
                          [-sb, cb * sa, ca * cb]])
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = np.array(xyz, float) * 1000.0     # 米 → 毫米
        if age <= stale_s and np.abs(T[:3, 3]).max() > 1.0:
            return T, "latest.json(%.1fs)" % age, age
        errs.append("latest.json 陈旧(%.0fs)或全0" % (age or -1))
    except Exception as e:
        errs.append("latest.json: %r" % (e,))

    # ② Orin 桥
    try:
        with urllib.request.urlopen(ORIN_BRIDGE + "/status", timeout=6) as r:
            st = json.loads(r.read().decode("utf-8"))
        p6 = st.get("endInRef")
        if not p6:
            raise ValueError("桥 status 无 endInRef")
        xyz = [float(p6[0]), float(p6[1]), float(p6[2])]
        rpy = [float(p6[3]), float(p6[4]), float(p6[5])]
        a, b, c = rpy
        ca, sa = np.cos(a), np.sin(a)
        cb, sb = np.cos(b), np.sin(b)
        cc, sc = np.cos(c), np.sin(c)
        R = np.array([[cb * cc, cc * sa * sb - ca * sc, ca * cc * sb + sa * sc],
                      [cb * sc, ca * cc + sa * sb * sc, -cc * sa + ca * sb * sc],
                      [-sb, cb * sa, ca * cb]])
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = np.array(xyz, float) * 1000.0
        return T, "orin_bridge/endInRef", 0.0
    except Exception as e:
        errs.append("orin_bridge: %r" % (e,))

    raise RuntimeError("tool1 位姿读不到: " + " | ".join(errs))


def handeye():
    """T_cam2tool (毫米)。

    🔴 关键: 这里的 "tool" 就是 **tool1(模块头)**, 不是 tool0(法兰)。
       判据: inv(T_cam2tool) 的平移投影深度 = 222.0mm == /api/toolframe 的 cam_z=221.98mm。
       (第二版曾在外面再乘一次 URDF 的 tool0→tool1, 深度变 444mm, 正好 2 倍 —— 错的。)
    """
    he = _load(HAND_EYE)
    if not he.get("ok"):
        raise ValueError("手眼未标定 (handeye_state.json ok=false)")
    T = np.array(he["T_cam2tool"], float).copy()
    if np.linalg.norm(T[:3, 3]) < 2.0:      # 米 → 毫米 (与 tcp_ar_server.toolframe_px 同判据)
        T[:3, 3] *= 1000.0
    return T, he


def intrinsics():
    d = _load(REAL_CAL)
    return np.array(d["K"], float).reshape(3, 3), np.array(d["dist"], float).ravel()


def box_verts_tool1(along: str = "+z", offset_mm: float = 0.0):
    """光模块长方体 8 顶点(tool1 系, 毫米)。

    轴定义(ar3d 页面 bMod 按钮 tooltip 原文):
        **X = 上表面法向(厚度) · Y = 侧面法向(宽度) · Z = 上表面中轴线(长度)**
    tool1 原点 = **模块头中心** ⇒ 主体从原点沿 Z 向后延伸 L=56.5mm。
    (第一版把宽/厚分配反了: 写成 [v,n,u] 即 x=宽 y=厚, 与真源相反。)
    along: '+z'(默认, 向后) / '-z'(向前)
    offset_mm: 整体沿 Z 平移(细调)
    """
    L, W, T = MOD_H_MM, MOD_W_MM, MOD_T_MM
    s = 1.0 if along.startswith("+") else -1.0
    xs = [-T / 2.0, T / 2.0]          # 厚度方向
    ys = [-W / 2.0, W / 2.0]          # 宽度方向
    zs = [0.0, s * L]                 # 长度方向(模块头 → 尾部)
    pts = []
    for z in zs:
        for y in ys:
            for x in xs:
                pts.append([x, y, z + offset_mm])
    return np.array(pts, float)


def tool0_tool1():
    """URDF tool0(法兰) → tool1(模块头) 的固定变换(毫米)。与 tcp_ar_server.TOOL01_* 同源。"""
    xyz = np.array([-0.01588615307905028, 0.018348498948158043, 0.2586775713451509], float) * 1000.0
    rpy = (0.03702517838719945, 0.6751675651256659, 2.375248653715161)
    a, b, c = rpy
    ca, sa = np.cos(a), np.sin(a)
    cb, sb = np.cos(b), np.sin(b)
    cc, sc = np.cos(c), np.sin(c)
    R = np.array([[cb * cc, cc * sa * sb - ca * sc, ca * cc * sb + sa * sc],
                  [cb * sc, ca * cc + sa * sb * sc, -cc * sa + ca * sb * sc],
                  [-sb, cb * sa, ca * cb]])
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = xyz
    return T


def align_shift(default=(-150.53, 132.35)):
    """几何投影 → 实际 pegtip 的固定 2D 像素偏移。相机刚性固定在腕上 ⇒ 这个偏移是常数。

    🔴 为什么必须加(L5 实测否证过): 纯几何投影(手眼+内参)得到 tool1 头部在 [325.0, 48.6],
       而实际夹爪里的光模块头在 [174.5, 181.0] —— 差 [-150.5, +132.4]px, 而且 L5 判读
       「黄色框位于画面上方偏中, 套在竖直的金属杆/线缆上, 并未套在下方夹爪上」。
       这个偏差来自手眼标定的结构性残差(残差自身只有 0.32mm, 但 tool1 原点的物理定义
       与实际模块头位置有系统差), 8797 的 /api/toolframe 用 align_box 同样把它补偿掉了。
    优先从 /api/toolframe 实时取; 取不到用默认常数。
    """
    try:
        tf = _get_json(AR_BASE + "/api/toolframe", timeout=6)
        if tf.get("ok") and tf.get("align_shift_px"):
            s = tf["align_shift_px"]
            return float(s[0]), float(s[1]), "toolframe(%s)" % tf.get("align_to", "?")
    except Exception:                                        # noqa: BLE001
        pass
    return float(default[0]), float(default[1]), "默认常数"


def project(T_base_tool1=None, along="+z", offset_mm=0.0, T_cam2tool=None, K=None, dist=None,
            shift=None):
    """光模块 8 顶点 → 像素坐标(N,2) + 相机系点(N,3,毫米)。

    🔴 2026-11-15 踩坑三次才定的正确链路:
       错① 用 T_base_tool1 @ T_cam2tool 当 base→cam: 把 tool1 实时位姿混进 tool0 标定,
           得到 [325,48]; 而真值 [174.5,181]。根因: **臂相机装在腕上, 像素与位姿无关**。
       错② 再乘 URDF tool0→tool1: 深度 222mm → 444mm(正好2倍)。根因: handeye 里的 "tool" 就是 tool1。
       错③ 不加 align_shift: 框画到画面上方 [325,48], L5 判「未套在夹爪上」。
       正确: P_cam = inv(T_cam2tool) @ P_tool1, 再整体加 align_shift_px。
       对账: tool1 原点 221.98mm == /api/toolframe cam_z; 加 shift 后 == toolframe origin [174.5,181.0]。
    """
    T_ct = T_cam2tool if T_cam2tool is not None else handeye()[0]
    K, dist = (K, dist) if K is not None else intrinsics()
    P_tool1 = box_verts_tool1(along, offset_mm)                   # (8,3) mm, tool1 系
    T_cam_tool1 = np.linalg.inv(T_ct)                             # tool1 → cam
    Ph = np.hstack([P_tool1, np.ones((len(P_tool1), 1))])
    P_cam = (T_cam_tool1 @ Ph.T).T[:, :3]                         # mm
    P_base = np.full((8, 3), np.nan)                              # base 系(取决于位姿, 不参与投影)
    P_m = P_cam / 1000.0                                          # 米
    front = P_m[:, 2] > 1e-6
    uv = np.full((8, 2), np.nan)
    if front.any():
        rvec = np.zeros(3)
        tvec = np.zeros(3)
        try:
            import cv2
            uv[front] = cv2.projectPoints(P_m[front].reshape(-1, 1, 3), rvec, tvec,
                                          K, dist)[0].reshape(-1, 2)
        except Exception:
            x = P_m[front]
            uv[front] = np.stack([K[0, 0] * x[:, 0] / x[:, 2] + K[0, 2],
                                  K[1, 1] * x[:, 1] / x[:, 2] + K[1, 2]], 1)
    # 整体 2D 对齐(相机刚性固定 ⇒ 常数偏移): 让框落到夹爪里实际模块头的位置
    # shift=None → 自动从 /api/toolframe 取; shift=(0,0) → 纯几何(不推荐, 会偏上)
    if shift is None:
        shift = align_shift()[:2]
    s = np.asarray(shift, float).reshape(2)
    if np.any(s):
        uv = uv + s
    return uv, P_cam, P_base


# 12 条棱(顶点索引: u∈{0,1} × v∈{0,1} × n∈{0,1} → i = u*4+v*2+n)
EDGES = [(0, 1), (0, 2), (1, 3), (2, 3),      # 头部面
         (4, 5), (4, 6), (5, 7), (6, 7),      # 尾部面
         (0, 4), (1, 5), (2, 6), (3, 7)]      # 纵向


def draw(img, uv, color=(0, 220, 255), thick=2, fill_alpha=0.18):
    """把长方体画到 BGR 图上: 半透明填充 + 实线棱。"""
    import cv2
    out = img.copy()
    if np.isnan(uv).any():
        ok = ~np.isnan(uv[:, 0])
        if ok.sum() < 4:
            return out, 0
    h, w = out.shape[:2]
    pts = uv.astype(np.float32)
    # 头部/尾部两面填充(半透明)
    for quad in ((0, 1, 3, 2), (4, 5, 7, 6)):
        q = pts[list(quad)]
        if not np.isnan(q).any():
            ov = out.copy()
            cv2.fillConvexPoly(ov, q.astype(np.int32), color)
            out = cv2.addWeighted(ov, fill_alpha, out, 1 - fill_alpha, 0)
    n_drawn = 0
    for a, b in EDGES:
        pa, pb = pts[a], pts[b]
        if np.isnan(pa).any() or np.isnan(pb).any():
            continue
        cv2.line(out, tuple(pa.astype(int)), tuple(pb.astype(int)), color, thick)
        n_drawn += 1
    # 角点
    for p in pts:
        if not np.isnan(p).any():
            cv2.circle(out, tuple(p.astype(int)), 3, (0, 0, 255), -1)
    return out, n_drawn


def main():
    import argparse
    ap = argparse.ArgumentParser(description="虚拟光模块 → 臂相机图像投影")
    ap.add_argument("--along", default="-z", help="光模块主体方向: -z/+z/-x/+x/-y/+y")
    ap.add_argument("--offset", type=float, default=0.0, help="头部沿轴向偏移 mm")
    ap.add_argument("--img", default=None, help="输入图(默认现抓 8791/snapshot/arm.jpg)")
    ap.add_argument("--out", default=None, help="输出图")
    ap.add_argument("--json", action="store_true", help="只输出数值不带图")
    a = ap.parse_args()

    T, src, age = read_tool1()
    uv, P_cam, P_base = project(T, a.along, a.offset)
    print("tool1 源: %s  位置(mm)=%s" % (src, np.round(T[:3, 3], 1).tolist()))
    print("沿轴向: %s  offset=%.1fmm  尺寸 H/W/T=%.1f/%.1f/%.1f" % (
        a.along, a.offset, MOD_H_MM, MOD_W_MM, MOD_T_MM))
    print("相机系深度(m): " + " ".join("%.3f" % v for v in (P_cam[:, 2] / 1000.0)))
    print("像素坐标:")
    for i, p in enumerate(uv):
        print("  v%d  %s" % (i, "NaN(相机后方)" if np.isnan(p).any() else "[%.1f, %.1f]" % (p[0], p[1])))

    if a.json:
        return
    import cv2
    if a.img:
        img = cv2.imread(a.img)
    else:
        buf = urllib.request.urlopen("http://127.0.0.1:8791/snapshot/arm.jpg", timeout=10).read()
        img = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print("❌ 取不到图"); return
    out, n = draw(img, uv)
    cv2.putText(out, "virtual OPT module (tool1)  %s" % src, (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2)
    op = a.out or os.path.join(ROOT, "zmax_data/reports/gripper/mod_proj_%s.jpg" % time.strftime("%H%M%S"))
    os.makedirs(os.path.dirname(op), exist_ok=True)
    cv2.imwrite(op, out)
    print("画出 %d 条棱 → %s" % (n, op))


if __name__ == "__main__":
    main()
