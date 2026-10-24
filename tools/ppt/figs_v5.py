# -*- coding: utf-8 -*-
"""figs_v5.py — v5 的 9 张图（数据只从 data_v5.json 读）"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager as fm
from matplotlib.patches import Circle, Rectangle

D = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_v5.json"),
                   encoding="utf-8"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fig5")
os.makedirs(OUT, exist_ok=True)

for p in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
          "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"):
    if os.path.exists(p):
        fm.fontManager.addfont(p)
CJK = fm.FontProperties(fname="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc").get_name()
plt.rcParams.update({"font.family": CJK, "axes.unicode_minus": False,
                     "figure.dpi": 200, "savefig.dpi": 200})

CN = "#2E6FD9"; OS = "#E8873A"; RED = "#D93A3A"; GRN = "#2FA36B"; ME = "#7B3FF2"
INK = "#1A1D24"; MUT = "#6B7280"; GRID = "#E6E9EE"; LINE = "#D4D9E1"


def save(fig, name, tight=True):
    p = os.path.join(OUT, name)
    if tight:
        fig.savefig(p, bbox_inches="tight", pad_inches=0.14, facecolor="white")
    else:
        fig.savefig(p, facecolor="white")
    plt.close(fig)
    print("→", name)
    return p


# ═══ 图1 全球前 10：估值条形 + 每台估值 ═══════════════════════
def fig_g10():
    rows = [r for r in D["global10"] if r[3]]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.6, 4.6),
                                 gridspec_kw={"width_ratios": [1.35, 1]})
    fig.subplots_adjust(left=0.115, right=0.985, top=0.90, bottom=0.16, wspace=0.42)
    nm = [r[1] for r in rows][::-1]; vv = [r[3] for r in rows][::-1]
    cc = [OS if i < 3 else CN for i in range(len(rows))][::-1]
    a1.barh(range(len(nm)), vv, color=cc, height=0.62)
    for i, v in enumerate(vv):
        a1.text(v + 30, i, "%.0f" % v, va="center", fontsize=8.6, color=INK)
    a1.set_yticks(range(len(nm))); a1.set_yticklabels(nm, fontsize=8.8)
    a1.set_xlabel("估值 / 市值（亿元人民币，2026-10-24）", fontsize=9, color=MUT)
    a1.set_xlim(0, max(vv) * 1.16)
    a1.grid(axis="x", color=GRID); a1.set_axisbelow(True)
    for sp in ("top", "right"): a1.spines[sp].set_visible(False)

    # 统一换成「万元/台」，差 41 倍不能画线性轴 → log
    per = [("Figure AI", 2788 * 1e4 / 150), ("宇树科技", 2475 * 1e4 / 5500),
           ("智元", 500 * 1e4 / 5168)]
    pn = [x[0] for x in per]; pv = [x[1] for x in per]
    a2.barh(range(len(pn))[::-1], pv, color=[OS, CN, CN], height=0.5)
    for i, v in enumerate(pv):
        lab = ("%.1f 亿元/台" % (v / 1e4)) if v >= 1e4 else ("%.0f 万元/台" % v)
        a2.text(v * 1.18, len(pn) - 1 - i, lab, va="center", fontsize=9.4, color=INK,
                weight="bold")
    a2.set_yticks(range(len(pn))[::-1]); a2.set_yticklabels(pn, fontsize=9)
    a2.set_xscale("log")
    a2.set_xlim(500, 4.0e5)
    a2.set_xlabel("单台估值（对数轴，万元 / 台）", fontsize=9, color=MUT)
    a2.grid(axis="x", color=GRID); a2.set_axisbelow(True)
    for sp in ("top", "right"): a2.spines[sp].set_visible(False)
    fig.text(0.012, 0.008, "左图仅 9 家（Optimus 无独立估值、未入图）；右图按 Figure 2025 约 150 台、"
                           "宇树约 5500 台、智元 5168 台换算，口径不同，只用于说明溢价倍数。",
             fontsize=7.8, color=MUT)
    return save(fig, "fig_g10.png")


# ═══ 图2 国内前 20：估值 + 口径性质 ═══════════════════════════
def fig_d20():
    rows = D["domestic20"]
    lab = [r[1] for r in rows]; val = [r[3] or 0 for r in rows]
    COL = {"科创板": CN, "科创板 IPO": CN, "港股": "#1F9D8F", "Pre-IPO": "#9AA3AF",
           "私募": "#7FA8E8", "私募（拟港股）": CN, "私募（已递表港交所）": "#7FA8E8"}
    cc = [COL.get(r[4], MUT) for r in rows]
    fig, ax = plt.subplots(figsize=(12.6, 5.4))
    fig.subplots_adjust(left=0.145, right=0.985, top=0.93, bottom=0.145)
    y = np.arange(len(rows))[::-1]
    ax.barh(y, val, color=cc, height=0.66)
    for i, r in enumerate(rows):
        if r[3]:
            ax.text(r[3] + 25, y[i], "%.0f" % r[3], va="center", fontsize=8.2, color=INK)
        else:
            ax.text(25, y[i], r[2] if "未折算" in r[2] else r[2] + "（未折算）",
                    va="center", fontsize=8.2, color=MUT)
    ax.set_yticks(y); ax.set_yticklabels(["%d %s" % (r[0], r[1]) for r in rows], fontsize=8.4)
    ax.set_xlabel("估值 / 市值（亿元人民币，2026-10-24）", fontsize=9.2, color=MUT)
    ax.set_xlim(0, max(val) * 1.14)
    ax.grid(axis="x", color=GRID); ax.set_axisbelow(True)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    hs = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (CN, "#1F9D8F", "#9AA3AF", "#7FA8E8")]
    ax.legend(hs, ["科创板 / 拟港股", "港股", "Pre-IPO（未达百亿）", "私募"],
              loc="lower right", frameon=False, fontsize=8.8)
    return save(fig, "fig_d20.png")


# ═══ 图3 竞合 2×2 ═══════════════════════════════════════════
def fig_rel():
    fig, ax = plt.subplots(figsize=(7.4, 6.0))
    Q = [(5, 5, 4.8, 4.8, "#FDEEEB", "直接竞品", "打", RED, "它石、智元"),
         (0.2, 5, 4.8, 4.8, "#EEF3FD", "模型伙伴", "谈", GRN, "具脑、无界"),
         (0.2, 0.2, 4.8, 4.8, "#F4F6F8", "能力补充", "看", MUT, "RIMBOT 日冕"),
         (5, 0.2, 4.8, 4.8, "#F1EAFE", "元任务层 · 我方", "守", ME, "只有我方")]
    for x0, y0, w, h, c, t1, act, ac, t2 in Q:
        ax.add_patch(Rectangle((x0, y0), w, h, facecolor=c, edgecolor="white", lw=2.2))
        top = t1.startswith("能力补充") or t1.startswith("元任务")
        ty = y0 + h - 0.52 if top else y0 + 0.95
        ax.text(x0 + 0.2, ty, t1, fontsize=10.4, weight="bold", color=ac)
        ax.text(x0 + 0.2, ty - 0.42, t2, fontsize=8.2, color=MUT)
        ax.text(x0 + w - 0.26, ty - 0.1, act, fontsize=17, weight="bold", color=ac,
                ha="right", alpha=0.45)
    P = [("智元", 7.9, 9.15, "comp"), ("它石智航", 8.5, 7.3, "comp"),
         ("具脑磐石", 2.4, 8.6, "partner"), ("无界智航", 3.3, 7.2, "partner"),
         ("RIMBOT 日冕", 3.0, 2.2, "watch"), ("我方 Z-MAX", 8.5, 1.0, "me")]
    C4 = {"comp": RED, "partner": GRN, "watch": "#9AA3AF", "me": ME}
    OFF = {"智元": (-12, 12, "right"), "它石智航": (-11, -16, "right"),
           "具脑磐石": (10, 13, "left"), "无界智航": (10, 12, "left"),
           "RIMBOT 日冕": (11, 12, "left"), "我方 Z-MAX": (-13, 12, "right")}
    for nm, x, y, q in P:
        ax.scatter(x, y, s=300 if q == "me" else 175, color=C4[q],
                   edgecolor="white", lw=1.6, zorder=6, marker="*" if q == "me" else "o")
        dx, dy, ha = OFF[nm]
        ax.annotate(nm, (x, y), textcoords="offset points", xytext=(dx, dy), fontsize=8.8,
                    color=ME if q == "me" else INK, weight="bold" if q == "me" else "normal",
                    ha=ha, va="center", zorder=7,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none",
                              alpha=0.9))
    ax.set_xlim(0, 10); ax.set_ylim(-0.4, 10)
    ax.set_xlabel("与工厂精细操作的场景重叠度（低 → 高）", fontsize=9.4, color=MUT)
    ax.set_ylabel("自研本体程度（低 → 高）", fontsize=9.4, color=MUT)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    return save(fig, "fig_rel.png")


# ═══ 图4 四维雷达 ═══════════════════════════════════════════
def fig_radar():
    rows = D["score4"]
    cols = ["场景", "模型", "数据", "本体"]
    n = len(rows)
    fig, axes = plt.subplots(2, 3, figsize=(12.6, 7.0), subplot_kw=dict(polar=True))
    fig.subplots_adjust(left=0.055, right=0.945, top=0.905, bottom=0.075, hspace=0.58, wspace=0.46)
    ang = np.linspace(0, 2 * np.pi, len(cols), endpoint=False).tolist()
    ang += ang[:1]
    C4 = {"comp": RED, "partner": GRN, "watch": "#9AA3AF", "me": ME}
    for k, r in enumerate(rows):
        ax = axes[k // 3][k % 3]
        v = list(r[1:5]) + [r[1]]
        ax.plot(ang, v, color=C4[r[5]], lw=2)
        ax.fill(ang, v, color=C4[r[5]], alpha=0.22)
        ax.set_xticks(ang[:-1]); ax.set_xticklabels(cols, fontsize=8.8)
        ax.tick_params(axis="x", pad=1.5)
        ax.set_ylim(0, 10); ax.set_yticks([3, 6, 9]); ax.set_yticklabels([], fontsize=7)
        ax.grid(color=GRID)
        ax.set_title(r[0], fontsize=10.2, weight="bold", color=C4[r[5]], pad=9)
    for k in range(n, 6):
        axes[k // 3][k % 3].axis("off")
    return save(fig, "fig_radar.png", tight=False)


# ═══ 图5 模型架构分布 ═══════════════════════════════════════
def fig_arch():
    rows = D["model20"]
    cats = {"VLA": [], "JEPA": [], "World": [], "触觉": [], "数据": [], "控制器": []}
    for r in rows:
        t = r[9]
        if "JEPA" in t: cats["JEPA"].append(r[1])
        elif "触觉" in t or "VTLA" in t: cats["触觉"].append(r[1])
        elif "数据" in t: cats["数据"].append(r[1])
        elif "控制器" in t or "原子技能" in t: cats["控制器"].append(r[1])
        elif "VLA" in t: cats["VLA"].append(r[1])          # 「VLA + World」归 VLA 系
        elif ("World" in t or "预测" in t or "物理反演" in t
              or "重建" in t): cats["World"].append(r[1])
        else: cats["控制器"].append(r[1])
    order = ["World", "VLA", "JEPA", "触觉", "控制器", "数据"]
    vals = [len(cats[k]) for k in order]
    COL2 = ["#1F9D8F", CN, "#7B3FF2", GRN, "#9AA3AF", OS]
    fig, ax = plt.subplots(figsize=(12.4, 4.2))
    fig.subplots_adjust(left=0.06, right=0.985, top=0.86, bottom=0.30)
    bars = ax.bar(order, vals, color=COL2, width=0.56)
    for b, v, k in zip(bars, vals, order):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.12, str(v), ha="center", fontsize=13,
                weight="bold", color=INK)
    ax.set_ylim(0, max(vals) + 1.2)
    ax.set_ylabel("家数", fontsize=9.5, color=MUT)
    ax.set_title("20 家模型/数据公司的技术路线分布（按公开可查的架构标签分类；"
                 "每家的标签见第 26–27 页表格第 4 列）", fontsize=10.5, pad=10)
    ax.grid(axis="y", color=GRID); ax.set_axisbelow(True)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    return save(fig, "fig_arch.png")


# ═══ 图6 开源可验证性阶梯 ═══════════════════════════════════
def fig_open():
    rows = D["model20"]
    L1, L2, L3 = [], [], []
    for r in rows:
        o = r[2]
        neg = ("未明确" in o or "无开源" in o or "不开源" in o
               or "闭源" in o or "未开源" in o or "非开源" in o)
        if neg:
            L3.append(r[1])
        elif "数据集" in o and "权重" not in o:
            L2.append(r[1])          # 只开数据，模型仍闭源
        elif "开源" in o:
            L1.append(r[1])
        else:
            L2.append(r[1])
    fig, ax = plt.subplots(figsize=(12.4, 4.4))
    fig.subplots_adjust(left=0.04, right=0.985, top=0.88, bottom=0.10)
    ax.axis("off")
    tiers = [("权重 + 代码可下载（可自证）", L1, GRN),
             ("只开数据 / 部分开源（半可证）", L2, OS),
             ("未明确或不开放（不可验证）", L3, "#9AA3AF")]
    for i, (t, names, c) in enumerate(tiers):
        y = 0.80 - i * 0.30
        ax.add_patch(Rectangle((0.01, y - 0.115), 0.98, 0.20, facecolor=c, alpha=0.10,
                               edgecolor=c, lw=1.4, transform=ax.transAxes))
        ax.text(0.025, y + 0.035, "%s   %d 家" % (t, len(names)), fontsize=11.5, weight="bold",
                color=c, transform=ax.transAxes)
        ax.text(0.025, y - 0.055, " · ".join(names), fontsize=9.2, color=INK,
                transform=ax.transAxes, wrap=True)
    ax.set_title("三档：能自证 / 半可证 / 不可验证（合作前按这个顺序筛）",
                 fontsize=11.5, pad=8)
    return save(fig, "fig_open.png")


# ═══ 图7 轮式 15 家 × 数据资产 ══════════════════════════════
def fig_wheel():
    rows = D["wheel15"]
    fig, ax = plt.subplots(figsize=(12.4, 4.6))
    fig.subplots_adjust(left=0.13, right=0.985, top=0.86, bottom=0.20)
    y = np.arange(len(rows))[::-1]
    score, txt = [], []
    for r in rows:
        d = r[4]
        if "未披露" in d or "未公开" in d:
            score.append(1); txt.append("未披露")
        elif "未开源" in d or "非开源" in d:
            score.append(2); txt.append("有但拿不到")
        elif "开源" in d or "TB" in d or "百亿" in d or "500+" in d:
            score.append(3); txt.append("可自证")
        else:
            score.append(2); txt.append("有但拿不到")
    C3 = {3: GRN, 2: OS, 1: "#C9CED6"}
    ax.barh(y, score, color=[C3[s] for s in score], height=0.6)
    for i, r in enumerate(rows):
        ax.text(score[i] + 0.06, y[i], txt[i] + "　" + r[4][:34], va="center", fontsize=7.6,
                color=INK)
    ax.set_yticks(y); ax.set_yticklabels([r[1] for r in rows], fontsize=8.6)
    ax.set_xlim(0, 4.6); ax.set_xticks([1, 2, 3])
    ax.set_xticklabels(["未披露", "有但未开源", "开源自证"], fontsize=8.6)
    ax.set_title("轮式 15 家的数据资产强度（绿=能自证，橙=有但拿不到，灰=未披露）", fontsize=11, pad=8)
    ax.grid(axis="x", color=GRID); ax.set_axisbelow(True)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    return save(fig, "fig_wheel.png")


# ═══ 图8 混合 15 家数据痕迹 ═════════════════════════════════
def fig_hybrid():
    rows = D["hybrid15"]
    ng = [r[1] for r in rows if r[6]]
    nb = [r[1] for r in rows if not r[6]]
    fig, ax = plt.subplots(figsize=(12.4, 2.35))
    fig.subplots_adjust(left=0.03, right=0.99, top=0.80, bottom=0.08)
    ax.axis("off")
    ax.add_patch(Rectangle((0.01, 0.52), 0.98, 0.34, facecolor=GRN, alpha=0.10,
                           edgecolor=GRN, lw=1.4, transform=ax.transAxes))
    ax.text(0.025, 0.76, "有数据痕迹 / 模型合作     %d 家" % len(ng), fontsize=11.5,
            weight="bold", color=GRN, transform=ax.transAxes)
    ax.text(0.025, 0.60, " · ".join(ng), fontsize=9.2, color=INK, transform=ax.transAxes)
    ax.add_patch(Rectangle((0.01, 0.08), 0.98, 0.34, facecolor="#9AA3AF", alpha=0.12,
                           edgecolor="#9AA3AF", lw=1.4, transform=ax.transAxes))
    ax.text(0.025, 0.32, "模型或数据写「未公开」    %d 家" % len(nb), fontsize=11.5,
            weight="bold", color="#5C636E", transform=ax.transAxes)
    ax.text(0.025, 0.16, " · ".join(nb), fontsize=9.2, color=INK, transform=ax.transAxes)
    ax.set_title("混合形态（AMR+协作臂）：15 家里 10 家能拿出数据或模型合作痕迹", fontsize=12, pad=8)
    return save(fig, "fig_hybrid.png")


# ═══ 图9 我们的投入-覆盖（沿用实测）═══════════════════════════
def fig_invest():
    x = [0, 4, 8, 12, 16, 17]
    y = [38.1, 33.3, 69.4, 79.2, 93.1, 100.0]
    fig, ax = plt.subplots(figsize=(7.4, 4.5))
    fig.subplots_adjust(left=0.135, right=0.965, top=0.90, bottom=0.215)
    ax.plot(x, y, "-o", color=ME, lw=2.4, ms=7, zorder=4)
    ax.axhline(100, color=GRN, lw=1.1, ls=(0, (4, 3)))
    ax.text(0.15, 104.5, "9/9 场景全覆盖", fontsize=9.2, color=GRN)
    SH = {4: "只做 4 条 → 33%", 8: "8 条插拔（6 纯软件）→ 69%"}
    OF = {4: (6, -19, "left"), 8: (-7, -21, "left")}
    for xi, yi in zip(x, y):
        if xi in SH:
            dx, dy, ha = OF[xi]
            ax.annotate(SH[xi], (xi, yi), textcoords="offset points", xytext=(dx, dy),
                        fontsize=9.2, color=INK, ha=ha, va="center",
                        bbox=dict(boxstyle="round,pad=0.22", facecolor="white", edgecolor="none",
                                  alpha=0.9))
    ax.set_xlabel("投入（能力条数，工程量口径）", fontsize=9.4, color=MUT)
    ax.set_ylabel("元任务覆盖率（%）", fontsize=9.4, color=MUT)
    ax.set_ylim(0, 118); ax.set_xlim(-0.6, 18.2)
    ax.grid(color=GRID); ax.set_axisbelow(True)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    return save(fig, "fig_invest.png")


if __name__ == "__main__":
    for f in (fig_g10, fig_d20, fig_rel, fig_radar, fig_arch, fig_open, fig_wheel,
              fig_hybrid, fig_invest):
        f()
