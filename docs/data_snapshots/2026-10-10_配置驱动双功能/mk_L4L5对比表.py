# -*- coding: utf-8 -*-
"""L4/L5 层 配置对比 + 实测对比 → PNG (手机可读)。"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

FW_C = {  # 插拔 配置值 (真源 config/ss_task_binding.json)
    "阶段链": "13 段 (接近→…→插入→拔出→AOI转移→AOI检测→回程→放下→完成)",
    "工序": "取料→扫码→翻转→对位→插入→异步测试→拔出→AOI飞拍→分拣 (9)",
    "公差": "单边 ≤1.000mm / yaw ≤1.00°",
    "力上限指令": "5.0N (来自 ins.force_ctrl「力峰≤5N」)",
    "节拍/速度指令": "单颗CT ≤3.15s → 速度指令 ×1.00",
    "目标数值": "ins.depth=35.0mm (插入深度目标)",
    "档位": "L4-INTACT 开 · L4-DiT 开 · 流形yaw 开 · L3全链 开 · 引擎快演 关",
}
TR_C = {
    "阶段链": "8 段 (接近→…→转移→放入→完成)",
    "工序": "定位识别→取件→转运对位→放入→判态循环 (5)",
    "公差": "单边 ≤1.000mm / yaw ≤1.00°",
    "力上限指令": "3.0N (place.down_force_max 为文本 → 默认 3.0N)",
    "节拍/速度指令": "单颗CT ≤3.15s → 速度指令 ×1.00",
    "目标数值": "真空建立 200ms · 保持 5s · 无插入深度目标",
    "档位": "L4-INTACT 关 · L4-DiT 关 · 流形yaw 关 · L3全链 关 · 引擎快演 开",
}
ROWS = [("L5 阶段链", "阶段链"), ("L5 工序(任务书)", "工序"), ("L5 公差", "公差"),
        ("L5 力指令", "力上限指令"), ("L5 节拍→速度", "节拍/速度指令"), ("L5 目标数值", "目标数值"),
        ("L4 档位", "档位")]

MEAS = [
    # (列, 帧, 限速, 力否决, 超真机力上限帧, INTACT平滑, DiT精炼, 步数, 结果)
    ("插拔·档位开(现状)", 678, 398, 16, 24, 91, 678, 678, "完成 success=True ✅"),
    ("插拔·档位关(A/B)", 698, 438, 29, 45, 0, 0, 698, "完成 success=True"),
    ("摆盘·档位关(现状)", 852, 0, 0, 0, 0, 0, 852, "合格 0.34mm ✅"),
    ("摆盘·档位开(A/B)", 872, 0, 0, 0, 374, 872, 872, "不合格 1.15mm ⚠️"),
]

fig = plt.figure(figsize=(13.2, 10.2), dpi=125)
fig.patch.set_facecolor("white")

fig.text(0.5, 0.975, "Z-MAX · L4/L5 进控制逻辑 —— 配置切换对比 (真源 config/ss_task_binding.json)",
         ha="center", fontsize=15, weight="bold")
fig.text(0.5, 0.945, "L5 下指令 = 任务意图→阶段/公差/力上限/节拍 · L4 保安全 = 每帧限速·力否决·z下限·档位介入方式",
         ha="center", fontsize=10.5, color="#444")

# ── 块1: 配置对比 ──
ax = fig.add_axes([0.03, 0.50, 0.94, 0.41]); ax.axis("off")
tb = ax.table(cellText=[[lbl, FW_C[k], TR_C[k]] for lbl, k in ROWS],
              colLabels=["层 / 配置项", "TASK-01-FW 插拔", "TASK-06-TRAY 摆盘"],
              cellLoc="left", colWidths=[0.17, 0.42, 0.41], loc="center")
tb.auto_set_font_size(False); tb.set_fontsize(9.6); tb.scale(1, 1.85)
for (r, c), cell in tb.get_celld().items():
    cell.set_text_props(wrap=True)
    if r == 0:
        cell.set_facecolor("#2d4a7a"); cell.set_text_props(color="white", weight="bold")
    elif c == 0:
        cell.set_facecolor("#eef2f8"); cell.set_text_props(weight="bold")
    else:
        cell.set_facecolor("#fbfbfd" if r % 2 else "#f4f6fa")
    if r and c == 2 and ROWS[r - 1][0].startswith("L4"):
        cell.set_facecolor("#fff4e5")
    if r and c == 1 and ROWS[r - 1][0].startswith("L4"):
        cell.set_facecolor("#e8f5e9")

# ── 块2: 实测 L4 行为 ──
ax2 = fig.add_axes([0.03, 0.14, 0.94, 0.30]); ax2.axis("off")
hd = ["实测 (同一条链, 只切配置档位)", "帧", "限速", "力否决(仿真尺度)", "超真机力上限帧", "INTACT平滑", "DiT精炼", "步数", "结果"]
tb2 = ax2.table(cellText=[list(m) for m in MEAS], colLabels=hd,
                cellLoc="center", colWidths=[0.235, 0.06, 0.065, 0.115, 0.135, 0.09, 0.085, 0.07, 0.155], loc="center")
tb2.auto_set_font_size(False); tb2.set_fontsize(9.0); tb2.scale(1, 2.0)
for (r, c), cell in tb2.get_celld().items():
    cell.set_text_props(wrap=True)
    if r == 0:
        cell.set_facecolor("#4a4a6a"); cell.set_text_props(color="white", weight="bold")
    else:
        good = "✅" in str(MEAS[r - 1][8])
        cell.set_facecolor("#f6fbf6" if good else "#fff2f2")
        if c == 0:
            cell.set_text_props(weight="bold", ha="left")
        if c == 8:
            cell.set_text_props(color=("#1b7f3b" if good else "#c0392b"), weight="bold")
ax2.text(0.0, -0.10,
         "结论 (实测两向): ①插拔开 L4 档位有利 — 力否决 16 vs 29、超真机力上限帧 24 vs 45、步数 678 vs 698;\n"
         "②摆盘开 L4 档位有害 — 一阶低通滞后末端对位, 精度 0.34mm → 1.15mm 掉出 ≤1mm 公差 (不合格)。\n"
         "⇒ 同一套 L4 档位, 由配置按任务切: 插拔开 / 摆盘关 (现状配置恰好如此)。下一步: 末端对位阶段自动关平滑。",
         fontsize=9.6, color="#333", va="top", linespacing=1.6)

fig.savefig("/tmp/shots/l45_switch_table.png", facecolor="white", bbox_inches="tight")
print("→ /tmp/shots/l45_switch_table.png")
