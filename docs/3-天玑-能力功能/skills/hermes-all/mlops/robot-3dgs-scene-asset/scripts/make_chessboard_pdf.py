"""生成 A4 棋盘标定板 PDF (CGB-020 口径: 内角点 5x4 · 方格 20mm)。

打印要求: **100%, 不缩放**; 打完拿卡尺量一格必须是 20.0mm。

用法:
    python3 make_chessboard_pdf.py --out /tmp/board_A4_20mm.pdf

依赖: opencv + PIL。注意 cv2.imwrite 不认 .pdf(没有 pdf writer) ⇒ 必须走 PIL 存 pdf 并给对 resolution,
否则打印出来尺寸不对。
"""

import argparse
import os

import cv2
import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="board_A4_20mm.pdf")
    ap.add_argument("--inner", default="5x4", help="内角点 cols x rows")
    ap.add_argument("--square-mm", type=float, default=20.0)
    ap.add_argument("--ppm", type=float, default=4.0, help="每毫米像素数(4 ≈ 102dpi,够检出)")
    a = ap.parse_args()

    inner_c, inner_r = (int(v) for v in a.inner.lower().split("x"))
    cols, rows = inner_c + 1, inner_r + 1          # 内角点 N ⇒ 格子 N+1
    W, H, ppm = 210.0, 297.0, a.ppm

    img = np.full((int(H * ppm), int(W * ppm)), 255, np.uint8)
    x0 = int((W - cols * a.square_mm) / 2 * ppm)
    y0 = int((H - rows * a.square_mm) / 2 * ppm)
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                cv2.rectangle(img, (x0 + int(c * a.square_mm * ppm), y0 + int(r * a.square_mm * ppm)),
                              (x0 + int((c + 1) * a.square_mm * ppm), y0 + int((r + 1) * a.square_mm * ppm)),
                              0, -1)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    png = os.path.splitext(a.out)[0] + ".png"
    cv2.imwrite(png, img)
    Image.open(png).convert("L").save(a.out, resolution=ppm * 25.4)   # dpi 换算成 ppm
    print("板: %s (%d B) · 内角点 %dx%d · 方格 %.1fmm · A4 · 打印 100%% 不缩放"
          % (a.out, os.path.getsize(a.out), inner_c, inner_r, a.square_mm))
    print("PNG 备用: %s" % png)


if __name__ == "__main__":
    main()
