#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""perception_fusion6d.py — L2 融合模块：2D 检测 ⊕ 2D→3D ⊕ 状态反馈 ⇒ 光模块 3D 位姿。

为什么单独一层（而不是塞进 to_3d）：
  · `to_3d()` 是"检测框中心 + 平面假设"的单点反投影, 只给位置, 且平面 z 写死;
  · 本模块把三路信息按**不确定度加权融合**, 输出位置 + 姿态 + 有效性 + 来源, 并直接能写进统一状态空间。

三路输入(缺哪路都能退化运行, 但必须标出退化):
  ① 2D 检测   : box(x1,y1,x2,y2)/conf/cls   —— 来自 YOLO (perception_yolo / yolo_peg_live.pt)
  ② 2D→3D     : depth + K + dist            —— 框内"深度近层"(模块顶面) 去畸变反投影 ⇒ P_cam,
                                              用已知尺寸(72×18.35×8.5)+ 2D 矩形长轴 ⇒ 相机系姿态
  ③ 状态反馈   : TCP 真值(tool1) / 夹爪读数 / 槽位几何 / 上一帧位姿  ⇒ 先验 μ_p, σ_p
      · 夹爪夹着 → 模块位姿 ≡ tool1 位姿 (用户定义: 抓取时两坐标系重合), σ≈1mm, 最可信
      · 落在槽里 → 槽位几何真值 (体中心 = 槽底 + 半高), σ≈8mm (模块可能在槽内滑动)
      · 都没有   → 上一帧位姿外推, σ≈15mm

融合: 位置 x = (Σ wᵢ xᵢ)/(Σ wᵢ), wᵢ = 1/σᵢ²; 姿态四元数按测地线加权 (SLERP), 用 atan2 形式避免 acos 在 q≈±1 处发散。
门限: |测量 − 先验| > 30mm ⇒ 判测量失效(通常是被遮挡/串件), 退回先验并把 valid 置 False —— 宁可输出"无效", 不输出看起来合理的错值。

输出契约(与 unified_state55 一致, 按名取值):
  peg_xyz  → SLICE["peg_xyz"]   [4:7]    单位 m
  peg_quat → SLICE["peg_quat"]  [51:55]  单位 - , wxyz, 全 0 = 未观测

CLI:
  python perception_fusion6d.py --live              # 真机取一帧(8794 图像/深度 + 8797 TCP) 融合并打印
  python perception_fusion6d.py --live --json       # 机器可读
  python perception_fusion6d.py --selftest          # 合成数据自检(已知位姿能否复原)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field, asdict

import numpy as np

try:
    import cv2
except Exception:                                                       # noqa: BLE001
    cv2 = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))
REL_ROOT = "/home/ubuntu/zmax"

# 光模块 QSFP28 (m) —— 已知尺寸是这一层的第二个观测源, 不是注释
L, W, H = 0.072, 0.01835, 0.0085

# 夹爪读数区间 (真机实测): 夹住 145/160/168/169/179/285 都算夹持, 全开 1000
GRIP_HOLD = (120.0, 340.0)
GRIP_OPEN_MIN = 900.0

RS_FRAME = "http://192.168.23.66:8794/frame.jpg"
RS_DEPTH = "http://192.168.23.66:8794/depth.png"
RS_INTR = "http://192.168.23.66:8794/intrinsics"
TCP_API = "http://127.0.0.1:8797/api/tcp"
TRAY_JSON = os.path.join(REL_ROOT, "config/points/tray_slots_14.json")
CAL_CANDIDATES = [
    os.path.join(REL_ROOT, "zmax_data/percept/calib/handeye_tool1_cam.json"),   # 平面 PnP (rvec/tvec: base→cam)
    os.path.join(REL_ROOT, "zmax_data/percept/calib/tcp_frame.json"),
]


# ── 四元数工具 (atan2 形式, 规避 acos 在 q≈±1 发散) ──────────────────────────────
def quat_from_R(R: np.ndarray) -> np.ndarray:
    """旋转矩阵 → 四元数 wxyz (Shepperd 分支, 数值稳)。"""
    m = np.asarray(R, float)
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], float)
    return q / (np.linalg.norm(q) + 1e-12)


def quat_angle_deg(q1, q2) -> float:
    """两姿态夹角(度)。r = q1⁻¹⊗q2, θ = 2·atan2(‖v‖, |w|) —— 不用 acos。"""
    q1 = np.asarray(q1, float) / (np.linalg.norm(q1) + 1e-12)
    q2 = np.asarray(q2, float) / (np.linalg.norm(q2) + 1e-12)
    w1, v1 = q1[0], q1[1:]
    w2, v2 = q2[0], q2[1:]
    rw = w1 * w2 + float(v1 @ v2)
    rv = w1 * v2 - w2 * v1 - np.cross(v1, v2)
    return float(np.degrees(2.0 * np.arctan2(np.linalg.norm(rv), abs(rw))))


def slerp(q1, q2, s: float):
    """球面插值, s=0→q1, s=1→q2。双覆盖先取短弧; 分母 clamp; θ<1e-4 走线性极限。"""
    q1 = np.asarray(q1, float) / (np.linalg.norm(q1) + 1e-12)
    q2 = np.asarray(q2, float) / (np.linalg.norm(q2) + 1e-12)
    dot = float(q1 @ q2)
    if dot < 0:
        q2, dot = -q2, -dot
    dot = float(np.clip(dot, -1.0, 1.0))
    theta = np.arctan2(np.sqrt(max(0.0, 1.0 - dot * dot)), dot)
    if theta < 1e-4:
        q = (1 - s) * q1 + s * q2
        return q / (np.linalg.norm(q) + 1e-12)
    sd = np.sin(theta)
    q = (np.sin((1 - s) * theta) / sd) * q1 + (np.sin(s * theta) / sd) * q2
    return q / (np.linalg.norm(q) + 1e-12)


# ── 输出结构 ────────────────────────────────────────────────────────────────
@dataclass
class Pose6D:
    xyz: list                    # 基座系, m
    quat: list                   # wxyz, 全 0 = 未观测
    valid: bool                  # 是否可作为真值使用
    src: str                     # fused / prior_grasp / prior_slot / prior_last / gated / invalid
    sigma_mm: float              # 融合后 1σ 位置不确定度
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class PegPoseFusion:
    """2D ⊕ 2D→3D ⊕ 状态反馈 ⇒ 光模块 3D 位姿。"""

    GATE_MM = 30.0          # 测量与先验差超过它 ⇒ 判测量失效

    def __init__(self, calib_path: str | None = None, tray_path: str = TRAY_JSON,
                 dims=(L, W, H), verbose: bool = False) -> None:
        self.L, self.W, self.H = dims
        self.verbose = verbose
        self.R_cb, self.t_cb = self._load_calib(calib_path)
        self.slots = self._load_slots(tray_path)
        self.last: Pose6D | None = None
        # 在线偏置估计: 外参是 4 点平面 PnP 解出来的, 系统性误差可达 60mm (槽10 实测 z 差 -60mm)。
        # 模块落在已知槽里时, "测量 − 槽位真值"就是一个偏置样本; 用 EMA 收, 再用它修正后续测量。
        # 不这么做的话, 融合只会把 60mm 的错值原样搬到状态空间里。
        self.bias = np.zeros(3)
        self.bias_n = 0
        self.sigma_bias_mm = 60.0        # 无样本时的系统误差先验 (实测 z 偏 60mm)

    # ---- 载入 ---------------------------------------------------------------
    @staticmethod
    def _load_calib(path: str | None):
        cands = [path] if path else CAL_CANDIDATES
        for p in cands:
            if not p or not os.path.exists(p):
                continue
            try:
                d = json.load(open(p))
            except Exception:                                           # noqa: BLE001
                continue
            if "rvec" in d and "tvec" in d:            # solvePnP: projectPoints(base)→pixel
                R, _ = cv2.Rodrigues(np.array(d["rvec"], float).reshape(3, 1))
                t = np.array(d["tvec"], float).reshape(3)
                # ⚠ 标定文件里的 tvec 是 **mm** (|t|≈650), 本模块内部一律 m ⇒ 按量级判单位。
                #   真实相机离基座原点不超过几米, 所以 |t|>10 只可能是 mm。
                return R, (t / 1000.0 if np.linalg.norm(t) > 10.0 else t)
            if "R_cam_from_base" in d:
                t = np.array(d["tvec"], float).reshape(3) if "tvec" in d else np.zeros(3)
                return np.array(d["R_cam_from_base"], float), (t / 1000.0 if np.linalg.norm(t) > 10.0 else t)
        return None, None

    @staticmethod
    def _load_slots(path: str):
        try:
            d = json.load(open(path))
            return {int(s["id"]): s for s in d.get("slots", [])}
        except Exception:                                               # noqa: BLE001
            return {}

    @property
    def has_extrinsic(self) -> bool:
        return self.R_cb is not None

    # ---- ① + ② 视觉测量 ------------------------------------------------------
    def measure(self, img, depth_raw, K, dist, box):
        """框内深度近层 → 相机系位置 + 姿态(相机系)。返回 (p_cam, R_cam, info) 或 None。"""
        if cv2 is None:
            raise RuntimeError("需要 opencv")
        Z = np.asarray(depth_raw, float) * 0.1                     # 0.1mm/unit ⇒ mm
        if Z.shape[:2] != img.shape[:2]:
            Z = cv2.resize(Z, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
        x1, y1, x2, y2 = [int(round(float(v))) for v in box]
        x1, y1 = max(0, x1), max(0, y1)
        sub = Z[y1:y2, x1:x2]
        ok = (sub > 150) & (sub < 1200)
        n_ok = int(ok.sum())
        if n_ok < 150:
            return None, None, {"why": "深度点少 %d" % n_ok}
        v = sub[ok]
        lo, hi = np.percentile(v, 3), np.percentile(v, 35)          # 最近层 = 模块顶面
        m = ok & (sub >= lo) & (sub <= hi)
        vs, us = np.nonzero(m)
        if vs.size < 120:
            return None, None, {"why": "近层点少 %d" % vs.size}
        z = sub[vs, us]
        Kmtx = np.array([[K["fx"], 0, K["cx"]], [0, K["fy"], K["cy"]], [0, 0, 1]], float)
        dist = np.array(dist or [0, 0, 0, 0, 0], float)
        uv = np.stack([us + x1, vs + y1], 1).astype(np.float64).reshape(-1, 1, 2)
        xn = cv2.undistortPoints(uv, Kmtx, dist).reshape(-1, 2)
        P = np.stack([xn[:, 0] * z, xn[:, 1] * z, z], 1) / 1000.0    # m, 相机系
        p_cam = np.median(P, axis=0)
        # 姿态: 图像里长轴方向 → 同深度两点 → 相机系方向; 再假设模块平躺(法向≈相机上下轴无关, 由基座水平面定)
        gg = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        mm = (gg < int(min(70, max(45, np.percentile(gg, 25) - 8)))).astype(np.uint8)
        cnts = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
        ang = None
        if cnts:
            cnt = max(cnts, key=cv2.contourArea)
            if cv2.contourArea(cnt) > 120:
                (rcx, rcy), (rw, rh), rang = cv2.minAreaRect(cnt)
                ang = np.deg2rad(rang if rw >= rh else rang + 90.0)
        zc = float(np.median(z))
        # 长轴方向(相机系): 图像矩形长轴 → 同深度两点 → 单位向量。
        # 方向只在"基座系里投影到水平面"之后才使用 (模块在槽里必然是平躺的, 这条约束比相机系自由旋转强得多)。
        dir_cam = None
        if ang is not None:
            d2 = np.array([np.cos(ang), np.sin(ang)], float)
            uc, vc = float(np.median(us + x1)), float(np.median(vs + y1))
            pts = np.array([[[uc - 20 * d2[0], vc - 20 * d2[1]]], [[uc + 20 * d2[0], vc + 20 * d2[1]]]], float)
            xn2 = cv2.undistortPoints(pts, Kmtx, dist).reshape(-1, 2)
            P2 = np.stack([xn2[:, 0] * zc, xn2[:, 1] * zc, np.full(2, zc)], 1) / 1000.0
            dir_cam = P2[1] - P2[0]
            dir_cam /= (np.linalg.norm(dir_cam) + 1e-12)
        return p_cam, dir_cam, {"why": "ok", "n_near": int(vs.size), "z_mm": round(zc, 1),
                                "rect_angle_deg": None if ang is None else round(float(np.degrees(ang)), 1)}

    def _slot_center(self, slot_id: int) -> np.ndarray:
        """槽位几何真值: 模块**体中心** (槽底 z + 半高), 基座系 m。"""
        s = self.slots[slot_id]
        return np.array([s["x"], s["y"], s["z"] + self.H * 1000.0 / 2.0], float) / 1000.0

    def _infer_slot_px(self, K: dict, dist, box, tol_px: float = 70.0) -> int | None:
        """检测框中心离哪个槽位**投影**最近 ⇒ 槽号 (像素域排序, 不吃 3D 外参的系统偏置)。

        为什么不比 3D 距离: 4 点平面 PnP 的外参在 3D 上偏 60mm, 但重投影只偏 1~14px,
        槽间间距 ~48mm(≈70px) ⇒ 像素域排序可靠; 实测 3D 域最近槽会选错 (槽10↔槽11)。
        """
        if not self.has_extrinsic or cv2 is None:
            return None
        Km = np.array([[K["fx"], 0, K["cx"]], [0, K["fy"], K["cy"]], [0, 0, 1]], float)
        dd = np.array(dist or [0, 0, 0, 0, 0], float)
        x1, y1, x2, y2 = [float(v) for v in box]
        uc, vc = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        rv, _ = cv2.Rodrigues(self.R_cb)
        tv = self.t_cb * 1000.0
        best, bestd = None, 1e9
        for sid, s in self.slots.items():
            P = np.array([[s["x"], s["y"], s["z"] + self.H * 1000.0 / 2.0]], float)
            uv, _ = cv2.projectPoints(P, rv, tv, Km, dd)
            u, v = uv[0, 0]
            d = float(np.hypot(u - uc, v - vc))
            if d < bestd:
                best, bestd = sid, d
        return best if bestd <= tol_px else None

    # ---- ③ 状态反馈先验 ------------------------------------------------------
    # σ 按**轴**给, 因为三路信息各有所长的轴不同:
    #   槽位几何  → y(槽位排布) 与 z(槽底+半高) 是硬约束 ⇒ 小 σ
    #   视觉测量  → x/y 由像素决定 (准), z 由外参+深度决定 (外参在 3D 上偏 60mm) ⇒ z 大 σ
    #   夹持 TCP  → 三个轴都准 (tool1 真值 0.1mm) ⇒ 都小 σ
    def prior(self, tcp_R=None, tcp_t=None, grip=None, slot_id=None,
              x_dir=None) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
        """返回 (xyz, quat, sigma_mm(3,), src)。xyz 与测量同一点: **金手指端中点**。"""
        holding = grip is not None and GRIP_HOLD[0] <= float(grip) <= GRIP_HOLD[1]
        if holding and tcp_R is not None and tcp_t is not None:
            R = np.asarray(tcp_R, float)
            return np.asarray(tcp_t, float), quat_from_R(R), np.array([2.0, 2.0, 2.0]), "prior_grasp"
        if slot_id is not None and slot_id in self.slots:
            xd = np.array([1.0, 0.0, 0.0]) if x_dir is None else np.asarray(x_dir, float)
            xd = np.array([xd[0], xd[1], 0.0])
            xd /= (np.linalg.norm(xd) + 1e-12)
            body = self._slot_center(slot_id)
            origin = body - (self.L / 2.0) * xd                  # 体中心 → 金手指端
            z_axis = np.array([0.0, 0.0, 1.0])
            y_axis = np.cross(z_axis, xd)
            q = quat_from_R(np.stack([xd, y_axis, z_axis], 1))
            # x 方向的 σ 大: 模块在槽里可能掉头 (金手指朝 ±X), 槽位表里没有朝向字段
            return origin, q, np.array([40.0, 8.0, 4.0]), "prior_slot"
        if self.last is not None and self.last.src != "invalid":
            return (np.asarray(self.last.xyz, float), np.asarray(self.last.quat, float),
                    np.array([20.0, 20.0, 20.0]), "prior_last")
        return np.zeros(3), np.zeros(4), np.array([99.0, 99.0, 99.0]), "prior_none"

    def meas_sigma(self) -> np.ndarray:
        """测量各轴 1σ(mm): 随机项 ⊕ 外参系统项(随偏置样本数 1/√n 收敛)。"""
        rand = np.array([6.0, 8.0, 10.0])
        syst = self.sigma_bias_mm * np.array([12.0, 25.0, 50.0]) / 50.0
        return np.hypot(rand, syst)

    # ---- 融合主入口 ----------------------------------------------------------
    def update(self, det, img, depth_raw, K, dist, tcp_R=None, tcp_t=None,
               grip=None, slot_id=None) -> Pose6D:
        """融合一帧: 2D+深度+外参 ⇒ 测量; 夹爪/TCP/槽位/上一帧 ⇒ 先验; 按轴加权 ⇒ 位姿。"""
        p_top_cam, dir_cam, info = self.measure(img, depth_raw, K, dist, det["box"])
        notes: dict = {"meas": info, "has_extrinsic": self.has_extrinsic}
        meas_xyz = meas_quat = None
        x_axis = None

        if p_top_cam is not None and self.has_extrinsic:
            p_top_base = self.R_cb.T @ (p_top_cam - self.t_cb)
            if dir_cam is not None:
                d = self.R_cb.T @ dir_cam
                d[2] = 0.0                                    # 模块在槽里平躺 ⇒ 长轴必在水平面
                if np.linalg.norm(d) > 1e-6:
                    x_axis = d / np.linalg.norm(d)
                    # 图像 +v 向下 = 相机 +Y; 金手指端在图像下沿 ⇒ X 轴(原点→体)指向图像上方
                    if float(dir_cam[1]) > 0:
                        x_axis = -x_axis
            if x_axis is None:
                x_axis = np.array([1.0, 0.0, 0.0])
            z_axis = np.array([0.0, 0.0, 1.0])
            y_axis = np.cross(z_axis, x_axis)
            body_center = p_top_base - np.array([0.0, 0.0, self.H / 2.0])
            meas_xyz = body_center - (self.L / 2.0) * x_axis   # 体中心 → **金手指端中点**
            meas_quat = quat_from_R(np.stack([x_axis, y_axis, z_axis], 1))
            notes.update({"meas_xyz_mm": [round(v * 1000, 1) for v in meas_xyz],
                          "x_axis": [round(v, 4) for v in x_axis]})
        elif p_top_cam is not None:
            info["why"] = "无外参(仅相机系测量, 不参与融合)"

        # 槽号: 像素域最近投影 (3D 域会被外参 60mm 偏置带偏, 实测选错槽)
        if slot_id is None and meas_xyz is not None:
            slot_id = self._infer_slot_px(K, dist, det["box"])
        prior_xyz, prior_quat, sig_p, prior_src = self.prior(tcp_R, tcp_t, grip, slot_id, x_axis)
        notes.update({"prior_src": prior_src, "slot": slot_id,
                      "sigma_prior_mm": [round(v, 1) for v in sig_p]})

        sig_m = self.meas_sigma()

        # 在线偏置估计: 槽位已知 ⇒ (测量 − 槽位真值) 即偏置样本; EMA 收敛后 σ 随之变小
        if prior_src == "prior_slot" and meas_xyz is not None:
            e = meas_xyz - prior_xyz
            notes["bias_sample_mm"] = [round(v * 1000, 1) for v in e]
            if float(np.linalg.norm(e) * 1000) < 250.0:
                a = 0.25 if self.bias_n == 0 else 0.2
                self.bias = (1 - a) * self.bias + a * e
                self.bias_n += 1
                self.sigma_bias_mm = max(3.0, 60.0 / np.sqrt(self.bias_n))
                meas_xyz = meas_xyz - self.bias
                sig_m = self.meas_sigma()
                notes.update({"bias_mm": [round(v * 1000, 1) for v in self.bias],
                              "bias_n": self.bias_n})

        notes["sigma_meas_mm"] = [round(v, 1) for v in sig_m]

        # 门限 (Mahalanobis, 3σ)
        gated = False
        if meas_xyz is not None and prior_src != "prior_none":
            combo = np.hypot(sig_m, sig_p)
            m2 = float(np.sum(((meas_xyz - prior_xyz) * 1000.0 / combo) ** 2))
            notes.update({"mahalanobis": round(m2, 2),
                          "gate_mm": [round(v * 1000, 1) for v in (meas_xyz - prior_xyz)]})
            gated = m2 > 9.0

        if meas_xyz is not None and not gated:
            wm = 1.0 / np.maximum(sig_m, 1e-3) ** 2
            if prior_src == "prior_none":
                wp = np.zeros(3)
                sig = sig_m
            else:
                wp = 1.0 / np.maximum(sig_p, 1e-3) ** 2
                sig = np.sqrt(1.0 / (wm + wp))
            xyz = (wm * meas_xyz + wp * prior_xyz) / (wm + wp)
            if meas_quat is not None and prior_src != "prior_none":
                ang = quat_angle_deg(meas_quat, prior_quat)
                notes["quat_delta_deg"] = round(ang, 2)
                quat = slerp(prior_quat, meas_quat, float(np.mean(wm / (wm + wp)))) if ang < 25.0 else prior_quat
            else:
                quat = meas_quat if meas_quat is not None else prior_quat
            out = Pose6D(xyz.tolist(), quat.tolist(), True, "fused", round(float(np.mean(sig)), 2), notes)
        elif gated:
            out = Pose6D(prior_xyz.tolist(), prior_quat.tolist(), False, "gated",
                         round(float(np.mean(sig_p)), 2), notes)
        else:
            src = prior_src if prior_src != "prior_none" else "invalid"
            out = Pose6D(prior_xyz.tolist(), prior_quat.tolist(), False, src,
                         round(float(np.mean(sig_p)), 2), notes)

        self.last = out
        return out


    # ---- 写进统一状态空间 ----------------------------------------------------
    def write_state(self, pose: Pose6D, visual39=None, tactile4=None, us=None):
        """peg_xyz → [4:7] (m); peg_quat → [51:55] (wxyz; 无效写全 0)。按名取值, 不数下标。"""
        try:
            from .unified_state55 import UnifiedState55D, SLICE               # type: ignore
        except Exception:                                                  # noqa: BLE001
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from unified_state55 import UnifiedState55D, SLICE              # type: ignore
        us = us or UnifiedState55D()
        v = np.zeros(39) if visual39 is None else np.asarray(visual39, float).ravel()[:39].copy()
        sl = SLICE["peg_xyz"]
        v[sl.start:sl.stop] = np.asarray(pose.xyz, float) if pose.src != "invalid" else np.zeros(3)
        t = np.zeros(4) if tactile4 is None else np.asarray(tactile4, float).ravel()[:4]
        q = np.asarray(pose.quat, float) if (pose.valid and np.linalg.norm(pose.quat) > 0.5) else np.zeros(4)
        return us.fuse(v, t, {"peg_quat": q})


# ── 真机取一帧 --------------------------------------------------------------
def _get(url, t=8):
    return urllib.request.urlopen(url, timeout=t).read()


def live_pose(slot_id=None, calib_path=None, quiet=False) -> Pose6D:
    import cv2 as _cv
    img = _cv.imdecode(np.frombuffer(_get(RS_FRAME), np.uint8), _cv.IMREAD_COLOR)
    raw = _cv.imdecode(np.frombuffer(_get(RS_DEPTH), np.uint8), _cv.IMREAD_UNCHANGED)
    K = json.loads(_get(RS_INTR))
    dist = K.get("coeffs") or [0, 0, 0, 0, 0]
    tcp = json.loads(_get(TCP_API))
    f = tcp.get("frames", {}).get("tool1", {})
    R = np.stack([np.array(f.get(a, [0, 0, 0]), float) for a in "xyz"], 1) if f else None
    t = np.array(f.get("origin", [0, 0, 0]), float) if f else None

    from ultralytics import YOLO
    w = os.path.join(REL_ROOT, "models/yolo_peg_live.pt")
    r = YOLO(w).predict(img, conf=0.25, device="cpu", verbose=False)[0]
    if not len(r.boxes):
        fus = PegPoseFusion(calib_path)
        p = fus.update({"box": [0, 0, 1, 1]}, img, raw, K, dist, R, t, None, slot_id)
        p.detail["why"] = "无检出"
        return p
    b = max(r.boxes, key=lambda x: float(x.conf))
    det = {"box": [float(v) for v in b.xyxy[0]], "conf": float(b.conf)}
    grip = None
    try:
        grip = float(json.loads(_get("http://127.0.0.1:8897/healthz", 3)).get("grip") or 0) or None
    except Exception:                                                      # noqa: BLE001
        grip = None
    return PegPoseFusion(calib_path).update(det, img, raw, K, dist, R, t, grip, slot_id)


def main() -> int:
    a = sys.argv[1:]
    if "--selftest" in a:
        print("[selftest] 四元数/SLERP 数学自检")
        R = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], float)   # 绕 Z 转 90°
        q = quat_from_R(R)
        qid = np.array([1.0, 0, 0, 0])
        chk = [
            ("quat 归一", abs(np.linalg.norm(q) - 1) < 1e-9, "‖q‖=%.9f" % np.linalg.norm(q)),
            ("90° 复原", abs(quat_angle_deg(q, qid) - 90) < 1e-6,
             "θ=%.6f°" % quat_angle_deg(q, qid)),
            ("q≈±1 不发散", np.isfinite(quat_angle_deg(q, q)), "θ=%.9f°" % quat_angle_deg(q, q)),
            ("slerp 中点", abs(quat_angle_deg(slerp([1, 0, 0, 0], [0.7071068, 0, 0, 0.7071068], 0.5),
                                                [1, 0, 0, 0]) - 45) < 1e-3,
             "θ=%.4f°" % quat_angle_deg(slerp([1, 0, 0, 0], [0.7071068, 0, 0, 0.7071068], 0.5), [1, 0, 0, 0])),
        ]
        ok = True
        for name, passed, note in chk:
            print("  %s %-12s %s" % ("✓" if passed else "×", name, note))
            ok &= bool(passed)
        print("自检:", "PASS" if ok else "FAIL")
        return 0 if ok else 1

    slot = None
    for i, v in enumerate(a):
        if v == "--slot" and i + 1 < len(a):
            slot = int(a[i + 1])
    pose = live_pose(slot_id=slot)
    if "--json" in a:
        print(json.dumps(pose.to_dict(), ensure_ascii=False, indent=1))
    else:
        q = np.asarray(pose.quat, float)
        print("位姿  xyz %.1f, %.1f, %.1f mm" % tuple(np.asarray(pose.xyz) * 1000))
        print("       quat %s  |q|=%.4f" % (np.round(q, 4).tolist(), np.linalg.norm(q)))
        print("       valid=%s · src=%s · σ=%.1fmm" % (pose.valid, pose.src, pose.sigma_mm))
        print("       detail", json.dumps(pose.detail, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
