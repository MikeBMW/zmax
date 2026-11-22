#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""draw_module_frame.py — 按槽位几何真值画出"光模块坐标系"(原点=模块头中心, 抓取时与 tool1 重合)。

口径(全部来自已固化的真源, 不含任何相机外参):
  · 槽位表  config/points/tray_slots_14.json   槽10 = (517.0, 404.0, 110.0), 槽深 8.5mm
  · 模块尺寸 72.0 × 18.35 × 8.5 mm  (QSFP28)
  · 排布规则 上排 1~7 x=649, 下排 8~14 x=517, 行内 y 递减, 列距 48.3mm
             ⇒ 长边 72 沿 +X, 宽 18.35 沿 +Y, 高 8.5 沿 +Z
  · 模块体中心 z = 槽底 110 + 半高 4.25 = 114.25
  · 用户定义: 模块头坐标系原点在模块头中间; 抓取时 模块坐标系 与 tool1 坐标系 重合
             ⇒ 原点取抓取点(模块头中心), 在本图里画在槽中心正上方 = (517.0, 404.0, 114.25)
"""
from __future__ import annotations

import json
import os

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D  # noqa

ROOT = "/home/ubuntu/zmax"
SLOT_ID = 10
OUT = os.path.join(ROOT, "zmax_data/percept/module_frame_slot10.png")

tray = json.load(open(os.path.join(ROOT, "config/points/tray_slots_14.json")))
slots = tray["slots"]
s = [x for x in slots if int(x["id"]) == SLOT_ID][0]
L, W, H = s["box"]["lx"], s["box"]["ly"], s["box"]["lz"]          # 72 / 18.35 / 8.5
o = np.array([s["x"], s["y"], s["z"] + H / 2.0])                   # 模块体中心 = 头中心
R = np.eye(3)                                                      # 轴与基座轴一致

fig = plt.figure(figsize=(16, 8))

# ── 左: 3D ─────────────────────────────────────────────────────────
ax = fig.add_subplot(121, projection="3d")
for t in slots:
    c = "#f59e0b" if int(t["id"]) == SLOT_ID else "#cbd5e1"
    ax.scatter([t["x"]], [t["y"]], [t["z"]], s=26 if int(t["id"]) == SLOT_ID else 12, color=c)
    ax.text(t["x"], t["y"], t["z"] - 16, str(t["id"]), fontsize=7, color="#64748b", ha="center")

# 模块长方体
cx = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
corners = np.array([o + R @ (np.array(c) * np.array([L, W, H]) / 2) for c in cx])
edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]
for a, b in edges:
    ax.plot(*zip(corners[a], corners[b]), color="#0ea5e9", lw=1.6)

# 模块坐标系(实线)
cols = {"X": "#dc2626", "Y": "#16a34a", "Z": "#2563eb"}
axis_len = {"X": L * 0.9, "Y": W * 3.2, "Z": H * 3.4}
for i, axn in enumerate("XYZ"):
    v = R[:, i] * axis_len[axn]
    ax.quiver(*o, *v, color=cols[axn], lw=3, arrow_length_ratio=0.25)
    ax.text(*(o + v * 1.15), "模块." + axn, color=cols[axn], fontsize=10, fontweight="bold")
ax.scatter(*o, s=80, color="k")
ax.text(*(o + np.array([6, -6, 20])), "原点 = 模块头中心\n(%.1f, %.1f, %.1f)" % tuple(o), fontsize=9)
ax.set_xlabel("base X mm"); ax.set_ylabel("base Y mm"); ax.set_zlabel("base Z mm")
ax.set_title("光模块坐标系（槽%d）· 抓取时与 tool1 重合" % SLOT_ID, fontsize=12)
ax.view_init(elev=26, azim=-62)
ax.set_box_aspect((1, 1, 0.5))

# ── 右: 顶视 XY ────────────────────────────────────────────────────
ax2 = fig.add_subplot(122)
for t in slots:
    ax2.add_patch(plt.Rectangle((t["x"] - L / 2, t["y"] - W / 2), L, W,
                                fill=False, ec="#cbd5e1", lw=0.8))
    ax2.text(t["x"], t["y"] + 16, str(t["id"]), fontsize=8, color="#94a3b8", ha="center")
ax2.add_patch(plt.Rectangle((o[0] - L / 2, o[1] - W / 2), L, W, fc="#0ea5e9", alpha=.35, ec="#0284c7", lw=1.8))
ax2.annotate("", xy=(o[0] + L / 2 + 8, o[1]), xytext=(o[0], o[1]),
             arrowprops=dict(arrowstyle="-|>", color=cols["X"], lw=2.4))
ax2.annotate("", xy=(o[0], o[1] + W / 2 + 22), xytext=(o[0], o[1]),
             arrowprops=dict(arrowstyle="-|>", color=cols["Y"], lw=2.4))
ax2.text(o[0] + L / 2 + 10, o[1] - 8, "模块.X (长 72)", color=cols["X"], fontsize=9)
ax2.text(o[0] + 6, o[1] + W / 2 + 24, "模块.Y (宽 18.35)", color=cols["Y"], fontsize=9)
ax2.plot(o[0], o[1], "o", color="k", ms=6)
ax2.text(o[0] - 60, o[1] - 26, "原点 (%.1f, %.1f, %.1f)\nZ 轴 ↑ 出纸面 (高 8.5)" % tuple(o), fontsize=9)
ax2.set_xlabel("base X mm"); ax2.set_ylabel("base Y mm")
ax2.set_title("顶视：14 槽与槽%d 模块（长边沿 X，宽沿 Y）" % SLOT_ID, fontsize=12)
ax2.set_aspect("equal"); ax2.grid(alpha=.25)
ax2.invert_yaxis()

plt.tight_layout()
plt.savefig(OUT, dpi=135)
print("→", OUT)
print("槽%d 槽底 %s · 模块体中心/头中心 %.2f,%.2f,%.2f mm · 尺寸 %.2f×%.2f×%.2f"
      % (SLOT_ID, (s["x"], s["y"], s["z"]), *o, L, W, H))
