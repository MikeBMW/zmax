#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_target_pair.py — 双臂**成对**输出 3D 引导位姿, 落到 AR (只写文件, 不下发运动)。

老倪 2026-11-22 定的口径:
  左 3D 引导位姿 = ar3d 左臂前面那块料盘 (最左/最上的一排) 的槽1  ⇒ 围栏「左槽1」几何
  右 3D 引导位姿 = 原来的槽3 (右臂前面那块料盘)                    ⇒ tray_slots_14.json 槽3
  两者成对发布 (TP2=左 / TP1=右), 同一次调用、同一时刻、同 pair_id。

用法:
  ./gui-venv311/bin/python tools/publish_target_pair.py                 # 左槽1 + 右槽3
  ./gui-venv311/bin/python tools/publish_target_pair.py --lslot 2 --rslot 4
  ./gui-venv311/bin/python tools/publish_target_pair.py --clear
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax/src/lerobot/policies/left_right/state_space")

from plan_guide import publish_target, dual_arm_guide              # noqa: E402

FENCE = "/home/ubuntu/zmax/zmax_data/ar_rs/fences.json"


def clear() -> dict:
    with open(FENCE, encoding="utf-8") as fh:
        d = json.load(fh) or {}
    items = d.get("items") or []
    n0 = len(items)
    d["items"] = [x for x in items if str(x.get("id")) not in ("TP1", "TP2")]
    tmp = FENCE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, FENCE)
    return {"ok": True, "removed": n0 - len(d["items"]), "items": len(d["items"])}


def _brief(p: dict) -> dict:
    return {"arm": p.get("arm"), "slot_name": p.get("slot_name"),
            "pos_mm": p.get("pos_mm"), "grasp_mm": p.get("grasp_mm"),
            "pre_pos_mm": p.get("pre_pos_mm"), "quat": p.get("quat"),
            "valid": p.get("valid"), "geom_src": p.get("geom_src"),
            "src": p.get("src")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lslot", type=int, default=1, help="左盘槽号 (围栏 左槽N), 默认 1")
    ap.add_argument("--rslot", type=int, default=3, help="右盘槽号 (tray_slots_14), 默认 3")
    ap.add_argument("--clear", action="store_true")
    a = ap.parse_args()

    if a.clear:
        print(json.dumps(clear(), ensure_ascii=False))
        return 0

    # 🤝 走**测地线引导里的双臂协同**(dual_arm_guide): 一对位姿 + 双真值/分区 owner/hold/间距证据
    pr_pair = dual_arm_guide(None, lslot=a.lslot, rslot=a.rslot)   # atomic: 一侧取不到就整对不发
    if not pr_pair.get("ok"):
        print("❌ 成对目标失效: %s" % pr_pair.get("why"), file=sys.stderr)
        return 1
    pair_id = pr_pair["pair_id"]
    out = {"pair_id": pair_id, "ts": round(time.time(), 3), "L": None, "R": None, "ok": False,
           "atomic": True}
    for tray, slot, key in (("L", a.lslot, "L"), ("R", a.rslot, "R")):
        r = publish_target(slot_id=slot, tray=tray)
        if not r.get("ok"):
            print("❌ %s 臂发布失败: %s" % (key, r.get("err")), file=sys.stderr)
            return 1
        out[key] = _brief(r["pose"])
        out[key]["json"] = r.get("json")

    # 成对证据落一份: 谁和谁是同一对, 什么时候算的
    doc = {"pair_id": pair_id, "ts": out["ts"],
           "t_str": time.strftime("%F %T"), "L": out["L"], "R": out["R"],
           "dual": {"dual_truth": pr_pair.get("dual_truth"), "zone": pr_pair.get("zone"),
                    "min_gap_mm": pr_pair.get("min_gap_mm"), "gap_warn": pr_pair.get("gap_warn"),
                    "hold": pr_pair.get("hold"), "why": pr_pair.get("why"),
                    "pair_valid": pr_pair.get("pair_valid")},
           "note": "双臂成对目标位姿 (测地线引导 dual_arm_guide 产出); 两臂各自只吃自己那一条, 不混发"}
    pj = "/home/ubuntu/zmax/zmax_data/ss_live/target_pose_pair.json"
    tmp = pj + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, pj)
    out["ok"] = True
    out["pair_json"] = pj
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
