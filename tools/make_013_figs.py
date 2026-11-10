#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_013_figs.py — 生成 ZMP-2026-013 交底书附图

图1: 插配几何与投影示意 (约束轴 n / 径向 P_t / 轴向 P_n / 接触力 F 及其径向分解)
图2: 视触觉融合跨层动作修正控制流

用英文标注 + 无衬线字体, 避免 matplotlib 中文字体缺失导致方框。
用法: gui-venv311/bin/python tools/make_013_figs.py
"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "1-天枢-产品边界", "patents", "figs")
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.size": 10, "font.family": "DejaVu Sans"})


# ══════════════════════════════════════════════════════════════════
# 图1 插配几何与投影
# ══════════════════════════════════════════════════════════════════
def fig1():
    fig, ax = plt.subplots(figsize=(7.2, 5.4))

    # 孔 (矩形开口, 轴向 = +Y 向上)
    hole_w, hole_top, hole_bot = 1.6, 2.2, -2.6
    ax.add_patch(Rectangle((-hole_w / 2, hole_bot), hole_w, hole_top - hole_bot,
                           fill=False, lw=2.2, ec="#333"))
    ax.text(0, hole_bot - 0.35, "Hole (socket)", ha="center", fontsize=9, color="#333")

    # 插入轴 n
    ax.annotate("", xy=(0, 3.0), xytext=(0, -3.2),
                arrowprops=dict(arrowstyle="<->", lw=1.6, color="#1f77b4", ls="--"))
    ax.text(0.12, 2.6, "axis n\n(insertion axis)", fontsize=9, color="#1f77b4", va="top")

    # 模块 (偏 +X, 未对中)
    peg_x, peg_w, peg_h = 0.45, 1.2, 1.6
    ax.add_patch(Rectangle((peg_x - peg_w / 2, 1.4), peg_w, peg_h,
                           facecolor="#cfe3f7", edgecolor="#1f77b4", lw=1.8))
    ax.text(peg_x, 2.2, "Module", ha="center", va="center", fontsize=9)
    ax.plot([peg_x], [1.4], marker="v", ms=7, color="#1f77b4")

    # 真实偏差 δ (径向)
    ax.annotate("", xy=(peg_x, 1.15), xytext=(0, 1.15),
                arrowprops=dict(arrowstyle="->", lw=1.8, color="#d62728"))
    ax.text(peg_x / 2, 0.82, r"$\delta$ (radial offset)", ha="center",
            fontsize=9, color="#d62728")

    # 接触力 F (孔壁把模块往 +X 排斥) 与径向分解
    fx, fy = 1.5, 1.0
    ax.annotate("", xy=(peg_x + 0.6 + fx * 0.55, 1.55 + fy * 0.55), xytext=(peg_x + 0.6, 1.55),
                arrowprops=dict(arrowstyle="-|>", lw=2.2, color="#2ca02c"))
    ax.text(peg_x + 0.7 + fx * 0.55, 1.35 + fy * 0.55,
            r"$F$ (contact, repulsive)", fontsize=9, color="#2ca02c")

    # P_t(F) 径向分量
    ax.annotate("", xy=(peg_x + 0.6 + fx * 0.55, 1.55), xytext=(peg_x + 0.6, 1.55),
                arrowprops=dict(arrowstyle="-|>", lw=2.0, color="#ff7f0e", ls="-"))
    ax.text(peg_x + 0.62, 1.68, r"$P_t F$", fontsize=9, color="#ff7f0e")

    # 投影公式框
    ax.text(-2.9, -3.05,
            r"$P_t = I - n n^{T}$  (radial)" "\n"
            r"$P_n = n n^{T}$  (axial)" "\n"
            r"$M = \sigma_t^{2} P_t + \sigma_n^{2} P_n$" "\n"
            r"$\sigma_t \ll \sigma_n \Rightarrow$ radial gain $(\sigma_n/\sigma_t)^{2}$",
            fontsize=9, va="bottom", family="DejaVu Sans",
            bbox=dict(boxstyle="round,pad=0.45", fc="#f7f7f7", ec="#999"))

    ax.text(1.75, -3.05,
            r"$\nabla V_{tac} = +P_t F$" "\n"
            r"$\Delta\xi = -\alpha M^{-1}\nabla V$" "\n"
            r"$\Rightarrow \Delta\xi \perp\!\!\perp F$ (toward hole center)",
            fontsize=9, va="bottom",
            bbox=dict(boxstyle="round,pad=0.45", fc="#fffbe6", ec="#d4a017"))

    ax.set_xlim(-3.2, 3.4)
    ax.set_ylim(-3.5, 3.3)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title("Fig.1  Insertion geometry, radial/axial projections and contact force",
                 fontsize=10.5, pad=8)
    p = os.path.join(OUT, "013_fig1_geometry.png")
    fig.savefig(p, dpi=190, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


# ══════════════════════════════════════════════════════════════════
# 图2 控制流
# ══════════════════════════════════════════════════════════════════
def fig2():
    fig, ax = plt.subplots(figsize=(8.0, 7.0))

    def box(x, y, w, h, label, fc="#ffffff", ec="#444", fs=9):
        ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                    boxstyle="round,pad=0.10", fc=fc, ec=ec, lw=1.5))
        ax.text(x, y, label, ha="center", va="center", fontsize=fs)

    def arrow(x1, y1, x2, y2, label="", color="#333"):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                     mutation_scale=13, lw=1.5, color=color))
        if label:
            ax.text((x1 + x2) / 2 + 0.09, (y1 + y2) / 2, label, fontsize=8, color=color)

    # 输入层
    box(-2.25, 4.15, 2.7, 0.85, "Vision input\n$\\delta_{vis}$  (far field)", fc="#eaf3fc")
    box(2.25, 4.15, 2.7, 0.85, "Force/torque input\n$F$  (near field)", fc="#eafaea")

    # 融合
    box(0, 2.95, 5.4, 1.0,
        "Fusion of potential field\n"
        "$\\nabla V = w_{vis}\\nabla\\tilde{V}_{vis} + w_{tac}\\nabla\\tilde{V}_{tac}$\n"
        "$\\nabla V_{tac} = +P_t F$,   $w_{tac}=w_{max}\\,clip(c/c_0,0,1)^{\\gamma}$",
        fc="#fff8e1", fs=8.5)

    # 度规
    box(0, 1.55, 5.4, 0.85,
        "Anisotropic Riemannian metric\n"
        "$M=\\sigma_t^{2}P_t+\\sigma_n^{2}P_n$   $\\Rightarrow$  radial gain $(\\sigma_n/\\sigma_t)^{2}$",
        fc="#f3e8fd", fs=8.5)

    # 自然梯度 + 门控
    box(0, 0.25, 5.4, 0.85,
        "Natural gradient + gate\n"
        "$\\Delta\\xi_{dir}=-\\alpha M^{-1}\\nabla V$,   $\\alpha=\\alpha_0\\eta\\exp(-V/V_0)\\cdot s(F)$",
        fc="#e8f4ea", fs=8.5)

    # 双重限幅
    box(0, -1.15, 5.4, 1.0,
        "Double clamping\n"
        "(1) $cap_1=\\max(\\beta\\,step,\\,c_{min})$     (2) $cap_2=0.95\\,\\delta_{est}$\n"
        "$\\delta_{est}=\\|F\\|/K$ for tactile path  $\\Rightarrow$ $\\Delta\\xi=clip(\\Delta\\xi_{dir})$",
        fc="#fdecea", fs=8.5)

    # 输出
    box(0, -2.45, 5.4, 0.8,
        "Output & logging\n"
        "$\\xi^{*}=\\xi_d+\\Delta\\xi$   |   report $\\Delta\\xi_{radial}$, $\\Delta\\xi_{axial}$, source, injected",
        fc="#eef0f3", fs=8.5)

    # 降级分支
    box(2.75, -3.55, 2.5, 0.62,
        "Degrade: $injected=false$\npass through $\\xi_d$ (no fabrication)",
        fc="#f5f5f5", ec="#999", fs=8)

    arrow(-2.25, 3.72, -0.95, 3.45)
    arrow(2.25, 3.72, 0.95, 3.45)
    arrow(0, 2.45, 0, 1.98)
    arrow(0, 1.12, 0, 0.68)
    arrow(0, -0.18, 0, -0.65)
    arrow(0, -1.65, 0, -2.05)
    arrow(0.0, -2.85, 1.6, -3.35, color="#999")

    ax.text(0, -3.55, "missing $\\nabla V$ / invalid axis\n/ force abnormal",
            ha="center", va="center", fontsize=8, color="#777")

    ax.set_xlim(-4.0, 4.0)
    ax.set_ylim(-4.1, 4.75)
    ax.axis("off")
    ax.set_title("Fig.2  Control flow of visuo-tactile cross-layer action correction",
                 fontsize=10.5, pad=6)
    p = os.path.join(OUT, "013_fig2_flow.png")
    fig.savefig(p, dpi=190, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


# ══════════════════════════════════════════════════════════════════
# 图3 触觉权重曲线
# ══════════════════════════════════════════════════════════════════
def fig3():
    import numpy as np
    c0, gamma, wmax = 0.35, 2.0, 0.9
    c = np.linspace(0, 1, 400)
    w = wmax * np.clip(c / c0, 0, 1) ** gamma
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.plot(c, w, lw=2.2, color="#1f77b4", label=r"$w_{tac}$")
    ax.plot(c, 1 - w, lw=1.8, ls="--", color="#ff7f0e", label=r"$w_{vis}=1-w_{tac}$")
    for cc, ww in ((0, 0), (0.15, 0.165), (0.35, 0.9), (0.7, 0.9), (1.0, 0.9)):
        ax.plot([cc], [ww], "o", ms=5, color="#d62728")
        ax.annotate("%.3f" % ww, (cc, ww), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=8, color="#d62728")
    ax.axvline(c0, ls=":", color="#666")
    ax.text(c0 + 0.015, 0.45, r"$c_0=0.35$", fontsize=8.5, color="#666")
    ax.set_xlabel("contact indicator  $c$   (0 = no contact, 1 = firm contact)")
    ax.set_ylabel("weight")
    ax.set_xlim(0, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.grid(alpha=0.3)
    ax.legend(loc="center right", fontsize=9)
    ax.set_title("Fig.3  Vision-to-tactile weight transition", fontsize=10.5)
    p = os.path.join(OUT, "013_fig3_weights.png")
    fig.savefig(p, dpi=190, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return p


if __name__ == "__main__":
    for f in (fig1(), fig2(), fig3()):
        print("OK", f, os.path.getsize(f), "bytes")
