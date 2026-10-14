#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画布重排: L4 后段链 —— INTACT 意图解码器 → **INTACT LoRA 微调** → 流形专家预测器 → 接触/性能流形

老倪 2026-10-14: 「L4 INTACT LoRA 微调节点接到 INTACT 意图解码器后面 (不想动 INTACT 原始权重,
只改 LoRA 节点)；元任务预测节点的输出也要接到 LoRA 节点；然后向后连接流形专家预测器、
以及接触流形、性能流形。UI 连线顺序改正确。」

幂等: 已有边就改标签, 缺的补, 绕过的旁路边删掉; 位置按左→右顺序摆好。改前备份, 改后回读校验。
"""
from __future__ import annotations

import json
import shutil
import sys
import time

CANVAS = "/home/ubuntu/zmax/data/database/zmax/sources/canvas/state_space_obs.json"

# (f, t, f_port, t_port, label)
WANT = [
    ("ssintact_dec", "ss_lora_l4", "out1", "in1", "意图 m_int (z_t / Δz) → LoRA 条件 (原权重冻结)"),
    ("n_intent_direct", "ss_lora_l4", "out1", "in2", "元任务预测值 → LoRA 增益门控 γ_eff"),
    ("ss_lora_l4", "ssmani_exp", "out1", "in1", "LoRA 适配后的条件 u_lora → 预测器条件"),
    ("ss_lora_l4", "ssmani_c", "out2", "in2", "u_lora → 接触流形约束 (摩擦锥/穿透罚)"),
    ("ss_lora_l4", "ssmani_p", "out3", "in2", "u_lora → 性能流形约束 (V_p/η · 黎曼梯度)"),
    ("ss_lora_l4", "ssdec", "out4", "in1", "L4 条件 (LoRA 后) → L3 DiT"),
]
# 被 LoRA 节点取代的旁路边 (直连会绕过微调, 与"接在解码器后面"矛盾)
DROP = [("ssintact_dec", "ssmani_exp"), ("ssintact_dec", "ssdec")]
# UI 顺序: 同一行左→右 (x), 元任务预测摆到 LoRA 左下方
POS = {"ss_lora_l4": (10430, 1546), "n_intent_direct": (9600, 1720)}


def main() -> int:
    d = json.load(open(CANVAS, encoding="utf-8"))
    links, nodes = d["links"], {n["id"]: n for n in d["nodes"]}
    assert "ss_lora_l4" in nodes, "画布缺 ss_lora_l4 节点"
    bak = "%s.bak_before_l4_lora_chain_%s" % (CANVAS, time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(CANVAS, bak)
    changed = []

    # ① 删旁路
    for f, t in DROP:
        for l in [x for x in links if x.get("f") == f and x.get("t") == t]:
            links.remove(l)
            changed.append("删旁路 %s→%s" % (f, t))

    # ② 补/改目标边
    for f, t, fp, tp, lab in WANT:
        hit = [x for x in links if x.get("f") == f and x.get("t") == t]
        if hit:
            hit[0]["label"], hit[0]["f_port"], hit[0]["t_port"] = lab, fp, tp
            changed.append("改标签 %s→%s" % (f, t))
        else:
            nid = "lk_l4_%s_%s" % (f, t)
            while any(x.get("id") == nid for x in links):
                nid += "x"
            links.append({"id": nid, "f": f, "t": t, "f_port": fp, "t_port": tp, "label": lab})
            changed.append("新增 %s→%s" % (f, t))

    # ③ UI 位置 (左→右)
    for nid, (x, y) in POS.items():
        if (nodes[nid].get("x"), nodes[nid].get("y")) != (x, y):
            changed.append("移 %s (%s,%s)→(%s,%s)" % (nid, nodes[nid].get("x"), nodes[nid].get("y"), x, y))
            nodes[nid]["x"], nodes[nid]["y"] = x, y
    nm = "🎛 L4 · INTACT LoRA 微调 (接在意图解码器后 · 冻结原权重 · 只调 ΔW=(α/r)BA)"
    if nodes["ss_lora_l4"].get("name") != nm:
        nodes["ss_lora_l4"]["name"] = nm
        changed.append("改名 ss_lora_l4")

    json.dump(d, open(CANVAS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    chk = json.load(open(CANVAS, encoding="utf-8"))
    got = {(x.get("f"), x.get("t")) for x in chk["links"]}
    miss = [(f, t) for f, t, *_ in WANT if (f, t) not in got]
    left = [(f, t) for f, t in DROP if (f, t) in got]
    print("改动 %d 项:" % len(changed))
    for c in changed:
        print("   ·", c)
    print("回读: 目标边缺 %s · 旁路残留 %s · 边数 %d" % (miss or "无", left or "无", len(chk["links"])))
    print("UI 顺序 (x 递增): INTACT 意图解码器 %s → L4 LoRA %s → 流形专家预测器 %s → 接触 %s → 性能 %s → DiT %s"
          % (nodes["ssintact_dec"]["x"], nodes["ss_lora_l4"]["x"], nodes["ssmani_exp"]["x"],
             nodes["ssmani_c"]["x"], nodes["ssmani_p"]["x"], nodes["ssdec"]["x"]))
    print("备份:", bak)
    return 1 if (miss or left) else 0


if __name__ == "__main__":
    sys.exit(main())
