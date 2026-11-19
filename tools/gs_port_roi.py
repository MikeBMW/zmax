#!/usr/bin/env python3
"""gs_port_roi.py — 从整幅采集数据里裁出"插口窗口"数据集, 让 3DGS 把像素集中到插口上。

为什么这样做 (老倪 2026-11-19: "在当前 3dGS 基础上提高插口的图清晰度"):
  整幅 1280x720 里插口只占几十个像素, 一个高斯摊不到几个像素 ⇒ 插口永远糊。
  把每帧裁成以插口为中心的小窗口 (默认 640x480), 同样的步数下插口像素密度提升 2~4 倍,
  再用 --init-ply 从现有模型续训 ⇒ 全局结构不动, 局部细节长出来。

坐标口径 (实测确认):
  cameras.json 的 T_cam2world 在"场景系"(不是机器人基座系), train_report.json 的
  normalize.center 就是场景系里的原点密度中心 ≈ 插口附近; 所以插口点用 center 即可。

用法:
  python3 tools/gs_port_roi.py --ds <ds_dir> --report <out>/train_report.json \
      --out <ds_roi_dir> [--win 640 --win-h 480] [--port x,y,z]
"""
import argparse
import json
import os
import shutil

import numpy as np
from PIL import Image


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", required=True)
    ap.add_argument("--report", required=True, help="train_report.json (取 normalize.center)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--win", type=int, default=640)
    ap.add_argument("--win-h", type=int, default=480)
    ap.add_argument("--port", default="", help="场景系插口点 x,y,z (默认用 normalize.center)")
    ap.add_argument("--mode", choices=("port", "center"), default="center",
                    help="center=按主点居中裁 (腕相机对准作业区时最稳); port=按投影点裁")
    ap.add_argument("--margin", type=float, default=0.15, help="插口投影离边缘至少占宽/高的比例")
    a = ap.parse_args()

    cj = json.load(open(os.path.join(a.ds, "cameras.json"), encoding="utf-8"))
    rep = json.load(open(a.report, encoding="utf-8"))
    center = np.array((rep.get("normalize") or {}).get("center") or [0, 0, 0], dtype=float)
    port = np.array([float(v) for v in a.port.split(",")], dtype=float) if a.port else center
    W, H = int(cj["width"]), int(cj["height"])
    K = np.array(cj["K"], dtype=float)
    img_dir = os.path.join(a.ds, "images")
    out_img = os.path.join(a.out, "images")
    os.makedirs(out_img, exist_ok=True)

    kept, skipped = [], 0
    for f in cj["frames"]:
        src = os.path.join(img_dir, f["file"])
        if not os.path.exists(src):
            skipped += 1
            continue
        T = np.array(f["T_cam2world"], dtype=float)
        if a.mode == "center":
            # 腕相机沿工具轴看作业区 ⇒ 插口落在主点附近, 直接按主点裁, 不依赖场景系口径
            u, v = float(K[0, 2]), float(K[1, 2])
        else:
            R, t = T[:3, :3], T[:3, 3]
            pc = R.T @ (port - t)                 # 世界→相机
            if pc[2] <= 1e-6:
                skipped += 1
                continue
            uv = K @ pc
            u, v = uv[0] / uv[2], uv[1] / uv[2]
        if not (a.margin * W <= u <= (1 - a.margin) * W and a.margin * H <= v <= (1 - a.margin) * H):
            skipped += 1
            continue
        im = Image.open(src).convert("RGB")
        ww, wh = min(a.win, W), min(a.win_h, H)
        x0 = int(max(0, min(W - ww, u - ww / 2)))
        y0 = int(max(0, min(H - wh, v - wh / 2)))
        im.crop((x0, y0, x0 + ww, y0 + wh)).save(os.path.join(out_img, f["file"]), quality=95)
        nf = dict(f)
        kept.append(nf)
        nf["_crop"] = [x0, y0]

    if not kept:
        print(json.dumps({"ok": False, "err": "没有帧能投影到插口, 检查 --port / center"}))
        return 1

    K2 = K.copy()
    K2[0, 2] -= kept[0]["_crop"][0]
    K2[1, 2] -= kept[0]["_crop"][1]
    ww, wh = min(a.win, W), min(a.win_h, H)
    out_cj = {k: v for k, v in cj.items() if k != "frames"}
    out_cj.update({"width": ww, "height": wh, "K": K2.tolist(),
                   "note": (cj.get("note") or "") + " | ROI 裁切: 以插口为中心 %dx%d, 由 gs_port_roi.py 生成" % (ww, wh)})
    out_cj["frames"] = [{k: v for k, v in f.items() if k != "_crop"} for f in kept]
    json.dump(out_cj, open(os.path.join(a.out, "cameras.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps({"ok": True, "kept": len(kept), "skipped": skipped,
                      "win": [ww, wh], "center": center.tolist(), "port": port.tolist(),
                      "out": a.out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
