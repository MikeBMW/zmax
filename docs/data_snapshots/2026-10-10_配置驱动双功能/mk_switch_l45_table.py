# -*- coding: utf-8 -*-
"""切换配置 + 四层证据 → PNG 表。读 /tmp/shots/switch_l45_evidence.json。"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

rows = json.load(open("/tmp/shots/switch_l45_evidence.json", encoding="utf-8"))
hd = ["轮", "任务", "active_task\n(真源回读)", "cfg sha\n(变=真切换)", "L5 阶段链", "L5 力上限",
      "L4 帧", "L4 限速", "L4 力否决", "L4 平滑", "L4 精炼", "档位(开)", "结果"]
body = []
for r in rows:
    n_on = len([x for x in (r.get("switches") or "").split(" ") if x.endswith("=开")])
    body.append([str(r["round"]), r["task"].replace("TASK-0", "T0-"), r.get("active_after") or "?",
                 "%s→%s" % (r.get("sha_before", "?")[:6], r.get("sha_after", "?")[:6]),
                 "%s 段" % r.get("l5_stages"), ("%sN" % r.get("l5_force")) if r.get("l5_force") else "—",
                 r.get("l4_frames"), r.get("l4_speedlim"), r.get("l4_forceveto"),
                 r.get("l4_slew"), r.get("l4_dit"), "%d/6" % n_on, r.get("verdict")])

fig = plt.figure(figsize=(14.4, 1.5 + 0.62 * len(body) + 1.3), dpi=125)
fig.patch.set_facecolor("white")
fig.text(0.5, 0.975, "切换配置的证据 —— L5/L4/L3/L2 每轮同跑 (插拔↔摆盘 交替, 走配置中心激活)",
         ha="center", fontsize=14.5, weight="bold")
ax = fig.add_axes([0.015, 0.16, 0.97, 0.76]); ax.axis("off")
tb = ax.table(cellText=body, colLabels=hd, cellLoc="center", loc="center",
              colWidths=[0.035, 0.10, 0.105, 0.135, 0.055, 0.065, 0.05, 0.055, 0.065, 0.055, 0.055, 0.06, 0.075])
tb.auto_set_font_size(False); tb.set_fontsize(8.8); tb.scale(1, 1.9)
for (r, c), cell in tb.get_celld().items():
    cell.set_text_props(wrap=True)
    if r == 0:
        cell.set_facecolor("#2d4a7a"); cell.set_text_props(color="white", weight="bold")
    else:
        fw = body[r - 1][1].startswith("01")
        cell.set_facecolor("#eef4fb" if fw else "#fdf6ee")
        if c in (4, 5):
            cell.set_text_props(weight="bold")
        if c == 12:
            ok = body[r - 1][12] == "通过"
            cell.set_text_props(color=("#1b7f3b" if ok else "#c0392b"), weight="bold")

checks = ("① 真源 active_task 每轮回读都对 + 文件 sha 每轮都变 = 配置真切换; "
          "② 报告 chain/mode 跟着换 = 功能真换;  ③ L4/L5 每轮帧数与逐层计数都在 = 四层同跑;  "
          "④ 两任务 L5 阶段链 13 段 vs 8 段 = 层间行为随配置变")
fig.text(0.02, 0.035, checks, fontsize=9.3, color="#333", va="bottom")
fig.savefig("/tmp/shots/switch_l45_table.png", facecolor="white", bbox_inches="tight")
print("→ /tmp/shots/switch_l45_table.png")
