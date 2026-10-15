#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_innov_right_feedback.py — 🧪状态校正器挪到**最右侧** + 输出回灌 📡融合定位建图。

老倪 2026-10-15: 「状态校正器是用于反馈物理信号状态的, 当前位置可以放到最右侧; 校正器的输出,
也要接到 融合定位建图 节点, 你来连线即可, 节点位置可以不动」

落法 (只动这一个节点的 x + 加一条线 + 目标加一个入口):
 ① 🧪状态校正器 (ssinnov) x 对齐到全图最右列 (与 🎥操作视频 / 🎯INTACT插拔策略 同列);
    它现在在 9670 (带内已是最右), 但全图最右列是 10450 ⇒ 之前看着"不算最右"。
 ② 它所在行带矩形跟着延长, 否则矩形不包住节点 (界面看着像"掉出带外")。
 ③ 📡融合定位建图 (sssensor) 的 in1~in4 **已全占用** ⇒ 先给它的端口表加 in5 (字符串列表格式),
    再把 ssinnov:out2 → sssensor:in5 接上。老倪说目标节点位置不动 ⇒ 不动。
 ④ 这条线按语义**必然是反向** (右下 → 左上, 物理状态回灌闭环), 与"左上→右下"主轴相反 —— 如实记录为
    **反馈线**, 不装作是前向线。已有反向线 (ssinnov→sssched 等) 同属这一类。

判据 (不达标拒写盘): 节点/线数只增这一条 · 无重复线 · 功能节点零重叠 · 端口格式是字符串列表
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
CANVAS = os.path.realpath(os.path.join(REPO, "flows", "state_space_obs.json"))
BG_TYPES = ("bg", "row_bg")
RIGHT_COL = 10450          # 全图最右功能节点的 x (与 操作视频 / INTACT插拔策略 同列)


def main():
    a = "--apply" in sys.argv
    d = json.load(open(CANVAS, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    by = {n["id"]: n for n in nodes}
    assert "ssinnov" in by and "sssensor" in by, "找不到 状态校正器 / 融合定位建图"
    ff, sn = by["ssinnov"], by["sssensor"]

    # ── ① 挪到最右列 (老倪: "最右侧") ──────────────────────────────────────
    old_x = ff["x"]
    ff["x"] = int(RIGHT_COL)

    # ── ② 行带矩形跟着延长 (bg 不包住节点 = 界面看着掉出带外) ────────────────
    band = None
    for b in nodes:
        if b.get("type") in BG_TYPES and b["y"] <= old_x * 0 + ff["y"] < b["y"] + b.get("h", 294):
            band = b
            break
    assert band is not None, "状态校正器不在任何行带里"
    need_r = ff["x"] + int(ff.get("w", 280)) + 40
    if band["x"] + band["w"] < need_r:
        band["w"] = int(need_r - band["x"])

    # ── ③ 目标节点补齐端口 (in1~in4 已占) ─────────────────────────────────
    ins = sn.get("inputs") or []
    assert all(isinstance(x, str) for x in ins), "目标节点端口不是字符串列表, 先归一"
    new_port = "in5"
    if new_port not in ins:
        sn["inputs"] = list(ins) + [new_port]

    # ── ④ 接线 (无重复) ───────────────────────────────────────────────────
    f_port, t_port = "out2", new_port
    used_out = {l.get("f_port") for l in links if l.get("f") == "ssinnov"}
    if f_port in used_out:
        assert any(l["f"] == "ssinnov" and l.get("f_port") == f_port
                   and l["t"] == "sssensor" for l in links), "out2 已被别的线占用"
    dup = [l for l in links if l["f"] == "ssinnov" and l["t"] == "sssensor"]
    if not dup:
        links.append({
            "id": "lkinnov_sensor",
            "f": "ssinnov", "t": "sssensor", "f_port": f_port, "t_port": t_port,
            "label": "↩ 物理状态回灌: 校正后的状态 → 融合定位建图 (闭环)",
        })

    # ── 判据 ──────────────────────────────────────────────────────────────
    funcs = [n for n in nodes if n.get("type") not in BG_TYPES]
    ov = []
    for i in range(len(funcs)):
        for j in range(i + 1, len(funcs)):
            A, B = funcs[i], funcs[j]
            if (A["x"] < B["x"] + B.get("w", 280) and B["x"] < A["x"] + A.get("w", 280)
                    and A["y"] < B["y"] + B.get("h", 110) and B["y"] < A["y"] + A.get("h", 110)):
                ov.append((A["id"], B["id"]))
    rev = []
    for l in links:
        if l["f"] in by and l["t"] in by:
            fx, fy, fw = by[l["f"]]["x"], by[l["f"]]["y"], by[l["f"]].get("w", 280)
            if fx + fw > by[l["t"]]["x"]:
                rev.append((l["f"], l["t"], by[l["t"]]["y"] - fy))

    print("状态校正器 x: %d → %d (最右列 %d)" % (old_x, ff["x"], RIGHT_COL))
    print("新线: ssinnov:%s → sssensor:%s · 节点 %d · 连线 %d" % (f_port, t_port, len(nodes), len(links)))
    print("功能节点重叠 %d 对 %s" % (len(ov), ov[:3]))
    print("反向线 %d 条 (反馈/回环):" % len(rev))
    for r in rev:
        print("   %-14s → %-14s Δy=%+6d" % r)
    need = []
    if ov:
        need.append("重叠")
    if len(links) != 191:
        need.append("线数 %d != 191" % len(links))
    if len(nodes) != 89:
        need.append("节点数 %d != 89" % len(nodes))
    if need:
        print("❌ 拒写盘: %s" % " · ".join(need))
        return 1
    if not a:
        print("(干跑; 加 --apply 落盘)")
        return 0

    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(REPO, "flows", "_archive", "state_space_obs_before_innov_right_%s.json" % ts)
    os.makedirs(os.path.dirname(bak), exist_ok=True)
    shutil.copy2(CANVAS, bak)
    from lerobot.engineering import flows as F
    F.save_canvas(d)
    d2 = json.load(open(CANVAS, encoding="utf-8"))
    b2 = {n["id"]: n for n in d2["nodes"]}
    print("已写盘 · 备份 %s\n还原: cp %s %s" % (bak, bak, CANVAS))
    print("回读: 节点 %d · 连线 %d · 校正器 x=%d · 建图 in=%s" % (
        len(d2["nodes"]), len(d2["links"]), b2["ssinnov"]["x"], b2["sssensor"]["inputs"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
