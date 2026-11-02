#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画「右臂世界坐标系下，一个光模块的整条轨迹」—— 自建透视投影, 铺满画布。

数据: GET /api/sim_insert 的 plan[]（毫米, 右臂基座 = 世界原点）, 取 mod=1 的 28 段:
  取件(槽1) → 插入孔1 47mm → 松爪 → 重新夹住 → 拔出 → 金手指 + 4 侧面 AOI → 下料盘。
投影: 手写透视 (eye→target, 焦距 f, 透视除法), 不用 mplot3d —— 它的立方体永远是方的,
      铺不满 2.4:1 的画布。深度排序按相机 z 由远到近画, 近处料盘自然比远处孔位大。
输出: zmax_data/ar_mujoco/figs/traj_world_persp.png
"""
import json
import math
import os
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, Polygon

ROOT = "/home/ubuntu/zmax"
OUT = os.path.join(ROOT, "zmax_data/ar_mujoco/figs/traj_world_persp.png")
FONT = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"

PH = [("① 取件", "#1B7F3B"), ("② 插入", "#1B64D1"), ("③ 拔出", "#0E8A9B"),
      ("④ 检测 AOI", "#C2610C"), ("⑤ 分拣", "#7A3FB8")]


def fetch():
    try:
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:8797/api/sim_insert", timeout=8).read())
        return d, "api/sim_insert"
    except Exception:                                            # noqa: BLE001
        d = json.load(open(os.path.join(ROOT, "zmax_data/runtime/traj/sim_insert.json"), encoding="utf-8"))
        return d, "zmax_data/runtime/traj/sim_insert.json (离线快照)"


def phase_bounds(P):
    def first(pred, dflt):
        for i, s in enumerate(P):
            if pred(s):
                return i
        return dflt
    i_ins = first(lambda s: ("孔" in (s.get("label") or "")) and ("(拔)" not in (s.get("label") or "")), 4)
    i_pull = first(lambda s: "(拔)" in (s.get("label") or ""), i_ins + 5)
    i_aoi = first(lambda s: s["kind"] == "golden", i_pull + 5)
    i_sort = first(lambda s: "下料盘" in (s.get("label") or ""), i_aoi + 6)
    return [0, i_ins, i_pull, i_aoi, i_sort, len(P)]


class Cam:
    """右手相机: eye/target/up → 透视投影到 2D (u, v) 与深度 d。"""

    def __init__(self, az_deg, el_deg, dist, target, f):
        az, el = math.radians(az_deg), math.radians(el_deg)
        self.eye = [target[0] + dist * math.cos(el) * math.cos(az),
                    target[1] + dist * math.cos(el) * math.sin(az),
                    target[2] + dist * math.sin(el)]
        fw = self._norm([target[i] - self.eye[i] for i in range(3)])
        rt = self._norm(self._cross(fw, [0.0, 0.0, 1.0]))
        up2 = self._cross(rt, fw)
        self.R = (rt, up2, fw)
        self.f = f

    @staticmethod
    def _norm(v):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    @staticmethod
    def _cross(a, b):
        return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]

    def __call__(self, p):
        d = [p[i] - self.eye[i] for i in range(3)]
        x, y, z = (sum(self.R[i][j] * d[j] for j in range(3)) for i in range(3))
        z = max(z, 1.0)
        return (self.f * x / z, self.f * y / z, z)


def render():
    d, src = fetch()
    P = [s for s in d["plan"] if s.get("mod") == 1]
    B = phase_bounds(P)
    dur = [round(sum(s["t"] for s in P[B[k]:B[k + 1]]), 2) for k in range(5)]
    ph_of = {}
    for k in range(5):
        for i in range(B[k], B[k + 1]):
            ph_of[i] = k

    poly, marks = [], []
    t = 0.0
    for i, s in enumerate(P):
        if not poly or tuple(poly[-1]) != tuple(s["a"]):
            poly.append(tuple(s["a"]))
        poly.append(tuple(s["b"]))
        t += s["t"]
        if s["kind"] in ("grip", "release", "insert", "pull", "golden", "side"):
            marks.append((tuple(s["a"]), s["label"]))
    holes = d["holes"]

    if os.path.exists(FONT):
        font_manager.fontManager.addfont(FONT)
    plt.rcParams["font.family"] = "WenQuanYi Zen Hei"
    plt.rcParams["axes.unicode_minus"] = False

    # 相机: 右前上方看, 近处是料盘(x≈490,y≈500), 远处是孔位(x≈790)与 AOI(x≈360,y≈-120)
    cam = Cam(az_deg=120, el_deg=22, dist=1300, target=(470, 60, 250), f=1600)

    fig = plt.figure(figsize=(5.6, 5.4), dpi=320)   # 按幻灯片上的实际大小出图, 字号才是真字号
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor("white")
    ax.axis("off")

    def line(pts, **kw):
        uv = [cam(p) for p in pts]
        ax.plot([u for u, v, _ in uv], [v for u, v, _ in uv], **kw)

    def poly3(pts, **kw):
        ax.add_patch(Polygon([(u, v) for u, v, _ in (cam(p) for p in pts)], closed=True, **kw))

    # 台面 + 网格
    poly3([(0, 0, 0), (1150, 0, 0), (1150, 600, 0), (0, 600, 0)],
          facecolor="#F4F6F9", edgecolor="#C2CBD8", lw=1.4, zorder=0)
    for gy in range(0, 601, 100):
        line([(0, gy, 0), (1150, gy, 0)], color="#E6EBF2", lw=0.7, zorder=0)

    # 料盘 / 下料盘 / 孔位
    def plate(x0, y0, w, dep, col, lab, z=0.0):
        poly3([(x0, y0, z), (x0 + w, y0, z), (x0 + w, y0 + dep, z), (x0, y0 + dep, z)],
              facecolor=col + "22", edgecolor=col, lw=1.5, zorder=1)
        u, v, _ = cam((x0 + w / 2, y0 + dep / 2, z))
        ax.text(u, v, lab, color=col, fontsize=10.5, ha="center", va="center", zorder=8,
                bbox=dict(boxstyle="round,pad=0.22", fc="white", ec=col, lw=0.7, alpha=0.85))

    plate(430, 440, 120, 140, "#2E7D32", "取件料盘 · 槽1")
    plate(430, 40, 120, 120, "#7A3FB8", "下料盘 · 分拣位")
    for h in holes[:4]:
        m, ins = h["mouth"], h["insert"]
        line([m, ins], color="#1B64D1", lw=7, alpha=0.35, solid_capstyle="round", zorder=2)
        line([m, ins], color="#1B64D1", lw=2.2, zorder=3)
        u, v, _ = cam(m)
        ax.text(u, v - 10, h["name"], color="#1B64D1", fontsize=9.5, ha="center", va="top", zorder=8)

    # 轨迹: 按深度由远到近画, 近处压住远处
    order = sorted(range(len(poly) - 1), key=lambda i: -cam(poly[i])[2])
    for i in order:
        a, b = poly[i], poly[i + 1]
        col = PH[ph_of[min(i, len(P) - 1)]][1]
        line([a, b], color=col, lw=6.0, alpha=0.15, solid_capstyle="round", zorder=3)
        line([a, b], color=col, lw=2.2, solid_capstyle="round", zorder=4)

    for xyz, lab in marks:
        u, v, _ = cam(xyz)
        ax.scatter([u], [v], s=20, color="#26303C", zorder=6)
    st, en = poly[0], poly[-1]
    for xyz, mk, txt, dy in ((st, "o", "起点 · 槽1 取件", 24), (en, "*", "终点 · 下料分拣", 26)):
        u, v, _ = cam(xyz)
        ax.scatter([u], [v], s=180 if mk == "*" else 95, marker=mk, color="#111827", zorder=9)
        ax.annotate(txt, (u, v), textcoords="offset points", xytext=(0, dy), ha="center",
                    fontsize=11, fontweight="bold", color="#111827", zorder=9)

    # 落线: 关键点垂到台面, 读高度
    for xyz in (st, en, tuple(holes[0]["insert"]), (360.0, -117.0, 654.0)):
        line([(xyz[0], xyz[1], 0), xyz], color="#AAB4C2", lw=0.9,
             linestyle=(0, (3, 3)), zorder=1)

    # 阶段标注 (贴在投影点旁, 自动避让)
    anchors = [(tuple(poly[0]), 0, (-16, 50)), (tuple(holes[0]["insert"]), 1, (74, 30)),
               (tuple(holes[0]["mouth"]), 2, (60, -34)), ((360.0, -117.0, 654.0), 3, (0, 46)),
               ((490.0, 75.6, 118.0), 4, (18, -50))]
    texts = []
    for xyz, k, off in anchors:
        u, v, _ = cam(xyz)
        texts.append(ax.annotate("%s %.2f 秒" % (PH[k][0], dur[k]), (u, v), textcoords="offset points",
                                 xytext=off, ha="center", va="center", fontsize=10.8,
                                 color=PH[k][1], fontweight="bold", zorder=10,
                                 bbox=dict(boxstyle="round,pad=0.30", fc="white",
                                           ec=PH[k][1], lw=0.9, alpha=0.94)))
    fig.canvas.draw()
    _ov = 0
    for _ in range(60):
        boxes = [tx.get_window_extent() for tx in texts]
        moved = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if boxes[i].overlaps(boxes[j]):
                    x, y = texts[j].xyann
                    texts[j].xyann = (x, y + 16)
                    moved = True
        if not moved:
            break
    _boxes = [tx.get_window_extent() for tx in texts]
    for i in range(len(_boxes)):
        for j in range(i + 1, len(_boxes)):
            if _boxes[i].overlaps(_boxes[j]):
                _ov += 1

    # 坐标轴 (世界原点 = 右臂基座)
    for vec, col, lab in (((210, 0, 0), "#C0392B", "X"), ((0, 210, 0), "#1E8449", "Y"),
                          ((0, 0, 210), "#1B64D1", "Z")):
        u0, v0, _ = cam((0, 0, 0))
        u1, v1, _ = cam(vec)
        ax.add_patch(FancyArrowPatch((u0, v0), (u1, v1), arrowstyle="-|>", mutation_scale=15,
                                     lw=2.4, color=col, zorder=7))
        ax.text(u1, v1, lab, color=col, fontsize=11.5, fontweight="bold", ha="center",
                va="center", zorder=8)
    u, v, _ = cam((0, 0, 0))
    ax.annotate("右臂基座原点 (0,0,0)", (u, v), textcoords="offset points", xytext=(-16, -20),
                ha="right", fontsize=9.6, color="#5A6574", zorder=8)

    allp = [cam(p) for p in poly] + [cam((1150, 600, 0)), cam((0, 0, 0))]
    us = [p[0] for p in allp]
    vs = [p[1] for p in allp]
    padu, padv = (max(us) - min(us)) * 0.14, (max(vs) - min(vs)) * 0.18
    ax.set_xlim(min(us) - padu, max(us) + padu)
    ax.set_ylim(min(vs) - padv, max(vs) + padv * 1.5)
    ax.set_aspect("equal", adjustable="box")

    tot = sum(s["t"] for s in P)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fig.savefig(OUT, facecolor="white")
    plt.close(fig)

    from PIL import Image
    import numpy as np
    a = np.asarray(Image.open(OUT).convert("RGB"))
    ink = (a < 245).any(2)
    ys, xs = np.where(ink)
    print("图已出: %s (%.0f KB) %dx%d" % (OUT, os.path.getsize(OUT) / 1024.0, a.shape[1], a.shape[0]))
    print("墨迹覆盖 x %.0f%% y %.0f%% · 墨比 %.1f%%"
          % (100 * (xs.max() - xs.min()) / a.shape[1],
             100 * (ys.max() - ys.min()) / a.shape[0], 100 * ink.mean()))
    print("阶段标签重叠对 %d (0 = 全部让开)" % _ov)
    print("源: %s · 段 %d · %.2f s · 阶段 %s" % (src, len(P), tot, dur))
    return dict(img=OUT, total=round(tot, 2), nseg=len(P), dur=dur,
                nseg_ph=[B[k + 1] - B[k] for k in range(5)], src=src)


if __name__ == "__main__":
    render()
