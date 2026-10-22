#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 判据: S³ 力场表盘「合」指针方向 == 太阳系地球那根 F合 箭头方向 (老倪 2026-10-22)。

真因 (2026-10-22 实测): `_proj` 的"近大远小"因子 sc = R·zoom·(1+0.10·z4) 会**变负**。
把长矢量 (力×像素长, 模长到 ~160) 直接投进去, z4 → -60 ⇒ 因子负 ⇒ 整根翻 180°;
而单位 q̂ 投进去 z4≈±1 不翻 ⇒ 同一个力在球上是这个方向, 在表盘上是反方向。

判据:
  D1 缩放不变: 同一方向, 矢量乘 1e-3 ~ 1e4 后屏幕角不许变 (≤0.5°) —— 旧的"先投影长矢量"必红
  D2 共用一条: 画箭头的函数与画表盘的函数都调 `_force_dir_screen` (源码级)
  D3 数据面同源: q̂ 矢量部与 F合 同向
  D4 按"旧口径(直接投影长矢量)"复算, 记录旧口径会翻多少度 (证据, 不作判据)
覆盖: 万有引力表 8 个阶段 × 6 个视角。
"""
import inspect
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DISPLAY", ":0")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "src")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from PyQt5.QtWidgets import QApplication                                  # noqa: E402

import orbital_arch as OA                                                 # noqa: E402

OA.OrbitalArchData._ui_run = (lambda self: (True, "judge: 在跑分支"))
PASS = FAIL = 0


def chk(tag, title, got, ok, expect=""):
    global PASS, FAIL
    PASS += bool(ok)
    FAIL += (not ok)
    print("%s %-4s %s" % ("✅" if ok else "❌", tag, title))
    print("        got=%s  expect=%s" % (str(got)[:320], str(expect)[:200]))


def _ang(dx, dy):
    return math.degrees(math.atan2(dy, dx)) % 360.0


def _diff(a, b):
    d = abs((a - b) % 360.0)
    return min(d, 360.0 - d)


def main():
    app = QApplication.instance() or QApplication(sys.argv)   # noqa: F841
    view = OA.OrbitalArchView(root=ROOT)
    import gravity_table as gt
    f = view.data._field()
    rows = [r for r in (f.rows or []) if (r.get("vec") and r.get("q"))]
    if not rows:
        print("❌ 万有引力表无可用行 —— 无法比对")
        return 2

    views = [("默认", view.yaw, view.pitch, view.zoom, False),
             ("yaw+0.6/pitch.35", 0.6, 0.35, 1.2, False),
             ("yaw-0.9/pitch-.4", -0.9, -0.40, 0.8, False),
             ("yaw1.7/pitch.55/zoom1.6", 1.7, 0.55, 1.6, False),
             ("yaw0/pitch0", 0.0, 0.0, 1.0, False),
             ("地球视角", 0.3, 0.20, 1.0, True)]
    scales = (1e-3, 0.01, 1.0, 100.0, 1e4)

    worst_scale, worst_old = 0.0, 0.0
    rows_bad, old_flips = [], []
    for r in rows:
        vec = [float(x) for x in r["vec"]]
        for nm, yaw, pitch, zoom, foc in views:
            view.yaw, view.pitch, view.zoom, view._focus = yaw, pitch, zoom, foc
            a0 = None
            for k in scales:
                ux, uy = view._force_dir_screen([x * k for x in vec])
                a = _ang(ux, uy)
                if a0 is None:
                    a0 = a
                d = _diff(a0, a)
                worst_scale = max(worst_scale, d)
                if d > 0.5:
                    rows_bad.append("%s @%s ×%.0e: %.1f° vs %.1f°" % (r.get("stage"), nm, k, a0, a))
            # 旧口径: 直接把 力×120px 投进去 (会翻 180°)
            ln = 120.0
            px, py, _ = view._proj(vec[0] * ln, vec[1] * ln, vec[2] * ln, 0.0, 0.0, 1.0)
            a_old = _ang(px, py)
            d_old = _diff(a_old, a0)
            worst_old = max(worst_old, d_old)
            if d_old > 90.0:
                old_flips.append("%s @%s: 旧 %.1f° / 新 %.1f° (翻 %s)"
                                 % (r.get("stage"), nm, a_old, a0, "180°" if d_old > 170 else "%.0f°" % d_old))

    chk("D1", "力箭头/表盘指针与矢量长度无关 (矢量 ×1e-3…×1e4 屏幕角不变)",
        "max 角差 %.2f°" % worst_scale, worst_scale <= 0.5, "≤0.5° (8 阶段 × 6 视角 × 5 尺度)")

    src_arrow = inspect.getsource(OA.OrbitalArchView._earth_force_arrows)
    src_panel = inspect.getsource(OA.OrbitalArchView._s3_panel)
    both = ("_force_dir_screen" in src_arrow) and ("_force_dir_screen" in src_panel)
    chk("D2", "球上的力箭头与 S³ 表盘指针**共用** _force_dir_screen (同一条方向)",
        {"箭头用它": "_force_dir_screen" in src_arrow, "表盘用它": "_force_dir_screen" in src_panel},
        both, "两处都调同一函数")

    q, _n, _s2 = gt._qnorm(rows[-1].get("q"))
    vec = [float(x) for x in rows[-1]["vec"]]
    _qn = math.sqrt(sum(float(x) ** 2 for x in q[1:])) or 1e-9
    _vn = math.sqrt(sum(x ** 2 for x in vec)) or 1e-9
    _dot = sum(float(a) / _qn * b / _vn for a, b in zip(q[1:], vec))
    chk("D3", "q̂ 矢量部与 F合 同向 (数据面同源, 不是两个独立量)", "%+.4f" % _dot, _dot > 0.999, ">0.999")

    print("    [证据] 旧口径(直接投影长矢量)最大偏差 %.1f°, 其中翻 180° 的 %d 例"
          % (worst_old, sum(1 for x in old_flips if "180°" in x)))
    for _o in old_flips[:4]:
        print("           -", _o)
    for _b in rows_bad[:4]:
        print("    ⚠️", _b)
    print("\n合计: PASS=%d FAIL=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
