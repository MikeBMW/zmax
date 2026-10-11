#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ar_exposure_sweep.py — 给 AR 底图找一档"不过曝又不压黑工作区"的曝光(实测, 不拍脑袋)

背景: 视觉复核 640x480 帧里 **10.8% 像素 >250 全白**(顶部中央强逆光), 会污染 AR 叠加与检测。
做法: 关自动曝光, 逐档设 exposure/gain, 每档等 1.5s 让 AE 收敛 → 取帧 → 统计:
  ① 全帧过曝占比(>250) ② 过曝团区(x280-400,y15-170) ③ 工作区(料盘/台面 y330-480, x230-640) 亮度均值/标准差
判据: 过曝占比↓且工作区均值落在 60~170(能看清细节) 为佳。
用法: gui-venv311/bin/python tools/ar_exposure_sweep.py            # 只测(不动设备)
      gui-venv311/bin/python tools/ar_exposure_sweep.py --apply 60,32   # 定格到指定档(实测回读)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

import cv2
import numpy as np

UP = "http://127.0.0.1:8797"


def _get(path, timeout=15):
    with urllib.request.urlopen(UP + path, timeout=timeout) as r:
        return r.read()


def frame(after_settle=1.5):
    time.sleep(after_settle)
    a = np.frombuffer(_get("/snapshot/rs.jpg"), np.uint8)
    return cv2.imdecode(a, cv2.IMREAD_COLOR)


def stats(im):
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    blob = g[15:170, 280:400]
    work = g[330:480, 230:640]
    return {"blown_pct": round(float((g > 250).mean()) * 100, 2),
            "blob_pct": round(float((blob > 250).mean()) * 100, 1),
            "work_mean": round(float(work.mean()), 1),
            "work_std": round(float(work.std()), 1),
            "work_p5": int(np.percentile(work, 5)), "work_p95": int(np.percentile(work, 95)),
            "frame_mean": round(float(g.mean()), 1)}


def set_exp(auto=None, exposure=None, gain=None):
    q = []
    if auto is not None:
        q.append("auto=%d" % (1 if auto else 0))
    if exposure is not None:
        q.append("exposure=%g" % exposure)
    if gain is not None:
        q.append("gain=%g" % gain)
    return json.loads(_get("/api/rs_exposure" + ("?" + "&".join(q) if q else "")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply")
    a = ap.parse_args()
    if a.apply:
        e, g = (a.apply.split(",") + ["32"])[:2]
        print("定格:", json.dumps(set_exp(auto=False, exposure=float(e), gain=float(g)), ensure_ascii=False))
        print("稳后统计:", json.dumps(stats(frame(2.0)), ensure_ascii=False))
        return
    rows = []
    print("== 现状(自动曝光) ==")
    cur = json.loads(_get("/api/rs_exposure"))
    s0 = stats(frame(1.0))
    print(json.dumps({"auto": cur.get("auto_exposure"), "exposure_us": cur.get("exposure_us"),
                      "gain": cur.get("gain"), **s0}, ensure_ascii=False))
    rows.append({"set": "auto", **s0})
    for e, g in ((166, 64), (120, 48), (80, 32), (60, 24), (40, 16)):
        r = set_exp(auto=False, exposure=e, gain=g)
        if not r.get("ok"):
            print("设定失败:", r)
            return
        s = stats(frame(1.6))
        print(json.dumps({"set": "e%d/g%d" % (e, g), "readback_us": r.get("exposure_us"),
                          "readback_gain": r.get("gain"), **s}, ensure_ascii=False))
        rows.append({"set": "e%d/g%d" % (e, g), **s})
    # 收尾: 有更优就留最优, 否则回自动曝光
    best = min([r for r in rows if 60 <= r["work_mean"] <= 170], key=lambda r: r["blown_pct"], default=None)
    if best and best["set"] != "auto":
        e, g = best["set"][1:].split("/")
        set_exp(auto=False, exposure=float(e[0:]), gain=float(g[1:]))
        print("⇒ 留最优档:", best["set"], "过曝", best["blown_pct"], "% · 工作区均值", best["work_mean"])
    else:
        set_exp(auto=True)
        print("⇒ 都不优, 回自动曝光(宁可用自动也不压黑工作区)")
    print("落档:", json.dumps(json.loads(_get("/api/rs_exposure")), ensure_ascii=False))
    open("/home/ubuntu/zmax/zmax_data/ar_rs/exposure_sweep.json", "w", encoding="utf-8").write(
        json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
