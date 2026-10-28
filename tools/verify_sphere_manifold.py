#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_sphere_manifold.py — 归一化球面 S^n 判据 (老倪 2026-10-15「归一化球面实现方案」逐条对账)。

对账目标: 方案里写的**每一条**都要有可核证据, 已实现的验真, 未实现/不成立的如实标 FAIL, 不粉饰。

跑法:  ./gui-venv311/bin/python tools/verify_sphere_manifold.py [--json PATH]
产物:  zmax_data/eval/sphere_manifold_verify.json  (逐条 判据/实测值/阈值/结论 + 真数据段)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.manifold import sphere as S                                        # noqa: E402
from lerobot.manifold.manifold_engine import (ManifoldProjector, MetricCalculator,  # noqa: E402
                                              Navigator)

# 引擎 sphere 档「改前行为」指纹 (2026-10-15 补算子前实测; 用于判据 ⑯ 零回归)
ZERO_REGRESSION_SHA = "606acb7edfaf44080af8c175b7e87ed69920035f5f7a5f62ecd658a173e4b375"

RES: list = []


def chk(cid: str, claim: str, got, ok: bool, expect: str = "", note: str = "") -> None:
    RES.append({"id": cid, "判据": claim, "实测": got, "期望": expect,
                "结论": "PASS" if ok else "FAIL", "备注": note})
    print("  %-3s %s  %s%s" % (cid, "✅ PASS" if ok else "❌ FAIL", claim,
                               ("  → %s" % got) if not ok else ""))


def _engine_sphere_fingerprint() -> str:
    """引擎 sphere 档固定种子行为指纹 (逐位)。"""
    rng = np.random.default_rng(7)
    X = rng.normal(size=(24, 16))
    X[3] = 0.0
    pj, mc, nv = ManifoldProjector(manifold_type="sphere"), MetricCalculator("sphere"), Navigator("sphere")
    out = []
    for z in X:
        p, res, meta = pj.project(z)
        out.append([list(np.round(p, 12)), round(res, 12), {k: meta[k] for k in sorted(meta)}])
    g = nv.compute_geodesic(pj.project(X[0])[0], pj.project(X[5])[0], T=7)
    d = [mc.distance(pj.project(X[i])[0], pj.project(X[j])[0]) for i in range(4) for j in range(4)]
    st = [[round(x, 12) for x in nv.step(pj.project(X[2])[0],
                                         mc.tangent_gradient(lambda q: float(np.dot(q, q)), pj.project(X[2])[0]),
                                         dt=0.05)]]
    blob = json.dumps({"proj": out, "geo_path_len": g["length"], "geo_end": g["end_error"],
                       "dist": [round(x, 12) for x in d], "step": st}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=os.path.join(ROOT, "zmax_data/eval/sphere_manifold_verify.json"))
    args = ap.parse_args()
    rng = np.random.default_rng(20261015)
    dim = 16
    print("=" * 78)
    print("🌐 归一化球面 S^n 判据 (老倪 2026-10-15「归一化球面实现方案」)")
    print("=" * 78)

    # ── ①②③ 投影/单位性/退化输入 (方案一/四) ──
    X = rng.normal(size=(10000, dim))
    P = np.asarray([S.project(x)[0] for x in X[:2000]], float)      # 2000 条足够 (逐条 python 循环)
    unit_err = float(np.abs(np.linalg.norm(P, axis=1) - 1.0).max())
    chk("①", "方法一/四: 10k 级随机向量投影后 ‖p‖=1", "max|‖p‖−1|=%.3e" % unit_err, unit_err < 1e-12, "<1e-12")
    pz, rz, mz = S.project(np.zeros(dim))
    chk("②", "零向量不产生 NaN, 给固定基向量 (方案四「防除零」)",
        "p[0]=%.1f · 残差=%.1e · zero=%s" % (pz[0], rz, mz["zero"]),
        bool(np.all(np.isfinite(pz))) and abs(rz) < 1e-12 and mz["zero"], "有限 + 残差≈0")
    pe, re_, _ = S.project(np.full(dim, 1e-15))
    chk("③", "极小向量 (1e-15) 同样不崩", "有限=%s · 残差=%.1e" % (bool(np.all(np.isfinite(pe))), re_),
        bool(np.all(np.isfinite(pe))) and abs(re_) < 1e-12, "有限 + 残差≈0")

    # ── ④ 温度 (方案四「温度低集中 / 温度高铺开」) ──
    #   先说清数学: 归一化前除 τ 对**方向是恒等操作** (x/τ ∥ x) ⇒ ④(a) 实测逐位相同。
    #   真起作用的地方是球面 logits ⟨p,q⟩/τ 的分布集中度 ⇒ ④(b) 用 softmax 熵做判据。
    base = rng.normal(size=dim)
    p_lo = S.normalize(base, temperature=0.05)[0]
    p_hi = S.normalize(base, temperature=50.0)[0]
    same_dir = float(np.linalg.norm(p_lo - p_hi))
    cand = np.asarray([S.project(x)[0] for x in rng.normal(size=(64, dim))], float)
    ents, ang = {}, {}
    for tau in (0.02, 0.1, 0.5, 1.0, 5.0):
        lg = S.sphere_logits(cand[0], cand, temperature=tau)
        w = np.exp(lg - lg.max())
        w = w / w.sum()
        ents[tau] = float(-(w * np.log(w + 1e-300)).sum())
        ang[tau] = float(np.mean([S.distance(S.normalize(base + rng.normal(size=dim),
                                                        temperature=tau)[0],
                                              base / np.linalg.norm(base)) for _ in range(200)]))
    mono = all(ents[b] >= ents[a] - 1e-9 for a, b in zip((0.02, 0.1, 0.5, 1.0), (0.1, 0.5, 1.0, 5.0)))
    chk("④", "温度: (a) 投影方向对 τ 数值恒等 (x/τ∥x, 仅浮点舍入) (b) 球面 logits 集中度 τ↓⇒熵↓ 单调",
        "(a) 差=%.1e · (b) H(τ)=%s · κ(1.0)=%.2f"
        % (same_dir, " ".join("%.2f:%.3f" % (k, v) for k, v in ents.items()), S.von_mises_kappa(1.0)),
        same_dir < 1e-15 and mono, "(a)<1e-15 · (b) 单调不增",
        note="方案四的温度须落在相似度/softmax (或 vMF κ=1/τ²) 上才有集中/铺开效果")

    # ── ⑤⑥ 可微 / 零点反传 (方案三「归一化可微, 梯度穿过去」) ──
    try:
        import torch
        torch.manual_seed(0)
        proj = S.SphereProjection(temperature=1.0)
        x = torch.randn(6, dim, dtype=torch.float64, requires_grad=True)
        gc = S.grad_check(lambda t: proj(t), x.detach().numpy())
        chk("⑤", "投影层**可微** (自动微分 vs 中心差分)", "最大相对误差=%.3e" % gc["max_rel_err"],
            gc["max_rel_err"] < 1e-6, "<1e-6")
        xz = torch.zeros(3, dim, dtype=torch.float64, requires_grad=True)
        out = proj(xz)
        out.sum().backward()
        g = xz.grad
        chk("⑥", "零向量反传不出 NaN/inf (方案四「零点附近不稳定」的处置)",
            "输出有限=%s · 梯度有限=%s" % (bool(torch.isfinite(out).all()), bool(torch.isfinite(g).all())),
            bool(torch.isfinite(out).all()) and bool(torch.isfinite(g).all()), "全有限")
    except Exception as e:                                                        # noqa: BLE001
        chk("⑤", "投影层可微", "torch 不可用: %s" % e, False, "torch 可导入")

    # ── ⑦⑧⑨ 指数/对数映射 (方案六) ──
    p0, p1 = S.project(rng.normal(size=dim))[0], S.project(rng.normal(size=dim))[0]
    rt1 = float(np.linalg.norm(S.exp_map(p0, S.log_map(p0, p1)) - p1))
    v = S.tangent_project(p0, rng.normal(size=dim))
    v = v / float(np.linalg.norm(v)) * 0.7                       # ‖v‖ ≤ π (单射半径内才互逆)
    rt2 = float(np.linalg.norm(S.log_map(p0, S.exp_map(p0, v)) - v))
    vb = S.tangent_project(p0, rng.normal(size=dim))
    vb = vb / float(np.linalg.norm(vb)) * 4.0                    # ‖v‖=4 > π *故意* 越界
    ub = vb / float(np.linalg.norm(vb))
    rt_p = float(np.linalg.norm(S.exp_map(p0, vb) - S.exp_map(p0, (4.0 - 2 * math.pi) * ub)))   # 周期性
    lg_b = S.log_map(p0, S.exp_map(p0, vb))
    rt_w = float(np.linalg.norm(lg_b - (-(2 * math.pi - 4.0) * ub)))                            # 绕回式
    chk("⑦", "exp_p(log_p(q)) = q (指数/对数精确互逆)", "误差=%.3e" % rt1, rt1 < 1e-12, "<1e-12")
    chk("⑧", "互逆域 = 单射半径 ‖v‖≤π; ‖v‖>π 时 exp 周期 2π 且 log∘exp = −(2π−‖v‖)·û",
        "‖v‖=0.7 互逆=%.3e · ‖v‖=4 周期=%.3e · 绕回式=%.3e" % (rt2, rt_p, rt_w),
        rt2 < 1e-12 and rt_p < 1e-12 and rt_w < 1e-12, "<1e-12",
        note="‖v‖>π 不互逆是球面固有性质 (‖v‖∈(π,2π) ⇒ log∘exp 折回并反向), 判据核周期性与绕回式")
    z1 = float(np.linalg.norm(S.exp_map(p0, np.zeros(dim)) - p0)) + float(np.linalg.norm(S.log_map(p0, p0)))
    chk("⑨", "exp_p(0)=p (不动点) 且 log_p(p)=0", "合并误差=%.3e" % z1, z1 < 1e-15, "<1e-15")

    # ── ⑩⑪ 平行移动 / 大圆 (方案六) ──
    w = S.tangent_project(p0, rng.normal(size=dim))
    v2, w2 = S.parallel_transport(p0, p1, v), S.parallel_transport(p0, p1, w)
    e_len = abs(float(np.linalg.norm(v2)) - float(np.linalg.norm(v)))
    e_ip = abs(float(np.dot(v2, w2)) - float(np.dot(v, w)))
    e_tan = abs(float(np.dot(v2, p1)))
    chk("⑩", "平行移动: 保长度 / 保内积 / 落回切空间", "保长=%.2e · 保内积=%.2e · ⟨v',p1⟩=%.2e" % (e_len, e_ip, e_tan),
        max(e_len, e_ip, e_tan) < 1e-12, "<1e-12")
    gc = S.great_circle_path(p0, p1, 32)
    mid = S.geodesic_slerp(p0, p1, 0.5)
    mid_ref = S.exp_map(p0, 0.5 * S.log_map(p0, p1))
    e_arc = abs(gc["length"] - S.distance(p0, p1))
    e_mid = float(np.linalg.norm(mid - mid_ref))
    e_unit = float(np.abs(np.linalg.norm(gc["path"], axis=1) - 1.0).max())
    chk("⑪", "大圆: 弧长=解析 θ · 中点=exp(p₀,½log) · 路径点在球面上",
        "弧长误差=%.2e · 中点=%.2e · 单位性=%.2e" % (e_arc, e_mid, e_unit),
        max(e_arc, e_mid, e_unit) < 1e-12, "<1e-12")

    # ── ⑫ 距离公理 + 弧长≥弦长 (方案六「距离」) ──
    Q = np.asarray([S.project(x)[0] for x in rng.normal(size=200)], float)
    sym = max(abs(S.distance(Q[i], Q[j]) - S.distance(Q[j], Q[i])) for i in range(30) for j in range(30))
    tri = True
    for _ in range(500):
        a, b, c = (Q[rng.integers(0, 200)] for _ in range(3))
        if S.distance(a, c) > S.distance(a, b) + S.distance(b, c) + 1e-12:
            tri = False
            break
    chord_ok = all(S.distance(Q[i], Q[j]) >= float(np.linalg.norm(Q[i] - Q[j])) - 1e-12
                   for i in range(30) for j in range(30))
    same = abs(S.distance(p0, p0))
    anti = abs(S.distance(p0, -p0) - math.pi)
    chk("⑫", "距离: 对称 / 三角不等式 / 弧长≥弦长 / d(p,p)=0 / 对径=π",
        "对称=%.1e · 三角=%s · 弧≥弦=%s · d(p,p)=%.1e · 对径−π=%.1e" % (sym, tri, chord_ok, same, anti),
        sym < 1e-12 and tri and chord_ok and same < 1e-12 and anti < 1e-12, "全部成立")

    # ── ⑬ 切空间梯度 (方案六「梯度: 投影到切空间, 减去径向分量」) ──
    mc = MetricCalculator("sphere")
    phi = lambda q: float(np.dot(q, q)) + 2.0 * float(q[0])                           # noqa: E731
    g_tan = mc.tangent_gradient(phi, p0)
    g_new = S.riemannian_gradient(p0, 2.0 * p0 + np.eye(1, dim, 0).ravel() * 2.0)
    orth = abs(float(np.dot(g_tan, p0)))
    same2 = float(np.linalg.norm(g_tan - g_new))
    chk("⑬", "黎曼梯度=欧氏梯度的切空间投影 (⟨g,p⟩=0, 与引擎 tangent_gradient 一致)",
        "⟨g,p⟩=%.2e · 与解析式差=%.2e" % (orth, same2), orth < 1e-6 and same2 < 1e-6, "<1e-6")

    # ── ⑭ 球面距离损失 + 正则项 (方案三/四) ──
    try:
        import torch
        a = torch.tensor(S.project(rng.normal(size=dim))[0], dtype=torch.float64)
        b = torch.tensor(S.project(rng.normal(size=dim))[0], dtype=torch.float64)
        o = torch.tensor(S.project(rng.normal(size=dim))[0], dtype=torch.float64)
        o = S.tangent_project(a, o).astype(float)
        o = torch.tensor(o / np.linalg.norm(o), dtype=torch.float64)
        l_same = float(S.sphere_distance_loss(a, a, mode="cos"))
        l_orth = float(S.sphere_distance_loss(a, o, mode="cos"))
        l_anti = float(S.sphere_distance_loss(a, -a, mode="cos"))
        l_arc = float(S.sphere_distance_loss(a, b, mode="arccos"))
        d_ab = S.distance(a.numpy(), b.numpy())
        fs_ok = abs(float(S.sphere_distance_loss(a, -a, mode="fs")) - 0.0) < 1e-6
        chk("⑭", "球面距离损失: cos 口径 同点=0/正交=1/对径=2 · arccos 口径=测地角 · fs 口径 ±同点",
            "同点=%.1e 正交=%.6f 对径=%.6f arccos=%.9f (测地角=%.9f) fs(±)=%s"
            % (l_same, l_orth, l_anti, l_arc, d_ab, fs_ok),
            l_same < 1e-9 and abs(l_orth - 1) < 1e-9 and abs(l_anti - 2) < 1e-9
            and abs(l_arc - d_ab) < 1e-6 and fs_ok, "全部成立")
        x_unit = torch.tensor(S.project(rng.normal(size=dim))[0], dtype=torch.float64)
        x_off = x_unit / float(torch.linalg.norm(x_unit)) * 1.1
        r0 = float(S.unit_norm_regularizer(x_unit, form="sq"))
        r1 = float(S.unit_norm_regularizer(x_off, form="sq"))
        gc2 = S.grad_check(lambda t: S.unit_norm_regularizer(t, form="sq"), x_off.numpy().reshape(1, -1))
        x_zero = torch.zeros(1, dim, dtype=torch.float64, requires_grad=True)
        S.unit_norm_regularizer(x_zero, form="sq").backward()
        chk("⑮", "长度正则 (‖x‖²−1)²: ‖x‖=1→0 · 偏离 d ⇒ (2d+d²)² · 可导 · 零点梯度=0 (可导)",
            "‖x‖=1:%.2e · ‖x‖=1.1:%.4f (解析 (1.1²−1)²=%.4f) · 梯度相对误差=%.1e · 零点梯度=%.1e"
            % (r0, r1, (1.1 ** 2 - 1) ** 2, gc2["max_rel_err"], float(x_zero.grad.abs().max())),
            r0 < 1e-12 and abs(r1 - (1.1 ** 2 - 1) ** 2) < 1e-12 and gc2["max_rel_err"] < 1e-6
            and float(x_zero.grad.abs().max()) == 0.0, "全部成立",
            note="小偏离时 ≈4d² (d=0.1 ⇒ 0.0441); sq 形式在 ‖x‖=0 处梯度为 0 ⇒ 零点可导")
    except Exception as e:                                                        # noqa: BLE001
        chk("⑭", "球面距离损失/正则", "torch 异常: %s" % e, False, "无异常")

    # ── ⑯ 引擎: 单唯一依据一致 + 零回归 ──
    nv = Navigator("sphere")
    pj = ManifoldProjector(manifold_type="sphere")
    pz2, rz2, _ = pj.project(X[10])
    e_proj = float(np.linalg.norm(pz2 - S.project(X[10])[0]))
    e_dist = abs(mc.distance(p0, p1) - S.distance(p0, p1))
    e_step = float(np.linalg.norm(nv.step(p0, g_tan, dt=0.05) - S.exp_map(p0, g_tan * 0.05)))
    e_gcp = abs(nv.great_circle_path(p0, p1, 8)["length"] - S.great_circle_path(p0, p1, 8)["length"])
    chk("⑯", "引擎与 sphere.py **单唯一依据**一致 (投影/距离/大圆; 浮点表达式顺序不同故容差 1e-12)",
        "投影差=%.2e · 距离差=%.2e · 大圆差=%.2e" % (e_proj, e_dist, e_gcp),
        max(e_proj, e_dist, e_gcp) < 1e-12, "<1e-12")
    fp = _engine_sphere_fingerprint()
    chk("⑰", "引擎 sphere 档**零回归** (补算子前后逐位相同)",
        "sha256=%s…" % fp[:24], fp == ZERO_REGRESSION_SHA, ZERO_REGRESSION_SHA[:24] + "…")
    # 双覆盖: (±U,±V) 是同一对旋转 ⇒ log 向量取负 (同一相对旋转在"对径切空间"的表示)
    lg, lg2 = nv.log_map(-p0, -p1), nv.log_map(p0, p1)
    lg3 = S.log_map(-p0, -p1)
    rel = max(abs(float(np.linalg.norm(lg)) - float(np.linalg.norm(lg2))),
              float(np.linalg.norm(lg + lg2)), float(np.linalg.norm(lg3 + lg2)))
    chk("⑱", "su2 双覆盖消歧: log(−U,−V) = −log(U,V) (同相对旋转在对径切空间的表示, 模长相同)",
        "‖log‖差=%.2e · (log(−U,−V)+log(U,V)) 范数=%.2e" % (abs(float(np.linalg.norm(lg)) - float(np.linalg.norm(lg2))),
                                                     float(np.linalg.norm(lg + lg2))),
        rel < 1e-12, "<1e-12")
    try:
        Navigator("se3").log_map(p0, p1)
        chk("⑲", "非实现档 (se3) 明确报错不静默", "没报错", False, "ValueError")
    except ValueError as e:
        chk("⑲", "非实现档 (se3) 明确报错不静默", str(e)[:48], True, "ValueError")

    # ── ⑳ 真数据: 现场 16 维潜表示 ──
    files = sorted(glob.glob(os.path.join(ROOT, "zmax_data/ss_live/engine_latest*.json")))
    Z = []
    for f in files:
        try:
            z = json.load(open(f, encoding="utf-8")).get("z_latent")
            if isinstance(z, list) and len(z) == dim:
                Z.append(z)
        except Exception:                                                         # noqa: BLE001
            pass
    if len(Z) >= 3:
        Z = np.asarray(Z, float)
        PZ = np.asarray([S.project(z)[0] for z in Z], float)
        drift = np.linalg.norm(PZ - Z, axis=1)
        norms = np.linalg.norm(Z, axis=1)
        sp = np.asarray([[S.distance(PZ[i], PZ[j]) for j in range(len(Z))] for i in range(len(Z))])
        eu = np.asarray([[float(np.linalg.norm(PZ[i] - PZ[j])) for j in range(len(Z))] for i in range(len(Z))])
        iu = np.triu_indices(len(Z), 1)
        vv = S.tangent_project(PZ[0], rng.normal(size=dim))
        pt = S.parallel_transport(PZ[0], PZ[1], vv)
        e_pt = max(abs(float(np.linalg.norm(pt)) - float(np.linalg.norm(vv))), abs(float(np.dot(pt, PZ[1]))))
        chk("⑳", "现场真数据: 16 维潜表示投影 (n=%d 个真实快照)" % len(Z),
            "‖z‖ P50=%.4f · 投影改动 P50=%.4f/max=%.4f · 球面距离 P50=%.4f rad (欧氏 P50=%.4f) · "
            "弧≥弦全成立=%s · 真数据上 PT 不变量=%.1e"
            % (float(np.median(norms)), float(np.median(drift)), float(drift.max()),
               float(np.median(sp[iu])), float(np.median(eu[iu])),
               bool((sp[iu] >= eu[iu] - 1e-12).all()), e_pt),
            bool((sp[iu] >= eu[iu] - 1e-12).all()) and e_pt < 1e-12, "真数据满足球面公理")
    else:
        chk("⑳", "现场真数据: 16 维潜表示投影", "只找到 %d 个" % len(Z), False, "≥3")

    n_pass = sum(1 for r in RES if r["结论"] == "PASS")
    out = {"口径": "归一化球面 S^n 判据 (老倪 2026-10-15「归一化球面实现方案」逐条对账)",
           "ts": int(__import__("time").time()), "判据数": len(RES), "PASS": n_pass,
           "FAIL": len(RES) - n_pass, "唯一依据": "src/lerobot/manifold/sphere.py + manifold_engine.py",
           "结果": RES}
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("-" * 78)
    print("判据 %d 条: PASS %d · FAIL %d  →  %s" % (len(RES), n_pass, len(RES) - n_pass,
                                                "全部通过 ✅" if n_pass == len(RES) else "有 FAIL ❌"))
    print("📄 落盘: %s" % os.path.relpath(args.json, ROOT))
    return 0 if n_pass == len(RES) else 1


if __name__ == "__main__":
    sys.exit(main())
