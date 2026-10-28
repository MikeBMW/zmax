# -*- coding: utf-8 -*-
"""urdf_proxy.py — 给 AR 三维视图用的 URDF 轻量外形 (每条 link 的降采样点云 + 关节链)

为什么不是直接发 STL:
  AR 页面是浏览器 canvas, 没有 WebGL/three.js 依赖通道; 整条 STL(每条几万三角面)传过去
  也没法在 2D canvas 里高效画。做法: 服务端起读 URDF + STL, 每条 link 降采样成 N 个点
  (link 自身坐标系, 米), 页面用当前关节角做正运动学, 把点云变换后按深度排序画出来
  ⇒ 看到的是**这条臂的真实外形**(不是示意块), 5Hz 跟随真机姿态。

输出:
  {"links": [{"name":..., "pts":[[x,y,z]...], "n":N}, ...],
   "joints":[{"name","parent","child","xyz":[..],"rpy":[..],"axis":[..],"type"}],
   "base":"XMS5-R800-W4G3B4C_base", "tip":"tool1", "src":"...urdf"}
"""
from __future__ import annotations

import os
import re
import struct

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
URDF = os.path.join(REPO, "data/database/zmax/sources/config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf")
PTS_PER_LINK = 220


def _stl_points(path, limit=PTS_PER_LINK):
    """读 STL(二进制优先/ASCII 保障) 取三角面顶点, 按三角形等间隔抽 limit 个点"""
    try:
        with open(path, "rb") as f:
            head = f.read(84)
            if len(head) < 84:
                return []
            ntri = struct.unpack("<I", head[80:84])[0]
            size = os.path.getsize(path)
            if 84 + ntri * 50 == size and ntri > 0:              # 二进制 STL
                tris = []
                f.seek(84)
                blob = f.read(ntri * 50)
                for i in range(ntri):
                    o = i * 50 + 12
                    tris.append(struct.unpack("<9f", blob[o:o + 36]))
            else:                                                 # ASCII STL
                f.seek(0)
                txt = f.read().decode("utf-8", "ignore")
                vals = [float(x) for x in re.findall(r"vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", txt)
                        for x in x] if False else []
                tri_pts = re.findall(r"vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", txt)
                coords = [[float(a), float(b), float(c)] for a, b, c in tri_pts]
                tris = []
                for i in range(0, len(coords) - 2, 3):
                    tris.append([c for p in coords[i:i + 3] for c in p])
                del vals
    except Exception:                                             # noqa: BLE001
        return []
    if not tris:
        return []
    nt = len(tris)
    step = max(1, nt // max(1, limit))
    out = []
    for i in range(0, nt, step):
        t = tris[i]
        out.append([round(t[0], 4), round(t[1], 4), round(t[2], 4)])   # 每个三角形取第一个顶点
        if len(out) >= limit:
            break
    return out


def load(urdf=URDF, pts_per_link=PTS_PER_LINK):
    txt = open(urdf, encoding="utf-8").read()
    folder = os.path.dirname(urdf)
    joints, links = [], {}
    for m in re.finditer(r"<joint\s+name=\"([^\"]+)\"\s+type=\"([^\"]+)\">(.*?)</joint>", txt, re.S):
        body = m.group(3)
        g = lambda pat: (re.search(pat, body).group(1) if re.search(pat, body) else None)   # noqa: E731
        joint = {"name": m.group(1), "type": m.group(2),
                 "parent": g(r'<parent\s+link="([^"]+)"'), "child": g(r'<child\s+link="([^"]+)"'),
                 "xyz": [float(v) for v in (g(r'<origin[^>]*xyz="([^"]+)"') or "0 0 0").split()],
                 "rpy": [float(v) for v in (g(r'<origin[^>]*rpy="([^"]+)"') or "0 0 0").split()],
                 "axis": ([float(v) for v in g(r'<axis[^>]*xyz="([^"]+)"').split()]
                          if g(r'<axis[^>]*xyz="([^"]+)"') else [0.0, 0.0, 1.0])}
        joints.append(joint)
    for m in re.finditer(r'<link\s+name="([^"]+)">(.*?)</link>', txt, re.S):
        name, body = m.group(1), m.group(2)
        mesh = re.search(r'filename="([^"]+)"', body)
        pts = []
        if mesh:
            p = os.path.join(folder, mesh.group(1))
            if os.path.exists(p):
                pts = _stl_points(p, pts_per_link)
                # 🔴 实测(2026-10-18): 这套 STL 的坐标是**毫米**(link2 长轴 517), 而 URDF 场景是米
                #    ⇒ 不换算就画出 1000 倍大的臂(投影直接飞出画布, 凸包糊满一片)
                if pts:
                    mx = max(max(abs(c) for c in q) for q in pts)
                    if mx > 5.0:                       # 明显是毫米单位
                        pts = [[c / 1000.0 for c in q] for q in pts]
        links[name] = {"name": name, "n": len(pts), "pts": pts}
    base = next((j["child"] for j in joints if j["type"] == "fixed" and j["parent"] == "world"),
                (joints[0]["parent"] if joints else ""))
    tip = "tool1" if any(l["name"] == "tool1" for l in links.values()) else ""
    return {"links": [l for l in links.values() if l["n"] > 0], "joints": joints,
            "base": base, "tip": tip, "src": os.path.basename(urdf),
            "n_links": len(links), "n_joints": len(joints)}


if __name__ == "__main__":
    import json
    import sys
    d = load()
    print(json.dumps({"links": [{"name": l["name"], "n": l["n"]} for l in d["links"]],
                      "base": d["base"], "tip": d["tip"]}, ensure_ascii=False, indent=1))
    print("JSON 大小: %.1f KB" % (len(json.dumps(d)) / 1024.0))
    if "--out" in sys.argv:
        with open(sys.argv[sys.argv.index("--out") + 1], "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
