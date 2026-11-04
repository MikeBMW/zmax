#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成白皮书图件: 节拍甘特图 (数据源 甘特_300UPH_数据源.json)"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
from matplotlib.patches import Patch                 # noqa: E402

SRC = "/home/ubuntu/zmax/docs/1-天枢-产品边界/deliverables/2-机器人方案/甘特_300UPH_数据源.json"
OUT = "/home/ubuntu/zmax/zmax_data/deliverables/20261103/img"
BG, FG, MUTED = "#0B1220", "#E8F1FF", "#93A9C9"
COLORS = {"insert": "#22D3EE", "pull": "#F59E0B", "aoi": "#34D399", "place": "#A78BFA"}
LABEL = {"insert": "右臂 · 补插新模块", "pull": "右臂 · 拔出", "aoi": "右臂 · AOI 五点", "place": "右臂 · 良品落盘"}


def gantt(d, fname, t0, t1, title, sub, show_dwell=True, tick=None, pieces=None):
    fig, ax = plt.subplots(figsize=(12.4, 5.6), dpi=150)
    fig.patch.set_facecolor(BG); ax.set_facecolor(BG)
    rows = ["insert", "pull", "aoi", "place"]
    ypos = {k: i for i, k in enumerate(rows)}
    for b in d["blocks"]:
        if b["t1"] < t0 or b["t0"] > t1:
            continue
        s, e = max(b["t0"], t0), min(b["t1"], t1)
        if e - s <= 0:
            continue
        ax.barh(ypos[b["kind"]], e - s, left=s, height=0.55,
                color=COLORS[b["kind"]], alpha=0.9, edgecolor="none")
    # 停留 dwell
    if show_dwell:
        for it in d["dwell"]["items"]:
            s, e = max(it["t0"], t0), min(it["t1"], t1)
            if e - s <= 0:
                continue
            ax.barh(4, e - s, left=s, height=0.42, color="#4B5B75", alpha=0.55,
                    hatch="//", edgecolor="#7C8CA8", linewidth=0)
    # 节拍线
    if tick:
        x = tick["start"]
        while x <= t1:
            ax.axvline(x, color="#F87171", lw=1.0, alpha=0.85, ls="-")
            x += tick["step"]
    ax.set_yticks(list(range(5)))
    ylabels = [LABEL[r] for r in rows] + (["模块孔内停留"] if show_dwell else [])
    ax.set_yticklabels(ylabels, color=FG, fontsize=10)
    ax.set_xlabel("时间 (s)", color=MUTED, fontsize=10)
    ax.tick_params(colors=MUTED, labelsize=9)
    for sp in ax.spines.values():
        sp.set_color("#273B59")
    ax.grid(axis="x", color="#1B2A42", lw=0.6)
    ax.set_xlim(t0, t1)
    ax.set_ylim(-0.6, 4.6 if show_dwell else 3.6)
    ax.set_title(title, color=FG, fontsize=13, loc="left", pad=12)
    fig.text(0.012, 0.015, sub, color=MUTED, fontsize=8.5)
    handles = [Patch(color=COLORS[k], label=LABEL[k]) for k in rows]
    if show_dwell:
        handles.append(Patch(facecolor="#4B5B75", hatch="//", edgecolor="#7C8CA8", label="模块孔内停留 (dwell)"))
    if tick:
        handles.append(Patch(color="#F87171", label=f"节拍线 {tick['step']:.3f} s/件"))
    ax.legend(handles=handles, loc="upper right", facecolor="#131F33", edgecolor="#273B59",
              labelcolor=FG, fontsize=8.5, ncol=1)
    if pieces:
        for p in pieces:
            ax.text(p["t"], -0.45, p["label"], color="#22D3EE", fontsize=8, rotation=0, ha="center")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path = os.path.join(OUT, fname)
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    print("SAVED", path, os.path.getsize(path) // 1024, "KB")


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    os.makedirs(OUT, exist_ok=True)
    r = d["round"]; lp = d["loop"]
    gantt(d, "gantt_round14.png", 0, r["total_s"] + 2,
          f"一轮 14 件 · {r['total_s']:.2f} s（含模块孔内停留）· {r['n_pieces']} 件 / {r['n_segs']} 段",
          "蓝=补插  橙=拔出  绿=AOI  紫=落盘  灰虚=孔内停留(dwell, 与其它件并行)   数据源: 甘特_300UPH_数据源.json",
          show_dwell=True)
    gantt(d, "gantt_steady.png", lp["base"], lp["base"] + lp["dur"],
          f"稳态循环放大 · {lp['dur']:.3f} s / {lp['mods']} 件 = {lp['tact']:.3f} s/件（{lp['uph']:.0f} 件/h）",
          f"窗口 = loop.ks={lp['ks']}；红线 = 每件 {lp['tact']:.3f} s 节拍线；dwell {d['dwell']['min_s']}~{d['dwell']['max_s']} s 与作业并行",
          show_dwell=True, tick={"start": lp["base"], "step": lp["tact"]})


if __name__ == "__main__":
    main()
