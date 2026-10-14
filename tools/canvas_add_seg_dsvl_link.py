#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧩 canvas_add_seg_dsvl_link.py — 把 SAM3 分割结果接成 **DeepSeek-VL (L5) 的输入选项**

老倪 2026-10-14: 「把 SAM3 节点…作为一个 deepseek vl 的一个输入选项…这个节点的输出, 给输出到 融合定位建图节点」。

落法 (与既有分层不冲突, 只加**一条线**, 不挪任何节点):
  · 能力节点 🧩 开放词汇分割(SAM3) **留在 L2**(感知原语, 与 🎯 YOLO 同级) —— 不搬到 L5。
  · L5 侧接线: `ss_seg:out2 (掩膜/轮廓特征) → n_dsvl:in4`(🧿 DeepSeek-V4-Flash, 场景理解 L5 主路),
    即"分割结果作为大模型的一个输入选项"。in4 是该节点**空闲**入口 (in1 帧/in2 指令/in3 远程提示词)。
  · 「输出给融合定位建图」走既有链: `ss_seg → ss2d3d → sssensor`; 掩膜级 3D 由
    `📡 融合定位建图` 节点直接消费 (2026-10-14 已接通, 判据 tools/verify_seg_into_fusion.py 8/8)。

硬断言 (照 canvas_add_seg_node.py 模板):
  ① 幂等 ② 两端节点存在 ③ 端口在节点声明里 ④ **前向** (f.x+f.w <= t.x, 否则渲染反向线被拦)
  ⑤ 无重复 (f,t,f_port,t_port) ⑥ 不改任何既有连线 / 不改节点集合 / 不动坐标
  ⑦ 写盘只走 flows.save_canvas (自带校验 + 备份), 写后**回读核验**

用法:
    ./gui-venv311/bin/python tools/canvas_add_seg_dsvl_link.py            # dry-run
    ./gui-venv311/bin/python tools/canvas_add_seg_dsvl_link.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

F, FP, T, TP = "ss_seg", "out2", "n_dsvl", "in4"
LID = "lk1014_seg_dsvl"
LABEL = "🧩 掩膜/轮廓+实例清单 → DeepSeek-VL 视觉输入选项 (L5 场景理解)"


def _key(l):
    return json.dumps({k: l.get(k) for k in ("f", "t", "f_port", "t_port")}, sort_keys=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    from lerobot.engineering import flows
    d, _errs = flows.load_canvas()
    ns = {n["id"]: n for n in d["nodes"]}
    links = d["links"]
    probs = []

    if any(_key(l) == _key({"f": F, "t": T, "f_port": FP, "t_port": TP}) for l in links):
        print("① 已存在同样的连线 ⇒ 幂等跳过 (无需改动)")
        return 0
    if any(l.get("id") == LID for l in links):
        probs.append("线 id 冲突: %s" % LID)
    if F not in ns or T not in ns:
        probs.append("端点节点不存在: %s / %s" % (F, T))
    else:
        if FP not in (ns[F].get("outputs") or []):
            probs.append("%s 没有输出口 %s (declared=%s)" % (F, FP, ns[F].get("outputs")))
        if TP not in (ns[T].get("inputs") or []):
            probs.append("%s 没有输入口 %s (declared=%s)" % (T, TP, ns[T].get("inputs")))
        fx = int(ns[F].get("x") or 0) + int(ns[F].get("w") or 0)
        tx = int(ns[T].get("x") or 0)
        if not (fx <= tx):
            probs.append("非前向: %s 右缘 %d > %s 左缘 %d" % (F, fx, T, tx))
        else:
            print("④ 前向成立: %s 右缘 %d ≤ %s 左缘 %d (跨行 L2→L5)" % (F, fx, T, tx))
    if probs:
        print("❌ 断言不过, 拒绝改动:")
        for p in probs:
            print("   -", p)
        return 2

    new = {"id": LID, "f": F, "t": T, "f_port": FP, "t_port": TP, "label": LABEL}
    nodes_before = sorted(ns)
    links_before = [_key(l) for l in links]
    print("② 现有: %d 节点 / %d 连线" % (len(d["nodes"]), len(links)))
    print("③ 新线: %s.%s → %s.%s" % (F, FP, T, TP))
    print("   %s" % LABEL)
    if not a.apply:
        print("(dry-run) 加 --apply 才写盘")
        return 0

    d["links"] = links + [new]
    p, bak = flows.save_canvas(d, reason="add_seg_dsvl_link")
    print("✅ 已写盘: %s" % p)
    if bak:
        print("   ↩️ 还原: cp %s %s" % (bak, p))

    # ⑦ 回读核验: 新线在 + 既有连线逐条不变 + 节点集合不变
    d2 = json.load(open(os.path.realpath(p), encoding="utf-8"))
    l2 = d2["links"]
    ok_new = any(_key(l) == _key(new) for l in l2)
    rest = [_key(l) for l in l2 if _key(l) != _key(new)]
    same_links = sorted(rest) == sorted(links_before)
    same_nodes = sorted(n["id"] for n in d2["nodes"]) == nodes_before
    print("⑤ 回读: 新线在=%s · 既有 %d 条逐条不变=%s · 节点集合不变=%s" % (
        ok_new, len(rest), same_links, same_nodes))
    print("   现在: %d 节点 / %d 连线" % (len(d2["nodes"]), len(l2)))
    return 0 if (ok_new and same_links and same_nodes) else 3


if __name__ == "__main__":
    sys.exit(main())
