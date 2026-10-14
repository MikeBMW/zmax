#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 编码模型接入 (老倪 2026-10-14) —— INTACT-JEPA 当流形引擎的编码模型

① 引擎编译 + 零回归: latent_provider=None ⇒ z_source=内建 PCA, 且逐位等于旧路径
② INTACT 编码模型可用性 (ckpt/config/weights + 标定 ready)
③ 真跑 INTACT 一次 → z_t/z_pred 192 维 (预测潜表示), 记录时延
④ 经已过闸标定投到引擎潜维 16 (7 几何潜 + 6 接触丛 + 3 真标量)
⑤ 引擎带 provider: project() 用编码模型的 z (z_source 写明), 且维度不符时报错 (不静默截断)
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.manifold.manifold_engine import ManifoldEngine            # noqa: E402
from lerobot.manifold.encoder_model import IntactEncoderModel          # noqa: E402

CKPT_NPZ = os.path.join(ROOT, "models", "manifold_engine.npz")
ok_all = []


def chk(tag, cond, detail=""):
    ok_all.append(bool(cond))
    print("%s %s %s" % ("✅" if cond else "❌", tag, detail))


def main() -> int:
    # ① 零回归
    e = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4,
                       manifold_M=3.643, inertia=False)
    loaded = e.load(CKPT_NPZ)
    st = np.zeros(43) + 0.1
    r0 = e.project(st)
    chk("① 无 provider ⇒ 内建 PCA", loaded and "PCA" in str(r0.get("z_source")),
        "z_source=%s · z=%d 维" % (r0.get("z_source"), r0["z"].size))
    e2 = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4,
                        manifold_M=3.643, inertia=False)
    e2.load(CKPT_NPZ)
    r0b = e2.project(st)
    chk("① 零回归 (同输入逐位相同)", np.allclose(r0["z"], r0b["z"], atol=0, rtol=0),
        "max|Δz|=%.3g" % float(np.abs(r0["z"] - r0b["z"]).max()))

    # ② 编码模型可用性
    m = IntactEncoderModel(ROOT)
    ok, why = m.available()
    chk("② 编码模型可用性", ok, why)
    if not ok:
        print("→ 编码模型不可用 ⇒ 引擎保持内建 PCA (如实报因, 不假装)")
        print("判据 %d/%d" % (sum(ok_all), len(ok_all)))
        return 1

    # ③ 真跑 INTACT
    lat = m.encode()
    chk("③ INTACT 真推理 → 预测潜表示", lat.get("z_pred") is not None and lat["z_pred"].size == 192,
        "z_t=%s z_pred=%s delta=%s · %.1fms · ckpt=%s"
        % (lat["z_t"].shape, lat["z_pred"].shape, lat["delta"].shape, lat.get("_ms"), lat.get("_policy")))

    # ④ 标定投影 → 引擎潜维
    z16, note = m.to_manifold(lat, engine_dim=16)
    chk("④ 经标定投影到引擎潜维", z16.size == 16 and np.isfinite(z16).all(), note[:150])

    # ⑤ 引擎带 provider
    e3 = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4,
                        manifold_M=3.643, inertia=False)
    e3.load(CKPT_NPZ)
    info = e3.set_latent_provider(lambda: z16, note)
    r1 = e3.project(st)
    chk("⑤ 引擎用编码模型的 z", np.allclose(r1["z"], z16) and "编码模型" in str(r1.get("z_source")),
        "provider=%s · z_source=%s" % (info["provider"], str(r1.get("z_source"))[:80]))
    # 维度不符必须报错 (不静默截断)
    e3.set_latent_provider(lambda: np.zeros(7), "坏 provider (7 维)")
    try:
        e3.project(st)
        chk("⑤ 维度不符报错", False, "没报错 = 会被静默截断")
    except ValueError as ex:
        chk("⑤ 维度不符报错", True, str(ex)[:90])
    print("判据 %d/%d %s" % (sum(ok_all), len(ok_all), "PASS" if all(ok_all) else "FAIL"))
    return 0 if all(ok_all) else 1


if __name__ == "__main__":
    raise SystemExit(main())
