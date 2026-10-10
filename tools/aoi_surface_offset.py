#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_surface_offset.py — 侧面(表面)检测 10083 的"亮物相对程序ROI的偏差"测量件。

用途: 给侧面检测的视觉伺服/标定提供**同一个口径**的测量 —— 用真实抓拍链路
      (POST /capture_detect → 轮询 /last_result → GET /picture?kind=origin) 取原图,
      在原图(2448x2048)坐标系里找出过曝亮物(光模块亮面/亮条), 输出它相对程序 ROI 的偏差 px。

口径必须统一: **每次都走 capture_detect**, 不要直接 grab, 否则光照不同会给出假位移
(实测: 直接 grab 会拿到大面积过曝的顶灯帧)。

用法:
  python3 tools/aoi_surface_offset.py                 # 单次测量, 打印 JSON
  python3 tools/aoi_surface_offset.py --save /tmp/x.png  # 顺带存图
  python3 tools/aoi_surface_offset.py --th 220        # 改亮物阈值(默认 220)
"""
import argparse
import json
import time
import urllib.error
import urllib.request

HOST = "http://192.168.23.23:10083"
UA = {"User-Agent": "zmax-probe"}
# 检测程序真正看的区域(原图 2448x2048 坐标系, x1,y1,x2,y2) — 与 make_surface_evidence.py 同源
ROI = (330, 960, 1815, 1440)


def _req(url, method="GET", timeout=30):
    r = urllib.request.Request(url, method=method, headers=UA)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def capture_and_result(poll=8):
    """真抓一帧并取判决。返回 (last_result dict or None, 说明)。"""
    st, body = _req(HOST + "/capture_detect", "POST", timeout=60)
    note = "capture_detect http=%s %s" % (st, body[:120].decode("utf-8", "replace"))
    last = None
    for _ in range(poll):
        time.sleep(2)
        st, body = _req(HOST + "/last_result")
        try:
            d = json.loads(body.decode("utf-8", "replace"))
        except Exception:
            continue
        if d.get("judge") or d.get("count") is not None:
            last = d
            if d.get("judge_ok") is not None:
                break
    return last, note


def fetch_origin(path=None):
    st, body = _req(HOST + "/picture?kind=origin&grab=1", timeout=40)
    if st != 200 or len(body) < 50000:
        return None
    if path:
        with open(path, "wb") as f:
            f.write(body)
    return body


def measure(body, th=220, save=None):
    """返回亮物框/中心/相对 ROI 的偏差 (原图像素)。"""
    import numpy as np
    import cv2
    import io

    buf = np.frombuffer(body, np.uint8)
    g = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    if g is None:
        return {"ok": False, "why": "原图解码失败"}
    H, W = g.shape
    m = (g > th).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, lab, st, ce = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return {"ok": False, "why": "阈值 %d 无亮物" % th, "img": [W, H]}
    i = 1 + int(np.argmax(st[1:, 4]))
    x, y, w, h, a = [int(v) for v in st[i]]
    cx, cy = float(ce[i][0]), float(ce[i][1])
    x1, y1, x2, y2 = ROI
    inter = not (y + h < y1 or y > y2 or x + w < x1 or x > x2)
    rcx, rcy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    out = {
        "ok": True,
        "img": [W, H],
        "roi": list(ROI),
        "bbox": [x, y, x + w, y + h],
        "center": [round(cx, 1), round(cy, 1)],
        "area": a,
        "touch_roi": bool(inter),
        "need_px": {"dx_to_roi_center": round(rcx - cx, 1), "dy_to_roi_center": round(rcy - cy, 1),
                    "dy_top_into_roi": round(y1 - y, 1)},
    }
    if save:
        cv2.imwrite(save, g)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--th", type=int, default=220)
    ap.add_argument("--save", default=None)
    ap.add_argument("--no-capture", action="store_true", help="只取图不重新抓拍(调试用)")
    a = ap.parse_args()
    last = None
    if not a.no_capture:
        last, note = capture_and_result()
        print("抓拍: " + note)
    body = fetch_origin(a.save)
    if body is None:
        print(json.dumps({"ok": False, "why": "origin 取图失败"}, ensure_ascii=False))
        return 2
    res = measure(body, th=a.th, save=a.save)
    if last:
        res["judge_ok"] = last.get("judge_ok")
        res["judge_why"] = last.get("judge_why")
        res["count"] = last.get("count")
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
