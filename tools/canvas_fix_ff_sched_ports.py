#!/usr/bin/env python3
"""把「⚡ 前馈加速器 → 🧭 动作调制器」这条线的端口/标签写实 (老倪 2026-10-15)

老倪: 「前馈加速器的输出，要连到动作调制器；前馈加速器是 L2 功能一个状态预测模型，使用 MLP 实现；
这个预测的状态，进入动作调制器，变成规范动作」

现状 (改前实测):
  · 线 **已存在**: lkff_sched  ssff:out2 → sssched:in6  label「前馈 u_ff → 动作融合」
  · 但 ssff 只声明了 outputs=["out1"]，实际出线用了 out1(激活探针) 与 **out2**(u_ff 两条: →调制器/→INTACT)
    ⇒ 端口表与线不一致 (工程库/渲染显示不出 out2 的语义)
  · 标签太笼统，看不出「MLP 快通道 / 按阶段限速 ⇒ 规范动作」

本脚本只改: ① ssff.outputs 补 out2 + 端口语义标 _port_labels ② 该线与 in6 端口写上明确标签。
不动任何坐标、不删/不加线 (改后逐条比对: 线数不变, 节点坐标不变)。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "src"))
from lerobot.engineering import flows                                    # noqa: E402

LID = "lkff_sched"
NEW_LABEL = "⚡ 前馈加速器 u_ff (L2 · MLP 快通道, 权重30%) → 动作调制器融合 · 按阶段限速扣除幅 ⇒ 规范动作 u"


def main():
    d, _e = flows.load_canvas(validate=True)
    ns = {n["id"]: n for n in d["nodes"]}
    ff, sc = ns["ssff"], ns["sssched"]
    geom_before = {n["id"]: (n.get("x"), n.get("y"), n.get("w"), n.get("h")) for n in d["nodes"]}
    links_before = [json.dumps(l, ensure_ascii=False, sort_keys=True) for l in d["links"]]

    ff["outputs"] = ["out1", "out2"]
    ff.setdefault("params", {}).setdefault("_port_labels", {}).update(
        {"out1": "🔍 激活探针 (隐层激活 → 直方图)", "out2": "⚡ u_ff 建议动作 (L2 MLP 快通道, 4D)"})
    for l in d["links"]:
        if l.get("id") == LID:
            l["label"] = NEW_LABEL
    hit = [l for l in d["links"] if l.get("id") == LID]
    assert hit and hit[0]["f_port"] == "out2" and hit[0]["t_port"] == "in6", "线不是预期的 out2→in6"

    p, bak = flows.save_canvas(d, reason="ff_out2_ports")
    print("✅ 已写盘 %s\n   备份 %s" % (p, bak))
    d2, _e2 = flows.load_canvas(validate=True)
    ns2 = {n["id"]: n for n in d2["nodes"]}
    geom_after = {n["id"]: (n.get("x"), n.get("y"), n.get("w"), n.get("h")) for n in d2["nodes"]}
    assert geom_before == geom_after, "坐标被改动!"
    assert len(d2["links"]) == len(d["links"]), "线数变了!"
    ids_b = {l["id"] for l in d["links"]}
    ids_a = {l["id"] for l in d2["links"]}
    assert ids_b == ids_a, "线集合变了!"
    print("   坐标逐节点一致 ✅ · 线 %d 条集合一致 ✅ · ssff.outputs=%s"
          % (len(d2["links"]), ns2["ssff"]["outputs"]))
    print("   线标签: %s" % [l["label"] for l in d2["links"] if l["id"] == LID][0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
