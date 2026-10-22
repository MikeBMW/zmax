#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 verify_hjepa_engine.py — H-JEPA 真接进流形引擎的**判据** (老倪 2026-10-22 A)

判 9 条, 每条都指向"代码真的跑到了"而不是"文件存在":
  J1 权重 strict 全量对齐 (71 张量) —— 结构反推与权重一致的**唯一硬证据**
  J2 三层潜维 = 256/256/128 ⇒ 640 拼接 (以权重为准, 不是节点参数写的 128/128/64)
  J3 真帧前向输出有限 (无 NaN/Inf), 输出头 98 维
  J4 确定性: 同一 (帧, state) 两次前向逐位相同 (差 < 1e-6)
  J5 引擎接线: set_hjepa_provider 后 step() 的 rec["hjepa"] 真出现, z_dim=640, 三层范数/能量齐
  J6 一致性: rec["hjepa"].norms.z1 == 独立前向 ‖z1‖ (同 state 同帧)
  J7 零回归: 不接 provider ⇒ rec 里**没有** hjepa 键, 且 action/phi 与接前逐位相同
  J8 state 敏感度: state 单维 ±0.3 后潜表示余弦 < 0.999 (真在用它)
  J9 画面敏感度: 8 张真帧 v_enc 余弦 < 0.995 (⚠️ 这条是**该权重的体检**, 红了说明图像支路形同常数)
     —— 通了不代表模型好; 红/绿都如实报, 不拿它当"接入成功"的分。

跑法: gui-venv311/bin/python tools/verify_hjepa_engine.py
"""
from __future__ import annotations

import glob
import io
import json
import os
import sys

import numpy as np

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

R = []


def chk(tag, name, ok, detail=""):
    R.append((tag, name, bool(ok), detail))
    print(("%s %-4s %s%s" % ("✅" if ok else "❌", tag, name,
                             ("  · " + detail) if detail else "")))


def main() -> int:
    from lerobot.manifold.hjepa_model import HJEPAModel
    from lerobot.manifold.hjepa_state import HJEPAStateProvider

    traj = os.path.join(ROOT, "data/database/zmax/sources/canvas/ss_traj_last.json")
    with io.open(traj, encoding="utf-8") as fh:
        O = np.asarray(json.load(fh)["obs"], float)
    s43 = O[-1]
    s7 = s43[:7].copy()

    # 真帧 (内容非黑: 选 std 最大的目录)
    frames = []
    for d in sorted(glob.glob(os.path.join(ROOT, "zmax_data/eval_frames/live_*")))[-12:]:
        fs = sorted(glob.glob(os.path.join(d, "*.png")))
        if len(fs) >= 6:
            frames = fs[:8]
            break
    if not frames:
        frames = sorted(glob.glob(os.path.join(ROOT, "zmax_data/eval_frames/live_*/*.png")))[:8]

    import torch                                                    # noqa: PLC0415
    from PIL import Image                                           # noqa: PLC0415

    m = HJEPAModel(root=ROOT)

    # ── J1 ──
    ok, why = m.available()
    sd = torch.load(m.ckpt_path, map_location="cpu", weights_only=False) if os.path.isfile(m.ckpt_path) else {}
    chk("J1", "权重 strict 全量对齐 (71 张量, 无缺/无多)", ok and len(sd) == 71, why)

    # ── J2 ──
    img = np.asarray(Image.open(frames[3]).convert("RGB")) if frames else np.zeros((64, 64, 3), np.uint8)
    out = m.infer(img, s7)
    dims = list(out.get("dims") or [])
    zc = out.get("z_concat")
    zc_n = 0 if zc is None else int(np.asarray(zc).size)
    chk("J2", "三层潜维 256/256/128 ⇒ 640 拼接", dims == [256, 256, 128] and zc_n == 640,
        "dims=%s · z_concat=%d" % (dims, zc_n))

    # ── J3 ──
    fin = bool(out.get("ok")) and all(np.all(np.isfinite(x)) for x in
                                      ([out["z1"], out["z2"], out["z3"], out["head"]]))
    zc = out.get("z_concat")
    chk("J3", "真帧前向输出有限 (无 NaN/Inf), 动作头 98 维", fin and out.get("head") is not None
        and np.asarray(out["head"]).size == 98,
        "energy=%s · gates=%s" % (np.round(out.get("energy") or [], 3), np.round(out.get("gates") or [], 3)))

    # ── J4 确定性 ──
    o2 = m.infer(img, s7)
    dz = max(float(np.abs(np.asarray(out[k]) - np.asarray(o2[k])).max()) for k in ("z1", "z2", "z3"))
    chk("J4", "确定性: 同帧同 state 两次前向逐位相同 (<1e-6)", dz < 1e-6, "max|Δ|=%.2e" % dz)

    # ── J5/J6 引擎接线 ──
    from lerobot.manifold.manifold_engine import ManifoldEngine         # noqa: PLC0415
    eng = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4)
    fit = eng.fit(O[-400:])
    eng.goal_point = eng.project(O[-1])["p"]
    rec0 = eng.step(np.asarray(s43, float), dt=0.05)
    prov = HJEPAStateProvider(ROOT, state_fn=lambda: s7, frame_path=(frames[3] if frames else ""))
    okp, whyp = prov.start()
    info = eng.set_hjepa_provider(prov, prov.note_base)
    rec1 = eng.step(np.asarray(s43, float), dt=0.05)
    hj = rec1.get("hjepa")
    chk("J5", "引擎 step() 真出 rec['hjepa'] (z_dim=640 + 三层范数/能量)", okp and isinstance(hj, dict)
        and hj.get("ok") and hj.get("z_dim") == 640 and set(hj.get("norms") or {}) == {"z1", "z2", "z3"}
        and len(hj.get("energy") or []) == 3,
        "provider=%s · hjepa=%s" % (whyp, {k: hj.get(k) for k in ("z_dim", "norms", "energy", "ms")} if isinstance(hj, dict) else None))
    z1n = float(np.linalg.norm(out["z1"])) if out.get("ok") else float("nan")
    chk("J6", "一致性: 引擎里 ‖z₁‖ == 独立前向 ‖z₁‖ (同 state 同帧)",
        isinstance(hj, dict) and abs(float((hj.get("norms") or {}).get("z1") or -1) - z1n) < 1e-3,
        "引擎 %.4f vs 独立 %.4f" % (float((hj or {}).get("norms", {}).get("z1") or -1), z1n))

    # ── J7 零回归 (拿另一台干净引擎, 避免 provider 摘除路径受上次状态影响) ──
    eng2 = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4)
    eng2.fit(O[-400:])
    eng2.goal_point = eng2.project(O[-1])["p"]
    r_off = eng2.step(np.asarray(s43, float), dt=0.05)
    d_phi = abs(float(r_off.get("phi") or 0) - float(rec0.get("phi") or 0))
    d_a = float(np.abs(np.asarray(r_off.get("action"), float) - np.asarray(rec0.get("action"), float)).max())
    chk("J7", "零回归: 不接 provider ⇒ rec 无 hjepa 键, phi/action 与接前逐位相同",
        ("hjepa" not in r_off) and d_phi < 1e-12 and d_a == 0.0,
        "Δφ=%.2e · max|Δa|=%.2e · 键=%d" % (d_phi, d_a, len(r_off)))

    # ── J8 state 敏感度 ──
    Zs = []
    for j in range(7):
        s = s7.copy()
        s[j] += 0.3
        Zs.append(np.asarray(m.infer(img, s)["z_concat"], float))
    Zs = np.stack(Zs)
    base = np.asarray(out["z_concat"], float)
    cs = [float(base @ z / (np.linalg.norm(base) * np.linalg.norm(z) + 1e-12)) for z in Zs]
    chk("J8", "state 单维 ±0.3 后潜表示余弦 < 0.999 (真在用它)", max(cs) < 0.999,
        "cos=%s" % np.round(cs, 4))

    # ── J9 画面敏感度 (权重体检; 红=图像支路不生效) ──
    V = []
    with torch.no_grad():
        for f in frames:
            a = np.asarray(Image.open(f).convert("RGB"))
            V.append(m._net.v_enc(m._prep_frame(a))[0].numpy())          # type: ignore[union-attr]
    V = np.stack(V)
    cim = [float(V[0] @ v / (np.linalg.norm(V[0]) * np.linalg.norm(v) + 1e-12)) for v in V[1:]]
    #   阈值 0.995 = "至少 0.5% 的方向差"; 实测 0.9982~1.0000 ⇒ 图像支路近似常数 (如实判红, 不抬线)
    chk("J9", "画面: 8 张真帧 v_enc 余弦 < 0.995 (图像支路生效)", min(cim) < 0.995,
        "帧间 cos min=%.6f max=%.6f · |v| %.2f~%.2f" % (min(cim), max(cim),
                                                       float(np.linalg.norm(V, axis=1).min()),
                                                       float(np.linalg.norm(V, axis=1).max())))

    n_pass = sum(1 for _, _, o, _ in R if o)
    print("\n═══ 判据 %d 条: PASS %d · FAIL %d ═══" % (len(R), n_pass, len(R) - n_pass))
    out_dir = os.path.join(ROOT, "zmax_data/eval")
    os.makedirs(out_dir, exist_ok=True)
    with io.open(os.path.join(out_dir, "hjepa_engine_verify.json"), "w", encoding="utf-8") as fh:
        json.dump({"ts": __import__("time").strftime("%F %T"), "pass": n_pass, "n": len(R),
                   "items": [{"tag": t, "name": n, "ok": o, "detail": d} for t, n, o, d in R]},
                  fh, ensure_ascii=False, indent=1)
    prov.stop() if hasattr(prov, "stop") else None
    return 0 if n_pass == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
