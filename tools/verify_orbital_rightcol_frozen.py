#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌞 判据: 太阳系视图「右侧文字栏」在数据跳动时**不许动** (老倪 2026-10-22)。

判法 (纯几何, 不靠肉眼):
  同一窗口尺寸下, 把右侧栏那 10 行的**数据**换成量宽不同的两套 (数字位数/符号变化),
  重算布局 target 矩形:
    S1 左缘 x    max|Δx| 必须 = 0 px   (文字列左右不许挪)
    S2 行 y      max|Δy| 必须 = 0 px   (行上下不许挪)
    S3 右缘      恒等于 W-14            (列贴右边, 不随内容变)
    S4 行数      两套数据行数一致        (行数变 ⇒ 整列跳)
多窗口尺寸 × 同上 (窄窗/宽窗都要定住)。
"""
import copy
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DISPLAY", ":0")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "src")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from PyQt5.QtWidgets import QApplication                              # noqa: E402

import orbital_arch as OA                                             # noqa: E402

OA.OrbitalArchData._ui_run = (lambda self: (True, "judge: 在跑分支"))

PASS = FAIL = 0


def chk(tag, title, got, ok, expect=""):
    global PASS, FAIL
    PASS += bool(ok)
    FAIL += (not ok)
    print("%s %-4s %s" % ("✅" if ok else "❌", tag, title))
    print("        got=%s  expect=%s" % (str(got)[:260], str(expect)[:200]))


def _variant(body, tag):
    """同一份真数据的两种量宽 (模拟数字跳动: 位数/符号/状态字形都变)。"""
    b = copy.deepcopy(body)
    if tag == "A":                       # 短数值 (基准)
        b.setdefault("earth", {})["req_mps"] = 0.35
        b.setdefault("mercury", {})["progress"] = 0.42
        b.setdefault("moon", {})["err"] = 0.02
    else:                                # 长数值: 多一位、负号、百分比到 100%
        b.setdefault("earth", {})["req_mps"] = 12.05
        b.setdefault("mercury", {})["progress"] = 1.00
        b.setdefault("moon", {})["err"] = -0.12
    return b


def main():
    app = QApplication.instance() or QApplication(sys.argv)   # noqa: F841
    view = OA.OrbitalArchView(root=ROOT)
    base = view.data.body

    sizes = ((700, 600), (900, 620), (560, 520), (1240, 900))
    worst_x = worst_y = 0.0
    bad_rows = []
    right_edge_ok = True
    same_n = True

    for (w, h) in sizes:
        view.resize(w, h)
        W, H, S, cx, cy, R = view._geom()
        pos = view.positions(cx, cy, R)
        view._lbl_pos = {}                       # 别的判据跑过会留平滑态 → 清掉
        blkA, _ = view._label_blocks(pos, _variant(base, "A"), cx, cy, R, S, W, H)
        view._lbl_pos = {}
        blkB, _ = view._label_blocks(pos, _variant(base, "B"), cx, cy, R, S, W, H)
        if len(blkA) != len(blkB):
            same_n = False
            print("    ! %dx%d 行数不同: %d vs %d" % (w, h, len(blkA), len(blkB)))
            continue
        for i, (ra, rb) in enumerate(zip(blkA, blkB)):
            dx, dy = abs(ra[0].x() - rb[0].x()), abs(ra[0].y() - rb[0].y())
            worst_x = max(worst_x, dx)
            worst_y = max(worst_y, dy)
            if dx > 0.001 or dy > 0.001:
                bad_rows.append("%dx%d#%d dx=%.1f dy=%.1f | %s" % (w, h, i, dx, dy, ra[1][0][:34]))
            if abs((ra[0].x() + ra[0].width()) - (W - 14.0)) > 0.5:
                right_edge_ok = False
        print("    %4dx%-4d W=%d H=%d 行=%d 宽度=%s" %
              (w, h, W, H, len(blkA), sorted({round(x[0].width(), 1) for x in blkA})))

    chk("S1", "数据跳动时右栏文字左缘不动 (max|Δx| = 0 px)", "max|Δx| = %.1f px" % worst_x,
        worst_x <= 0.001, "0.0 px")
    chk("S2", "数据跳动时右栏各行 y 不动 (max|Δy| = 0 px)", "max|Δy| = %.1f px" % worst_y,
        worst_y <= 0.001, "0.0 px")
    chk("S3", "右栏右缘钉在 W-14 (不随内容宽度伸缩)", right_edge_ok, True)
    chk("S4", "两套数据下行数一致 (行数变 = 整列跳)", same_n, True)
    if bad_rows:
        print("\n  会动的行 (前 8 条):")
        for _r in bad_rows[:8]:
            print("   -", _r)
    print("\n合计: PASS=%d FAIL=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
