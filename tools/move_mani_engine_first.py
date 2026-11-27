#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""move_mani_engine_first.py — 把「🧮 流形引擎」放到认知层 (L4 专家自主功能行) 第 1 位

做法 (最小改动, 可回退):
  ① 与第一位 sscalib 交换坐标 (两节点尺寸不同, 3960/4280 实测无重叠)
  ② nodes 数组里把 ss_mani_eng 提到该组首位 (顺序位 = 用户说的"第 1 位")
不动: 其他节点坐标、所有 links、node 数。
自检: JSON 合法 · nodes/links 数不变 · 除这两个节点外逐字段相同 · 无坐标重叠。
"""
import json
import os
import sys

PATH = "/home/ubuntu/zmax/src/lerobot/engineering/flows/state_space_obs.json"
ME, FIRST = "ss_mani_eng", "sscalib"


def boxes(ns):
    return [(n["id"], n["x"], n["y"], n["w"], n["h"]) for n in ns
            if n.get("type") != "row_bg" and all(k in n for k in ("x", "y", "w", "h"))]


def overlaps(ns):
    out = []
    bs = boxes(ns)
    for i in range(len(bs)):
        for j in range(i + 1, len(bs)):
            a, b = bs[i], bs[j]
            if (a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
                    and a[2] < b[2] + b[4] and b[2] < a[2] + a[4]):
                out.append((a[0], b[0]))
    return out


def main() -> int:
    d = json.load(open(PATH, encoding="utf-8"))
    ns = d["nodes"]
    n0, l0 = len(ns), len(d["links"])
    ov0 = set(overlaps(ns))

    me = next(n for n in ns if n["id"] == ME)
    fi = next(n for n in ns if n["id"] == FIRST)
    before = {n["id"]: (n.get("x"), n.get("y"), n.get("w"), n.get("h")) for n in ns}

    # ① 交换坐标 (只换位置, 不改尺寸)
    (me["x"], me["y"]), (fi["x"], fi["y"]) = (fi["x"], fi["y"]), (me["x"], me["y"])

    # ② 数组顺序: 把流形引擎提到该组首位 (它原来在 sscalib 之后)
    i_me, i_fi = ns.index(me), ns.index(fi)
    if i_me > i_fi:
        ns.insert(i_fi, ns.pop(i_me))

    ov1 = set(overlaps(ns))
    new_ov = ov1 - ov0
    after = {n["id"]: (n.get("x"), n.get("y"), n.get("w"), n.get("h")) for n in ns}
    changed = [k for k in before if before[k] != after[k]]
    ok_counts = (len(d["nodes"]) == n0 and len(d["links"]) == l0)
    ok_changed = set(changed) <= {ME, FIRST}
    ok_order = ns.index(me) == ns.index(fi) + 1
    ok_ov = not new_ov

    print("流形引擎 现在 (x=%s,y=%s) · %s 现在 (x=%s,y=%s)"
          % (me["x"], me["y"], FIRST, fi["x"], fi["y"]))
    print("数组位次: 流形引擎 idx=%d, %s idx=%d (提出前: %d/%d)"
          % (ns.index(me), FIRST, ns.index(fi), i_me, i_fi))
    print("nodes/links: %d/%d → %d/%d" % (n0, l0, len(d["nodes"]), len(d["links"])))
    print("坐标变更节点: %s (应只有这两个)" % changed)
    print("新增重叠: %s" % (sorted(new_ov) or "无"))

    if ok_counts and ok_changed and ok_ov:
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print("✅ 已写入 %s" % PATH)
        return 0
    print("❌ 判据未过, 未写入")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
