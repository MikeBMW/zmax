#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_capability_dbc.py — 能力特征库的读取、覆盖率计算与缺口排序

为什么要有这个文件：竞品分析如果只出「谁估值高」，对研发没有约束力。
把竞品能力落成 35 条可测 feature 之后，元任务平台的进度就有了统一的尺子：
  coverage = (done + 0.5*partial) / total
而且每条缺失都能回答三个问题：缺什么、缺了现场会怎样、要不要买硬件。

缺口优先级 = 影响面 × 可纯软件补 × 竞品已有而未普及
  w = 1.0（missing）/ 0.5（partial）
      × 1.6（software_only：不买硬件、不换本体）
      × 1.3（该方向是光模块插拔主战场：精密插拔 / 数据效率）
      ÷ (1 + 0.15*log1p(竞品证据数))        证据越硬越该补

用法：
  python3 tools/ss_capability_dbc.py                 # 打印 + 落 JSON
  python3 tools/ss_capability_dbc.py --json out.json
"""
from __future__ import annotations

import json
import math
import os
import sys

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 跨机：<repo>/tools/x.py
_CAND = [os.path.join(REPO, "capability", "capability_feature.dbc.yaml"),
         os.path.join(REPO, "config", "capability_feature.dbc.yaml"),
         os.path.join(REPO, "data", "database", "zmax", "sources", "config",
                      "capability_feature.dbc.yaml")]
DBC = next((p for p in _CAND if os.path.exists(p)), _CAND[0])
def _out(name):
    base = os.path.expanduser("~/zmax_data/deliverables")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:                                                    # noqa: BLE001
        base = os.path.expanduser("~/evolve")
    return os.path.join(base, name)


OUT = _out("capability_coverage.json")

W_STATUS = {"done": 1.0, "partial": 0.5, "missing": 1.0}   # 覆盖率用 prob；缺口排序里 missing 权重最高
HOT_DIRS = {"精密插拔", "数据效率"}          # 光模块插拔的主战场


def load(path=DBC):
    d = yaml.safe_load(open(path, encoding="utf-8"))
    feats = d["features"]
    ids = [f["id"] for f in feats]
    assert len(ids) == len(set(ids)), "feature_id 重复"
    for f in feats:
        assert f["zmax"] in W_STATUS, "非法状态 %s @ %s" % (f["zmax"], f["id"])
    return d["meta"], feats


def summary(feats):
    n = len(feats)
    cnt = {k: sum(1 for f in feats if f["zmax"] == k) for k in W_STATUS}
    cover = (cnt["done"] + 0.5 * cnt["partial"]) / n
    by_dir = {}
    for f in feats:
        b = by_dir.setdefault(f["dir"], {"n": 0, "done": 0, "partial": 0, "missing": 0, "cover": 0.0})
        b["n"] += 1
        b[f["zmax"]] += 1
    for b in by_dir.values():
        b["cover"] = round((b["done"] + 0.5 * b["partial"]) / b["n"], 4)
    return {"total": n, **cnt, "coverage": round(cover, 4),
            "coverage_pct": round(100 * cover, 1), "by_dir": by_dir}


def gaps(feats, top=12):
    out = []
    for f in feats:
        if f["zmax"] == "done":
            continue
        w = 1.0 if f["zmax"] == "missing" else 0.5
        if f.get("software_only"):
            w *= 1.6
        if f["dir"] in HOT_DIRS:
            w *= 1.3
        w /= (1.0 + 0.15 * math.log1p(1))     # 每条都有至少 1 份证据，作温和归一
        out.append({
            "id": f["id"], "name": f["name"], "dir": f["dir"], "status": f["zmax"],
            "software_only": bool(f.get("software_only")),
            "priority": round(w, 3),
            "metric": f["metric"], "evidence": f["evidence"],
            "note": f.get("zmax_note", ""),
        })
    out.sort(key=lambda x: -x["priority"])
    return out[:top]


def main() -> int:
    meta, feats = load()
    s = summary(feats)
    g = gaps(feats)
    print("能力特征库 %s 版, %d 条" % (meta.get("version"), s["total"]))
    print("覆盖: %.1f%%  = (done %d + 0.5×partial %d) / %d"
          % (s["coverage_pct"], s["done"], s["partial"], s["total"]))
    print("缺口: missing %d / partial %d" % (s["missing"], s["partial"]))
    print("\n分方向:")
    for k, v in sorted(s["by_dir"].items(), key=lambda kv: -kv[1]["n"]):
        print("  %-8s n=%-3d done=%-2d partial=%-2d missing=%-2d  cover=%.0f%%"
              % (k, v["n"], v["done"], v["partial"], v["missing"], 100 * v["cover"]))
    print("\n缺口优先级 Top:")
    for x in g[:8]:
        print("  %.2f  %-11s %-22s %-8s %s" % (x["priority"], x["id"], x["name"],
                                               x["status"], "软件可补" if x["software_only"] else "要硬件"))
    out = {"meta": meta, "summary": s, "gaps": g, "features": feats}
    dest = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else OUT
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    json.dump(out, open(dest, "w"), ensure_ascii=False, indent=1)
    print("\n→", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
