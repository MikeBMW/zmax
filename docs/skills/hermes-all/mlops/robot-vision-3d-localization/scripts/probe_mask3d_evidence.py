#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测"分割掩膜 → base 系 3D"整条链, 并出一张自带状态横幅的取证图。

用途: 被问"这模型能不能做位姿/3D 引导"时,**先跑出真数再答**, 不靠印象。
前提: 分割服务在跑 (默认 127.0.0.1:8796, POST /seg), 推流服务能给帧 (默认 127.0.0.1:8791/snapshot/<cam>.jpg),
      且深度源/手眼/TCP 门控在位 (任一不在位 → 回应里会给 {ok:false, reason}, 原样贴进报告, 别猜填)。

用法:
  python probe_mask3d_evidence.py --out /tmp/seg3d.png
  python probe_mask3d_evidence.py --box 520,300,760,560 --text object --out /tmp/seg3d.png
  python probe_mask3d_evidence.py --text "green connector" --out /tmp/text_route.png   # 文本路由探针 (常 0 实例)
"""
import argparse
import datetime as dt
import io
import json
import time
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONTS = ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
         "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def font(sz: int):
    for p in FONTS:
        try:
            return ImageFont.truetype(p, sz)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default="arm", help="相机源; 3D 只对腕上深度相机成立")
    ap.add_argument("--box", default="", help="上游给的区域框 x1,y1,x2,y2 (推荐: 让模型出掩膜而不是自己找料)")
    ap.add_argument("--text", default="", help="文本概念 (英文; 现场域常 0 实例)")
    ap.add_argument("--seg", default="http://127.0.0.1:8796/seg")
    ap.add_argument("--snap", default="http://127.0.0.1:8791/snapshot/{cam}.jpg")
    ap.add_argument("--out", default="/tmp/mask3d_evidence.png")
    a = ap.parse_args()

    t_grab = time.time()
    raw = urllib.request.urlopen(a.snap.format(cam=a.cam), timeout=20).read()
    img = Image.open(io.BytesIO(raw)).convert("RGB")

    req_body = {"cam": a.cam, "three_d": True}
    if a.box:
        req_body["boxes"] = [[float(v) for v in a.box.split(",")]]
    if a.text:
        req_body["texts"] = [a.text]
    req = urllib.request.Request(a.seg, data=json.dumps(req_body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    d = json.loads(urllib.request.urlopen(req, timeout=300).read())
    ms = (time.time() - t0) * 1000.0
    print("推理 %.0f ms  count=%s  src=%s" % (ms, d.get("count"), d.get("src")))
    for it in d.get("instances") or []:
        c3d = it.get("c3d") or {}
        if c3d.get("ok"):
            print("  score=%.3f area_px=%s center_base=%s z_mm=%.1f xy_size=%s yaw=%.1f° n_px=%s" % (
                it.get("score", -1), it.get("area_px"), [round(v, 4) for v in c3d["center_base"]],
                c3d["z_mm"], [round(v, 1) for v in c3d["xy_size_mm"]], c3d["yaw_deg"], c3d["n_px"]))
        else:
            print("  score=%.3f  3D 拒答: %s" % (it.get("score", -1), c3d.get("reason")))
    if not d.get("count"):
        print("  0 实例 ⇒ 文本路由不可靠或提示框里没目标 (报这个事实, 别调参数凑数)")

    dr = ImageDraw.Draw(img, "RGBA")
    it = (d.get("instances") or [{}])[0]
    c3d = it.get("c3d") or {}
    for poly in it.get("polys") or []:
        pts = [tuple(p) for p in poly]
        dr.line(pts + [pts[0]], fill=(255, 210, 0, 255), width=2)
    if a.box:
        dr.rectangle([float(v) for v in a.box.split(",")], outline=(0, 255, 255, 255), width=1)

    f1, f2 = font(17), font(15)
    lines = ["分割掩膜 → base 系 3D (%s, 提示来源: %s)" % (
                 a.cam, "上游区域框" if a.box else ("文本概念 '%s'" % a.text if a.text else "全帧"))]
    if c3d.get("ok"):
        lines += ["center_base=(%.3f, %.3f, %.3f) m  z=%.1f mm  %d×%d mm  yaw=%.1f°" % (
                      c3d["center_base"][0], c3d["center_base"][1], c3d["center_base"][2], c3d["z_mm"],
                      round(c3d["xy_size_mm"][0]), round(c3d["xy_size_mm"][1]), c3d["yaw_deg"]),
                  "掩膜 %d px · 深度龄 %.1fs · 手眼闭环 ±%.2f mm · 推理 %.0f ms" % (
                      c3d.get("n_px", 0), c3d.get("depth_age_s", -1),
                      c3d.get("handeye_closed_loop_std_mm") or -1, ms)]
    else:
        lines += ["3D 拒答: %s" % (c3d.get("reason") or "无掩膜"), "—"]
    lines += ["帧 %s 龄 %.1fs" % (dt.datetime.fromtimestamp(t_grab).strftime("%m-%d %H:%M:%S"),
                                  time.time() - t_grab)]
    bh = 22 * len(lines) + 12
    dr.rectangle([0, 0, img.width, bh], fill=(0, 0, 0, 190))
    for i, ln in enumerate(lines):
        dr.text((8, 6 + i * 22), ln, font=f1 if i == 0 else f2, fill=(255, 255, 255, 255))
    img.save(a.out)
    print("写出取证图:", a.out, img.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
