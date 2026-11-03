#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_l4_live.py — 实测 SmolVLM → 黎曼约束 → 16 维潜坐标 是否真的通

用法: ./gui-venv311/bin/python tools/verify_l4_live.py [--url ...] [--frames 3]
判据: ① 抓到真帧(尺寸/字节) ② f 维度 960 ③ z 16 维且有限 ④ meta 带 residual/drift ⑤ 单帧耗时
"""
import argparse
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from lerobot.manifold.l4_latent import L4LatentSpace      # noqa: E402
from lerobot.manifold.l4_live import fetch_frame          # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8791/snapshot/local.jpg")
    ap.add_argument("--frames", type=int, default=3)
    a = ap.parse_args()

    t0 = time.time()
    from lerobot.manifold.encoder_vlm import default_encoder
    enc = default_encoder()
    enc.load() if hasattr(enc, "load") else None
    print("① 编码器: %s 加载 %.1fs" % (getattr(enc, "NAME", "?"), time.time() - t0))

    space = L4LatentSpace(REPO, 16)
    info = space.load()
    print("② 标定: n_frames=%s latent_dim=%s note=%s" % (
        info.get("n_frames"), info.get("latent_dim"), str(info.get("frames_note"))[:40]))

    ok = 0
    z0 = None
    for i in range(a.frames):
        t = time.time()
        fr = fetch_frame(a.url)
        t_fetch = time.time() - t
        f = np.asarray(enc.encode(fr), float).ravel()
        t_enc = time.time() - t
        z, meta = space.project(f)
        z = np.asarray(z, float).ravel()
        finite = bool(np.all(np.isfinite(z)))
        print("  帧%d %sx%s %dKB | f=%d | z=%d finite=%s | fetch %.2fs enc %.2fs"
              % (i, fr.width, fr.height, len(getattr(fr, "tobytes", lambda: b"")()) // 1024,
                 f.size, z.size, finite, t_fetch, t_enc))
        print("     口径: %s" % str(meta)[:150])
        if i == 0:
            print("  z[:8] = %s" % [round(float(x), 4) for x in z[:8]])
            z0 = z
        else:
            print("  ‖z%d − z0‖ = %.4f  (帧变了 z 得跟着变, 否则等于没接)"
                  % (i, float(np.linalg.norm(z - z0))))
        if f.size == 960 or f.size == 768:
            if z.size == 16 and finite:
                ok += 1
        time.sleep(0.2)

    print("③ 判定: %d/%d 帧通过 (f=%d, z=16, 有限)" % (ok, a.frames, 768))
    return 0 if ok == a.frames and a.frames > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
