#!/usr/bin/env python3
"""批量预标注: 用 /station/gold 的「自动找19根」算法 + 首尾等距修正, 给 30~50 张真机图出候选框。

为什么要「首尾等距修正」这一步:
  _gold_annot_auto() 直接给的结果实测只有 18 根、pitch 75.0、间距忽宽忽窄(40~95px),
  单靠它做标注会把系统误差写进数据集。而老倪手画的 19 根实测 pitch=70.84、RMS 1.39px。
  所以: 算法只用来定「最左/最右」两根, 中间 17 根按等距生成 —— 精度取决于首尾, 不再取决于算法。

输出:
  /tmp/gold_pre/overlay/<stem>.jpg   叠框图(19 根绿框 + 序号 + 间距注记), 供人眼逐张复核
  /tmp/gold_pre/boxes.json           每张的 19 个框 + 诊断(算法原给几根/首尾/间距/残差)

用法:
  python3 gold_prelabel.py [--limit 30] [--src DIR] [--out DIR]
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

# 手画 19 根的实测模板(来自 gold_boxes_echo.json 的线性拟合结果)
TEMPLATE = {"w": 54.5, "h": 68.0, "pitch": 70.84, "dy_per": 0.925, "n": 19}


def _首尾等距(boxes, n=19, w=TEMPLATE["w"], h=TEMPLATE["h"]):
    """把算法给的若干框压成 n 根等距: 只信首尾两根的中心, 宽高用模板。"""
    if not boxes:
        return []
    bs = sorted(boxes, key=lambda b: b[0])
    f, l = bs[0], bs[-1]
    c0 = (f[0] + f[2]) / 2.0
    c1 = (l[0] + l[2]) / 2.0
    yc0 = (f[1] + f[3]) / 2.0
    yc1 = (l[1] + l[3]) / 2.0
    step = (c1 - c0) / (n - 1)
    dy = (yc1 - yc0) / (n - 1)
    out = []
    for i in range(n):
        cx = c0 + step * i
        cy = yc0 + dy * i
        out.append([int(round(cx - w / 2)), int(round(cy - h / 2)),
                    int(round(cx + w / 2)), int(round(cy + h / 2))])
    return out, {"c0": round(c0, 1), "c1": round(c1, 1), "pitch": round(step, 2),
                 "dy": round(dy, 3), "span": round(c1 - c0, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--src", default="/home/ubuntu/zmax/zmax_data/gold_collect_20261020")
    ap.add_argument("--out", default="/tmp/gold_pre")
    ap.add_argument("--min-side", type=int, default=2000, help="只要原图(2448x2048), 跳过 900x332 判据图")
    a = ap.parse_args()

    import cam_live_stream as C

    fs = sorted(glob.glob(os.path.join(a.src, "**", "*.png"), recursive=True) +
                glob.glob(os.path.join(a.src, "**", "*.jpg"), recursive=True))
    keep = []
    for f in fs:
        im = cv2.imread(f)
        if im is None:
            continue
        if min(im.shape[:2]) >= a.min_side:
            keep.append(f)
    # 按亮度分布抽样: 排序后均匀取, 覆盖最暗到最亮
    if len(keep) > a.limit:
        meas = []
        for f in keep:
            g = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
            meas.append((float(g.mean()), f))
        meas.sort()
        idx = np.linspace(0, len(meas) - 1, a.limit).round().astype(int)
        keep = [meas[i][1] for i in idx]

    os.makedirs(os.path.join(a.out, "overlay"), exist_ok=True)
    recs, warned = [], []
    for k, f in enumerate(keep, 1):
        bgr = cv2.imread(f)
        if bgr is None:
            continue
        try:
            r = C._gold_annot_auto(bgr, live_band=False)   # 离线跑历史图: 不能问 10082 要实时条带
        except Exception as e:                                            # noqa: BLE001
            warned.append({"file": os.path.basename(f), "err": "%s: %s" % (type(e).__name__, e)})
            continue
        raw = r.get("boxes") or []
        res = _首尾等距(raw)
        if isinstance(res, tuple):
            boxes19, diag = res
        else:
            boxes19, diag = res, {}
        rec = {"file": f, "stem": os.path.splitext(os.path.basename(f))[0],
               "algo_n": len(raw), "algo_pitch": r.get("pitch"),
               "n": len(boxes19), "boxes": boxes19, "diag": diag,
               "mean_lum": round(float(cv2.imread(f, cv2.IMREAD_GRAYSCALE).mean()), 1)}
        recs.append(rec)

        # 叠图: 绿框 + 序号 + 顶部注记
        vis = bgr.copy()
        for i, b in enumerate(boxes19):
            cv2.rectangle(vis, (b[0], b[1]), (b[2], b[3]), (80, 220, 120), 3)
            cv2.putText(vis, str(i + 1), (b[0], max(18, b[1] - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 220, 90), 2)
        tag = "%s  algo=%d根 pitch=%.1f -> 等距19根 pitch=%.2f  lum=%.0f" % (
            rec["stem"], rec["algo_n"], float(r.get("pitch") or 0),
            diag.get("pitch", 0), rec["mean_lum"])
        cv2.rectangle(vis, (0, 0), (vis.shape[1], 44), (0, 0, 0), -1)
        cv2.putText(vis, tag, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (230, 240, 250), 2)
        cv2.imwrite(os.path.join(a.out, "overlay", rec["stem"] + ".jpg"), vis,
                    [cv2.IMWRITE_JPEG_QUALITY, 88])
        print("[%d/%d] %-14s algo=%2d -> 19  pitch=%.2f" % (k, len(keep), rec["stem"], rec["algo_n"], diag.get("pitch", 0)),
              flush=True)

    with open(os.path.join(a.out, "boxes.json"), "w", encoding="utf-8") as fh:
        json.dump({"n": len(recs), "template": TEMPLATE, "items": recs, "errors": warned},
                  fh, ensure_ascii=False, indent=1)
    print("\n完成 %d 张 -> %s" % (len(recs), a.out))
    if warned:
        print("失败 %d 张: %s" % (len(warned), warned[:3]))


if __name__ == "__main__":
    main()
