#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""USB 固定相机(8791 的 local 路)上的光模块 2D 边界框。

为什么不用 YOLO:
  在役权重 models/yolo_peg_live.pt 只认腕上 D405 的视角/尺度, 直接喂 USB 帧实测 **0 框**
  (2026-10-22 现场实测), 硬上就是画假框。

这里走的是"锚点+标定偏移":
  ① 绿拉环是这支光模块最稳的特征 —— HSV 阈值能把它在黑色泡棉上锁死(实测面积≈1300px, 稳定);
  ② 整支模块相对拉环的偏移与尺度, **只学一次**(用视觉定位的整支框标定), 存 params.json;
  ③ 之后每帧只做"找拉环 → 拉环中心 + 偏移" ⇒ 5ms 级, 视角不变时框跟着模块走。

边界(必须写明):
  · 观测量只有拉环中心; 模块尺寸/角度是标定值 ⇒ **只在这个固定视角、模块不被遮挡时成立**;
  · 拉环找不到 ⇒ 返回 ok=False 且不给框, 绝不拿上一帧的框冒充;
  · 模块转了大角度(比标定时转 >10°)要重新标定 params.json。
"""
import os
import json

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PARAMS = os.path.join(HERE, "..", "data", "scene", "mod2d_usb.json")

# 2026-10-22 现场标定(640x480 USB 帧, 视觉定位整支框 + 绿环实测中心 (336,147))
#   box=(288,115,371,350)  ring=(336,147)  ⇒ 相对偏移如下
_DEFAULT = {
    "frame_wh": [640, 480],
    "ring": [336.0, 147.0],
    "box": [288.0, 115.0, 371.0, 350.0],
    "note": "偏移=box-ring; 换机位/换镜头必须重标",
}


def load_params():
    try:
        with open(PARAMS, "r", encoding="utf-8") as f:
            d = json.load(f)
        if all(k in d for k in ("ring", "box")):
            return d
    except Exception:
        pass
    return dict(_DEFAULT)


_LAST = {"t": 0.0, "xy": None}          # 上一帧锁到的拉环(连续性约束, 防止墙上/屏上的杂绿抢走)


def _ring(bgr, min_area=80, cluster_r=60.0):
    """绿拉环锚点 = 绿色块簇的质心(按面积加权)。

    实测(2026-10-22, 640x480 USB 帧): 拉环不是一块, 是**两根绿条**
    (x314-329/y9-48 与 x349-359/y13-81, 实测簇质心 (336,45))。
    只取"最大绿块"会左右偏 ~13px、上下偏 ~23px, 框跟着整体歪 ⇒ 必须按簇算。
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, np.array([35, 70, 45]), np.array([95, 255, 255]))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, ce = cv2.connectedComponentsWithStats(m, 8)
    blobs = []
    for i in range(1, n):
        a = int(st[i, cv2.CC_STAT_AREA])
        if a < min_area:
            continue
        blobs.append((a, float(ce[i][0]), float(ce[i][1]),
                      int(st[i, cv2.CC_STAT_WIDTH]), int(st[i, cv2.CC_STAT_HEIGHT])))
    if not blobs:
        return None
    blobs.sort(reverse=True)
    a0, x0, y0, w0, h0 = blobs[0]
    grp = [b for b in blobs if ((b[1] - x0) ** 2 + (b[2] - y0) ** 2) ** 0.5 <= cluster_r]
    tot = sum(b[0] for b in grp)
    cx = sum(b[0] * b[1] for b in grp) / tot
    cy = sum(b[0] * b[2] for b in grp) / tot
    # 簇的像素尺度(面积开方), 用于判断"机位/距离有没有变"
    import math
    scale = math.sqrt(tot)
    return cx, cy, tot, scale


def detect(frame, params=None):
    """在 USB 帧上给光模块 2D 框。返回 {ok, boxes, ring, err, params_src}"""
    p = params or load_params()
    H, W = frame.shape[:2]
    r = _ring(frame)
    if not r:
        return {"ok": False, "boxes": [], "err": "绿拉环未锁定(遮挡/未入画/光照变化)", "params_src": PARAMS}
    cx, cy, area, scale = r
    # 尺度守卫(只挡极端): 阈值型锚点的像素尺度会随距离变 ⇒ 用**比例偏移**(px 按拉环尺度归一),
    # 距离变了框自动跟着缩放, 不再需要固定像素偏移(那正是之前"一换距离就歪"的原因)。
    s0 = float(p.get("ring_scale") or 0) or None
    if s0 and not (0.4 <= (scale / s0) <= 2.5):
        return {"ok": False, "boxes": [], "ring": [round(cx, 1), round(cy, 1), area],
                "err": "拉环尺度异常(%.1f vs 标定 %.1f, 超 ±150%%) ⇒ 判为认错目标/严重遮挡, 不画" % (scale, s0),
                "params_src": PARAMS}
    rx, ry = p["ring"]
    bx1, by1, bx2, by2 = p["box"]
    # 比例偏移: 标定时 拉环尺度 = ring_scale(px), 现在实测 scale(px) ⇒ 整体按 scale/ring_scale 缩放
    k = (scale / s0) if s0 else 1.0
    x1 = max(0.0, cx + (bx1 - rx) * k)
    y1 = max(0.0, cy + (by1 - ry) * k)
    x2 = min(W - 1.0, cx + (bx2 - rx) * k)
    y2 = min(H - 1.0, cy + (by2 - ry) * k)
    dx = (x1 - bx1); dy = (y1 - by1)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return {"ok": False, "boxes": [], "err": "框退化(拉环偏移超出画面)", "params_src": PARAMS}
    conf = min(0.99, 0.6 + 0.4 * min(1.0, area / 1300.0))
    return {
        "ok": True,
        "boxes": [{"xyxy": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                   "conf": round(conf, 3), "name": "OPT_Gold", "src": "ring_anchor"}],
        "ring": [round(cx, 1), round(cy, 1), area],
        "offset": [round(dx, 1), round(dy, 1)], "scale_ratio": round(k, 3),
        "tab_scale": round(scale, 1),
        "note": "绿拉环簇质心 + 标定偏移; 视角不变时有效",
        "params_src": PARAMS,
    }


if __name__ == "__main__":
    import sys
    f = sys.argv[1] if len(sys.argv) > 1 else "/tmp/usb_box.jpg"
    im = cv2.imread(f)
    out = detect(im)
    print(json.dumps(out, ensure_ascii=False))
    if out.get("ok"):
        b = out["boxes"][0]["xyxy"]
        vis = im.copy()
        cv2.rectangle(vis, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 255, 0), 2)
        if out.get("ring"):
            cv2.circle(vis, (int(out["ring"][0]), int(out["ring"][1])), 5, (0, 0, 255), -1)
        dst = "/tmp/usb_mod2d.jpg"
        cv2.imwrite(dst, vis)
        print("已画:", dst)
