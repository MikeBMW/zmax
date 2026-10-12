#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backfill_point_abc.py — 给历史点位补上姿态 a b c (老倪 2026-10-12: 「6 个数字都要记录」)

为什么要补: 点位库从 2026-08 起只存 pos + quat(四元数), a b c 是这次要求的第 4/5/6 个数。
口径 = tools/pt_pose.py (四元数 → RPY 度), 与 8793 页面 tooltip / 配置中心完全同一份实现 ⇒ 不产生第二套数。

作用范围(只补缺的, 已有 abc 的记录一律不动):
  · data/skills/l2_atomic/space_points.json     (空间点1~8)
  · data/skills/l2_atomic/taught_points.json    (示教点/号位/侧面点/准备点/安全点)
  · reports/aoi_points/<点名>.json              (AOI 台账 = 配置中心的真源)

用法:
  gui-venv311/bin/python tools/backfill_point_abc.py --dry     # 先看要改几个
  gui-venv311/bin/python tools/backfill_point_abc.py           # 真写(先备份到 /tmp)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from pt_pose import abc_deg                                                     # noqa: E402

STORE_DIR = os.path.join(ROOT, "data/skills/l2_atomic")
LEDGER_DIR = os.path.join(ROOT, "reports/aoi_points")
STORES = ("space_points.json", "taught_points.json")


def _fill(path: str, dry: bool) -> tuple:
    """给一个"points: {名: {pos,quat,...}}"结构补 abc。返回 (改了几个, 总数)。"""
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
    except Exception as e:                                                      # noqa: BLE001
        return (0, 0, "读不到: %s" % str(e)[:60])
    pts = j.get("points") or {}
    n, tot = 0, 0
    for k, v in pts.items():
        if not isinstance(v, dict):
            continue
        tot += 1
        if isinstance(v.get("abc"), (list, tuple)) and len(v["abc"]) == 3:
            continue
        a = abc_deg(v.get("quat"))
        if not a:
            continue
        v["abc"] = a
        v["abc_src"] = "quat2rpy(backfill %s)" % time.strftime("%Y-%m-%d")
        n += 1
    if n and not dry:
        bak = "/tmp/%s.bak_abc_%s" % (os.path.basename(path), time.strftime("%m%d_%H%M%S"))
        shutil.copy(path, bak)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    return (n, tot, "")


def _fill_ledger(path: str, dry: bool) -> tuple:
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
    except Exception as e:                                                      # noqa: BLE001
        return (0, 0, "读不到: %s" % str(e)[:60])
    if not isinstance(j, dict) or not j.get("pos"):
        return (0, 0, "")
    if isinstance(j.get("abc"), (list, tuple)) and len(j["abc"]) == 3:
        return (0, 1, "")
    a = abc_deg(j.get("quat"))
    if not a:
        return (0, 1, "quat 读不到, 没补")
    j["abc"] = a
    j["abc_src"] = "quat2rpy(backfill %s)" % time.strftime("%Y-%m-%d")
    if not dry:
        bak = "/tmp/%s.bak_abc_%s" % (os.path.basename(path), time.strftime("%m%d_%H%M%S"))
        shutil.copy(path, bak)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    return (1, 1, "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    print("补姿态 a b c —— 口径 tools/pt_pose.py(四元数→RPY 度) · %s"
          % ("演练(不落盘)" if a.dry else "真写(先备份 /tmp)"))
    tot_n = tot_all = 0
    for s in STORES:
        p = os.path.join(STORE_DIR, s)
        n, tot, err = _fill(p, a.dry)
        tot_n += n
        tot_all += tot
        print("  %-20s 补 %d / %d%s" % (s, n, tot, ("  ⛔ " + err) if err else ""))
    try:
        files = sorted(f for f in os.listdir(LEDGER_DIR) if f.endswith(".json"))
    except OSError:
        files = []
    ln = ltot = 0
    for f in files:
        n, tot, _e = _fill_ledger(os.path.join(LEDGER_DIR, f), a.dry)
        ln += n
        ltot += tot
    print("  %-20s 补 %d / %d" % ("reports/aoi_points/", ln, ltot))
    print("\n合计: 补 %d 条 / 共 %d 条" % (tot_n + ln, tot_all + ltot))
    if not a.dry and (tot_n + ln):
        print("   🔴 补完请重跑: gui-venv311/bin/python tools/task_build.py  (把 a b c 推给配置中心)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
