#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calib_grab_view.py —— 采一个"腕相机标定视图": 抓臂相机帧 + 同刻 TCP 真值, 追加到清单

用法:
  ./gui-venv311/bin/python tools/calib_grab_view.py --tag up100
输出:
  zmax_data/calib_d435/view_<tag>_<ts>.jpg  +  manifest json (追加)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
OUT = os.path.join(REPO, "zmax_data", "calib_d435")
MAN = os.path.join(OUT, "views.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="v")
    ap.add_argument("--arm-url", default="http://192.168.23.66:8792/frame.jpg")
    ap.add_argument("--ctl", default="http://127.0.0.1:8793")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    for _ in range(3):                       # 位姿要稳: 连读三次, 最大漂移 <0.3mm 才采
        p1 = json.loads(urllib.request.urlopen(a.ctl + "/pose", timeout=6).read())
        time.sleep(0.25)
        p2 = json.loads(urllib.request.urlopen(a.ctl + "/pose", timeout=6).read())
        drift = max(abs(p1["xyz"][i] - p2["xyz"][i]) for i in range(3)) * 1000
        if drift < 0.3:
            break
    else:
        print("机器人还在动(漂移 %.2fmm) ⇒ 不采点" % drift)
        return 2

    img = urllib.request.urlopen(a.arm_url, timeout=8).read()
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUT, "view_%s_%s.jpg" % (a.tag, ts))
    open(path, "wb").write(img)

    import cv2
    import calib_fixed_cam as CF
    mk = CF.find_markers(cv2.imread(path))
    view = {"img": path, "tcp": {"xyz": p1["xyz"], "abc_rad": p1["abc_rad"]},
            "t": ts, "tag": a.tag, "markers": sorted(mk), "drift_mm": round(drift, 3)}
    man = []
    if os.path.exists(MAN):
        try:
            man = json.load(open(MAN, encoding="utf-8"))
        except Exception:                                                   # noqa: BLE001
            man = []
    man.append(view)
    json.dump(man, open(MAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("视图 %s · TCP %s · 检出 marker %s · 累计 %d 视图" % (
        os.path.basename(path), [round(v * 1000, 1) for v in p1["xyz"]], sorted(mk), len(man)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
