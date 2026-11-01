#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_hybrid_sheet.py — 把混合机器人四视图拼成一张交付图 (2×2 + 标题 + 口径)。"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

REPO = "/home/ubuntu/zmax"
FIG = os.path.join(REPO, "docs/6-开阳-工程落地/figs_ar_robot")
OUT = os.path.join(FIG, "hybrid_sheet.png")

plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

PANELS = [
    ("hybrid_zero_front_dim.png", "① 正面（看 −X）：总宽 833.6 mm · 总高 1981.1 mm"),
    ("hybrid_zero_side_dim.png", "② 侧面（看 −Y）：总长 600 mm（箱体） · 总高 1981.1 mm"),
    ("hybrid_zero_top_dim.png", "③ 俯视：总宽 833.6 mm · 总长 600 mm"),
    ("hybrid_zero_iso.png", "④ 透视：两臂 + 箱体 + 顶视立柱"),
]


def main():
    fig = plt.figure(figsize=(16, 12.4), dpi=150)
    fig.patch.set_facecolor("white")
    fig.text(0.035, 0.955, "AR 工位混合机器人 · 外形总图", fontsize=26, weight="bold", color="#14181F")
    fig.text(0.035, 0.918,
             "左右臂（珞石 XMS5-R800-W4G3B4C ×2，中心距 500 mm）＋ 移动底盘箱体 600×800×750 mm ＋ 顶视相机（立柱 Ø140×328 mm，RealSense 模板）",
             fontsize=12, color="#5B6472")
    fig.text(0.035, 0.898,
             "坐标：箱体顶板 = 两臂安装面 = z 0；地面 z −750 mm。外形取自厂家 STL 网格 + AR 页面安装几何（tcp-ar.html 同源）。",
             fontsize=11.5, color="#5B6472")

    axs = [(0.03, 0.50, 0.45, 0.36), (0.51, 0.50, 0.45, 0.36),
           (0.03, 0.08, 0.45, 0.36), (0.51, 0.08, 0.45, 0.36)]
    for (fname, cap), (x, y, w, h) in zip(PANELS, axs):
        ax = fig.add_axes([x, y, w, h])
        ax.imshow(mpimg.imread(os.path.join(FIG, fname)))
        ax.set_title(cap, fontsize=12.5, color="#14181F", pad=8)
        ax.axis("off")
        for s in ax.spines.values():
            s.set_visible(False)
    fig.savefig(OUT, dpi=150, facecolor="white")
    print("saved", OUT)


if __name__ == "__main__":
    main()
