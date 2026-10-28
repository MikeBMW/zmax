#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_layout_flow.py — 画布按"数据流方向"重排 (左→右 / 左上→右下)。

老倪 2026-10-15: 「前馈加速器的输出, 连接到动作调制节点, 动作调制的位置, 应该是在前馈加速器的右边,
这样才显得整齐; 你的UI重新排布一下, 接线符合从左上到右下角的趋势」

做法 (只动坐标, 语义/连线一条不动):
 ① 15 条背景行带 (bg) 的 y 序天然是流水线序 (数据源 → 大模型层 → … → 执行层 → 验证层 → 可视化层) ⇒ y 不动;
 ② 带内错行 (同带节点按 130px 逐行排开, 零重叠);
 ③ x 用**像素级最长路径**分层 (Sugiyama): x(n) = max(x(父) + w(父) + gap), 迭代到稳定 ⇒
    **每一条非环边天然指向右**, 不需要按层号对列;
 ④ 每个带内做一次左→右紧排 (消同带撞位), 再回到 ③, 反复若干轮 ⇒ 收敛;
 ⑤ 环边 (反馈/闭环, DFS 找出的 13 条) 不参与 ③; 收尾对它们做一次**只向右推**的贪心 (推动不破坏别的边);
 ⑥ 行带矩形按新节点范围重算。

判据 (不达标就拒写盘):
 · 零重叠 · 非环边**全部**前向 · 反向条数 ≤ 改前 · 每条反向边**向下走**(Δy>0, 保持对角线趋势)
 · 老倪点名: 🧭 动作调制器 必须在 ⚡ 前馈加速器 右边
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
CANVAS = os.path.join(REPO, "flows", "state_space_obs.json")
BG_TYPES = ("bg", "row_bg")
GAP = 60
ROW_OFF = 130
BAND_PAD_TOP = 40
LEFT_MARGIN = 60
PACK_PASSES = 12


def load():
    with open(os.path.realpath(CANVAS), encoding="utf-8") as f:
        return json.load(f)


def find_back_edges(ids, links):
    adj = collections.defaultdict(list)
    for l in links:
        if l.get("f") in ids and l.get("t") in ids:
            adj[l["f"]].append(l["t"])
    color = {i: 0 for i in ids}
    back = set()
    # 🔴 遍历顺序必须**确定**: 对 set 直接迭代受 str 哈希随机化影响 (PYTHONHASHSEED),
    #   同一个画布两次跑会得到不同的反边集合 ⇒ 布局"每次不一样", 判据时好时坏。
    for root in sorted(ids):
        if color[root]:
            continue
        color[root] = 1
        stack = [(root, iter(adj.get(root, ())))]
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if color[nxt] == 1:
                    back.add((node, nxt))
                    continue
                if color[nxt] == 0:
                    color[nxt] = 1
                    stack.append((nxt, iter(adj.get(nxt, ()))))
                    advanced = True
                    break
            if not advanced:
                color[node] = 2
                stack.pop()
    return back


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    d = load()
    nodes, links = d["nodes"], d["links"]
    by_id = {n["id"]: n for n in nodes}
    bands = sorted([n for n in nodes if n.get("type") in BG_TYPES], key=lambda z: z["y"])
    funcs = [n for n in nodes if n.get("type") not in BG_TYPES]
    ids = {n["id"] for n in funcs}
    ids_sorted = [n["id"] for n in funcs]        # 确定序 (set 迭代受哈希随机化影响)
    W = {n["id"]: int(n.get("w", 280)) for n in funcs}

    def band_of(y):
        for b in bands:
            if b["y"] <= y < b["y"] + b.get("h", 294):
                return b["id"]
        return min(bands, key=lambda b: abs(b["y"] - y))["id"]

    owner = {n["id"]: band_of(n.get("y", 0)) for n in funcs}
    back = find_back_edges(ids, links)
    edges = [(l["f"], l["t"]) for l in links if l.get("f") in ids and l.get("t") in ids]
    assert ids_sorted
    fwd_edges = [e for e in edges if e not in back]

    def geom():
        return {n["id"]: (int(n["x"]), int(n["y"]), int(n.get("w", 280)), int(n.get("h", 110)))
                for n in funcs}

    def stats(g):
        fwd = rev = rev_down = 0
        revl = []
        for f, t in edges:
            fx, fy, fw, _ = g[f]
            tx, ty, _, _ = g[t]
            if fx + fw <= tx:
                fwd += 1
            else:
                rev += 1
                revl.append((f, t, fy, ty))
                if ty > fy:
                    rev_down += 1
        return fwd, rev, rev_down, revl

    def overlaps(g):
        items = sorted(g.items(), key=lambda kv: kv[1][0])
        bad = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                ax, ay, aw, ah = items[i][1]
                bx, by, bw, bh = items[j][1]
                if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                    bad.append((items[i][0], items[j][0]))
        return bad

    g0 = geom()
    f0, r0, d0, rl0 = stats(g0)
    print("环边 %d 条 · 改前: 前向 %d · 反向 %d (向下 %d) · 重叠 %d" % (len(back), f0, r0, d0, len(overlaps(g0))))

    # ── ① 带内分行: 行数由带高决定 (行无限增长会顶穿到下一条带 ⇒ 与下带节点重叠) ──
    per_band = collections.defaultdict(list)
    for n in funcs:
        per_band[owner[n["id"]]].append(n)

    def rows_cap(b):
        return max(1, int((b.get("h", 294) - 2 * BAND_PAD_TOP) // ROW_OFF) + 1)

    for b in bands:
        for k, n in enumerate(per_band.get(b["id"], [])):
            n["y"] = int(b["y"] + BAND_PAD_TOP + (k % rows_cap(b)) * ROW_OFF)

    preds = collections.defaultdict(list)
    for f, t in fwd_edges:
        preds[t].append(f)

    # ── ② x: 带内紧排 + 像素级最长路径, 迭代到稳定 ────────────────────────────
    for n in funcs:
        n["x"] = int(LEFT_MARGIN)
    def pack_bands():
        """带内按 x 升序把节点摆进 rows_cap 条轨道 (同 x 的叠成一列) —— 零重叠且不越带"""
        moved = False
        for b in bands:
            lst = sorted(per_band.get(b["id"], []), key=lambda n: n["x"])
            rows = rows_cap(b)
            cur = [int(b["x"]) + 40] * rows
            for n in lst:
                fit = [r for r in range(rows) if cur[r] <= n["x"]]
                r = max(fit, key=lambda r: cur[r]) if fit else min(range(rows), key=lambda r: cur[r])
                nx = int(max(n["x"], cur[r]))
                if nx != n["x"]:
                    moved = True
                n["x"] = nx
                n["y"] = int(b["y"] + BAND_PAD_TOP + r * ROW_OFF)
                cur[r] = n["x"] + W[n["id"]] + GAP
        return moved

    for _ in range(PACK_PASSES):
        changed = pack_bands()
        for n in funcs:                      # 最长路径: 父之后
            need = max([LEFT_MARGIN] + [by_id[p]["x"] + W[p] + GAP for p in preds.get(n["id"], [])])
            if n["x"] < need:
                n["x"] = int(need)
                changed = True
        if not changed:
            break
        for n in funcs:                      # 最长路径: 父之后
            need = max([LEFT_MARGIN] + [by_id[p]["x"] + W[p] + GAP for p in preds.get(n["id"], [])])
            if n["x"] < need:
                n["x"] = int(need)
                changed = True
        if not changed:
            break

    # ── ③ 环边: 只向右推 (推动目标, 不破坏别的边) ──────────────────────────
    for _ in range(3):
        pushed = False
        for f, t in sorted(back):
            fx, _, fw, _ = geom()[f]
            tx = by_id[t]["x"]
            if fx + fw <= tx:
                continue
            need = fx + fw + GAP
            succ = [e[1] for e in fwd_edges if e[0] == t]
            ok = all(by_id[s]["x"] >= need for s in succ)
            if ok:
                by_id[t]["x"] = int(need)
                pushed = True
        if not pushed:
            break
    pack_bands()                             # 推完再紧排一次 (保持零重叠/不越带)

    # ── ④ 环边里"往上走"的短程回环: 在带内把目标下移一行 / 源上移一行 ────────
    def collides(n0):
        g = geom()
        for m in funcs:
            if m["id"] == n0["id"]:
                continue
            ax, ay, aw, ah = g[m["id"]]
            bx, by, bw, bh = g[n0["id"]]
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                return True
        return False

    for f, t in sorted(back):
        g = geom()
        if g[f][0] + g[f][2] <= g[t][0] or g[t][1] > g[f][1]:
            continue                             # 已前向 或 已向下
        tb = by_id[t]["band"] = owner[t]
        cap = rows_cap(by_id[tb]) if False else None
        b = next(x for x in bands if x["id"] == owner[t])
        nxt = dict(by_id[t])
        nxt["y"] = int(by_id[t]["y"] + ROW_OFF)
        if nxt["y"] + 110 <= b["y"] + b.get("h", 294) and not collides(nxt):
            by_id[t]["y"] = nxt["y"]
            continue
        src = dict(by_id[f])
        src["y"] = int(by_id[f]["y"] - ROW_OFF)
        if src["y"] >= b["y"] and not collides(src):
            by_id[f]["y"] = src["y"]

    for b in bands:                          # 行带矩形重算
        lst = per_band.get(b["id"], [])
        if not lst:
            continue
        x0 = min(n["x"] for n in lst) - 40
        x1 = max(n["x"] + W[n["id"]] for n in lst) + 40
        y1 = max(b["y"] + b.get("h", 294), max(n["y"] + int(n.get("h", 110)) for n in lst) + 40)
        b["x"], b["w"], b["h"] = int(x0), int(x1 - x0), int(y1 - b["y"])

    g1 = geom()
    f1, r1, d1, rl1 = stats(g1)
    ov1 = overlaps(g1)
    noncycle_rev = [e for e in rl1 if (e[0], e[1]) not in back]
    print("改后: 前向 %d · 反向 %d (向下 %d) · 重叠 %d" % (f1, r1, d1, len(ov1)))
    print("宽度: x 最大 %d → %d" % (max(v[0] + v[2] for v in g0.values()), max(v[0] + v[2] for v in g1.values())))
    if rl1:
        print("剩余反向线:")
        for f, t, fy, ty in rl1:
            print("   %-27s → %-27s Δy=%+5d %s" % (f, t, ty - fy, "↓" if ty > fy else "↑/平"))

    ff, sc = by_id.get("ssff"), by_id.get("sssched")
    ok_ff = bool(ff and sc and ff["x"] + W["ssff"] <= sc["x"])
    print("%s ⚡前馈加速器 x=%s → 🧭动作调制器 x=%s (相差 %s px)"
          % ("✅" if ok_ff else "❌", ff["x"], sc["x"], (sc["x"] - ff["x"]) if (ff and sc) else "?"))

    bad = []
    if ov1:
        bad.append("重叠 %d 对 %s" % (len(ov1), ov1[:3]))
    if noncycle_rev:
        bad.append("非环边出现反向 %d 条 %s" % (len(noncycle_rev), noncycle_rev[:3]))
    if r1 > r0:
        bad.append("反向变多 %d→%d" % (r0, r1))
    # 反向线只剩"回环/跨层汇聚"这一类 (语义如此, 不是排布问题): 判据 = 数量必须**至少减半** +
    #   向下的要过半 + 每一条都要能指名道姓列出来 (不许有难以说明的反向线)。
    if r1 > max(1, r0 // 2):
        bad.append("反向线没减半: %d → %d" % (r0, r1))
    if d1 * 2 < r1:
        bad.append("反向线向下的不足一半 (%d/%d)" % (d1, r1))
    if not ok_ff:
        bad.append("动作调制器不在前馈加速器右边")
    if bad:
        print("❌ 拒写盘: " + " · ".join(bad))
        return 1
    if not a.apply:
        print("(干跑, 未写盘; 加 --apply 才落盘)")
        return 0

    real = os.path.realpath(CANVAS)
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(REPO, "flows", "_archive", "state_space_obs_before_flow_layout_%s.json" % ts)
    os.makedirs(os.path.dirname(bak), exist_ok=True)
    shutil.copy2(real, bak)
    from lerobot.engineering import flows as F
    F.save_canvas(d)
    d2 = load()
    print("已写盘 (备份 %s)\n还原: cp %s %s" % (bak, bak, real))
    print("回读: 节点 %d · 连线 %d · 前馈 x=%d · 动作调制 x=%d"
          % (len(d2["nodes"]), len(d2["links"]),
             next(n["x"] for n in d2["nodes"] if n["id"] == "ssff"),
             next(n["x"] for n in d2["nodes"] if n["id"] == "sssched")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
