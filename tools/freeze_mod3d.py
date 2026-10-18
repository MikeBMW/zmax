#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""freeze_mod3d.py —— 把光模块 3D 标注框"钉死"在画面某个位置(老倪 2026-10-18: 「绿色标注框，在画面中的位置，保持不动都可以」)

为什么可以钉死: 相机装在手爪上, 模块被夹爪夹住 ⇒ 两者是刚体关系, 模块在画面里的像素位置本来就该是常量。
现场要的是"别抖、别变长", 不是"每帧重新追"。

用法:
  ... freeze_mod3d.py --freeze          # 把当前结果钉住(写入 /dev/shm/mod3_freeze.json)
  ... freeze_mod3d.py --freeze --box 314,0,347,62   # 直接指定像素框钉住
  ... freeze_mod3d.py --status          # 看当前钉住的是什么
  ... freeze_mod3d.py --clear           # 解除, 回到实时跟踪
"""
from __future__ import annotations

import argparse
import json
import os
import time

SRC = "/dev/shm/mod3_latest.json"
FRZ = "/dev/shm/mod3_freeze.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--box", default="", help="x1,y1,x2,y2 像素")
    a = ap.parse_args()
    if a.clear:
        if os.path.exists(FRZ):
            os.remove(FRZ)
        print("已解除钉住")
        return 0
    if a.status or not a.freeze:
        if os.path.exists(FRZ):
            d = json.load(open(FRZ, encoding="utf-8"))
            print("钉住中: 框 %s · dims %s · d %.1fmm · 钉于 %s" % (
                [round(v) for v in d["box2d"]], d.get("dims_mm"), d.get("dist_mm", 0),
                time.strftime("%H:%M:%S", time.localtime(d.get("frozen_at", 0)))))
        else:
            print("未钉住(实时跟踪)")
        return 0
    d = json.load(open(SRC, encoding="utf-8"))
    if not d.get("ok"):
        print("当前没有有效结果, 不钉")
        return 2
    if a.box:
        bx = [float(v) for v in a.box.split(",")]
        sc_x = (bx[2] - bx[0]) / max(1e-6, (d["box2d"][2] - d["box2d"][0]))
        sc_y = (bx[3] - bx[1]) / max(1e-6, (d["box2d"][3] - d["box2d"][1]))
        cx0 = (d["box2d"][0] + d["box2d"][2]) / 2.0
        cy0 = (d["box2d"][1] + d["box2d"][3]) / 2.0
        cx1 = (bx[0] + bx[2]) / 2.0
        cy1 = (bx[1] + bx[3]) / 2.0
        d["corners_px"] = [[cx1 + (p[0] - cx0) * sc_x, cy1 + (p[1] - cy0) * sc_y] for p in d["corners_px"]]
        d["box2d"] = bx
    d["frozen_at"] = time.time()
    d["frozen_note"] = "老倪要求: 绿框在画面位置保持不动(相机在腕上, 模块随爪刚性)"
    json.dump(d, open(FRZ, "w", encoding="utf-8"), ensure_ascii=False)
    print("已钉住: 框 %s · dims %s" % ([round(v) for v in d["box2d"]], d.get("dims_mm")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
