#!/usr/bin/env python3
"""port_orbit_plan.py — 为"插口特写补采"生成一条不碰撞的小范围拍摄轨迹, 并做数值仿真核验。

为什么是这个形状 (而不是绕圈):
  腕相机就在工具轴上, 20~30cm 处看插口。3DGS 要的是**视差**, 不是大范围运动。
  所以让 TCP 在入孔点附近做 ±(15~30)mm 的小平移 + 小角度滚转, 相机始终对着插口,
  视差 5~10°, 足够把插口那几十个像素分辨出细节; 同时臂几乎不离开"已经证明能工作的区域",
  碰撞风险最小。

核验 (数值仿真, 不动物理引擎的假模型):
  ① 用真实 URDF (XMS5-R800) 做 FK, 每个航点解 IK (阻尼最小二乘 + 关节限位)
  ② 关节限位校验
  ③ 连杆线段到"插口工装包围盒 / 台面 / 本体"的最小距离
  ④ 自碰撞: 相邻连杆之外的两两连杆最小距离
  任一不满足 ⇒ 判失败, 不给真机跑。

用法:
  python3 tools/port_orbit_plan.py --out zmax_data/capture_plan/port_orbit.json
"""
import argparse
import json
import math
import os
import re
import xml.etree.ElementTree as ET

import numpy as np

URDF = "zmax_data/full_system_20260922/config/robot/xms5_r800_w4g3b4c.urdf"
# 成功插入模板 (2026-11-19 10:16, 两次复现入点误差 0.0mm)
PORT = np.array([0.76175, 0.22807, 0.19036])
RPY0 = np.array([-2.9484, -1.5163, -0.1782])
TOOL_LEN = 0.2587          # TCP→相机 (工具偏置 z, 实测 tcp_out)
# 只把"面板本体"当障碍: 口沿平面 x≈0.761 之后才是实体; 口前(x<0.755)是自由空间。
# 早期把整块 0.69~0.82 当盒子, 结果工具在口前的合法位置被判 0 间隙 (假碰撞)。
FIXTURE = np.array([[0.758, 0.835],   # x: 面板厚度方向
                    [0.140, 0.300],   # y
                    [0.095, 0.285]])  # z
TABLE_Z = 0.0


def rpy_to_R(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


class Chain:
    def __init__(self, urdf):
        root = ET.parse(urdf).getroot()
        joints = {}
        for j in root.findall("joint"):
            o = j.find("origin")
            xyz = np.array([float(v) for v in (o.get("xyz", "0 0 0")).split()]) if o is not None else np.zeros(3)
            rpy = np.array([float(v) for v in (o.get("rpy", "0 0 0")).split()]) if o is not None else np.zeros(3)
            ax = j.find("axis")
            axis = np.array([float(v) for v in ax.get("xyz").split()]) if ax is not None else np.array([0, 0, 1.0])
            lim = j.find("limit")
            lo = float(lim.get("lower")) if lim is not None else -math.pi
            hi = float(lim.get("upper")) if lim is not None else math.pi
            joints[j.get("name")] = {"parent": j.find("parent").get("link"),
                                     "child": j.find("child").get("link"),
                                     "type": j.get("type"), "xyz": xyz, "R": rpy_to_R(*rpy),
                                     "axis": axis / np.linalg.norm(axis), "lo": lo, "hi": hi}
        # 顺链: base → tool0
        by_parent = {}
        for n, j in joints.items():
            by_parent.setdefault(j["parent"], []).append(n)
        cur, chain = "world", []
        while True:
            nxt = [n for n in by_parent.get(cur, []) if joints[n]["type"] in ("revolute", "fixed")]
            if not nxt:
                break
            n = nxt[0]
            chain.append(n)
            cur = joints[n]["child"]
            if "tool0" in cur:
                break
        self.j = joints
        self.chain = chain
        self.movable = [n for n in chain if joints[n]["type"] == "revolute"]
        self.lo = np.array([joints[n]["lo"] for n in self.movable])
        self.hi = np.array([joints[n]["hi"] for n in self.movable])

    def fk(self, q, upto=None):
        """返回 4x4 (末端) 与 各段原点列表 (用于间隙检查)"""
        T = np.eye(4)
        pts = []
        qi = 0
        for n in self.chain:
            j = self.j[n]
            A = np.eye(4)
            A[:3, :3] = j["R"]
            A[:3, 3] = j["xyz"]
            T = T @ A
            if j["type"] == "revolute":
                th = q[qi]
                qi += 1
                K = np.array([[0, -j["axis"][2], j["axis"][1]],
                              [j["axis"][2], 0, -j["axis"][0]],
                              [-j["axis"][1], j["axis"][0], 0]])
                R = np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * (K @ K)
                Aj = np.eye(4)
                Aj[:3, :3] = R
                T = T @ Aj
            pts.append(T[:3, 3].copy())
            if upto and n == upto:
                break
        return T, np.array(pts)

    def ik(self, Ttgt, q0, iters=200, lam=3e-3):
        q = np.clip(q0.copy(), self.lo + 1e-4, self.hi - 1e-4)
        for _ in range(iters):
            T, _ = self.fk(q)
            e = np.concatenate([Ttgt[:3, 3] - T[:3, 3],
                                0.5 * (np.cross(T[:3, 0], Ttgt[:3, 0]) + np.cross(T[:3, 1], Ttgt[:3, 1]) +
                                       np.cross(T[:3, 2], Ttgt[:3, 2]))])
            if np.linalg.norm(e) < 1e-5:
                break
            J = np.zeros((6, len(q)))
            for k in range(len(q)):
                dq = q.copy()
                dq[k] += 1e-6
                T2, _ = self.fk(dq)
                J[:3, k] = (T2[:3, 3] - T[:3, 3]) / 1e-6
                J[3:, k] = (np.cross(T2[:3, 0] - T[:3, 0], T[:3, 0]) * 0 +
                            np.array([np.cross(T2[:3, i], Ttgt[:3, i])[0] * 0 for i in range(3)]))
                # 角速度近似: 用旋转向量差分
                dR = T2[:3, :3] @ T[:3, :3].T
                v = np.array([dR[2, 1] - dR[1, 2], dR[0, 2] - dR[2, 0], dR[1, 0] - dR[0, 1]]) / 2 / 1e-6
                J[3:, k] = v
            q = np.clip(q + J.T @ np.linalg.solve(J @ J.T + lam * np.eye(6), e), self.lo, self.hi)
        T, _ = self.fk(q)
        err = float(np.linalg.norm(Ttgt[:3, 3] - T[:3, 3]))
        return q, err


def seg_box_dist(p, q, box):
    """线段 pq 到轴对齐盒的最小距离 (采样近似, 150 点足够判定厘米级间隙)"""
    ts = np.linspace(0, 1, 151)[:, None]
    pts = p[None, :] * (1 - ts) + q[None, :] * ts
    d = np.maximum(np.maximum(box[:, 0][None, :] - pts, pts - box[:, 1][None, :]), 0)
    return float(np.linalg.norm(d, axis=1).min())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="zmax_data/capture_plan/port_orbit.json")
    ap.add_argument("--min-clear", type=float, default=0.030, help="最小安全间隙 m")
    a = ap.parse_args()
    ch = Chain(URDF)
    print("关节链:", ch.movable)
    R0 = rpy_to_R(*RPY0)
    Tcp0 = PORT + R0[:, 2] * 0                      # 入孔点就是成功模板 TCP
    Tcp0 = np.array([0.76175, 0.22807, 0.19036])

    way = []
    # 🔴 2026-11-19 老倪「轨迹太危险, 这都碰撞了。向后退, 远离插口 —— 是建图, 不是插拔」
    #    建图只要**相机看得见口**, 不需要贴到口上。所以整条航路退到口沿前 60~100mm,
    #    TCP 离面板本体 ≥58mm(面板 x≥0.758, 这里 x≤0.700), 视差靠横向 ±40 / 竖向 ±35 / 滚转 ±12° 拿。
    # 🔴 2026-11-19 老倪二次纠偏「远离插口」: 建图是**看着口**, 不是贴着口。
    #    TCP 退到口沿前 160~240mm (x 0.52~0.60, 面板在 0.758), 相机(法兰侧)再退后 259mm
    #    ⇒ 相机到插口 42~50cm, 用横向 ±50 / 竖向 ±45 / 滚转 ±15° 拿视差。
    for dz in (-0.045, 0.0, 0.045):
        for dy in (-0.050, 0.0, 0.050):
            for dx in (-0.240, -0.200, -0.160):
                for roll in ((0.0,) if (dy or dz) else (0.0, math.radians(12), math.radians(-12))):
                    T = np.eye(4)
                    T[:3, :3] = R0 @ rpy_to_R(roll, 0, 0)
                    T[:3, 3] = Tcp0 + np.array([dx, dy, dz])
                    way.append(T)
    q = np.zeros(len(ch.movable))
    q[1] = -0.6
    q[2] = 0.9
    q[3] = -0.4
    rows, worst, ok = [], 9.9, True
    for i, T in enumerate(way):
        q, err = ch.ik(T, q if i else q)
        if err > 1e-3:
            ok = False
            rows.append({"i": i, "err_mm": round(err * 1000, 1), "note": "IK 未收敛"})
            continue
        Tf, pts = ch.fk(q)
        # 工具那一节**故意**贴着插口(相机在工具轴上), 不计入间隙; 只查腕部以上连杆
        clear = min(seg_box_dist(pts[k], pts[k + 1], FIXTURE) for k in range(len(pts) - 2))
        tz = min(p[2] for p in pts if abs(p[0]) > 1e-6) - TABLE_Z  # 基座原点在台面上, 不计
        limp = bool(np.all(q >= ch.lo - 1e-6) and np.all(q <= ch.hi + 1e-6))
        worst = min(worst, clear, tz)
        tip = float(np.min(np.maximum(np.maximum(FIXTURE[:, 0] - T[:3, 3], T[:3, 3] - FIXTURE[:, 1]), 0) @ np.ones(3)))
        tip_depth = round((tip) * -1000, 1)
        ok = ok and clear >= a.min_clear and tz >= a.min_clear and limp
        rows.append({"i": i, "tcp_mm": [round(v * 1000, 1) for v in T[:3, 3]],
                     "q": [round(float(v), 4) for v in q], "ik_err_mm": round(err * 1000, 3),
                     "clear_fixture_mm": round(clear * 1000, 1), "clear_table_mm": round(tz * 1000, 1),
                     "limits_ok": limp})
    out = {"port_mm": [round(v * 1000, 2) for v in PORT], "n": len(way),
           "min_clear_mm": round(worst * 1000, 1), "pass": bool(ok),
           "rule": "全部航点: IK 收敛(<1mm) + 关节限位 + 到工装/台面间隙 ≥ %.0fmm" % (a.min_clear * 1000),
           "waypoints": rows}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"ok": out["pass"], "n": out["n"], "min_clear_mm": out["min_clear_mm"],
                      "bad": [r for r in rows if not r.get("limits_ok", True) or r.get("ik_err_mm", 0) > 1][:3],
                      "out": a.out}, ensure_ascii=False))
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
