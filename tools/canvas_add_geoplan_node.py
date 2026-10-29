#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_add_geoplan_node.py — 画布加「🧭 测地线块规划」节点 (老倪 2026-10-29 定序)

要求: 「YOLO → 融合定位 → 状态空间(obs) → 运动规划 ‖ 前馈MLP → 加权 → 动作调制器
       → 安全执行边界 → 原子技能派发 → 动作执行器 → 机器人」
  · 这里的「运动规划」是**状态空间测地线块规划**, 与前馈 MLP 同位并列, 同在加权之前;
  · 与既有 n_moveit (MoveIt 关节空间规划, 在技能之后) 是两个不同的东西, 不合并、不改名。

入线: 🧩 SU(2) 统一状态空间(ssobs) → 测地线块规划   (obs 43D)
出线: 测地线块规划 → 🧭 动作调制器(sssched)          (块 [H,4] → 加权/调制, 与前馈 u_ff 汇合)
硬断言: id 唯一 / int 坐标 / 零重叠 / 端口存在 / 前向 / 无重复连线; 写盘走 flows.save_canvas (原子+备份+工程库同步)
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/home/ubuntu/zmax/src")
from lerobot.engineering import flows  # noqa: E402

NID = "n_geoplan"
NAME = "🧭 测地线块规划 · 指数映射+slerp (H=8)"
DESC = ("obs43 → ManifoldEngine.project(潜空间) → 目标点(本段目标槽 obs[36:39]) → "
        "navigator.compute_geodesic(H 步, 指数映射+slerp) → readout ridge 解码(限幅) → 块 chunk[H,4]。"
        "与块流水线 tools/ss_chunk_pipeline.py::_chunk 逐行同源; 只出块, 不下发、不碰授权。"
        "注意: 与 n_moveit (MoveIt 关节空间规划, 在原子技能之后) 不是同一个节点。"
        "源码 src/lerobot/engineering/nodes/geo_plan_impl.py")
BGW = ("bg", "row_bg")


def overlaps(a, b, pad=6):
    return not (a["x"] + a["w"] + pad <= b["x"] or b["x"] + b["w"] + pad <= a["x"] or
                a["y"] + a["h"] + pad <= b["y"] or b["y"] + b["h"] + pad <= a["y"])


def main(dry=True):
    d, errs = flows.load_canvas()
    if errs:
        print("画布校验有错, 停:", errs[:3])
        return 1
    nodes, links = d["nodes"], d["links"]
    by = {n["id"]: n for n in nodes}
    if NID in by:
        print("节点已存在:", NID)
        return 1

    ff = by["ssff"]
    # 位置: 与前馈加速器**同一行**, 在其右侧 40px (语义: 规划 ‖ 前馈, 规划在右)
    x = int(ff["x"] + ff["w"] + 40)
    y = int(ff["y"])
    node = {"id": NID, "type": "model", "name": NAME, "x": x, "y": y, "w": 280, "h": 110,
            "desc": DESC, "inputs": ["in1", "in2"], "outputs": ["out1"],
            "params": {"state_space": True, "geo_chunk": {"H": 8, "latent": 16, "state_dim": 43,
                                                          "manifold": "SU(2)", "M": 3.643,
                                                          "decode": "ridge (readout + readout_b, 硬限幅)"},
                       "role": "运动规划支 (与前馈 MLP 并列, 进加权)",
                       "desc": DESC, "source": "src/lerobot/engineering/nodes/geo_plan_impl.py",
                       "source_symbol": "run",
                       "_port_labels": {"in1": "obs 43D", "in2": "目标点(可选)", "out1": "块 chunk[H,4]"}}}
    for n in nodes:
        if n.get("type") in BGW:
            continue
        assert not overlaps(node, n), "与 %s(%s) 重叠" % (n["id"], (n.get("name") or "")[:18])

    # 端口: sssched 需要一个新入口 (现 in1..in8 已被技能/记忆/质量门等占满)
    by[NID] = node
    if "in9" not in (by["sssched"].get("inputs") or []):
        by["sssched"]["inputs"] = list(by["sssched"].get("inputs") or []) + ["in9"]
    new_links = []
    for f, t, fp, tp, lb in (("ssobs", NID, "out1", "in1", "obs 43D → 潜空间测地线规划"),
                             (NID, "sssched", "out1", "in9", "规划块 chunk[H,4] → 加权(与 u_ff 汇合)→ 调制")):
        assert fp in (by[f].get("outputs") or []), "%s 无出端口 %s" % (f, fp)
        assert tp in (by[t].get("inputs") or []), "%s 无入端口 %s" % (t, tp)
        assert (f, t) not in [(l["f"], l["t"]) for l in links], "重复连线 %s→%s" % (f, t)
        new_links.append({"f": f, "t": t, "f_port": fp, "t_port": tp, "label": lb})

    print("新增节点: %s @ (%d,%d) 280x110  (前馈加速器同排, 右侧 40px)" % (NAME, x, y))
    for l in new_links:
        print("  连线:", l["f"], "→", l["t"], "|", l["label"])
    print("前: %d 节点 / %d 连线  →  后: %d 节点 / %d 连线" %
          (len(nodes), len(links), len(nodes) + 1, len(links) + len(new_links)))
    if dry:
        print("(--dry-run 未写盘)")
        return 0
    nodes.append(node)
    links.extend(new_links)
    p, bak = flows.save_canvas(d, reason="add-n_geoplan-geodesic-chunk-planner")
    print("✅ 已写:", p, "\n   备份:", bak)
    d3, _ = flows.load_canvas()
    print("回读: %d 节点 / %d 连线 · n_geoplan 在位 %s" %
          (len(d3["nodes"]), len(d3["links"]), any(n["id"] == NID for n in d3["nodes"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(dry="--apply" not in sys.argv))
