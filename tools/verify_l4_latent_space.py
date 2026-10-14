#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: L4 潜空间 (VLM 通用视觉编码器 → 黎曼度规约束 → INTACT 意图解码) —— 老倪 2026-10-14

① VLM 通用视觉编码器真跑 (帧 → 特征维度 / 时延 / 设备)
② 用**真实帧**拟 L4 标定 (n 帧 · 解释方差 · det(g_f)=1 · V 在 g_f 下正交)
③ 帧 → 16 维潜坐标 (有限、非退化)
④ 流形引擎接入: latent_provider=VLM→L4; z_source 写明; 无 provider 时零回归 (PCA 逐位)
⑤ 度规约束证据: g_f 白化后特征协方差 ≈ I · 引擎侧 g=M·G(x) det=1
⑥ INTACT 意图解码: 潜空间 Δz=z_goal−z_t (真实两帧) + INTACT 现状如实标 (z_t 有限 / z_pred NaN)
"""
from __future__ import annotations

import glob
import os
import sys
import time

import numpy as np

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.manifold.manifold_engine import ManifoldEngine            # noqa: E402
from lerobot.manifold.encoder_vlm import VLMVisionEncoder              # noqa: E402
from lerobot.manifold.l4_latent import L4LatentSpace                   # noqa: E402

ok_all = []


def chk(tag, cond, detail=""):
    ok_all.append(bool(cond))
    print("%s %s %s" % ("✅" if cond else "❌", tag, detail))


def collect_frames(n_max: int = 24) -> list:
    """真实帧来源: L5 槽位图 (真机/工位相机) + AR 相机快照。取不到就如实报少。"""
    fs = []
    for pat in ("zmax_data/l5_slots/*/local2.jpg", "zmax_data/l5_slots/*/local.jpg",
                "zmax_data/ar_snapshots/*.jpg", "zmax_data/ar_snapshots/*/*.jpg",
                "/tmp/zmax_ar_*.jpg"):
        fs += sorted(glob.glob(os.path.join(ROOT, pat)))
    fs = fs[:n_max]
    return fs


def main() -> int:
    frames = collect_frames()
    print("真实帧来源: %d 张 (L5 槽位图/AR 快照)" % len(frames))
    enc = VLMVisionEncoder()
    ok, why = enc.available()
    chk("① VLM 通用视觉编码器", ok, why)
    if not ok:
        print("判据 %d/%d (编码器不可用 ⇒ 如实停在这里)" % (sum(ok_all), len(ok_all)))
        return 1
    if not frames:
        print("❌ 没有真实帧 ⇒ 无法拟标定 (如实停, 不造数据)")
        return 2

    t0 = time.time()
    feats = []
    for p in frames:
        feats.append(enc.encode(p))
    F = np.asarray(feats, float)
    dt = (time.time() - t0) / max(1, len(frames))
    chk("① 编码时延/维度", F.shape[1] == int(enc.feature_dim) and F.shape[0] == len(frames),
        "特征 %s · %.0fms/帧 (设备 %s)" % (F.shape, dt * 1e3, getattr(enc, "_device", "?")))

    space = L4LatentSpace(ROOT, 16)
    calib = space.fit(F, frames_note="L5 槽位图/AR 快照", save=True)
    chk("② 拟标定 (真实帧)", int(calib["n_frames"]) == len(frames) and abs(calib["det_g_f"] - 1.0) < 1e-6,
        "n=%d · det(g_f)=%.6f · 解释方差 %.1f%% · latent=%d"
        % (calib["n_frames"], calib["det_g_f"], 100 * calib["explained_var"], calib["latent_dim"]))

    zs = []
    for f in F[:8]:
        z, note = space.project(f)
        zs.append(z)
    Z = np.asarray(zs)
    chk("③ 帧 → 16 维潜坐标", Z.shape[1] == 16 and np.isfinite(Z).all() and float(Z.std(0).max()) > 1e-6,
        "z%s · 各维 std 范围 %.3g~%.3g" % (Z.shape, float(Z.std(0).min()), float(Z.std(0).max())))

    # ⑤ 黎曼度规约束的两条**可验证**证据 (不看空话看数):
    #    (a) g_f 白化后各维方差 ≈ 1 (单位度量) —— 允许 (n-1)/n 的样本估计偏差
    #    (b) 潜坐标在度规下已解耦: cov(z) 非对角 / 对角 ≈ 0
    c = space.calib
    mu = np.asarray(c["mu"], float)
    gd = np.asarray(c["g_f_diag"], float)
    mask = np.asarray(c.get("dim_mask") or [True] * mu.size, bool)
    Fk = F[np.isfinite(F).all(axis=1)][:, mask]
    W = (1.0 / np.sqrt(gd)) * (Fk - mu)
    var = np.var(W, axis=0)
    # 白化 + det=1 归一的**正确不变量**: 各维方差**相同**(各向同性); det=1 只定整体尺度 ⇒ 不要求 var=1
    ratio = float(var.max() / max(var.min(), 1e-12))
    chk("⑤a g_f 白化 ⇒ 各维等方差 (各向同性)", ratio < 1.05,
        "var max/min=%.4f (均匀尺度 %.4f) · 参与度规维 %s/%s · det(g_f)=%.6f (体积保持)"
        % (ratio, float(var.mean()), c.get("n_dims_kept"), mu.size, c["det_g_f"]))
    V = np.asarray(c["V"], float)
    Zc = V.T @ W.T                     # V(d,dim)ᵀ · Wᵀ(d,n) ⇒ (dim,n)
    Cz = np.cov(Zc) if Zc.shape[1] > 1 else np.eye(Zc.shape[0])
    rel = float(np.abs(Cz - np.diag(np.diag(Cz))).max() / max(float(np.diag(Cz).max()), 1e-12))
    chk("⑤b 度规下潜坐标解耦 (非对角/对角≈0)", rel < 0.05, "相对非对角=%.2e" % rel)

    # ④ 引擎接入 + 零回归
    npz = os.path.join(ROOT, "models", "manifold_engine.npz")
    e0 = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4, manifold_M=3.643)
    e0.load(npz)
    r0 = e0.project(np.zeros(43) + 0.1)
    e1 = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4, manifold_M=3.643)
    e1.load(npz)
    z_now, note = space.project(F[-1])
    e1.set_latent_provider(lambda: z_now, note)
    r1 = e1.project(np.zeros(43) + 0.1)
    chk("④ 引擎接入 L4 潜空间", np.allclose(r1["z"], z_now) and "L4 潜空间" in str(r1["z_source"]),
        "z_source=%s" % str(r1["z_source"])[:110])
    chk("④ 无 provider ⇒ 零回归内建 PCA", "PCA" in str(r0["z_source"]),
        "z_source=%s" % str(r0["z_source"])[:70])

    # ⑥ INTACT 意图解码 (潜空间 Δz + INTACT 现状)
    dz = z_now - Z[0]
    chk("⑥ 潜空间 Δz=z_goal−z_t (给意图解码用)", bool(np.isfinite(dz).all()),
        "Δz%s · ‖Δz‖₂=%.4f" % (dz.shape, float(np.linalg.norm(dz))))
    try:
        from lerobot.manifold.encoder_model import IntactEncoderModel
        m = IntactEncoderModel(ROOT)
        okj, whyj = m.available()
        if okj:
            lat = m.encode()
            zp = np.asarray(lat.get("z_pred"), float)
            fin = bool(np.isfinite(zp).all())
            chk("⑥ INTACT 意图解码可用 (z_t 有限)", bool(np.isfinite(np.asarray(lat.get("z_t"), float)).all()),
                "z_t=%s 有限 · z_pred %s (动作块 NaN ⇒ 预测潜表示拿不到, 如实标)"
                % (np.asarray(lat.get("z_t")).shape, "有限" if fin else "= NaN (上游 chunk 空)"))
        else:
            chk("⑥ INTACT 意图解码可用", False, whyj[:110])
    except Exception as ex:                                           # noqa: BLE001
        chk("⑥ INTACT 意图解码可用", False, "%s: %s" % (type(ex).__name__, str(ex)[:90]))

    print("判据 %d/%d %s" % (sum(ok_all), len(ok_all), "PASS" if all(ok_all) else "FAIL(见上)"))
    print("标定落盘: models/l4_latent_calib.json")
    return 0 if all(ok_all) else 1


if __name__ == "__main__":
    raise SystemExit(main())
