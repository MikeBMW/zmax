#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📏 从运行帧里量「7 槽排 + 槽尺寸」—— 用示教已知的 49mm 槽距当标尺。

为什么这么做: YOLO 没有 slot/tray 类别(实测 787 帧 0 检出), 所以不能靠检测器;
但槽是"7 个等间距暗孔排成一列"的强几何图案, 经典视觉能测, 而且**槽距 49mm 是已知真值**
⇒ 量出像素间距就得到 mm/px ⇒ 槽的宽高、料盘跨度都能换算成毫米。

输出: 每帧的候选(框选数、像素间距、换算尺寸), 以及最终建议值
"""
import glob
import json
import os
import sys

import cv2
import numpy as np

REPO = os.path.expanduser("~/zmax")
PITCH_MM = 49.0          # 示教真值: 槽间距中位 49mm (slot1..slot7)


def blobs(gray):
    g = cv2.GaussianBlur(gray, (5, 5), 0)
    _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(th, 8)
    out = []
    H, W = gray.shape
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (60 <= area <= 6000):
            continue
        if not (6 <= w <= 90 and 6 <= h <= 90):
            continue
        ar = w / float(h)
        if not (0.35 <= ar <= 2.8):
            continue
        fill = area / float(w * h)
        if fill < 0.45:                     # 孔一般是实心暗块
            continue
        out.append({"cx": float(cent[i][0]), "cy": float(cent[i][1]),
                    "w": int(w), "h": int(h), "area": int(area), "fill": round(fill, 2)})
    return out


def row_of_seven(bs):
    """找共线的 7 个等间距块(允许 5~7 个)。"""
    if len(bs) < 5:
        return None
    best = None
    pts = np.array([[b["cx"], b["cy"]] for b in bs])
    for ang_deg in range(0, 180, 3):
        a = np.radians(ang_deg)
        u = np.array([np.cos(a), np.sin(a)])
        proj = pts @ u
        off = pts @ np.array([-u[1], u[0]])
        order = np.argsort(proj)
        proj_s, off_s, idx_s = proj[order], off[order], order
        # 按偏移聚类(容差 6px)
        for i in range(len(off_s)):
            m = np.abs(off_s - off_s[i]) < 6.0
            sel = np.where(m)[0]
            if len(sel) < 5 or len(sel) > 8:
                continue
            d = np.diff(proj_s[sel])
            if len(d) < 4:
                continue
            med = float(np.median(d))
            if med < 8 or med > 200:
                continue
            if np.max(np.abs(d - med)) > max(3.0, 0.22 * med):   # 等间距
                continue
            score = len(sel) - float(np.std(d)) / max(1e-6, med)
            if best is None or score > best["score"]:
                best = {"score": score, "n": len(sel), "pitch_px": med,
                        "ids": [int(idx_s[s]) for s in sel], "ang": ang_deg}
    return best


def main():
    dirs = sorted(glob.glob(os.path.join(REPO, "zmax_data", "run_capture", "*")))[-2:]
    files = []
    for d in dirs:
        man = os.path.join(d, "manifest.jsonl")
        if not os.path.exists(man):
            continue
        for line in open(man, encoding="utf-8"):
            r = json.loads(line)
            files.append((r.get("cursor"), os.path.join(d, r["file"]), r.get("pose_mm")))
    print("候选帧 %d（两批运行采集）" % len(files))
    hits = []
    for cur, f, pose in files:
        img = cv2.imread(f)
        if img is None:
            continue
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        bs = blobs(g)
        r = row_of_seven(bs)
        if not r or r["n"] < 5:
            continue
        mmpp = PITCH_MM / r["pitch_px"]
        sel = [bs[i] for i in r["ids"]]
        wmm = float(np.median([b["w"] for b in sel])) * mmpp
        hmm = float(np.median([b["h"] for b in sel])) * mmpp
        span = r["pitch_px"] * (r["n"] - 1) * mmpp
        hits.append({"file": f, "cursor": cur, "pose": pose, "n": r["n"],
                     "pitch_px": round(r["pitch_px"], 2), "mm_per_px": round(mmpp, 4),
                     "slot_w_mm": round(wmm, 1), "slot_h_mm": round(hmm, 1),
                     "span_mm": round(span, 1), "ang": r["ang"]})
    print("命中候选 %d 帧" % len(hits))
    if not hits:
        print("⚠️ 没找到 7 槽排(可能槽不在视野内, 或图案不是暗孔)")
        return 0
    hits.sort(key=lambda h: (-h["n"], abs(h["slot_w_mm"] - 14)))
    print("-" * 92)
    print(" n  游标  像素间距  mm/px    槽宽mm  槽高mm  排跨度mm  角度  文件")
    for h in hits[:12]:
        print(" %d  %4s  %7.2f  %6.4f  %6.1f  %6.1f  %7.1f  %4d°  %s"
              % (h["n"], h["cursor"], h["pitch_px"], h["mm_per_px"],
                 h["slot_w_mm"], h["slot_h_mm"], h["span_mm"], h["ang"],
                 os.path.basename(h["file"])))
    # 稳健汇总: 取 n>=6 且尺寸中位数
    good = [h for h in hits if h["n"] >= 6]
    if good:
        w = float(np.median([h["slot_w_mm"] for h in good]))
        hh = float(np.median([h["slot_h_mm"] for h in good]))
        sp = float(np.median([h["span_mm"] for h in good]))
        print("-" * 92)
        print("建议值(取 n>=6 的 %d 帧中位): 槽 宽 %.1f × 高 %.1f mm · 7 槽排跨度 %.1f mm" % (len(good), w, hh, sp))
    out = os.path.join(REPO, "zmax_data", "reports", "slot_size_from_frames.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"pitch_mm_assumed": PITCH_MM, "hits": hits}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("明细: %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
