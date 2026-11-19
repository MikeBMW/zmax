#!/usr/bin/env python3
"""gs_merge_ply.py — 把「全局模型」和「插口细节模型」合并成一个 gs.ply。

原理: 3DGS 就是一堆高斯; 只要两个模型在**同一场景系、同一归一化(center,S)** 下,
直接拼接属性数组在数学上等价于"两个模型同时渲染"。
前提必须核实: 两份 train_report.json 的 normalize.center 与 S 一致 (同一批相机位姿)。

用法:
  python3 tools/gs_merge_ply.py --a <全局>/gs.ply --rep-a <全局>/train_report.json \
      --b <细节>/gs.ply --rep-b <细节>/train_report.json --out <合并>/gs.ply
"""
import argparse
import json
import sys

import numpy as np

try:
    from plyfile import PlyData, PlyElement
except Exception:                                                       # noqa: BLE001
    PlyData = None


def load(path):
    if PlyData is None:
        raise SystemExit("需要 plyfile: pip install plyfile")
    ply = PlyData.read(path)
    el = ply["vertex"]
    names = [p.name for p in el.properties]
    return {n: np.asarray(el[n]) for n in names}, names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--rep-a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--rep-b", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tol", type=float, default=1e-4, help="归一化一致性容差")
    a = ap.parse_args()
    ra = json.load(open(a.rep_a, encoding="utf-8")).get("normalize") or {}
    rb = json.load(open(a.rep_b, encoding="utf-8")).get("normalize") or {}
    ca, sa = np.array(ra.get("center") or [0, 0, 0], float), float(ra.get("S") or 1.0)
    cb, sb = np.array(rb.get("center") or [0, 0, 0], float), float(rb.get("S") or 1.0)
    dc, ds = float(np.abs(ca - cb).max()), abs(sa - sb)
    print("归一化比对: Δcenter=%.3e · ΔS=%.3e (容差 %.1e)" % (dc, ds, a.tol))
    if dc > a.tol or ds > a.tol:
        print("❌ 两份模型不在同一归一化下, 直接拼接会错位 ⇒ 拒绝合并")
        return 2
    A, names_a = load(a.a)
    B, names_b = load(a.b)
    common = [n for n in names_a if n in names_b]
    if len(common) != len(names_a) or len(common) != len(names_b):
        print("❌ 属性不一致: A=%d B=%d 交集=%d" % (len(names_a), len(names_b), len(common)))
        return 3
    merged = {}
    for n in common:
        merged[n] = np.concatenate([A[n], B[n]], 0)
    n = len(merged[common[0]])
    dtype = [(n_, merged[n_].dtype) for n_ in common]
    arr = np.zeros(n, dtype=dtype)
    for n_ in common:
        arr[n_] = merged[n_]
    el = PlyElement.describe(arr, "vertex")
    PlyData([el]).write(a.out)
    print(json.dumps({"ok": True, "out": a.out, "n_a": int(len(A[common[0]])),
                      "n_b": int(len(B[common[0]])), "n_total": n}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
