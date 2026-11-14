#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 在已有运行帧里找「标定板」—— 有板就能用手眼标定, 不用你拖点、不用另打印。

背景(技能台账 2026-09-26 老倪确认): 台面上有一块标定板在**手臂相机正前方**(板面 z≈0.2526)。
⇒ 只要固定轨迹的某些位姿让板进画面, 就能用这些 (板位姿, 机器人位姿) 成对解出 T_tcp_cam。

扫描四族图案, 谁检出就是谁(不预设):
  棋盘格 findChessboardCorners (多尺寸) · 圆阵 findCirclesGrid (对称/非对称)
  ArUco 单标记/板 (DICT_4X4_50 / 5X5_50 / 6X6_250 / ORIGINAL)

输出: zmax_data/reports/board_scan_<ts>.json
"""
import glob
import json
import os
import sys
import time

import cv2
import numpy as np

REPO = os.path.expanduser("~/zmax")
CHESS = [(5, 4), (4, 5), (6, 5), (5, 6), (7, 6), (6, 7), (9, 6), (6, 9), (8, 6), (11, 4), (4, 11)]
CIRC = [(4, 11), (5, 4), (4, 5), (6, 4), (4, 6), (7, 6)]


def try_chess(g):
    for pat in CHESS:
        ok, cs = cv2.findChessboardCorners(g, pat, cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if ok:
            return {"kind": "chess", "pattern": pat, "n": len(cs)}
    return None


def try_circles(g):
    for pat in CIRC:
        for flag, nm in ((cv2.CALIB_CB_SYMMETRIC_GRID, "sym"), (cv2.CALIB_CB_ASYMMETRIC_GRID, "asym")):
            try:
                ok, cs = cv2.findCirclesGrid(g, pat, flags=flag | cv2.CALIB_CB_CLUSTERING)
            except Exception:
                continue
            if ok:
                return {"kind": "circles", "pattern": pat, "mode": nm, "n": len(cs)}
    return None


ARUCO_DICTS = ["DICT_4X4_50", "DICT_5X5_50", "DICT_6X6_250", "DICT_ARUCO_ORIGINAL"]


def try_aruco(g, detectors):
    for name, det in detectors:
        try:
            corners, ids, _ = det.detectMarkers(g)
        except Exception:
            continue
        if ids is not None and len(ids) >= 1:
            return {"kind": "aruco", "dict": name, "n": int(len(ids))}
    return None


def main():
    dirs = sorted(glob.glob(os.path.join(REPO, "zmax_data", "run_capture", "*")))[-2:]
    files = []
    for d in dirs:
        man = os.path.join(d, "manifest.jsonl")
        if not os.path.exists(man):
            continue
        for line in open(man, encoding="utf-8"):
            r = json.loads(line)
            files.append({"cursor": r.get("cursor"), "file": os.path.join(d, r["file"]),
                          "pose_mm": r.get("pose_mm"), "quat": r.get("quat"),
                          "joint_deg": r.get("joint_deg"), "dir": d})
    # 位姿四元数: manifest 里没有 quat ⇒ 按 cursor 从 215 点真轨迹补(禁手推)
    try:
        _tj = json.load(open(os.path.join(REPO, "tools", "web", "real_traj_joints.json"),
                             encoding="utf-8"))["frames"]
    except Exception:
        _tj = []
    for f in files:
        c = f.get("cursor")
        if f.get("quat") is None and isinstance(c, int) and 0 <= c < len(_tj):
            f["quat"] = _tj[c].get("q")
            f["joints_rad"] = _tj[c].get("j")
    if "--all" in sys.argv:      # 全帧扫(不解去重): 板可能只出现在某个瞬间
        uniq = files
    else:
        seen, uniq = set(), []
        for f in files:
            k = f["cursor"]
            if k in seen:
                continue
            seen.add(k)
            uniq.append(f)
    print("候选 %d 帧 (扫描 %d)" % (len(files), len(uniq)))

    detectors = []
    for nm in ARUCO_DICTS:
        if hasattr(cv2, "aruco") and hasattr(cv2.aruco, nm):
            try:
                detectors.append((nm, cv2.aruco.ArucoDetector(
                    cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, nm)),
                    cv2.aruco.DetectorParameters())))
            except Exception:
                pass

    hits = []
    for i, f in enumerate(uniq):
        img = cv2.imread(f["file"])
        if img is None:
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        r = try_chess(g) or try_circles(g) or (try_aruco(g, detectors) if detectors else None)
        if r:
            r.update({"file": f["file"], "cursor": f["cursor"], "pose_mm": f["pose_mm"],
                      "quat": f["quat"], "dir": f["dir"]})
            hits.append(r)
            print("  ✅ 游标 %-4s %s %s n=%d" % (f["cursor"], r["kind"], r.get("pattern") or r.get("dict"), r["n"]))
        if (i + 1) % 100 == 0:
            print("    …扫了 %d/%d, 命中 %d" % (i + 1, len(uniq), len(hits)), flush=True)

    print("-" * 70)
    kinds = {}
    for h in hits:
        k = "%s%s" % (h["kind"], h.get("pattern") or h.get("dict"))
        kinds[k] = kinds.get(k, 0) + 1
    print("命中合计 %d 帧 · 分布 %s" % (len(hits), kinds))
    out = os.path.join(REPO, "zmax_data", "reports", "board_scan_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"n_scanned": len(uniq), "hits": hits}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("明细 %s" % out)
    print("⇒ 若某族命中 ≥8 帧(位姿各异), 可直接解手眼 T_tcp_cam")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
