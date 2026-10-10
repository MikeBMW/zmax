# -*- coding: utf-8 -*-
"""插拔(FW) vs 摆盘(TRAY) 切换项对比表 → PNG。"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

d = json.load(open("/home/ubuntu/zmax/config/ss_task_binding.json", encoding="utf-8"))
T = {t["task_id"]: t for t in d["tasks"]}
A, B = T["TASK-01-FW"], T["TASK-06-TRAY"]
ra = json.load(open("/home/ubuntu/zmax/reports/ss_task_run_TASK-01-FW_latest.json", encoding="utf-8"))
rb = json.load(open("/home/ubuntu/zmax/reports/ss_task_run_TASK-06-TRAY_latest.json", encoding="utf-8"))


def g(a):
    return " · ".join("%s=%s" % (k, v) for k, v in a.items())


rows = [
    ("功能模式 ss_mode ★", A["ss_mode"] + " (插拔)", B["ss_mode"] + " (摆盘取放)"),
    ("执行链 (由 mode 选)", "gen_ss_metaworld_episode.py", "gen_tray_place_video.py"),
    ("场景 scene_ref", A["scene_ref"], B["scene_ref"]),
    ("工艺类型 recipe_type", A["recipe_type"], B["recipe_type"]),
    ("工序 steps", " → ".join(s["name"] for s in A["steps"]),
     " → ".join(s["name"] for s in B["steps"])),
    ("工艺分段", "applies 8 段 (含「5 拔出/取回」)", "applies 7 段 · 排除「5 拔出/取回」"),
    ("L2 原子技能", "8 段: 接近→对位→下降→抓取→抬起→转移→插入→完成",
     "8 段: 接近→对位→下降→抓取→抬起→转移→放入→完成"),
    ("L3 阶段链", "13 段 (含 拔出/AOI转移/AOI检测/回程/放下)",
     "8 段 (放入=放下, 无拔出/AOI)"),
    ("六档位 run_cfg", "开 5 / 关 1 — 开: L3全链 · 流形yaw · L4-INTACT · L4-DiT · L2兼容 / 关: 引擎快演",
     "开 2 / 关 4 — 开: 引擎快演 · L2兼容 / 关: L3全链 · 流形yaw · L4-INTACT · L4-DiT"),
    ("参数覆盖 overrides", g(A["overrides"]), g(B["overrides"])),
    ("判据 targets", g(A["targets"]), g(B["targets"])),
    ("触发 trigger", A["trigger"], B["trigger"]),
    ("循环 loop", A["loop"], B["loop"]),
    ("工单规则 orders_rule", A["orders_rule"], B["orders_rule"]),
    ("启用节点 enabled_nodes", "52 个 (与摆盘完全相同)", "52 个 (与插拔完全相同)"),
    ("禁用节点 disabled_nodes", "— 无", "— 无"),
    ("站点 site / 安全 safety", "相同 (继承站点 Sys-0, 任务不可覆盖)", "相同 (继承站点 Sys-0)"),
]

fig, ax = plt.subplots(figsize=(15.5, 12.4), dpi=130)
ax.axis("off")
ax.set_title("Z-MAX 插拔 / 摆盘 —— 配置切换到底切了哪些参数\n"
             "真源 config/ss_task_binding.json (配置中心) · ★ = 直接决定跑哪条链的功能开关",
             fontsize=14, pad=18)
data = [[k, a, b] for k, a, b in rows]
tb = ax.table(cellText=data, colLabels=["配置项", "TASK-01-FW 插拔", "TASK-06-TRAY 摆盘"],
              colWidths=[0.17, 0.40, 0.40], loc="center", cellLoc="left")
tb.auto_set_font_size(False)
tb.set_fontsize(9.2)
tb.scale(1, 2.05)
for (i, j), c in tb.get_celld().items():
    c.set_edgecolor("#c9c9c9")
    if i == 0:
        c.set_facecolor("#1f6feb")
        c.set_text_props(color="white", weight="bold")
        continue
    key = data[i - 1][0]
    same = data[i - 1][1] == data[i - 1][2]
    if "启用节点" in key or "禁用节点" in key or "site" in key:
        c.set_facecolor("#fff6e0")          # 不随任务变 —— 诚实标注
    elif same:
        c.set_facecolor("#f2f7f2")
    elif i % 2 == 0:
        c.set_facecolor("#f7f9fc")
plt.text(0.5, 0.055,
         "不随任务切换的项 (黄底): 启用/禁用节点两边完全相同 (52 个) · 站点 site · 安全 safety 继承站点不可覆盖\n"
         "⇒ 切任务 = 切「功能模式 + 工序/分段 + 六档位 + 参数覆盖 + 判据」, 不是靠剪节点",
         ha="center", fontsize=10, color="#7a4b00")
plt.savefig("/tmp/shots/param_switch_table.png", bbox_inches="tight", facecolor="white")
print("→ /tmp/shots/param_switch_table.png")
