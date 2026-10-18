#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线校验: URDF 正运动学 (tool0 / tool1) 与真机 TCP 的差 (不动臂, 只读 JSON)。

📚 2026-10-18 老倪: 「你先别动真机，想想用 moveit，怎么精确控制机器人，先给出完整方案」
   方案的第一块地基 = MoveIt 的几何口径到底对不对。plan 文件里那句
   「FK(真关节)与真机 TCP 差 259.2mm ⇒ 关节零位/符号口径不同」需要先证伪/证实:
   URDF 里 joint_tool1 的 origin z = 0.2587 ⇒ 259mm 很可能只是"量到法兰 vs 量到夹爪尖"。
"""
import json
import math
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np

URDF = "zmax_data/rokae_sdk/urdf/xms5_r800_w4g3b4c.urdf"


def rpy2m(r, p, y):
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def axis_rot(axis, q):
    a = np.asarray(axis, float)
    n = np.linalg.norm(a)
    if n == 0:
        return np.eye(3)
    a = a / n
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(q) * K + (1 - math.cos(q)) * (K @ K)


def load_chain(urdf_path, target_link):
    root = ET.parse(urdf_path).getroot()
    by_child = {}
    for j in root.findall("joint"):
        by_child[j.find("child").get("link")] = j
    chain, link = [], target_link
    while link in by_child:
        j = by_child[link]
        chain.append(j)
        link = j.find("parent").get("link")
    return list(reversed(chain))


def fk(urdf_path, target_link, q):
    T = np.eye(4)
    i = 0
    for j in load_chain(urdf_path, target_link):
        o = j.find("origin")
        xyz = [float(v) for v in (o.get("xyz") or "0 0 0").split()] if o is not None else [0, 0, 0]
        rpy = [float(v) for v in (o.get("rpy") or "0 0 0").split()] if o is not None else [0, 0, 0]
        M = np.eye(4)
        M[:3, :3] = rpy2m(*rpy)
        M[:3, 3] = xyz
        T = T @ M
        if j.get("type") == "revolute":
            a = j.find("axis")
            ax = [float(v) for v in a.get("xyz").split()] if a is not None else [0, 0, 1]
            R = np.eye(4)
            R[:3, :3] = axis_rot(ax, q[i])
            T = T @ R
            i += 1
    return T


def samples():
    out = []
    for path, keys in (("zmax_data/rokae_sdk/tcp_out/latest.json", ("joint", "x", "y", "z")),
                       ("zmax_data/runtime/moveit_plan/plan_req.json", ("jpos", "tcp", None, None))):
        if not os.path.exists(path):
            continue
        d = json.load(open(path))
        if keys[0] == "joint":
            q = d["joint"] if isinstance(d["joint"], list) else json.loads(d["joint"])
            tcp = [float(d["x"]), float(d["y"]), float(d["z"])]
            tag = "tcp_out/latest"
        else:
            q = d["jpos"] if isinstance(d["jpos"], list) else json.loads(d["jpos"])
            tcp = json.loads(d["tcp"]) if isinstance(d["tcp"], str) else d["tcp"]
            tag = "plan_req"
        if len(q) >= 6:
            out.append((tag, q[:6], tcp))
    return out


def main():
    print("URDF:", URDF)
    bad = 0
    for tag, q, tcp in samples():
        t0 = fk(URDF, "tool0", q)
        t1 = fk(URDF, "tool1", q)
        p0, p1 = t0[:3, 3], t1[:3, 3]
        e0 = np.linalg.norm(p0 - np.array(tcp)) * 1000
        e1 = np.linalg.norm(p1 - np.array(tcp)) * 1000
        print("\n[%s]" % tag)
        print("  真机 TCP      = (%.4f, %.4f, %.4f)" % tuple(tcp))
        print("  FK(tool0)     = (%.4f, %.4f, %.4f)   误差 %7.1f mm" % (p0[0], p0[1], p0[2], e0))
        print("  FK(tool1)     = (%.4f, %.4f, %.4f)   误差 %7.1f mm" % (p1[0], p1[1], p1[2], e1))
        print("  tool1-tool0   = %.1f mm  (URDF 里 joint_tool1 的 z 偏移)" % (np.linalg.norm(p1 - p0) * 1000))
        if e1 > 5.0:
            bad += 1
    print("\n结论: %s" % ("✅ FK(tool1) 与真机 TCP 同源 (<5mm) ⇒ 259mm 是工具长度口径, 不是关节零位错"
                        if bad == 0 else "❌ FK(tool1) 仍差 >5mm ⇒ 还需查关节零位/符号"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
