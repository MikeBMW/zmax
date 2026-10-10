# -*- coding: utf-8 -*-
"""四层同跑证据: 从同一条 episode 的 trace 逐帧画出 L5/L4/L3/L2 各自的活跃痕迹。

用法: python mk_4layer_panel.py <trace.npz> <标题> <输出.png>
"""
import sys

import matplotlib
matplotlib.use("Agg")
import numpy as np
import matplotlib.pyplot as plt

matplotlib.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

path, title, out = sys.argv[1], sys.argv[2], sys.argv[3]
z = np.load(path, allow_pickle=True)
t = np.asarray(z["t"], dtype=float)
n = len(t)


def arr(k, default=0.0):
    if k in z.keys():
        a = np.asarray(z[k], dtype=float).ravel()
        return a if len(a) == n else np.full(n, default)
    return np.full(n, default)


stage = np.asarray(z["stage"]).astype(str) if "stage" in z.keys() else np.array(["?"] * n)
l4_du = arr("l4_du")
l4_f = arr("l4_f")
u_ff = arr("u_ff")
u_sat = arr("u_sat")
res = arr("residual")
grip = arr("gripper")
lat = np.asarray(z["latent_vec"], dtype=float) if "latent_vec" in z.keys() else None

fig, axes = plt.subplots(4, 1, figsize=(13.6, 9.6), sharex=True,
                         gridspec_kw=dict(height_ratios=[1.05, 1.0, 1.0, 1.0]))
fig.patch.set_facecolor("white")
fig.suptitle(title, fontsize=14.5, weight="bold", y=0.985)

# ── L5: 阶段时间线 (每帧所处阶段 = L5 下的目标切换点) ──
ax = axes[0]
uniq = [s for s in dict.fromkeys(stage.tolist())]
codes = np.array([uniq.index(s) for s in stage])
ax.step(t, codes, where="post", color="#1f6fb2", lw=1.6)
ax.set_yticks(range(len(uniq)))
ax.set_yticklabels([s.split()[0][:6] for s in uniq], fontsize=7.5)
ax.set_title("L5 下指令 — 阶段链推进 (每帧所处阶段; 段数 %d)" % len(uniq), fontsize=10.5, loc="left")
ax.grid(alpha=0.25)
# 阶段切换点竖线
ch = np.where(np.diff(codes) != 0)[0]
for i in ch:
    ax.axvline(t[i], color="#bbb", lw=0.6, ls=":")

# ── L4: 逐帧介入量 + 力 ──
ax = axes[1]
ax.fill_between(t, 0, l4_du, color="#e07b39", alpha=0.75, lw=0)
ax.set_ylabel("L4 介入量 |Δu|", fontsize=9, color="#b35c14")
ax.set_title("L4 保安全 — 逐帧介入 (非零 %d/%d 帧, 峰值 %.4f) · 力曲线为辅轴"
             % (int((l4_du > 1e-9).sum()), n, l4_du.max()), fontsize=10.5, loc="left")
ax.grid(alpha=0.25)
ax2 = ax.twinx()
ax2.plot(t, l4_f, color="#7d3c98", lw=0.9, alpha=0.75)
ax2.set_ylabel("接触力 (N)", fontsize=9, color="#7d3c98")
veto = np.asarray(z["l4_veto"], dtype=bool) if "l4_veto" in z.keys() else np.zeros(n, dtype=bool)
if veto.any():
    ax2.scatter(t[veto], l4_f[veto], s=15, color="red", zorder=5, label="力否决帧 %d" % int(veto.sum()))
    ax2.legend(loc="upper right", fontsize=8)

# ── L3: 世界模型残差 ──
ax = axes[2]
ax.plot(t, res, color="#1e8449", lw=1.0)
ax.set_ylabel("L3 世界模型残差", fontsize=9)
ax.set_title("L3 编流程 — 世界模型先验/残差 (均值 %.5f, 非零 %d 帧)" % (res.mean(), int((np.abs(res) > 1e-12).sum())),
             fontsize=10.5, loc="left")
ax.grid(alpha=0.25)

# ── L2: 前馈 vs 下发 ──
ax = axes[3]
ax.plot(t, u_ff, color="#2c3e50", lw=1.0, label="L2 前馈 |u_ff|")
ax.plot(t, u_sat, color="#c0392b", lw=1.0, alpha=0.85, label="执行层 |u_exec|")
ax.set_xlabel("时间 (s)", fontsize=9)
ax.set_ylabel("指令幅值", fontsize=9)
ax.set_title("L2 操作 — 前馈指令 vs 最终下发 (非零 %d/%d 帧)" % (int((u_ff > 1e-9).sum()), n), fontsize=10.5, loc="left")
ax.legend(fontsize=8.5, loc="upper right")
ax.grid(alpha=0.25)

fig.tight_layout(rect=(0, 0, 1, 0.965))
fig.savefig(out, facecolor="white", dpi=115)
print("→ %s" % out)
print("  四层逐帧: 帧数 %d | L5 阶段 %d 段 | L4 介入帧 %d (峰 %.4f) 力否决 %d | L3 残差非零 %d | L2 前馈非零 %d"
      % (n, len(uniq), int((l4_du > 1e-9).sum()), l4_du.max(), int(veto.sum()),
         int((np.abs(res) > 1e-12).sum()), int((u_ff > 1e-9).sum())))
