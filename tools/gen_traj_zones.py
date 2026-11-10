# -*- coding: utf-8 -*-
"""gen_traj_zones — 从 AR 场景真实轨迹派生命名区域 (不改工程真源 env_model.json)。

为什么要有这一层:
  env_model.json::zones 是"点位台账聚类"出来的 5 个区, 实测覆盖不到工作空间全貌 ——
  AR 三条可用轨迹共 96 点, 只有 11 点(11.5%)落在命名区内, 其余全进"其它"。
  ⇒ 位姿驱动的感知调度会大段时间处于"无区可依"。

做法 (派生层, 不污染真源):
  ① 读 8797 /api/traj/named 的轨迹真点
  ② 按轨迹语义切成区, bbox = 实测点集 + margin
  ③ 落 config/calib/traj_zones.json, 由 camera_scheduler 以"低优先级"合并
     (同名时 env_model 胜出 ⇒ 工程配置永远优先)

用法: gui-venv311/bin/python tools/gen_traj_zones.py [--margin-mm 30]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "config", "calib", "traj_zones.json")

# 轨迹 key → 区域定义。只登记"整条轨迹构成一片作业区"的, 不硬套。
TRAJ_ZONE = {
    "xiaohong": {
        "zone": "运输直线通道",
        "why": "轨迹1 · 小红: x=0.70 固定, y 从 +0.20 到 -0.20, z=0.36 的横向搬运直线",
        "cams": {"local2": "overview", "arm": "guide"},
    },
    "map": {
        "zone": "建图扫描区",
        "why": "轨迹3 · 建图: 3 行 40 点 937mm 覆盖路径, z=0.23 —— 需要深度源",
        "cams": {"rs": "localize", "local2": "overview"},
    },
}


def get(u):
    with urllib.request.urlopen(u, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def bbox_of(pts, margin_m):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    return {
        "x": [round(min(xs) - margin_m, 4), round(max(xs) + margin_m, 4)],
        "y": [round(min(ys) - margin_m, 4), round(max(ys) + margin_m, 4)],
        "z": [round(min(zs) - margin_m, 4), round(max(zs) + margin_m, 4)],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--margin-mm", type=float, default=30.0)
    ap.add_argument("--host", default="http://127.0.0.1:8797")
    a = ap.parse_args()
    margin_m = a.margin_mm / 1000.0

    out = {
        "_doc": "AR 轨迹派生的作业区 —— 非工程真源; env_model.json::zones 优先。由 tools/gen_traj_zones.py 生成。",
        "_gen": "tools/gen_traj_zones.py",
        "_margin_mm": a.margin_mm,
        "zones": {},
    }
    for key, meta in TRAJ_ZONE.items():
        d = get("%s/api/traj/named?k=%s" % (a.host, key))
        pts = d.get("pts") or []
        if not pts:
            print("跳过 %s: 无点 (%s)" % (key, (d.get("note") or "")[:60]))
            continue
        p3 = [tuple(float(v) for v in p[:3]) for p in pts]
        z = meta["zone"]
        out["zones"][z] = {
            "n": len(p3),
            "bbox": bbox_of(p3, margin_m),
            "points": [],
            "cams": meta["cams"],
            "_src": "8797 /api/traj/named?k=%s" % key,
            "_label": d.get("label"),
            "_why": meta["why"],
            "_endpoints": [list(p3[0]), list(p3[-1])],
        }
        print("✅ %-8s n=%-3d bbox x%s y%s z%s" % (z, len(p3),
                                                 out["zones"][z]["bbox"]["x"],
                                                 out["zones"][z]["bbox"]["y"],
                                                 out["zones"][z]["bbox"]["z"]))

    if not out["zones"]:
        print("❌ 没有生成任何区 (8797 不可达?)")
        return 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print("\n写出 %s (%d B, %d 区)" % (OUT, os.path.getsize(OUT), len(out["zones"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
