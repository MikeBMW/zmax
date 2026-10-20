#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_peg_d435.py — 「D435 专用检测头」判据(不夸口径: 每条都给实测数字)。

老倪 2026-10-20 选 B: 「单独给 D435 视角训一个检测头(现权重 0 检出), 只能给 2D 框」。
训完必须证明"真的有用", 而不是只报一个 mAP。四道判据:

  J1 上线口径: 8789 `/api/detect_d435` 真的在跑 models/yolo_peg_d435.pt(不是别的权重), 有帧龄、有耗时
  J2 实时检出率: 连续 N 次轮询, 统计"有框的轮次 / 总轮次" + conf 中位 + 框中心位置(应随臂动)
  J3 反误检(关键): 在腕相机模型被证伪的两个**静止杂物**位置 (271,449)/(309,445) 上, 新头**不应**出框
      —— 这是这次能不能信的核心判据(旧权重在这两处 657/700 帧都误检)
  J4 同源对照: 同一批已存帧上, 旧权重(yolo_peg_live) vs 新头 的检出帧数/框数对照, 落 4 张标注图

用法:
  gui-venv311/bin/python tools/verify_peg_d435.py            # 全跑
  gui-venv311/bin/python tools/verify_peg_d435.py --skip-j4  # 只跑线上三项
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.request

import numpy as np

ROOT = "/home/ubuntu/zmax"
RS = "http://127.0.0.1:8789"
AR = "http://127.0.0.1:8797"
CLUTTER = [(271.0, 449.0), (309.0, 445.0)]      # 实测被证伪的两处静止误检中心
FAILS: list[str] = []
OKS: list[str] = []


def _get(url, timeout=8.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _json(url, timeout=8.0):
    return json.loads(_get(url, timeout).decode("utf-8", "ignore"))


def j1():
    print("── J1 上线口径 ──")
    d = _json(RS + "/api/detect_d435?conf=0.30&imgsz=416")
    print("   ", json.dumps(d, ensure_ascii=False)[:300])
    if not d.get("ok"):
        FAILS.append("J1: /api/detect_d435 不通: %s" % d.get("err"))
        return None
    if d.get("model") != "yolo_peg_d435.pt":
        FAILS.append("J1: 跑的不是 D435 专用头, 而是 %s" % d.get("model"))
    else:
        OKS.append("J1: 权重=yolo_peg_d435.pt · %sms · 帧龄 %ss · 检出 %s"
                   % (d.get("ms"), d.get("age_s"), d.get("n")))
    # 8789 直连 + 8797 代理 两条路都要通
    try:
        p = _json(AR + "/api/rs_detect_d435?conf=0.30")
        if p.get("ok"):
            OKS.append("J1: 8797 代理也通(页面走这条)")
        else:
            FAILS.append("J1: 8797 代理失败: %s" % p.get("err"))
    except Exception as e:                                              # noqa: BLE001
        FAILS.append("J1: 8797 代理异常 %s: %s" % (type(e).__name__, str(e)[:100]))
    return d


def j2(n=24, gap=0.45):
    print("── J2 实时检出率 ──")
    hit, confs, cs, ms = 0, [], [], []
    for i in range(n):
        try:
            d = _json(RS + "/api/detect_d435?conf=0.30&imgsz=416")
        except Exception:                                               # noqa: BLE001
            time.sleep(gap); continue
        if d.get("ok"):
            ms.append(d.get("ms") or 0)
            if d.get("boxes"):
                hit += 1
                b = max(d["boxes"], key=lambda x: x["conf"])
                confs.append(b["conf"])
                cs.append(((b["xyxy"][0] + b["xyxy"][2]) / 2, (b["xyxy"][1] + b["xyxy"][3]) / 2))
        time.sleep(gap)
    rate = 100.0 * hit / max(1, n)
    print("    有框 %d/%d (%.0f%%) · conf 中位 %s · 耗时中位 %sms"
          % (hit, n, rate, (round(float(np.median(confs)), 2) if confs else "—"),
             (round(float(np.median(ms)), 1) if ms else "—")))
    if cs:
        xs = [c[0] for c in cs]; ys = [c[1] for c in cs]
        print("    框中心 x %d..%d · y %d..%d (极差 %d×%d px)"
              % (min(xs), max(xs), min(ys), max(ys), max(xs) - min(xs), max(ys) - min(ys)))
    if rate < 50:
        FAILS.append("J2: 实时检出率 %.0f%% < 50%%" % rate)
    else:
        OKS.append("J2: 实时检出率 %.0f%% (%d/%d), conf 中位 %s" %
                   (rate, hit, n, (round(float(np.median(confs)), 2) if confs else "—")))
    return cs


def j3(cs):
    print("── J3 反误检(静止杂物位置不许出框) ──")
    if not cs:
        print("    没有检出, 跳过判定")
        return
    bad = [c for c in cs if any(abs(c[0] - x) <= 25 and abs(c[1] - y) <= 25 for x, y in CLUTTER)]
    print("    落在被证伪静止杂物位置附近的框: %d / %d" % (len(bad), len(cs)))
    if bad:
        FAILS.append("J3: %d 个框落在静止杂物位置上(旧权重的病没治好)" % len(bad))
    else:
        OKS.append("J3: 0 个框落在两处静止杂物位置(旧权重那里 657/700 帧都误检)")


def j4(limit=40):
    print("── J4 同源对照(同一批已存帧) ──")
    from ultralytics import YOLO
    import cv2
    new_p = os.path.join(ROOT, "models/yolo_peg_d435.pt")
    old_p = os.path.join(ROOT, "models/yolo_peg_live.pt")
    if not os.path.exists(new_p):
        FAILS.append("J4: 缺 models/yolo_peg_d435.pt")
        return
    m_new, m_old = YOLO(new_p), YOLO(old_p)
    files = sorted(glob.glob(os.path.join(ROOT, "zmax_data/datasets/peg_d435/raw/*.jpg")))[-limit:]
    files += sorted(glob.glob(os.path.join(ROOT, "zmax_data/datasets/peg_d435_b/raw/*.jpg")))[-limit:]
    st = {"new_frames": 0, "new_boxes": 0, "old_frames": 0, "old_boxes": 0, "both": 0}
    samp = []
    for p in files:
        im = cv2.imread(p)
        rn = m_new.predict(im, conf=0.30, verbose=False)[0]
        ro = m_old.predict(im, conf=0.30, verbose=False)[0]
        if len(rn.boxes):
            st["new_frames"] += 1; st["new_boxes"] += len(rn.boxes)
        if len(ro.boxes):
            st["old_frames"] += 1; st["old_boxes"] += len(ro.boxes)
        if len(rn.boxes) and len(ro.boxes):
            st["both"] += 1
        if len(rn.boxes) and len(samp) < 4:
            out = os.path.join(ROOT, "zmax_data/reports", "d435_new_%s" % os.path.basename(p))
            cv2.imwrite(out, rn.plot()); samp.append(out)
    print("    帧数 %d · 新头 有框帧 %d (框 %d) · 旧权重 有框帧 %d (框 %d) · 两者都有 %d"
          % (len(files), st["new_frames"], st["new_boxes"], st["old_frames"], st["old_boxes"], st["both"]))
    print("    标注图: %s" % ", ".join(os.path.basename(x) for x in samp))
    if st["new_frames"] <= st["old_frames"]:
        FAILS.append("J4: 新头检出帧数 %d 不高于旧权重 %d" % (st["new_frames"], st["old_frames"]))
    else:
        OKS.append("J4: 新头有框帧 %d vs 旧权重 %d(同一批 %d 帧, conf>=0.30)"
                   % (st["new_frames"], st["old_frames"], len(files)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-j4", action="store_true")
    ap.add_argument("--rounds", type=int, default=24)
    a = ap.parse_args()
    d = j1()
    cs = j2(a.rounds)
    j3(cs)
    if not a.skip_j4:
        j4()
    print("\n===== 结果 =====")
    for s in OKS:
        print("  ✅ " + s)
    for s in FAILS:
        print("  ❌ " + s)
    print("  %d 项通过 / %d 项失败" % (len(OKS), len(FAILS)))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
