#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_surface_display.py — 表面检测(10083)「曝光过大」这条的判据 (2026-10-12)

老倪: 「侧面检测的曝光太大了，你能改么？」 实测结论与理由见 docs/AOI_SURFACE_EXPOSURE_20261012.md:
  · 真相机曝光**不能**降 —— 降了表面判据 v12.1 连续失败(它靠"找过曝亮条"量厚度);
  · 10083 的判据图是**归一化渲染**, 降曝光它也不会变暗(80000/40000 两档逐像素平均差 0.25/255);
  · 所以只把**显示**侧的死白压成浅灰。本判据就是钉住这三条, 谁改回去都会红。

判据:
  ① 相机曝光 == 产线口径 80000us / gain 1.8 (不是 40000 之类被误留的值)
  ② 8791 显示帧(/snapshot/aoi_surface.jpg) 死白(≥250) ≤ 2%  —— 压高光真的生效
  ③ 工控机原判据图白区占比仍 ~43% (说明我们改的是显示, 没动工控机/没伪造)
  ④ 8793/station 页面 200 且 表面面板里有"已压高光"标注(不让显示处理变成悄悄发生的)
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.request

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "zmax-verify"}
EXPO_US, EXPO_GAIN = 80000.0, 1.8
_fails = []


def chk(cond, msg):
    print("  %s %s" % ("✅" if cond else "❌", msg))
    if not cond:
        _fails.append(msg)
    return bool(cond)


def get(url: str, timeout: int = 20) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def gray(raw: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(raw)).convert("L")).astype(np.float32)


def main() -> int:
    print("① 相机曝光 == 产线口径 (%gus / gain %g)" % (EXPO_US, EXPO_GAIN))
    try:
        e = json.loads(get("http://192.168.23.23:10083/exposure").decode("utf-8", "replace"))
        chk(abs(float(e.get("us", -1)) - EXPO_US) < 1 and abs(float(e.get("gain", -1)) - EXPO_GAIN) < 0.01,
            "实测 us=%s gain=%s (src=%s)" % (e.get("us"), e.get("gain"), e.get("src")))
    except Exception as ex:                                                       # noqa: BLE001
        chk(False, "读不到 %s/exposure: %s" % ("192.168.23.23:10083", str(ex)[:60]))

    print("\n② 8791 显示帧: 死白(≥250) ≤ 2% (显示压高光生效)")
    disp = None
    try:
        disp = gray(get("http://127.0.0.1:8791/snapshot/aoi_surface.jpg"))
        sat = 100 * float((disp >= 250).mean())
        chk(sat <= 2.0, "显示帧 %s 死白 %.2f%% (均值 %.1f, p90 %d)" % (disp.shape, sat, disp.mean(), int(np.percentile(disp, 90))))
    except Exception as ex:                                                       # noqa: BLE001
        chk(False, "取 8791 显示帧失败: %s" % str(ex)[:60])

    print("\n③ 工控机原判据图仍过曝 (证明动的是显示侧, 没替工控机造假)")
    try:
        j = gray(get("http://192.168.23.23:10083/picture?kind=judge"))
        sat_j = 100 * float((j >= 250).mean())
        chk(sat_j >= 5.0, "工控机判据图 %s 死白 %.2f%% (改前 43.12%% 同量级即正常)" % (j.shape, sat_j))
    except Exception as ex:                                                       # noqa: BLE001
        chk(False, "取工控机判据图失败: %s" % str(ex)[:60])

    print("\n④ 页面在线 + 标注在 (显示处理不许悄悄发生)")
    try:
        chk(len(get("http://127.0.0.1:8793/station")) > 5000, "8793/station → 200 且非空")
    except Exception as ex:                                                       # noqa: BLE001
        chk(False, "8793/station 无法打开: %s" % str(ex)[:60])
    html = open(os.path.join(ROOT, "tools/web/station.html"), encoding="utf-8").read()
    chk("已压高光" in html, "station.html 表面面板有「已压高光」标注")
    src = open(os.path.join(ROOT, "tools/cam_live_stream.py"), encoding="utf-8").read()
    chk("_deglare_bgr" in src and "ZMAX_SURFACE_DEGLARE" in src, "cam_live_stream 有 _deglare_bgr + 开关(可回滚)")

    print("\n════════════════════════════════════════════════")
    if _fails:
        print("❌ 失败 %d 项" % len(_fails))
        return 1
    print("✅ 全部通过 — 曝光=产线口径 · 显示压高光生效 · 工控机未动 · 标注在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
