#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""del_canvas_node.py — 从画布真源删除一个节点及其全部连线 (带备份 + 悬空自检)

用法: ./gui-venv311/bin/python tools/del_canvas_node.py --id ssintact [--apply]
"""
import argparse
import json
import shutil
import time

P = "data/database/zmax/sources/canvas/state_space_obs.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="要删的节点 id")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    nid = a.id

    d = json.load(open(P, encoding="utf-8"))
    ids = {n["id"] for n in d["nodes"]}
    if nid not in ids:
        print("❌ 画布上没有 %s" % nid)
        return 1

    ins = [k["f"] for k in d["links"] if k.get("t") == nid]
    outs = [k["t"] for k in d["links"] if k.get("f") == nid]
    n0, l0 = len(d["nodes"]), len(d["links"])

    # 下游失去这个上游后, 还剩几个上游 (判断会不会变成孤岛)
    down = {}
    for t in outs:
        down[t] = [k["f"] for k in d["links"] if k.get("t") == t and k.get("f") != nid]

    d["nodes"] = [n for n in d["nodes"] if n["id"] != nid]
    d["links"] = [k for k in d["links"] if k.get("f") != nid and k.get("t") != nid]

    left = {n["id"] for n in d["nodes"]}
    dangling = [(k.get("f"), k.get("t")) for k in d["links"]
                if k.get("f") not in left or k.get("t") not in left]

    print("删 %s | 节点 %d → %d | 连线 %d → %d | 悬空 %d"
          % (nid, n0, len(d["nodes"]), l0, len(d["links"]), len(dangling)))
    print("  原入边:", ins)
    print("  原出边:", outs)
    for t, rest in down.items():
        print("  下游 %-12s 剩余上游 %d 个: %s" % (t, len(rest), rest))
    if dangling:
        print("❌ 悬空:", dangling[:5])
        return 1

    if a.apply:
        bak = "zmax_data/backup_state_space_obs_%s.json" % time.strftime("%m%d_%H%M%S")
        shutil.copy2(P, bak)
        json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("✅ 已写入 (备份 %s)" % bak)
    else:
        print("(dry-run, 加 --apply 才写盘)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
