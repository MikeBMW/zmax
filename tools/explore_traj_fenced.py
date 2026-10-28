# -*- coding: utf-8 -*-
"""explore_traj_fenced.py —— 避让围栏的自主探索覆盖轨迹 (base 系真坐标)

老倪 2026-10-26:
「还有建图轨迹，太长了，都碰到检测设备了，你前面的围栏，你看到了么？重新规划」

原来那条 54 点的"建图轨迹"是 2D 栅格**平移到台面的示意坐标**(ox=0.28, oy=-0.30),
一路铺到 x=+0.72m —— 而工程配置里「检测设备」围栏是 x 712~844mm / y -91~302mm / z 0~340mm。
x=712mm 之后就直接压进设备里了。这不是"看起来碰到", 是真撞。

本文件按**工程配置里的围栏**重新规划 (不是另编一套坐标):
  ① 工作区取 x∈[--xmin,--xmax], y∈[--ymin,--ymax], z=--z (默认 280mm, 台面上方);
  ② 逐行扫描 (boustrophedon), 行距 --row-gap;
  ③ 每一行先算"这一 y 上、这一 z 高度上"被哪些盒子占掉, 从工作区里**减掉**
     (盒子按 --clear + 围栏外扩余量 inflated) ⇒ 只留最大的一段可用区间;
  ④ 逐点再用 fence_store.check_point() 复核 (唯一依据判定, 不是我估算), 任何一点命中就报错;
  ⑤ 输出 base 系米制点列 + 航点 + 总长 + 每条围栏的最小净距。

用法:
  python tools/explore_traj_fenced.py                  # 默认 3 行, 20mm 步长
  python tools/explore_traj_fenced.py --rows 3 --row-gap 120 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import fence_store as FS                                                # noqa: E402

OUT = os.path.join(REPO, "zmax_data", "ss_live", "explore_traj_fenced.json")


def free_intervals(lo, hi, y, z, margins_m):
    """在给定 y / z 上, 把被围栏占掉的 [x_lo,x_hi] 从 [lo,hi] 里减掉。

    盒子: 三个轴都重叠 ⇒ 占掉它的 x 区间。
    直线: 沿线段采样, 采样点的 (y,z) 落进本行容差 ⇒ 占掉该采样点附近的 x。
          (工程配置里「小兰」「小青」是直线元素, fence_store.check_point 也把它们当围栏,
           所以规划时必须一起避 —— 不然规划完复核会报"点落在围栏里", 那次实测就是 3 个点撞小兰。)
    """
    blocked = []
    for it in FS.listing()["items"]:
        if not it.get("enabled", True):
            continue
        if it.get("type") == "line":
            a = [float(v) for v in it["p1"]]
            b = [float(v) for v in it["p2"]]
            N = 60
            for i in range(N + 1):
                t = i / float(N)
                sy = a[1] + (b[1] - a[1]) * t
                sz = a[2] + (b[2] - a[2]) * t
                if abs(sy - y) <= margins_m and abs(sz - z) <= margins_m:
                    sx = a[0] + (b[0] - a[0]) * t
                    blocked.append((sx - margins_m, sx + margins_m))
            continue
        if it.get("type") != "box":
            continue
        x1, y1, z1 = [float(v) for v in it["p1"]]
        x2, y2, z2 = [float(v) for v in it["p2"]]
        by_lo, by_hi = min(y1, y2) - margins_m, max(y1, y2) + margins_m
        bz_lo, bz_hi = min(z1, z2) - margins_m, max(z1, z2) + margins_m
        if not (by_lo <= y <= by_hi and bz_lo <= z <= bz_hi):
            continue
        blocked.append((min(x1, x2) - margins_m, max(x1, x2) + margins_m))
    blocked.sort()
    out, cur = [], lo
    for b_lo, b_hi in blocked:
        if b_hi <= cur or b_lo >= hi:
            continue
        if b_lo > cur:
            out.append((cur, min(b_lo, hi)))
        cur = max(cur, b_hi)
        if cur >= hi:
            break
    if cur < hi:
        out.append((cur, hi))
    return [(a, b) for a, b in out if b - a > 0.02]


def min_clear(pts):
    """每条围栏到整条路径的最小距离 (mm) —— 汇报用, 让人一眼看出还有多少余量。"""
    res = {}
    mg = 0.0
    for it in FS.listing()["items"]:
        if it.get("type") != "box" or not it.get("enabled", True):
            continue
        x1, y1, z1 = [float(v) for v in it["p1"]]
        x2, y2, z2 = [float(v) for v in it["p2"]]
        lo = [min(x1, x2) - mg, min(y1, y2) - mg, min(z1, z2) - mg]
        hi = [max(x1, x2) + mg, max(y1, y2) + mg, max(z1, z2) + mg]
        best = 1e9
        for p in pts:
            d = 0.0
            for i in range(3):
                if p[i] < lo[i]:
                    d += (lo[i] - p[i]) ** 2
                elif p[i] > hi[i]:
                    d += (p[i] - hi[i]) ** 2
            best = min(best, d ** 0.5)
        res[it.get("name") or it["id"]] = round(best * 1000, 1)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xmin", type=float, default=340.0, help="工作区 x 下限 mm")
    ap.add_argument("--xmax", type=float, default=700.0, help="工作区 x 上限 mm (检测设备在 712 起)")
    ap.add_argument("--ymin", type=float, default=-200.0)
    ap.add_argument("--ymax", type=float, default=200.0)
    ap.add_argument("--z", type=float, default=280.0, help="扫描高度 mm")
    ap.add_argument("--rows", type=int, default=3, help="扫描行数 (越少越短)")
    ap.add_argument("--row-gap", type=float, default=120.0, help="行距 mm")
    ap.add_argument("--step", type=float, default=20.0, help="采样步长 mm")
    ap.add_argument("--clear", type=float, default=30.0, help="离围栏额外净距 mm")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    z = a.z / 1000.0
    margin_m = (float(FS.listing().get("margin_mm") or 10.0) + a.clear) / 1000.0
    ys = [a.ymin + i * a.row_gap for i in range(max(1, a.rows))]
    pts, rows_info = [], []
    total = 0.0
    prev = None
    for r, y_mm in enumerate(ys):
        ivs = free_intervals(a.xmin / 1000.0, a.xmax / 1000.0, y_mm / 1000.0, z, margin_m)
        if not ivs:
            rows_info.append({"y_mm": y_mm, "skip": "这一行全是围栏, 跳过"})
            continue
        x_lo, x_hi = max(ivs, key=lambda t: t[1] - t[0])
        xs = []
        x = x_lo
        while x <= x_hi + 1e-9:
            xs.append(x)
            x += a.step / 1000.0
        if xs[-1] < x_hi - 1e-6:
            xs.append(x_hi)
        if r % 2 == 1:                                  # 蛇形: 奇数行反向
            xs = xs[::-1]
        row_pts = [[xx, y_mm / 1000.0, z] for xx in xs]
        for p in row_pts:
            if prev:
                total += sum((p[i] - prev[i]) ** 2 for i in range(3)) ** 0.5 * 1000
            pts.append(p)
            prev = p
        rows_info.append({"y_mm": y_mm, "x_from_mm": round(x_lo * 1000, 1),
                          "x_to_mm": round(x_hi * 1000, 1), "n": len(xs)})

    if len(pts) < 2:
        raise SystemExit("⛔ 分不出可用区间 (工作区全被围栏占住?) —— 检查 --xmin/--xmax/--ymin/--ymax")

    bad = []
    for i, p in enumerate(pts):
        r = FS.check_point(p, margin_mm=a.clear)
        if r.get("hit"):
            bad.append((i, [round(v * 1000) for v in p], r.get("inside")))
    clr = min_clear(pts)

    rec = {"ok": not bad, "src": "tools/explore_traj_fenced.py", "at": time.strftime("%F %T"),
           "z_mm": a.z, "n": len(pts), "len_mm": round(total, 1),
           "pts": [[round(v, 4) for v in p] for p in pts],
           "waypoints": [{"x": round(p[0], 4), "y": round(p[1], 4)} for p in pts[::max(1, len(pts) // 12)]],
           "rows": rows_info, "clear_mm": clr,
           "note": "按工程配置围栏重规划的覆盖路径: %d 行 / %d 点 / %.0fmm / z=%.0fmm · 离围栏最小净距 %s"
                   % (len(rows_info), len(pts), total, a.z,
                      ", ".join("%s %.0fmm" % (k, v) for k, v in clr.items()))}

    print("工作区 x[%.0f,%.0f] y[%.0f,%.0f] z=%.0fmm · 行距 %.0fmm · 额外净距 %.0fmm"
          % (a.xmin, a.xmax, a.ymin, a.ymax, a.z, a.row_gap, a.clear))
    for r in rows_info:
        if "skip" in r:
            print("  y=%+.0f : %s" % (r["y_mm"], r["skip"]))
        else:
            print("  y=%+.0f : x %.0f~%.0f (%d 点)" % (r["y_mm"], r["x_from_mm"], r["x_to_mm"], r["n"]))
    print("合计 %d 点 · 路径长 %.0fmm" % (len(pts), total))
    print("离各围栏最小净距: " + ", ".join("%s %.0fmm" % (k, v) for k, v in clr.items()))
    if bad:
        print("⛔ 有 %d 个点落在围栏里(不该发生): %s" % (len(bad), bad[:3]))
        return 2
    print("✅ 逐点 check_point 复核: 0 命中 (围栏判定用的是唯一依据 fence_store)")

    if a.dry_run:
        print("(dry-run: 没写 %s)" % OUT)
        return 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print("✅ 写入 %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
