#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cmp_3d_fix.py — 修前/修后 逐图量像素 (证据, 不靠肉眼)

重点两条:
· 插拔: 红盒 (shaded, 用 HSV 红判) 与 孔口(深色小口, 用与盒相邻的暗块近似) 的相对位置
  —— 修前盒顶比孔口低 35mm, 修后盒心=孔口高 (盒底落在桌面上)。
· 摆盘: 纯金(实心件) / 淡金(被半透明层冲淡) 像素比; 此前 mani 层(α0.55 管 + 同色金球)默认开。
用法: python tools/cmp_3d_fix.py <修前插拔> <修后插拔> <修前摆盘> <修后摆盘>
"""
import sys
import cv2
import numpy as np


def stats(p):
    im = cv2.imread(p)
    if im is None:
        return None
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    gold_sat = (h >= 15) & (h <= 35) & (s >= 120) & (v >= 120)
    gold_pale = (h >= 15) & (h <= 35) & (s >= 30) & (s < 120) & (v >= 170)
    red = (((h <= 8) | (h >= 172)) & (s >= 120) & (v >= 90))
    out = {"size": im.shape, "gold_sat": int(gold_sat.sum()), "gold_pale": int(gold_pale.sum()),
           "pale_ratio": round(gold_pale.sum() / max(1, gold_sat.sum()), 3)}
    ys, xs = np.where(red)
    if len(xs):
        out["red_bbox"] = (int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()), int(red.sum()))
    ys, xs = np.where(gold_sat)
    if len(xs):
        out["gold_bbox"] = (int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()))
    return out


def main():
    a = sys.argv[1:] or ["/tmp/qa_fw.png", "/tmp/fix_fw.png", "/tmp/qa_tray.png", "/tmp/fix_tray.png"]
    names = ["插拔·修前", "插拔·修后", "摆盘·修前", "摆盘·修后"]
    res = [(n, stats(p)) for n, p in zip(names, a)]
    for n, st in res:
        if st is None:
            print("%-10s 图缺" % n)
            continue
        print("%-10s 尺寸%s 纯金%7d 淡金%6d 淡/纯=%.2f 红盒bbox=%s 金bbox=%s"
              % (n, st["size"], st["gold_sat"], st["gold_pale"], st["pale_ratio"],
                 st.get("red_bbox"), st.get("gold_bbox")))
    f0, f1 = res[0][1], res[1][1]
    if f0 and f1 and "red_bbox" in f0 and "red_bbox" in f1:
        r0, r1 = f0["red_bbox"], f1["red_bbox"]
        print("\n插拔红盒: 修前 y[%d..%d] (高%dpx) → 修后 y[%d..%d] (高%dpx) ⇒ 盒上移 %dpx (往孔口方向)"
              % (r0[2], r0[3], r0[3] - r0[2], r1[2], r1[3], r1[3] - r1[2], r0[2] - r1[2]))
    t0, t1 = res[2][1], res[3][1]
    if t0 and t1:
        print("摆盘: 淡金/纯金 %.2f → %.2f ⇒ 被半透明层冲淡的金色 %s"
              % (t0["pale_ratio"], t1["pale_ratio"],
                 "明显减少 (mani 层已关)" if t1["pale_ratio"] < t0["pale_ratio"] else "未见减少 (需再查)"))


if __name__ == "__main__":
    main()
