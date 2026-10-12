#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""孔口↔插入终点 对齐取证 (2026-10-12 老倪: 「夹具/孔座 与插入终点有横向偏差」)

判据用**唯一颜色**反查, 不再靠肉眼/松掩模:
  · 孔口亮青边框 (0.10,0.85,1.00)  → 画面里无他物用青色 ⇒ 唯一
  · 插入终点绿线框 (0.20,0.95,0.55) → 比绿色桌面(51,133,76)亮得多 ⇒ 用亮绿阈值区分
  · 夹具红盒 (栗色主体)  → 给出像素尺度 (mm/px) 与盒心, 把 Δpx 换算成 mm
"""
import os
import subprocess
import time

import cv2
import numpy as np

REPO = "/home/ubuntu/zmax"
PY = os.path.join(REPO, "gui-venv311/bin/python")


def sh(cmd, timeout=90):
    e = dict(os.environ)
    e["DISPLAY"] = ":0"
    return subprocess.run(cmd, shell=True, cwd=REPO, env=e, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.decode("utf-8", "ignore")


def comps(im, cond, tag, minpx=120, top=3):
    b, g, r = im[:, :, 0].astype(int), im[:, :, 1].astype(int), im[:, :, 2].astype(int)
    m = cond(r, g, b).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    cs = sorted([(int(st[i, 4]), int(st[i, 2]), int(st[i, 3]), int(st[i, 0]), int(st[i, 1]))
                 for i in range(1, n) if st[i, 4] >= minpx], reverse=True)
    print("   %-22s 连通块(≥%dpx)=%d" % (tag, minpx, len(cs)))
    for a, w, h, x, y in cs[:top]:
        print("      %8d px %4dx%-4d 中心(%.0f,%.0f)" % (a, w, h, x + w / 2, y + h / 2))
    if cs:
        a, w, h, x, y = cs[0]
        return (x + w / 2.0, y + h / 2.0, w, h, a)
    return None


print("── 切插拔 + 放大 3D 窗 ──")
sh("%s tools/ss_task_bind.py --activate TASK-01-FW >/dev/null 2>&1" % PY)
print("   ", sh("%s tools/ss_scene_switch.py --task TASK-01-FW 2>&1 | tail -1" % PY).strip())
time.sleep(12)
wl = sh("wmctrl -l")
wid = ""
for ln in wl.splitlines():
    if "3D场景" in ln:
        wid = ln.split()[0]
        break
sh("xdotool windowsize %s 2450 1520; xdotool windowmove %s 20 20" % (wid, wid))
time.sleep(3)
sh("xdotool windowactivate --sync %s" % wid)
time.sleep(2)
sh("scrot -u /tmp/v5_fw.png")
im = cv2.imread("/tmp/v5_fw.png")
if im is None:
    print("抓图失败")
    raise SystemExit(1)
print("── 量像素 (图 %dx%d) ──" % (im.shape[1], im.shape[0]))

box = comps(im, lambda r, g, b: (r > 30) & (r < 100) & (g > 6) & (g < 45) & (b < 36) & (r - g > 14),
            "夹具红盒(栗色主体)", 3000)
rim = comps(im, lambda r, g, b: (r < 120) & (g > 150) & (b > 180) & (b - r > 70),
            "孔口亮青边框", 60)
goal = comps(im, lambda r, g, b: (g > 200) & (r < 110) & (b > 90) & (b < 190) & (g - b > 60),
             "插入终点绿线框", 80)
mouth_dark = comps(im, lambda r, g, b: (r < 18) & (g < 16) & (b < 15), "孔口深色内芯", 500)

if box and rim and goal:
    pxmm = None
    bx, by, bw, bh, _ = box
    gx, gy = goal[0], goal[1]
    rx, ry = rim[0], rim[1]
    print("   ⇒ 孔口(青框) ↔ 插入终点(绿框): Δx=%+d px  Δy=%+d px" % (gx - rx, gy - ry))
    print("   ⇒ 夹具红盒宽 %d px (真实宽约 190mm ⇒ %.3f mm/px)" % (bw, 190.0 / bw))
    print("   ⇒ 换算: Δx=%+.1f mm  Δy=%+.1f mm" % ((gx - rx) * 190.0 / bw, (gy - ry) * 190.0 / bw))
    print("   ⇒ 夹具中心 ↔ 插入终点: Δx=%+d px Δy=%+d px (%.1f mm / %.1f mm)" %
          (gx - bx, gy - by, (gx - bx) * 190.0 / bw, (gy - by) * 190.0 / bw))
else:
    print("   ⚠️ 关键块没找到: 盒=%s 青框=%s 绿框=%s 深芯=%s" %
          (bool(box), bool(rim), bool(goal), bool(mouth_dark)))

print("── 日志 ──")
log = sh("ls -t /tmp/studio_launch_*.log | head -1").strip()
print("   ", log)
for ln in sh("grep -aE '孔口可见化|抓握偏移|按孔口重定位' %s | tail -5" % log).splitlines():
    print("   ", ln)
