#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真鼠标验证: 在画布(状态空间工程)页面上点「🧠 模型引擎」按钮, 看独立窗口是否真的弹出来。

不预先固定坐标: 按按钮文字色 #c9a0ff 在截图里聚类 (配置中心 + 模型引擎 两个紫钮), 取**最右**那个 = 模型引擎。
用法: python tools/click_canvas_me_button.py <shot.png>   → 打印点击坐标 (再由 xdotool 点)
"""
import sys

from PIL import Image

shot = sys.argv[1]
im = Image.open(shot).convert("RGB")
px = im.load()
W, H = im.size

hits = []
for y in range(0, min(H, 200)):                      # 工具栏在第一排 (y<200)
    for x in range(0, W):
        r, g, b = px[x, y]
        if abs(r - 0xC9) < 28 and abs(g - 0xA0) < 28 and abs(b - 0xFF) < 28:
            hits.append((x, y))
print("紫色按钮像素数:", len(hits))
if not hits:
    sys.exit(1)

# 横向聚类 (间隙 > 40px 视为两个按钮)
hits.sort()
groups, cur = [], [hits[0]]
for p in hits[1:]:
    if p[0] - cur[-1][0] > 40:
        groups.append(cur)
        cur = [p]
    else:
        cur.append(p)
groups.append(cur)
for i, g in enumerate(groups):
    xs = [p[0] for p in g]
    ys = [p[1] for p in g]
    print("  紫钮#%d: x %d..%d (中心 %d) y %d..%d (中心 %d)" % (i, min(xs), max(xs),
          (min(xs) + max(xs)) // 2, min(ys), max(ys), (min(ys) + max(ys)) // 2))
g = groups[-1]                                        # 最右 = 模型引擎
cx = (min(p[0] for p in g) + max(p[0] for p in g)) // 2
cy = (min(p[1] for p in g) + max(p[1] for p in g)) // 2
print("CLICK %d %d" % (cx, cy))
