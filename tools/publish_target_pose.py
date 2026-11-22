#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_target_pose.py — 让测地线规划引导输出**唯一目标 3D 引导位姿**, 并落到 AR 页面。

用法:
  ./gui-venv311/bin/python tools/publish_target_pose.py --slot 3          # 指定槽位(几何先验, 标"未观测")
  ./gui-venv311/bin/python tools/publish_target_pose.py --fusion          # 用融合模块当前的实测位姿(槽10)
  ./gui-venv311/bin/python tools/publish_target_pose.py --clear           # 撤掉 AR 上的目标位姿层

落点:
  zmax_data/ss_live/target_pose.json      规范 JSON
  zmax_data/ar_rs/fences.json  id=TP1      AR 页 /api/fence 热读 ⇒ 刷新页面即可, 不用重启 8797
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax/src/lerobot/policies/left_right/state_space")

from plan_guide import publish_target, target_pose              # noqa: E402

FENCE = "/home/ubuntu/zmax/zmax_data/ar_rs/fences.json"


def clear() -> dict:
    with open(FENCE, encoding="utf-8") as fh:
        d = json.load(fh) or {}
    n0 = len(d.get("items") or [])
    d["items"] = [x for x in (d.get("items") or []) if str(x.get("id")) != "TP1"]
    tmp = FENCE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, FENCE)
    return {"ok": True, "removed": n0 - len(d["items"]), "items": len(d["items"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", type=int, default=None, help="要输出哪个槽位的目标位姿")
    ap.add_argument("--fusion", action="store_true", help="用融合模块实测位姿(不指定槽位)")
    ap.add_argument("--clear", action="store_true", help="撤掉 AR 上的目标位姿层")
    a = ap.parse_args()

    if a.clear:
        print(json.dumps(clear(), ensure_ascii=False))
        return 0
    if a.slot is None and not a.fusion:
        print("需要 --slot N 或 --fusion 或 --clear", file=sys.stderr)
        return 2

    r = publish_target(slot_id=a.slot if not a.fusion else None)
    if not r.get("ok"):
        print("失败:", r.get("err"), file=sys.stderr)
        return 1
    p = r["pose"]
    print(json.dumps({"pos_mm": p.get("pos_mm"), "quat": p.get("quat"),
                      "pre_pos_mm": p.get("pre_pos_mm"), "valid": p.get("valid"),
                      "slot": p.get("slot"), "src": p.get("src"),
                      "json": r.get("json"), "fence": r.get("fence")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
