#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔮 未来 N 点通道 —— 「你已经知道了实际轨迹, 那就给出未来的点」(老倪 2026-11-14)

既然每个点都是真机录下来的(215 点 SDK 真值), 那"预测"就是**查表**: 当前走到 i,
把 i+1 … i+N 的真实位姿取出来, 围成一条半径为 r 的管子 (通道), 画进 AR。
⇒ 通道永远只覆盖**接下来 N 个点**, 机器人往前走一帧, 管子跟着往前挪一帧。

真源: tools/web/real_traj_joints.json (frames[i].p 米) + 游标 zmax_data/rokae_sdk/traj_step_state.json
输出: zmax_data/ar_rs/fences.json 里的 PRED-* 线 (旧 PRED-* 自动清掉; COR-* 不动)

用法:
  python3 tools/pred_corridor_from_traj.py                    # 按当前游标出未来 10 点
  python3 tools/pred_corridor_from_traj.py --i 30 --n 10      # 指定起点
  python3 tools/pred_corridor_from_traj.py --write            # 写进 AR 场景
  python3 tools/pred_corridor_from_traj.py --watch --write     # 1Hz 跟着游标走
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

TRAJ = os.path.join(ROOT, "tools", "web", "real_traj_joints.json")
STATE = os.path.join(ROOT, "zmax_data", "rokae_sdk", "traj_step_state.json")
COLOR = "#f0a020"
R_MM = 80.0
N_AHEAD = 10


def load_frames():
    d = json.load(open(TRAJ, encoding="utf-8"))
    fr = d.get("frames") or []
    return [[float(f["p"][0]) * 1000.0, float(f["p"][1]) * 1000.0, float(f["p"][2]) * 1000.0] for f in fr]


def cursor_now():
    try:
        s = json.load(open(STATE, encoding="utf-8"))
        c = int(s.get("cursor") or 0)
        return max(0, min(c, 214))
    except Exception:                                                    # noqa: BLE001
        return 0


def live_tcp_mm():
    """当前真机末端 (mm) —— 用来判"走到第几个点了"。"""
    try:
        d = json.load(open(os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json"),
                           encoding="utf-8"))
        return [float(d["x"]) * 1000.0, float(d["y"]) * 1000.0, float(d["z"]) * 1000.0], float(d.get("ts") or 0)
    except Exception:                                                    # noqa: BLE001
        return None, 0.0


def nearest_index(pts_all, p):
    best, bi = 1e18, 0
    for i, q in enumerate(pts_all):
        d = sum((q[k] - p[k]) ** 2 for k in range(3))
        if d < best:
            best, bi = d, i
    return bi


def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _perp(u):
    a = [1.0, 0.0, 0.0] if abs(u[0]) < 0.9 else [0.0, 1.0, 0.0]
    e1 = _unit([u[1] * a[2] - u[2] * a[1], u[2] * a[0] - u[0] * a[2], u[0] * a[1] - u[1] * a[0]])
    e2 = _unit([u[1] * e1[2] - u[2] * e1[1], u[2] * e1[0] - u[0] * e1[2], u[0] * e1[1] - u[1] * e1[0]])
    return e1, e2


def build(i0, n=N_AHEAD, r=R_MM):
    """取 i0 起接下来的 n 个点(不含 i0 本身), 造 2 条母线 + 端环 + 逐点横档。"""
    pts_all = load_frames()
    i0 = max(0, min(int(i0), len(pts_all) - 1))
    i1 = min(i0 + int(n), len(pts_all) - 1)
    pts = pts_all[i0:i1 + 1]
    looped = False
    if len(pts) < int(n) + 1 and i1 >= len(pts_all) - 1:
        # 本圈走到头了 ⇒ 未来 10 点接下一圈的头 (连续生产, 不停)
        need = int(n) + 1 - len(pts)
        pts = pts + pts_all[:need]
        looped = True
    if len(pts) < 2:
        return {"i0": i0, "i1": i1, "n_pts": len(pts), "lines": [], "pts_mm": pts}
    # 全局参考基 (以整段起终点定, 避免逐段抖动)
    u = _unit([pts[-1][k] - pts[0][k] for k in range(3)])
    e1, e2 = _perp(u)
    lines = []
    tag = "PRED-%d" % i0
    note = "🔮 未来通道 · i=%d→%d · %d 点 · r=%.0fmm (真轨迹查表, 非猜测)%s" % (
        i0, i1, len(pts) - 1, r, " · 跨圈接下一件" if looped else "")

    def add(a, b, name):
        lines.append({"id": "%s-l%d" % (tag, len(lines)), "type": "line", "name": ("🔮 未来" + name),
                      "p1": [round(x / 1000.0, 6) for x in a], "p2": [round(x / 1000.0, 6) for x in b],
                      "color": COLOR, "enabled": True, "no_collision": True, "note": note})

    for k in range(len(pts) - 1):
        a, b = pts[k], pts[k + 1]
        if math.dist(a, b) < 0.2:
            continue
        for s in (1.0, -1.0):                                            # 两条母线
            oa = [a[j] + e1[j] * r * s for j in range(3)]
            ob = [b[j] + e1[j] * r * s for j in range(3)]
            add(oa, ob, "母线 %d-%d" % (k + 1, 1 if s > 0 else 2))
        # 逐点横档 (每个预测点一个横切面, 让人看清"第几个点")
        add([a[j] + e1[j] * r for j in range(3)], [a[j] - e1[j] * r for j in range(3)],
            "点 %d 横档" % (i0 + k))
    return {"i0": i0, "i1": i1, "n_pts": len(pts) - 1, "pts_mm": pts,
            "lines": lines, "r_mm": r, "len_mm": round(sum(math.dist(pts[k], pts[k + 1]) for k in range(len(pts) - 1)), 2)}


def write_ar(doc):
    import fence_store as FS

    # fence_store 自己发 id(不是我们给的 PRED-*) ⇒ 按**名字前缀**认自己画的通道, 重画前先清干净
    for it in list((FS._load().get("items") or [])):
        if str(it.get("name", "")).startswith(("🔮 未来", "未来母线", "未来点")):
            try:
                FS.delete(it["id"])
            except Exception:                                            # noqa: BLE001
                pass
    for ln in doc["lines"]:
        FS.add("line", ln["p1"], ln["p2"], ln["name"], ln["color"], ln["note"])
    return len(doc["lines"])


def main():
    argv = sys.argv[1:]
    i0, n, do_write, watch = None, N_AHEAD, False, False
    k = 0
    while k < len(argv):
        if argv[k] == "--i" and k + 1 < len(argv):
            i0 = int(argv[k + 1]); k += 2
        elif argv[k] == "--n" and k + 1 < len(argv):
            n = int(argv[k + 1]); k += 2
        elif argv[k] == "--write":
            do_write = True; k += 1
        elif argv[k] == "--watch":
            watch = True; k += 1
        elif argv[k] in ("-h", "--help"):
            print(__doc__); return 0
        else:
            k += 1

    while True:
        if i0 is not None:
            cur, why = i0, "指定"
        else:
            cur, why = cursor_now(), "游标"
            p, tsl = live_tcp_mm()
            if p is not None and (cur >= 214 or (time.time() - tsl) < 3.0):
                # 游标走完/或正在跑: 用真机当前位姿找最近的轨迹点 ⇒ 未来 10 点总是"真正接下来要走的"
                cur, why = nearest_index(load_frames(), p), "最近真机位姿"
                print("   (游标=%s ⇒ 改用%s (%.1f,%.1f,%.1f)mm)"
                      % (cursor_now(), why, p[0], p[1], p[2]))
        doc = build(cur, n)
        print("🔮 未来 %d 点通道 · i=%d→%d · 段长 %.1fmm · r=%.0fmm"
              % (doc["n_pts"], doc["i0"], doc["i1"], doc.get("len_mm", 0), doc.get("r_mm", R_MM)))
        for j, p in enumerate(doc["pts_mm"][1:], 1):
            print("   +%2d 点 i=%3d  x=%7.2f y=%8.2f z=%7.2f mm" % (j, doc["i0"] + j, p[0], p[1], p[2]))
        if do_write:
            print("   → AR 线 %d 条 (PRED-*) 已写入 fences.json" % write_ar(doc))
        if not watch:
            return 0
        time.sleep(1.0)


if __name__ == "__main__":
    raise SystemExit(main())
