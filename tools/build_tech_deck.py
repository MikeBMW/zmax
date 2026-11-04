#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建《Z-MAX 状态空间工程·技术白皮书》PPT

用法: /home/ubuntu/zmax/gui-venv311/bin/python tools/build_tech_deck.py [--out path.pptx]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax/tools")

import deck_content1, deck_content2, deck_content3, deck_content4    # noqa: E402
import deck_content5                                                 # noqa: E402
import deck_content6                                                 # noqa: E402
import deck_lib as L                                                  # noqa: E402

DECK_NAME = deck_content1.DECK


def _key(e):
    """按章节号排序: 导读0 / 正文n.m / 附录7 / 结语8"""
    import re
    if e["k"] == "cover":
        return (-1.0, 0.0)
    if e["k"] == "section":
        return (float(e["num"]), 0.0)
    s = e.get("ch") or e.get("chapter") or ""
    if s == "导读":
        return (0.0, 0.0)
    if s == "结语":
        return (9.0, 0.0)
    m = (re.match(r"^(\d)\.(\d+)", s)
         or re.match(r"^(\d)\.(\d+)", e.get("t", ""))
         or re.match(r"^(\d)\.(\d+)", e.get("title", "")))
    if m:
        return (float(m.group(1)), float(m.group(2)))
    m = re.match(r"^附录\s*([A-Z])", s)
    if m:
        return (7.0, float(ord(m.group(1)) - 64))
    return (6.9, 0.0)


def build(out_path: str) -> int:
    pr = L.new_deck()
    idx = 0
    entries = []
    for mod in (deck_content1, deck_content5, deck_content6, deck_content2, deck_content3, deck_content4):
        entries.extend(mod.CONTENT)
    entries.sort(key=_key)
    if True:
        for e in entries:
            idx += 1
            k = e["k"]
            ch = e.get("ch") or e.get("chapter") or ""
            if k == "cover":
                L.cover(pr, e["t"], e["sub"], e["meta"])
            elif k == "section":
                L.section(pr, e["num"], e["t"], e["desc"], e.get("items"))
            elif k == "bullets":
                L.bullets(pr, idx, DECK_NAME, ch, e["t"], e["items"],
                          sub=e.get("sub", ""), note=e.get("note", ""), size=e.get("size", 15))
            elif k == "formula":
                L.formula(pr, idx, DECK_NAME, ch, e["t"], e["lines"],
                          sub=e.get("sub", ""), note=e.get("note", ""))
            elif k == "table":
                L.table(pr, idx, DECK_NAME, ch, e["t"], e["headers"], e["rows"],
                        sub=e.get("sub", ""), note=e.get("note", ""),
                        col_w=e.get("col_w"), size=e.get("size", 12))
            elif k == "timeline":
                L.timeline(pr, idx, DECK_NAME, ch, e["t"], e["events"],
                           sub=e.get("sub", ""), note=e.get("note", ""))
            elif k == "layers":
                L.layers(pr, idx, DECK_NAME, ch, e["t"], e["rows"],
                         sub=e.get("sub", ""), note=e.get("note", ""))
            elif k == "cards":
                L.cards(pr, idx, DECK_NAME, ch, e["t"], e["items"],
                        sub=e.get("sub", ""), note=e.get("note", ""), cols=e.get("cols", 2))
            elif k == "bigstat":
                L.bigstat(pr, idx, DECK_NAME, ch, e["t"], e["stats"],
                          sub=e.get("sub", ""), note=e.get("note", ""))
            elif k == "nodeblock":
                L.nodeblock(pr, idx, DECK_NAME, ch, e["t"], e["name"], e["ins"], e["outs"],
                            desc=e.get("desc", ""), tick=e.get("tick", ""), code=e.get("code", ""),
                            sub=e.get("sub", ""))
            elif k == "figures":
                L.figures(pr, idx, DECK_NAME, ch, e["t"], e["items"], sub=e.get("sub", ""),
                          note=e.get("note", ""), cols=e.get("cols", 2))
            elif k == "funcmap":
                L.funcmap(pr, idx, DECK_NAME, ch, e["t"], e["rows"],
                          left_title=e.get("left_title", "输入"), left_items=e.get("left_items", ()),
                          right_title=e.get("right_title", "输出"), right_items=e.get("right_items", ()),
                          sub=e.get("sub", ""), note=e.get("note", ""))
            elif k == "quote":
                L.quote(pr, idx, DECK_NAME, "", e["text"], e["source"], title=e.get("title", ""))
            else:
                raise SystemExit(f"unknown kind: {k}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pr.save(out_path)
    print(f"SAVED {out_path} slides={len(pr.slides.__iter__.__self__._sldIdLst)} idx={idx}")
    return idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/home/ubuntu/zmax/zmax_data/deliverables/20261103/"
                                    "Z-MAX状态空间工程_技术白皮书_5.50.C-R6.pptx")
    a = ap.parse_args()
    n = build(a.out)
    print(f"PAGES {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
