#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧬 hjepa_m3_evolver_intel.py — 550C 方案3(双向跨模态 JEPA)自主进化

老倪: 「方案3 你考虑进自主进化」

进化的是方案3 的结构/训练超参:
    d_e (联合嵌入维度) / tau (对比温度) / lam_align / lam_g2i / lr / steps

## 适应度 (塌缩是硬闸, 不是加权项)
  ① **硬闸**: `collapse_score` 一旦判塌 ⇒ 整代作废。
     为什么不当加权项: 塌缩时对比 loss 极低、看起来各项指标都很好,
     加权一定会被它骗到 (方案3 最著名的失败模式)。
  ② img2geo 精度: 切空间 twist 的 L2 误差 (越小越好)
  ③ 对角优势  : pos − neg, 正样本对相似度比负样本高多少 (越大越好)
  ④ geo2img   : 视觉潜重构误差 (越小越好)

三个性能分量各自归一化后接**固定权重** (踩过: 让权重参与变异 ⇒ 假提升)。

台账 ~/hjepa_m3/evolve_ledger.json

用法 (Intel 上):
    PYTHONPATH=~/hjepa_m3 MR_GENS=6 ~/train_venv/bin/python evolve.py
"""
import json
import os
import os.path as osp
import sys
import time

import numpy as np

_R = os.environ.get("ZMAX_ROOT", "/home/intel/hjepa_m3")
for _p in (osp.join(_R, "src"), _R, os.path.expanduser("~/hjepa_m3")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OUT = osp.expanduser("~/hjepa_m3")
os.makedirs(OUT, exist_ok=True)
LEDGER = osp.join(OUT, "evolve_ledger.json")

D_VIS = 64          # 视觉潜维度 (模拟 z_vis; 真值是 H-JEPA ViT 输出的 D 维)
N_SAMPLES = 160


def log(*a):
    print(*a, flush=True)


def _import_m3():
    try:
        from lerobot.manifold.hjepa_m3 import (  # type: ignore
            build_m3_jepa, collapse_score)
    except Exception:
        from hjepa_m3 import build_m3_jepa, collapse_score  # type: ignore
    return build_m3_jepa, collapse_score


def make_data(seed=0, d_vis=D_VIS, n=N_SAMPLES):
    """造一对**真有相关结构**的模态: xi 是 z_vis 的线性投影 + 小噪声。

    为什么不用纯随机: 纯随机两模态之间没有可学结构, 任何模型都学不到东西,
    那样进化出来的是"哪个超参更能过拟合噪声", 没有意义。
    """
    rng = np.random.RandomState(seed)
    W = rng.normal(size=(d_vis, 6)) * 0.1
    Z = rng.normal(size=(n, d_vis)).astype(np.float32)
    X = (Z @ W + rng.normal(size=(n, 6)) * 0.005).astype(np.float32)
    return Z, X


def evaluate(hp):
    """按超参建方案3 模型, 训 steps 步, 算适应度。"""
    try:
        import torch
        build_m3_jepa, collapse_score = _import_m3()
        torch.manual_seed(int(hp["seed"]))
        m = build_m3_jepa(d_vis=D_VIS, d_geo=6, d_e=int(hp["d_e"]),
                          n_layers=int(hp["n_layers"]))
        Z, X = make_data(seed=int(hp["seed"]) % 100)
        Zt = torch.from_numpy(Z)
        Xt = torch.from_numpy(X)
        opt = torch.optim.AdamW(m.parameters(), lr=float(hp["lr"]))
        bs = int(min(hp["batch"], len(Z)))
        last = None
        for _ in range(int(hp["steps"])):
            idx = torch.randint(0, len(Z), (bs,))
            o = m(Zt[idx], Xt[idx], tau=float(hp["tau"]),
                  lam_align=float(hp["lam_align"]),
                  lam_geo2img=float(hp["lam_g2i"]))
            opt.zero_grad()
            o["loss"].backward()
            torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
            opt.step()
            last = o
        with torch.no_grad():
            o = m(Zt, Xt, tau=float(hp["tau"]),
                  lam_align=float(hp["lam_align"]),
                  lam_geo2img=float(hp["lam_g2i"]))
            ev_raw = m.vis_enc(Zt).cpu().numpy()
            eg_raw = m.geo_enc(Xt).cpu().numpy()
            ev_n = ev_raw / np.clip(np.linalg.norm(ev_raw, axis=1, keepdims=True), 1e-8, None)
            eg_n = eg_raw / np.clip(np.linalg.norm(eg_raw, axis=1, keepdims=True), 1e-8, None)
            S = ev_n @ eg_n.T
            pos = float(np.diag(S).mean())
            off = ~np.eye(S.shape[0], dtype=bool)
            neg = float(S[off].mean())
            sc = o["scalars"]

        cs = collapse_score(ev_raw, eg_raw)
        return {"ok": True, "collapsed": bool(cs["collapsed"]),
                "collapse_why": cs["why"],
                "eff_rank_vis": cs["eff_rank_vis"], "eff_rank_geo": cs["eff_rank_geo"],
                "std_min_vis": cs["std_min_vis"], "std_min_geo": cs["std_min_geo"],
                "img2geo": float(sc["img2geo"]), "geo2img": float(sc["geo2img"]),
                "adv": float(pos - neg), "pos": pos, "neg": neg,
                "loss": float(o["loss"]),
                "n_params": sum(p.numel() for p in m.parameters())}
    except Exception as e:                                             # noqa: BLE001
        import traceback
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:160]),
                "tb": traceback.format_exc()[-500:]}


def fitness_of(hp):
    r = evaluate(hp)
    if not r.get("ok"):
        return r
    # ① 硬闸: 塌缩 ⇒ 整代作废 (不计分, 不是扣分)
    if r["collapsed"]:
        return {"ok": False, "why": "判塌缩 ⇒ 整代作废: %s" % r["collapse_why"], "raw": r}
    # 各分量归一化到同量级 (参考尺度: img2geo 1e-3, 对角优势 0.5, geo2img 1e-2)
    u_i2g = -r["img2geo"] / 1e-3
    u_adv = r["adv"] / 0.5
    u_g2i = -r["geo2img"] / 1e-2
    fit = 1.0 * u_i2g + 1.0 * u_adv + 0.3 * u_g2i
    return {"ok": True, "fitness": float(fit), "u_i2g": float(u_i2g),
            "u_adv": float(u_adv), "u_g2i": float(u_g2i), "raw": r}


def load_ledger():
    if osp.exists(LEDGER):
        try:
            return json.load(open(LEDGER))
        except Exception:                                              # noqa: BLE001
            pass
    return {"entries": [], "best": None, "best_fitness": None}


def save_ledger(led):
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(led, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LEDGER)


BASE_HP = dict(d_e=32, n_layers=2, tau=0.07, lam_align=0.25, lam_g2i=1.0,
               lr=3e-3, steps=150, batch=64, seed=0)


def main():
    gens = int(os.environ.get("MR_GENS", "6"))
    margin = float(os.environ.get("MR_MARGIN", "0.02"))
    led = load_ledger()
    best = led.get("best")
    best_f = led.get("best_fitness")
    log("[550C] 方案3(双向跨模态JEPA)进化 · 已跑 %d 代 · best_fitness=%s"
        % (len(led["entries"]), best_f))

    rng = np.random.default_rng(int(os.environ.get("MR_SEED", "0")) + len(led["entries"]))
    accepted = rejected = collapsed_n = 0
    for _ in range(gens):
        base = dict(best["hp"]) if best else dict(BASE_HP)
        hp = dict(base)
        hp["d_e"] = int(rng.choice([16, 32, 48, 64]))
        hp["n_layers"] = int(rng.choice([2, 3]))
        hp["tau"] = float(np.clip(base["tau"] * rng.uniform(0.6, 1.8), 0.02, 0.5))
        hp["lam_align"] = float(np.clip(base["lam_align"] * rng.uniform(0.5, 2.0), 0.05, 1.0))
        hp["lam_g2i"] = float(np.clip(base["lam_g2i"] * rng.uniform(0.5, 2.0), 0.1, 5.0))
        hp["lr"] = float(np.clip(base["lr"] * rng.uniform(0.6, 1.6), 1e-4, 2e-2))
        hp["steps"] = int(np.clip(base["steps"] + rng.integers(-60, 120), 60, 400))
        hp["batch"] = int(rng.choice([32, 64, 96]))
        hp["seed"] = int(rng.integers(0, 10000))
        # 适应度权重固定 (踩过: 参与变异 ⇒ 假提升)

        t0 = time.time()
        r = fitness_of(hp)
        secs = time.time() - t0
        gen = len(led["entries"]) + 1

        if not r.get("ok"):
            reason = str(r.get("why"))[:120]
            if "塌缩" in reason:
                collapsed_n += 1
            log("[550C] gen%d 作废: %s" % (gen, reason))
            rejected += 1
            led["entries"].append({"gen": gen, "hp": hp, "ok": False,
                                   "why": reason, "secs": round(secs, 2)})
            save_ledger(led)
            continue

        f = r["fitness"]
        acc = (best_f is None) or (f > best_f + margin)
        if acc:
            best, best_f = {"hp": hp}, f
            accepted += 1
        else:
            rejected += 1
        raw = r["raw"]
        led["entries"].append({
            "gen": gen, "hp": hp, "ok": True, "fitness": round(f, 6),
            "u_i2g": round(r["u_i2g"], 6), "u_adv": round(r["u_adv"], 6),
            "u_g2i": round(r["u_g2i"], 6),
            "img2geo": round(raw["img2geo"], 8),
            "geo2img": round(raw["geo2img"], 6),
            "adv": round(raw["adv"], 6), "pos": round(raw["pos"], 6),
            "neg": round(raw["neg"], 6),
            "eff_rank_vis": raw["eff_rank_vis"], "eff_rank_geo": raw["eff_rank_geo"],
            "std_min_vis": raw["std_min_vis"], "std_min_geo": raw["std_min_geo"],
            "n_params": raw["n_params"], "secs": round(secs, 2), "accepted": bool(acc),
            "reason": "提升 → 采纳" if acc else
                      "未提升 (%.4f ≤ best %.4f + %.3f)" % (f, best_f or 0, margin)})
        led["best"], led["best_fitness"] = best, best_f
        save_ledger(led)
        log("[550C] gen%d fitness=%.4f (rank %.1f/%.1f, 对角优势=%.3f, "
            "img2geo=%.2e) d_e=%d τ=%.3f λ_align=%.2f %.1fs %s"
            % (gen, f, raw["eff_rank_vis"], raw["eff_rank_geo"], raw["adv"],
               raw["img2geo"], hp["d_e"], hp["tau"], hp["lam_align"], secs,
               "采纳" if acc else "回滚"))

    out = {"ok": True, "when": time.time(), "gens": gens,
           "accepted": accepted, "rejected": rejected, "collapsed": collapsed_n,
           "best_fitness": best_f, "best_hp": (best or {}).get("hp"),
           "n_entries": len(led["entries"]), "host": os.uname().nodename,
           "data": "合成双模态 (xi = z_vis·W + 噪声, 有真结构)",
           "fitness_semantics": "塌缩硬闸 + img2geo/对角优势/geo2img 归一化加权; 非真机精度"}
    print("__RESULT__" + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
