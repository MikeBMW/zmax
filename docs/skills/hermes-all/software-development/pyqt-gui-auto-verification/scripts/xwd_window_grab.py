#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xwd_window_grab.py <winid> <out.png> —— 抓某个 X 窗口自己的后备缓冲 (被遮挡也可用), 不依赖 ImageMagick。

为什么需要它:
  · 机器上常没有 ImageMagick (`import` 不存在), `scrot -u` 只截"当前聚焦窗口",
    而 `wmctrl -i -a <winid>` 抬窗可能静默失败 (mutter 把 frame 与 client 分成两个 id, 抬的是另一个)
    ⇒ 截到的是压在上面的窗口 (实测 OCR 出来全是自己的终端文字)。
  · `xwd -id <winid>` 在合成器下拿到的是该窗口自己的内容, 与是否被遮挡无关;
    只是 PIL 打不开 `.xwd` ⇒ 本脚本自己解 XWD 头并按 mask 还原通道。

用法:
  DISPLAY=:0 <venv>/bin/python xwd_window_grab.py 0x20058a /tmp/win.png
  winid 取自 `wmctrl -l` 或 `xwininfo -root -tree`。

输出末尾打印 尺寸 / 均值 / 非背景像素占比, 用于自证"不是黑图/空图"。
XWD 头 = 25 个大端 int (XWD_FILE_VERSION 7):
  h[0]=header_size · h[4]=w · h[5]=h · h[11]=bits_per_pixel · h[12]=bytes_per_line
  h[14..16]=red/green/blue mask · h[19]=ncolors · 像素起点 = header_size + ncolors*12
"""
import os
import struct
import subprocess
import sys

import cv2
import numpy as np


def grab(winid: str, out: str) -> int:
    tmp = out + ".xwd"
    subprocess.run(["xwd", "-id", winid, "-out", tmp], check=True,
                   env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")})
    d = open(tmp, "rb").read()

    hsize, _ver, _fmt, depth, w, h, _xoff, byte_order, _bu, _bbo, _bpad, bpp, bpl, _vis, \
        rmask, gmask, bmask, _brgb, _cmap, ncolors = struct.unpack(">20i", d[:80])
    off = hsize + ncolors * 12
    raw = d[off:off + bpl * h]
    if len(raw) != bpl * h:
        print("!! XWD 数据长度不符: got %d expect %d" % (len(raw), bpl * h), file=sys.stderr)
        return 2

    nb = (bpp + 7) // 8
    lines = np.frombuffer(raw, dtype=np.uint8).reshape(h, bpl)[:, :w * nb].reshape(h, w, nb)
    if byte_order == 0:          # LSBFirst
        val = sum(lines[:, :, i].astype(np.uint32) << (8 * i) for i in range(nb))
    else:                        # MSBFirst
        val = sum(lines[:, :, i].astype(np.uint32) << (8 * (nb - 1 - i)) for i in range(nb))

    def chan(mask):
        if not mask:
            return np.zeros((h, w), np.uint8)
        shift = (mask & -mask).bit_length() - 1
        depth_bits = bin(mask >> shift).count("1")
        v = ((val & mask) >> shift).astype(np.uint32)
        if depth_bits >= 8:
            return (v >> (depth_bits - 8)).astype(np.uint8)
        return (v << (8 - depth_bits)).astype(np.uint8)

    img = cv2.merge([chan(bmask), chan(gmask), chan(rmask)])
    cv2.imwrite(out, img)
    try:
        os.remove(tmp)
    except OSError:
        pass

    bg = int(np.bincount(img.reshape(-1, 3).dot(np.array([1, 256, 65536]))).argmax())
    b, g, r = bg & 0xFF, (bg >> 8) & 0xFF, (bg >> 16) & 0xFF
    nonbg = float((np.abs(img.astype(np.int16) - np.array([b, g, r])).sum(axis=2) > 30).mean())
    print("%s  %dx%d  depth=%d bpp=%d  均值=%.1f  非背景占比=%.3f  (背景 RGB=%d,%d,%d)"
          % (out, w, h, depth, bpp, float(img.mean()), nonbg, r, g, b))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(grab(sys.argv[1], sys.argv[2]))
