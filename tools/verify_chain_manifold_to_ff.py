#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_chain_manifold_to_ff.py — 老倪点名的那条数据链逐跳核验 (只读画布, 不改)。

老倪 2026-10-15: 「流形引擎 → INTACT意图解码 → INTACT微调解码 → 流形专家预测器 → 接触流形节点和性能流形节点
的输出, 已经给到了 DiT, 再给到前馈加速器, 这条数据链图, 是通的么?」

判据: 逐跳都**存在直连的线** (不是"能绕到"), 每跳打印 源→靶 + 端口 + 标签; 缺哪跳报哪跳。
另附: 这条路对 ⚡前馈加速器 的**直接入端**是什么 (in 端口哪些线进来)。
"""
from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.realpath(os.path.join(REPO, "flows", "state_space_obs.json")), encoding="utf-8"))
N = {n["id"]: n for n in d["nodes"]}
E = {}
for l in d["links"]:
    E.setdefault(l["f"], []).append(l)

HOPS = [
    ("ss_mani_eng", "ssintact_dec", "流形引擎", "INTACT 意图解码器"),
    ("ssintact_dec", "ss_lora_l4", "INTACT 意图解码器", "INTACT LoRA 微调 (微调解码)"),
    ("ss_lora_l4", "ssmani_exp", "INTACT LoRA 微调", "流形专家预测器"),
    ("ssmani_exp", "ssmani_c", "流形专家预测器", "接触流形 · 导航地图"),
    ("ssmani_exp", "ssmani_p", "流形专家预测器", "性能流形 · 耦合代价"),
    ("ssmani_c", "ssdec", "接触流形 · 导航地图", "DiT (Flow-Matching Action Head)"),
    ("ssmani_p", "ssdec", "性能流形 · 耦合代价", "DiT (Flow-Matching Action Head)"),
    ("ssdec", "ssff", "DiT", "⚡ 前馈加速器"),
]
ok = True
print("逐跳核验 (直连线, 不是\"能绕到\"):")
for f, t, fn, tn in HOPS:
    hit = [l for l in E.get(f, []) if l["t"] == t]
    mark = "✅" if hit else "❌"
    ok = ok and bool(hit)
    lab = (hit[0].get("label") or "")[:52] if hit else "—"
    print("   %s %-22s → %-30s %s | %s" % (mark, fn, tn,
                                          ("%s:%s→%s" % (f, hit[0].get("f_port"), hit[0].get("t_port"))) if hit else "",
                                          lab))
print("\n⚡ 前馈加速器 的**入端线** (谁真喂它):")
for l in d["links"]:
    if l["t"] == "ssff":
        print("   %-12s %-5s → in %-5s | %s" % (l["f"], l.get("f_port"), l.get("t_port"),
                                                (l.get("label") or "")[:60]))
print("\n⚡ 前馈加速器 的**出端线**:")
for l in E.get("ssff", []):
    print("   out %-5s → %-12s %-5s | %s" % (l.get("f_port"), l["t"], l.get("t_port"),
                                             (l.get("label") or "")[:60]))
print("\n结论: %s" % ("✅ 这条链在图上**是通的** (8/8 跳都有直连线)" if ok else "❌ 有断链, 见上面的 ❌"))
sys.exit(0 if ok else 1)
