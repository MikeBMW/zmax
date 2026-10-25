#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""位姿↔渲染对齐自检: 用 cameras.json 里**采集时的位姿**渲一帧, 与当帧真实照片对比。

用途(2026-10-25): 老倪要「3DGS 视角与手臂相机同步」。同步是否接对, 不能靠当前位姿黑不黑来判
(当前臂在碰撞位, 已离开采集覆盖锥), 要用**已知位姿 + 已知照片**来验:
  · 若 PSNR/SSIM 与训练报告的留出水平相当 ⇒ 位姿→viewmat→渲染 这条链是对的
  · 若明显偏低 ⇒ 位姿约定/手眼/归一化有错

用法: python gs_render_pose_check.py --job <dir> --ply <ply> --frames 4
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, "/home/intel/zmax_map/tools")
sys.path.insert(0, "/home/ubuntu/zmax/tools")
from gs_render_stream_intel import read_gs_ply  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--ply", default="")
    ap.add_argument("--frames", type=int, default=4)
    ap.add_argument("--outdir", default="/tmp/gs_pose_check")
    a = ap.parse_args()

    import torch
    import gsplat
    from PIL import Image

    cj = json.load(open(os.path.join(a.job, "ds/cameras.json"), encoding="utf-8"))
    rep = json.load(open(os.path.join(a.job, "out/train_report.json"), encoding="utf-8"))
    norm = rep.get("normalize") or {}
    center = np.array(norm.get("center"), dtype=float)
    S = float(norm.get("S"))
    W, H = int(cj["width"]), int(cj["height"])
    K = np.array(cj["K"], dtype=float)
    ply = a.ply or os.path.join(a.job, "out/gs_pruned.ply")

    P = read_gs_ply(ply)
    n = len(P["means"])
    dev = "xpu" if torch.xpu.is_available() else "cpu"
    means = torch.tensor(S * (P["means"] - center), dtype=torch.float32, device=dev)
    scales = torch.tensor(P["scales_log"] + math.log(S), dtype=torch.float32, device=dev)
    quats = torch.tensor(P["quats"], dtype=torch.float32, device=dev)
    opac = torch.tensor(P["opac"], dtype=torch.float32, device=dev)
    sh0 = torch.tensor(P["sh0"], dtype=torch.float32, device=dev)
    shN = torch.tensor(P["shN"], dtype=torch.float32, device=dev)
    sh_deg = int(round(math.sqrt(shN.shape[1] + 1) - 1))
    col = torch.cat([sh0, shN], dim=1)
    Kt = torch.tensor(K, dtype=torch.float32, device=dev).unsqueeze(0)
    print("ply=%s · %d 高斯 · SH%d · %dx%d · dev=%s" % (ply, n, sh_deg, W, H, dev), flush=True)

    frames = cj["frames"]
    step = max(1, len(frames) // a.frames)
    os.makedirs(a.outdir, exist_ok=True)
    rows = []
    for i in range(0, len(frames), step)[:a.frames]:
        fr = frames[i]
        T = np.array(fr["T_cam2world"], dtype=float)
        Tn = np.eye(4)
        Tn[:3, :3] = T[:3, :3]
        Tn[:3, 3] = S * (T[:3, 3] - center)
        vm = torch.tensor(np.linalg.inv(Tn), dtype=torch.float32, device=dev).unsqueeze(0)
        with torch.no_grad():
            img, _, _ = gsplat.rasterization(means, quats, torch.exp(scales), torch.sigmoid(opac), col,
                                             viewmats=vm, Ks=Kt, width=W, height=H,
                                             sh_degree=sh_deg, packed=True, near_plane=0.01)
        r = img[0].clamp(0, 1).mul(255).byte().cpu().numpy()
        img_path = os.path.join(a.job, "ds/images", fr["file"])
        if not os.path.exists(img_path):
            img_path = os.path.join(a.job, "ds", fr["file"])
        gt = np.array(Image.open(img_path).convert("RGB").resize((W, H)))
        mse = float(((r.astype(float) - gt.astype(float)) ** 2).mean())
        psnr = 10 * math.log10(255.0 ** 2 / max(mse, 1e-9))
        # 简易 SSIM(灰度, 8x8 块均值近似)
        ga = r.mean(2); gb = gt.astype(float).mean(2)
        mu_a, mu_b = ga.mean(), gb.mean()
        va, vb = ga.var(), gb.var()
        cov = ((ga - mu_a) * (gb - mu_b)).mean()
        ssim = ((2*mu_a*mu_b) * (2*cov)) / ((mu_a**2 + mu_b**2) * (va + vb) + 1e-9)
        both = np.concatenate([r, gt], axis=1)
        out = os.path.join(a.outdir, "cmp_%04d.png" % i)
        Image.fromarray(both).save(out)
        rows.append((i, fr["file"], psnr, ssim, out))
        print("  帧 %-4d %-12s PSNR %.2f dB  SSIM %.3f → %s" % (i, fr["file"], psnr, ssim, out), flush=True)

    if rows:
        p = np.array([x[2] for x in rows]); s = np.array([x[3] for x in rows])
        print("\n均值 PSNR %.2f dB · SSIM %.3f  (训练报告 holdout=%.2f / train=%.2f)"
              % (p.mean(), s.mean(), rep.get("psnr_holdout_db") or -1, rep.get("psnr_train_db") or -1))


if __name__ == "__main__":
    main()
