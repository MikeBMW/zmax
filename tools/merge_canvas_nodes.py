#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_canvas_nodes.py — 把一个画布节点的功能并入另一个节点 (A → B)

规则:
  ① A 的所有入边改挂 B (B 从此接收 A 的输入 = 承担 A 的职责)
  ② A 的所有出边改从 B 出发 (B 继续向下游供数)
  ③ 去掉 B→B 自环, 连线去重
  ④ 删掉 A 节点
自检: 悬空 0 · 节点 -1 · 连线数相符 · B 的入出边清单打印
"""
import argparse
import json
import shutil
import time

P = "data/database/zmax/sources/canvas/state_space_obs.json"


def load():
    return json.load(open(P, encoding="utf-8"))


def merge(d, A, B):
    n0, l0 = len(d["nodes"]), len(d["links"])
    a_in = [k["f"] for k in d["links"] if k.get("t") == A]
    a_out = [k["t"] for k in d["links"] if k.get("f") == A]
    b_in0 = [k["f"] for k in d["links"] if k.get("t") == B]
    b_out0 = [k["t"] for k in d["links"] if k.get("f") == B]

    d["nodes"] = [n for n in d["nodes"] if n["id"] != A]
    out, seen = [], set()
    for k in d["links"]:
        f, t = k.get("f"), k.get("t")
        if f == A:
            f = B
        if t == A:
            t = B
        if f == t:
            continue
        sig = (f, t, k.get("label") or "")
        if sig in seen:
            continue
        seen.add(sig)
        k2 = dict(k)
        k2["f"], k2["t"] = f, t
        out.append(k2)
    d["links"] = out

    b_in1 = [k["f"] for k in d["links"] if k.get("t") == B]
    b_out1 = [k["t"] for k in d["links"] if k.get("f") == B]
    left = {n["id"] for n in d["nodes"]}
    dangling = [(k.get("f"), k.get("t")) for k in d["links"]
                if k.get("f") not in left or k.get("t") not in left]
    ok = (len(d["nodes"]) == n0 - 1) and not dangling
    print("合并 %s → %s | 节点 %d → %d | 连线 %d → %d | 悬空 %d %s"
          % (A, B, n0, len(d["nodes"]), l0, len(d["links"]), len(dangling), "✅" if ok else "❌"))
    print("   %s 入: %s → %s" % (B, b_in0, b_in1))
    print("   %s 出: %s → %s" % (B, b_out0, b_out1))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True, help="A:B,A2:B2 形式")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    pairs = [p.split(":") for p in a.pairs.split(",") if ":" in p]

    d = load()
    ids = {n["id"] for n in d["nodes"]}
    for A, B in pairs:
        if A not in ids or B not in ids:
            print("❌ 节点不存在: %s / %s" % (A, B))
            return 1
        if not merge(d, A, B):
            return 1
        ids = {n["id"] for n in d["nodes"]}

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
