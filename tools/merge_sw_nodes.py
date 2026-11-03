#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_sw_nodes.py — 把 swds / swvideo 合并进 swworld (同一 bridge 脚本的三个开关)

规则:
  ① 删 nodes 里的 swds / swvideo
  ② 指向它们/由它们出发的连线, 端点改挂 swworld
  ③ swworld -> swds / swvideo 的自指边直接删
  ④ 去重, 并检查无悬空引用
自检: 节点 -2 · 连线不悬空 · swworld 出入边清单打印 · 认知层节点数
"""
import argparse
import json
import shutil
import time

P = "data/database/zmax/sources/canvas/state_space_obs.json"
DROP = ("swds", "swvideo")
KEEP = "swworld"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    d = json.load(open(P, encoding="utf-8"))
    n0, l0 = len(d["nodes"]), len(d["links"])
    before = {k: ([x["f"] for x in d["links"] if x.get("t") == k],
                  [x["t"] for x in d["links"] if x.get("f") == k]) for k in DROP + (KEEP,)}

    d["nodes"] = [n for n in d["nodes"] if n.get("id") not in DROP]

    out, seen = [], set()
    for k in d["links"]:
        f, t = k.get("f"), k.get("t")
        if f == KEEP and t in DROP:          # 自指边
            continue
        if f in DROP:
            f = KEEP
        if t in DROP:
            t = KEEP
        if f == t:
            continue
        sig = (f, t, k.get("label") or k.get("name") or "")
        if sig in seen:
            continue
        seen.add(sig)
        k2 = dict(k)
        k2["f"], k2["t"] = f, t
        out.append(k2)
    d["links"] = out

    ids = {n["id"] for n in d["nodes"]}
    dangling = [(k.get("f"), k.get("t")) for k in d["links"]
                if k.get("f") not in ids or k.get("t") not in ids]

    after = {k: ([x["f"] for x in d["links"] if x.get("t") == k],
                 [x["t"] for x in d["links"] if x.get("f") == k]) for k in (KEEP,)}

    print("节点 %d → %d | 连线 %d → %d | 悬空 %d" % (n0, len(d["nodes"]), l0, len(d["links"]), len(dangling)))
    for k in DROP + (KEEP,):
        i, o = before[k]
        print("  改前 %-8s 入 %-28s 出 %s" % (k, i, o))
    print("  改后 %-8s 入 %-28s 出 %s" % (KEEP, after[KEEP][0], after[KEEP][1]))
    if dangling:
        print("❌ 悬空引用:", dangling[:5])
        return 1
    if len(d["nodes"]) != n0 - 2:
        print("❌ 节点数不对")
        return 1

    if a.apply:
        bak = "zmax_data/backup_state_space_obs_%s.json" % time.strftime("%m%d_%H%M%S")
        shutil.copy2(P, bak)
        json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("✅ 已写入 %s (备份 %s)" % (P, bak))
    else:
        print("(dry-run, 加 --apply 才写盘)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
