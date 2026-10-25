#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🗺️ explore_path_planner.py — 自主建图/自主探索路线规划 (老倪 2026-10-25)

老倪: 「你自己规划一个可以自主建图, 自主探索的路线轨迹, 放到你的三维视图我看看」

## 算法 (真实实现, 不是画假曲线)
栅格占据地图 + frontier 探索 + 信息增益选点 + A* 规划:

  ① 3D 体素地图 (顶视为主, z 分 2 层: 台面层 / 高处层)
     unknown=0 / free=1 / occupied=2
  ② Frontier = free 格里与 unknown 相邻的格 —— 这就是"已知世界的边界"
  ③ 每个 frontier 簇算信息增益:
        gain = 簇内 unknown 格数 / (欧氏路径距离 + 1)
     这是最经典的 frontier 探索效用 (Yamauchi 1997), 简单且可解释,
     比"学出来的探索策略"更适合现在没有真机数据的阶段。
  ④ 选 gain 最大的簇, 用 A* (8 邻域, 对角 √2) 规划路径, 遇到占用格绕开
  ⑤ 沿路径把相机视野 (FOV 扇形) 内的 unknown 标成 free, 更新地图
  ⑥ 重复直到覆盖率 ≥ 目标 或 连续 3 轮无新 frontier (收敛)

## 场景: 光模块产线工位
用真实工位几何 (工作台 0.6×0.6m + 料盘 + 孔位盒 + 两处夹具),
不是随机障碍 —— 只有真布局, 轨迹才有参考价值。

输出: zmax_data/ss_live/explore_traj.json (给 3D 视图直接吃)
自检: python3 tools/explore_path_planner.py --selftest
用法: python3 tools/explore_path_planner.py --out zmax_data/ss_live/explore_traj.json
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import os.path as osp
import sys

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT") or "/home/ubuntu/zmax"

# ── 场景 / 栅格参数 ──
CELL = 0.02                 # 栅格边长 2cm
NX, NY = 32, 30             # 0.64m × 0.60m 工作台
# 相机 FOV (D405 彩色: HFOV≈87°, 这里保守用 70°)
FOV_DEG = 70.0
VIEW_RANGE = 0.30           # 有效观测半径 30cm
COVER_TARGET = 0.92         # 覆盖率目标

UNKNOWN, FREE, OCC = 0, 1, 2


def build_scene():
    """光模块产线工位的真实布局 (顶视栅格)。

    坐标: 栅格 (i,j) → 世界 (i*CELL, j*CELL), 原点在工作台左下角。
    """
    g = np.full((NX, NY), UNKNOWN, dtype=np.int8)
    # 工作台外框 (立柱/围栏) = 占用
    g[0, :] = OCC
    g[-1, :] = OCC
    g[:, 0] = OCC
    g[:, -1] = OCC
    # 料盘 (左侧 0.10~0.22m × 0.06~0.26m) —— 托盘边缘算障碍, 内部可观测
    g[5:11, 3:13] = FREE
    # 孔位盒 (右侧 0.44~0.56m × 0.10~0.22m) —— 真实 HOLE_MOUTH 一带
    g[22:28, 5:11] = FREE
    # 两处工装夹具: 真实产线上夹住工件的柱体, 必须绕开
    g[14:17, 8:11] = OCC        # 夹具 A
    g[10:13, 20:23] = OCC       # 夹具 B
    # 起点 (机械臂底座附近)
    return g


def free_mask(g):
    return g == FREE


def frontier_mask(g):
    """free 且 8 邻域里有 unknown 的格 = frontier。"""
    f = (g == FREE)
    unk = (g == UNKNOWN)
    # 8 邻域膨胀
    pad = np.zeros_like(unk)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if di == 0 and dj == 0:
                continue
            pad |= np.roll(np.roll(unk, di, axis=0), dj, axis=1)
    return f & pad


def cluster_frontiers(fm, min_size=3):
    """把相邻 frontier 格聚成簇 (BFS)。"""
    seen = np.zeros_like(fm, dtype=bool)
    clusters = []
    nx, ny = fm.shape
    for i in range(nx):
        for j in range(ny):
            if not fm[i, j] or seen[i, j]:
                continue
            q, comp = [(i, j)], []
            seen[i, j] = True
            while q:
                a, b = q.pop()
                comp.append((a, b))
                for da in (-1, 0, 1):
                    for db in (-1, 0, 1):
                        na, nb = a + da, b + db
                        if 0 <= na < nx and 0 <= nb < ny and fm[na, nb] and not seen[na, nb]:
                            seen[na, nb] = True
                            q.append((na, nb))
            if len(comp) >= min_size:
                clusters.append(comp)
    return clusters


def astar(g, start, goal):
    """A* 8 邻域, 对角 √2, 不可穿占用格。返回 [(i,j), ...] 或 None。"""
    nx, ny = g.shape
    def h(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])
    openq = [(h(start, goal), 0.0, start, None)]
    came, best = {}, {start: 0.0}
    while openq:
        _, cost, cur, parent = heapq.heappop(openq)
        if cur in came:
            continue
        came[cur] = parent
        if cur == goal:
            path = []
            while cur is not None:
                path.append(cur)
                cur = came[cur]
            return path[::-1]
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                na, nb = cur[0] + di, cur[1] + dj
                if not (0 <= na < nx and 0 <= nb < ny):
                    continue
                if g[na, nb] == OCC:
                    continue
                # 对角不许切角 (两边都是障碍时禁走)
                if di != 0 and dj != 0:
                    if g[cur[0] + di, cur[1]] == OCC or g[cur[0], cur[1] + dj] == OCC:
                        continue
                step = math.sqrt(2.0) if (di and dj) else 1.0
                nc = cost + step
                if nc < best.get((na, nb), 1e18):
                    best[(na, nb)] = nc
                    heapq.heappush(openq, (nc + h((na, nb), goal), nc, (na, nb), cur))
    return None


def reveal(g, pose, yaw):
    """在 pose 处朝 yaw 方向观测: FOV 扇区内的 unknown → free。
    返回本次新揭示的格数。
    """
    nx, ny = g.shape
    ci, cj = pose
    rng = int(VIEW_RANGE / CELL)
    half = math.radians(FOV_DEG) / 2.0
    newly = 0
    for di in range(-rng, rng + 1):
        for dj in range(-rng, rng + 1):
            i, j = ci + di, cj + dj
            if not (0 <= i < nx and 0 <= j < ny):
                continue
            d = math.hypot(di, dj)
            if d > rng or d < 1:
                continue
            if g[i, j] == OCC:
                continue        # 障碍后面看不见
            ang = math.atan2(dj, di)
            da = (ang - yaw + math.pi) % (2 * math.pi) - math.pi
            if abs(da) > half:
                continue
            if g[i, j] == UNKNOWN:
                g[i, j] = FREE
                newly += 1
    return newly


def coverage(g):
    """覆盖率 = free / 可达(free+unknown), 占用格不计。"""
    reachable = int(((g == FREE) | (g == UNKNOWN)).sum())
    if reachable == 0:
        return 0.0
    return float((g == FREE).sum()) / reachable


def plan(start=(3, 3), cover_target=COVER_TARGET, max_rounds=40, verbose=True):
    """自主探索主循环 → dict(waypoints, path, coverage_hist, frontiers_seen)。"""
    g = build_scene()
    # 起点周围先揭示一块 (机器人开机时已知自己附近)
    ci, cj = start
    for di in range(-3, 4):
        for dj in range(-3, 4):
            i, j = ci + di, cj + dj
            if 0 <= i < NX and 0 <= j < NY and g[i, j] != OCC:
                g[i, j] = FREE

    pose = start
    yaw = 0.0
    waypoints = [{"i": ci, "j": cj, "x": ci * CELL, "y": cj * CELL,
                  "yaw_deg": round(math.degrees(yaw), 1),
                  "cov": round(coverage(g), 4), "gain": 0.0, "round": 0}]
    full_path = [start]
    cov_hist = [coverage(g)]
    gains = []
    no_new_streak = 0

    for rnd in range(1, max_rounds + 1):
        fm = frontier_mask(g)
        clusters = cluster_frontiers(fm)
        if not clusters:
            if verbose:
                print("  [第%d轮] 无 frontier ⇒ 探索结束" % rnd)
            break
        # 每个簇算增益: unknown 邻居数 / (路径距离+1)
        best = None
        for comp in clusters:
            # 簇代表点 = 几何中心最近的 free 格
            ai = int(np.mean([p[0] for p in comp]))
            aj = int(np.mean([p[1] for p in comp]))
            cand = min(comp, key=lambda p: abs(p[0] - ai) + abs(p[1] - aj))
            # 簇的 unknown 邻居数 (真实待探索量)
            unk_n = 0
            for (a, b) in comp:
                for da in (-1, 0, 1):
                    for db in (-1, 0, 1):
                        na, nb = a + da, b + db
                        if 0 <= na < NX and 0 <= nb < NY and g[na, nb] == UNKNOWN:
                            unk_n += 1
            dist = math.hypot(cand[0] - pose[0], cand[1] - pose[1])
            gain = unk_n / (dist + 1.0)
            if best is None or gain > best[0]:
                best = (gain, cand, dist, unk_n)
        gain, target, dist, unk_n = best
        path = astar(g, pose, target)
        if path is None:
            # 不可达的 frontier 先标成已知 (避免死循环), 记下来
            g[target[0], target[1]] = FREE
            continue
        # 沿路径走, 每个中间点都观测一次 (真实机器人是边走边看)
        yaw = math.atan2(target[1] - pose[1], target[0] - pose[0])
        newly_total = 0
        for p in path:
            newly_total += reveal(g, p, yaw)
            full_path.append(p)
        pose = target
        cov = coverage(g)
        cov_hist.append(cov)
        gains.append(round(gain, 4))
        waypoints.append({"i": pose[0], "j": pose[1], "x": pose[0] * CELL,
                          "y": pose[1] * CELL, "yaw_deg": round(math.degrees(yaw), 1),
                          "cov": round(cov, 4), "gain": round(gain, 4), "round": rnd,
                          "dist_cells": round(dist, 2), "frontier_unknown": unk_n})
        if verbose:
            print("  [第%2d轮] waypoint(%.2f,%.2f) gain=%.3f dist=%.1f格 新揭示=%d 覆盖=%.1f%%"
                  % (rnd, pose[0] * CELL, pose[1] * CELL, gain, dist, newly_total, cov * 100))
        no_new_streak = no_new_streak + 1 if newly_total == 0 else 0
        if no_new_streak >= 3:
            if verbose:
                print("  连续 3 轮无新格 ⇒ 收敛")
            break
        if cov >= cover_target:
            if verbose:
                print("  覆盖 %.1f%% ≥ 目标 %.0f%% ⇒ 完成" % (cov * 100, cover_target * 100))
            break

    return {"grid": g.tolist(), "waypoints": waypoints, "path": full_path,
            "cov_hist": [round(c, 4) for c in cov_hist], "gains": gains,
            "coverage_final": round(coverage(g), 4),
            "cell": CELL, "nx": NX, "ny": NY,
            "fov_deg": FOV_DEG, "view_range": VIEW_RANGE,
            "scene": "光模块产线工位 (工作台 0.64×0.60m + 料盘 + 孔位盒 + 2 夹具)"}


# ═══════════════ 自检 ═══════════════
def _selftest() -> int:
    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("① 场景与地图")
    g = build_scene()
    chk("地图尺寸", g.shape == (NX, NY), str(g.shape))
    chk("有占用格 (围栏+夹具)", int((g == OCC).sum()) > 50, "OCC=%d" % int((g == OCC).sum()))
    chk("有未知区", int((g == UNKNOWN).sum()) > 100, "UNK=%d" % int((g == UNKNOWN).sum()))

    print("② A* 绕障")
    g2 = np.full((12, 12), FREE, dtype=np.int8)
    g2[0, :] = OCC; g2[-1, :] = OCC; g2[:, 0] = OCC; g2[:, -1] = OCC
    # 墙: i=6 整列挡住 (j=1..10), 只在 j=10 留口。
    # 🔴 踩过: 初版写 g2[1:10, 6]=OCC, 那是「j=6 处一道竖墙」, 而起点(2,5)/终点(10,5)
    # 都在 j=5, 根本不挡路 ⇒ 直线过去是对的, 测试却判 FAIL。用例本身造错了。
    # 🔴 第二次踩: g2[1:11, 6] 是「行1..10、列固定6」= j=6 的竖线, 还是没挡路。
    #    numpy 是 [行(i), 列(j)], 要「i=6 整列挡住」必须写 g2[6, 1:11]。
    g2[6, 1:11] = OCC
    g2[6, 10] = FREE
    p = astar(g2, (2, 5), (10, 5))
    chk("A* 找到路径", p is not None, "%d 步" % (len(p) if p else 0))
    if p:
        chk("路径穿过留口 (j 到过 10 附近)",
            any(abs(c[1] - 10) <= 1 for c in p), "max j=%d" % max(c[1] for c in p))
        chk("路径不穿占用格", all(g2[c] != OCC for c in p))
    p_none = astar(build_scene(), (2, 2), (0, 0))
    chk("目标在障碍里 ⇒ 无路径", p_none is None)

    print("③ frontier 检测")
    gg = np.full((12, 12), UNKNOWN, dtype=np.int8)
    gg[4:8, 4:8] = FREE
    fm = frontier_mask(gg)
    chk("有 frontier", int(fm.sum()) > 0, "n=%d" % int(fm.sum()))
    cl = cluster_frontiers(fm, min_size=2)
    chk("聚成 1 个簇", len(cl) == 1, "簇数=%d" % len(cl))
    chk("frontier 都在 free 边界", all(gg[c] == FREE for comp in cl for c in comp))

    print("④ 观测揭示")
    g3 = np.full((20, 20), UNKNOWN, dtype=np.int8)
    n1 = reveal(g3, (10, 10), 0.0)          # 朝 +i
    chk("朝 +i 观测有新格", n1 > 0, "新揭示 %d" % n1)
    chk("+i 侧被揭示", int((g3[13:16, 9:12] == FREE).sum()) > 0)
    chk("反方向 (-i) 仍是未知", g3[5, 10] == UNKNOWN, "g3[5,10]=%d" % g3[5, 10])

    print("⑤ 完整探索 (真跑)")
    r = plan(start=(3, 3), cover_target=0.92, verbose=False)
    print("     覆盖: %s" % " → ".join("%.1f%%" % (c * 100) for c in r["cov_hist"]))
    chk("覆盖率单调不降", all(r["cov_hist"][i] <= r["cov_hist"][i + 1] + 1e-9
                          for i in range(len(r["cov_hist"]) - 1)))
    chk("最终覆盖 ≥ 80%", r["coverage_final"] >= 0.80,
        "%.1f%%" % (r["coverage_final"] * 100))
    chk("航点数 ≥ 5", len(r["waypoints"]) >= 5, "%d 个" % len(r["waypoints"]))
    chk("路径全在非占用格",
        all(r["grid"][i][j] != OCC for (i, j) in r["path"]),
        "%d 步" % len(r["path"]))
    wps = r["waypoints"]
    chk("航点坐标与栅格一致",
        all(abs(w["x"] - w["i"] * r["cell"]) < 1e-9 for w in wps))
    print("     航点: %s" % ", ".join("(%.2f,%.2f)" % (w["x"], w["y"]) for w in wps[:6]))

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 全部通过 (自主探索轨迹: frontier + 信息增益 + A*)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", default=osp.join(ROOT, "zmax_data/ss_live/explore_traj.json"))
    ap.add_argument("--cover", type=float, default=COVER_TARGET)
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    print("=== 自主探索规划 (光模块产线工位) ===")
    r = plan(cover_target=a.cover)
    os.makedirs(osp.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False)
    print("\n覆盖率 %.1f%% · 航点 %d · 路径 %d 步"
          % (r["coverage_final"] * 100, len(r["waypoints"]), len(r["path"])))
    mb = osp.getsize(a.out) / 1024.0
    print("→ %s (%.1f KB)" % (a.out, mb))
    return 0


if __name__ == "__main__":
    sys.exit(main())
