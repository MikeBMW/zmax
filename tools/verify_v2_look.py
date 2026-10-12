#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""3D 场景取证 (2026-10-12 老倪两条焦点):
   ① 插拔: 夹具(红盒) / 孔口(深方口) / 插入终点(绿框) 三者的**像素级相对位置**
   ② 摆盘: 放好第 1 颗后, tray盘 槽位**是否留下件** + 件位置是否与 episode 真值一致
只读 + 截图 + 量像素, 不动任何工程状态。
"""
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np

REPO = "/home/ubuntu/zmax"
PY = os.path.join(REPO, "gui-venv311/bin/python")
DISP = ":0"


def sh(cmd, timeout=60):
    e = dict(os.environ)
    e["DISPLAY"] = DISP
    try:
        return subprocess.run(cmd, shell=True, cwd=REPO, env=e, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.decode("utf-8", "ignore")
    except Exception as ex:                                                     # noqa: BLE001
        return "ERR %r" % (ex,)


def scene(task):
    sh("%s tools/ss_task_bind.py --activate %s >/dev/null 2>&1" % (PY, task))
    out = sh("%s tools/ss_scene_switch.py --task %s 2>&1" % (PY, task))
    return out.strip().splitlines()[-1] if out.strip() else ""


def shot(path):
    wl = sh("wmctrl -l")
    wid = ""
    for ln in wl.splitlines():
        if "3D场景" in ln:
            wid = ln.split()[0]
            break
    if not wid:
        print("   ⚠️ 3D 窗不在, 无法抓图")
        return False
    sh("xdotool windowactivate --sync %s" % wid)
    time.sleep(1.5)
    sh("scrot -u %s" % path)
    return os.path.exists(path)


def masks(p):
    im = cv2.imread(p)
    if im is None:
        return None, None, None, None
    b, g, r = im[:, :, 0].astype(int), im[:, :, 1].astype(int), im[:, :, 2].astype(int)
    return im, (r, g, b), None, None


def blk(r, g, b, cond, tag, minpix=60):
    ys, xs = np.where(cond)
    if len(xs) < minpix:
        print("   %-16s 无 (%d px)" % (tag, len(xs)))
        return None
    c = (xs.mean(), ys.mean())
    print("   %-16s %5d px  x[%d..%d] y[%d..%d]  中心(%.0f,%.0f)" %
          (tag, len(xs), xs.min(), xs.max(), ys.min(), ys.max(), c[0], c[1]))
    return (c[0], c[1], xs.min(), xs.max(), ys.min(), ys.max(), len(xs))


print("═══ ① 插拔场景: 夹具 / 孔口 / 插入终点 ═══")
print("   切场景:", scene("TASK-01-FW"))
time.sleep(12)
if shot("/tmp/v2_fw.png"):
    im, (r, g, b), _, _ = masks("/tmp/v2_fw.png")
    print("   图 %dx%d" % (im.shape[1], im.shape[0]))
    box = blk(r, g, b, (r > 100) & (r < 215) & (g < 75) & (b < 65) & (r - g > 55), "红盒(夹具/孔座)")
    mouth = blk(r, g, b, (r < 26) & (g < 26) & (b < 34) & (abs(r - g) < 12), "深方口(孔口)")
    goal = blk(r, g, b, (abs(r - 51) < 55) & (abs(g - 242) < 45) & (abs(b - 140) < 60) & (g - b > 55), "绿框(插入终点)")
    if box and goal:
        print("   ⇒ 夹具中心 → 插入终点: Δx=%+d px  Δy=%+d px   (盒宽 %d px)" %
              (goal[0] - box[0], goal[1] - box[1], box[3] - box[2]))
    if box and mouth:
        print("   ⇒ 夹具中心 → 孔口    : Δx=%+d px  Δy=%+d px" % (mouth[0] - box[0], mouth[1] - box[1]))
    if box and goal and mouth:
        print("   ⇒ 孔口 → 插入终点     : Δx=%+d px  Δy=%+d px  (≈0 ⇒ 插入终点正好在孔口内侧)" %
              (goal[0] - mouth[0], goal[1] - mouth[1]))

print()
print("═══ ② 摆盘场景: 放好第 1 颗后 tray盘 槽位是否留件 ═══")
print("   切场景:", scene("TASK-06-TRAY"))
hit = False
for i in range(70):
    try:
        d = json.load(open(os.path.join(REPO, "zmax_data/ss_live/trace_live.json")))
        st = str(d.get("阶段", ""))
    except Exception:                                                           # noqa: BLE001
        st = ""
    if "完成" in st:
        print("   命中: 阶段=%s (第 %ds)" % (st, i * 2))
        hit = True
        break
    time.sleep(2)
if not hit:
    print("   ⚠️ 等 140s 没等到 完成 阶段 (重放可能没在跑)")
if shot("/tmp/v2_tray.png"):
    im, (r, g, b), _, _ = masks("/tmp/v2_tray.png")
    W, H = im.shape[1], im.shape[0]
    print("   图 %dx%d" % (W, H))
    m = ((abs(r - 235) <= 45) & (abs(g - 189) <= 45) & (abs(b - 61) <= 45) & (abs(r - b) > 60)).astype(np.uint8)
    n, lab, stt, _ = cv2.connectedComponentsWithStats(m, 8)
    comps = sorted([(int(stt[k, 4]), int(stt[k, 2]), int(stt[k, 3]), int(stt[k, 0]), int(stt[k, 1]))
                    for k in range(1, n) if stt[k, 4] >= 200], reverse=True)
    print("   金色块(≥200px): %d 个" % len(comps))
    for a, w_, h_, x_, y_ in comps[:8]:
        side = "左半(tray盘侧)" if (x_ + w_ / 2.0) < W * 0.5 else "右半(料盘侧)"
        print("     面积%6d %3dx%-3d @(%4d,%4d)  %s  长宽比%.2f" % (a, w_, h_, x_, y_, side, max(w_, h_) / max(1, min(w_, h_))))

print()
print("═══ ③ 控制台日志 (新码生效证据) ═══")
log = sh("ls -t /tmp/studio_launch_*.log | head -1").strip()
print("   日志:", log)
for ln in sh("grep -aE '抓握偏移|自动关掉|按孔口重定位|已装载|跟随画布' %s | tail -8" % log).splitlines():
    print("   ", ln)
