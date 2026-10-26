#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📊 采集会话体检: 帧/深度/位姿一一对应? 图像真的在变? 视角覆盖多少?
老倪 2026-10-26:「拖动了, 你看采集图像和位姿么」—— 这个脚本就是给"看见"的证据。
用法: python tools/map_session_report.py <session dir>
"""
import hashlib
import json
import os
import os.path as osp
import sys

import cv2
import numpy as np


def main():
    s = sys.argv[1] if len(sys.argv) > 1 else ""
    if not s or not osp.isdir(s):
        print("用法: map_session_report.py <session dir>")
        return 2
    fr = sorted(os.listdir(osp.join(s, "frames")))
    dp = sorted(os.listdir(osp.join(s, "depth"))) if osp.isdir(osp.join(s, "depth")) else []
    L = [json.loads(x) for x in open(osp.join(s, "poses.jsonl"), encoding="utf-8") if x.strip()]
    print("会话 %s" % osp.basename(s))
    print("帧 %d · 深度 %d · 位姿 %d  (一一对应: %s)"
          % (len(fr), len(dp), len(L), "是" if len(fr) == len(dp) == len(L) else "否"))

    # 图像真的在变? (最近 120 帧的 md5 去重)
    md = set()
    for f in fr[-120:]:
        with open(osp.join(s, "frames", f), "rb") as fh:
            md.add(hashlib.md5(fh.read()).hexdigest())
    print("最近 120 帧里不同图像 %d 张 (重复=相机没动/画面没变)" % len(md))

    if len(L) > 210:
        dt = L[-1]["ts"] - L[200]["ts"]
        if dt > 0:
            print("新增速率 %.1f 帧/秒" % ((len(L) - 200) / dt))

    P = np.array([p["tcp_mm"] for p in L], float)
    R = np.array([p["tcp_rpy"] for p in L], float)
    print("位姿 x %.0f~%.0f · y %.0f~%.0f · z %.0f~%.0f mm (跨度 %.0f/%.0f/%.0f)"
          % (P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(),
             P[:, 2].min(), P[:, 2].max(),
             P[:, 0].ptp(), P[:, 1].ptp(), P[:, 2].ptp()))
    vox = len(set(map(tuple, np.round(P / 30.0).astype(int))))
    print("30mm 体素 %d 个 · 转角跨度 %s 度"
          % (vox, [round(float(np.degrees(np.ptp(R[:, k]))), 1) for k in range(3)]))
    print("最近 6 个位姿:")
    for p in L[-6:]:
        print("   i=%-4d tcp=%s rpy=%s"
              % (p["i"], [round(v, 1) for v in p["tcp_mm"]], [round(v, 3) for v in p["tcp_rpy"]]))

    f0 = osp.join(s, "frames", fr[-1])
    a = cv2.imread(f0)
    print("最新帧 %s · %s · %d 字节" % (fr[-1], a.shape if a is not None else "读不到",
                                        osp.getsize(f0)))
    d0p = osp.join(s, "depth", fr[-1].replace(".jpg", ".png"))
    if osp.exists(d0p):
        d0 = cv2.imread(d0p, cv2.IMREAD_UNCHANGED)
        print("对应深度 dtype=%s · 有效 %.1f%% · 中位 %.0fmm · 深度非零点数 %d"
              % (d0.dtype, 100 * (d0 > 0).mean(),
                 float(np.median(d0[d0 > 0])) * 0.1 if (d0 > 0).any() else -1, int((d0 > 0).sum())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
